"""Reconciles a directory snapshot into departments / users / memberships / title groups.

Primary source: owns the department tree, users (profile, departments, job title, active
state). Departments removed upstream are archived (grants on them keep working), users are
disabled, never deleted. On first sync, local departments with the same full path and local
users matched by employee no > mobile > email > username are adopted instead of duplicated.

Non-primary source: only binds external identities (for QR-code login) to existing users.

`run(apply=False)` computes the full change plan without writing (preview).
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    LOCAL_SOURCE,
    SERVICE_USER_PREFIX,
    Department,
    DepartmentStatus,
    Group,
    User,
    UserDepartment,
    UserGroup,
    UserIdentity,
    UserRole,
)
from app.models.base import new_id
from app.repositories.org_repo import PATH_SEPARATOR, build_path_name
from app.repositories.role_repo import RoleRepository
from app.services.directory.snapshot import DeptRecord, Snapshot, UserRecord

TITLE_GROUP_PREFIX = "职务/"
MATCH_KEYS = ("employee_no", "mobile", "email", "username")
# Upstream may withhold these (field permissions); an empty value keeps the local one.
KEEP_IF_EMPTY = ("email", "mobile", "employee_no")
CHUNK = 500


@dataclass
class SyncOptions:
    source_type: str
    is_primary: bool
    max_disable_ratio: float = 0.2
    guard_min_disables: int = 5
    force: bool = False
    max_details: int = 500


@dataclass
class SyncResult:
    stats: dict[str, dict[str, int]]
    changes: dict[str, list[dict[str, Any]]]
    warnings: list[str] = field(default_factory=list)
    aborted: bool = False
    abort_reason: str | None = None
    applied: bool = False

    def summary(self) -> dict[str, Any]:
        return {
            "stats": self.stats,
            "warnings": self.warnings[:100],
            "aborted": self.aborted,
            "abort_reason": self.abort_reason,
        }


@dataclass
class _DeptOp:
    record: DeptRecord
    dept_id: str
    parent_id: str | None
    path_name: str
    existing: Department | None = None
    adopt: bool = False
    changes: list[str] = field(default_factory=list)


@dataclass
class _UserOp:
    record: UserRecord
    user_id: str
    existing: User | None
    values: dict[str, Any]
    dept_ids: list[str]
    primary_id: str | None
    title_group: str | None
    match: str | None = None
    new_identity: bool = False
    changes: list[str] = field(default_factory=list)
    depts_changed: bool = False
    title_changed: bool = False


@dataclass
class _State:
    depts: list[Department]
    users: list[User]
    identities: dict[str, UserIdentity]
    dept_links: dict[str, dict[str, bool]]
    groups_by_name: dict[str, Group]
    title_links: dict[str, set[str]]


def recompute_paths(depts: Iterable[Department]) -> list[Department]:
    """Rebuild every materialized path from parent_id; returns the departments that changed."""
    items = list(depts)
    by_id = {d.id: d for d in items}
    children: dict[str | None, list[Department]] = defaultdict(list)
    for d in items:
        parent = d.parent_id if d.parent_id in by_id else None
        children[parent].append(d)
    changed: list[Department] = []
    stack: list[tuple[Department, str]] = [(d, "/") for d in children[None]]
    while stack:
        dept, prefix = stack.pop()
        path = f"{prefix}{dept.id}/"
        if dept.path != path:
            dept.path = path
            changed.append(dept)
        stack.extend((c, path) for c in children[dept.id])
    return changed


def _topo(records: dict[str, DeptRecord]) -> list[str]:
    order: list[str] = []
    seen: set[str] = set()
    for ext in records:
        chain = []
        cursor: str | None = ext
        while cursor and cursor not in seen:
            chain.append(cursor)
            seen.add(cursor)
            cursor = records[cursor].parent_external_id
        order.extend(reversed(chain))
    return order


class DirectoryReconciler:
    def __init__(self, session: AsyncSession, org_id: str) -> None:
        self.session = session
        self.org_id = org_id

    # ---- loading -----------------------------------------------------------------------

    async def _load(self, provider: str) -> _State:
        org = self.org_id
        depts = list(
            (await self.session.execute(select(Department).where(Department.org_id == org)))
            .scalars()
            .all()
        )
        users = list(
            (
                await self.session.execute(
                    select(User).where(
                        User.org_id == org, ~User.username.startswith(SERVICE_USER_PREFIX)
                    )
                )
            )
            .scalars()
            .all()
        )
        identities = {
            i.external_id: i
            for i in (
                await self.session.execute(
                    select(UserIdentity).where(
                        UserIdentity.org_id == org, UserIdentity.provider == provider
                    )
                )
            ).scalars()
        }
        dept_links: dict[str, dict[str, bool]] = defaultdict(dict)
        rows = await self.session.execute(
            select(UserDepartment.user_id, UserDepartment.department_id).where(
                UserDepartment.org_id == org
            )
        )
        for user_id, dept_id in rows.all():
            dept_links[user_id][dept_id] = False
        for u in users:
            if u.department_id:
                dept_links[u.id][u.department_id] = True
        groups = (
            (await self.session.execute(select(Group).where(Group.org_id == org))).scalars().all()
        )
        title_links: dict[str, set[str]] = defaultdict(set)
        rows2 = await self.session.execute(
            select(UserGroup.user_id, UserGroup.group_id).where(
                UserGroup.org_id == org, UserGroup.source == provider
            )
        )
        for user_id, group_id in rows2.all():
            title_links[user_id].add(group_id)
        return _State(
            depts=depts,
            users=users,
            identities=identities,
            dept_links=dept_links,
            groups_by_name={g.name: g for g in groups},
            title_links=title_links,
        )

    # ---- entry point -------------------------------------------------------------------

    async def run(self, snapshot: Snapshot, opts: SyncOptions, *, apply: bool) -> SyncResult:
        snap = snapshot.normalized()
        state = await self._load(opts.source_type)
        if not opts.is_primary:
            return await self._run_identities(snap, state, opts, apply)

        dept_ops, archives, ext_to_id = self._plan_departments(snap, state, opts)
        user_ops, disables, unchanged = self._plan_users(snap, state, ext_to_id, opts)

        baseline = sum(1 for u in state.users if u.source == opts.source_type and u.is_active)
        disable_count = len(disables) + sum(
            1 for op in user_ops if op.existing and op.existing.is_active and not op.record.active
        )
        result = SyncResult(
            stats=self._stats(dept_ops, archives, user_ops, disables, unchanged, disable_count),
            changes=self._changes(dept_ops, archives, user_ops, disables, opts.max_details),
            warnings=snap.warnings,
        )
        if (
            baseline
            and disable_count >= opts.guard_min_disables
            and disable_count / baseline > opts.max_disable_ratio
            and not opts.force
        ):
            result.aborted = True
            result.abort_reason = (
                f"本次将停用 {disable_count}/{baseline} 人"
                f"（{disable_count / baseline:.0%}），超过阈值 {opts.max_disable_ratio:.0%}"
            )
            return result
        if apply:
            await self._apply_departments(dept_ops, archives, opts)
            await self._apply_users(user_ops, disables, state, opts)
            result.applied = True
        return result

    # ---- departments -------------------------------------------------------------------

    def _plan_departments(
        self, snap: Snapshot, state: _State, opts: SyncOptions
    ) -> tuple[list[_DeptOp], list[Department], dict[str, str]]:
        stype = opts.source_type
        by_ext = {d.external_id: d for d in state.depts if d.source == stype and d.external_id}
        names = {d.id: d.name for d in state.depts}
        local_by_path: dict[str, Department] = {}
        for d in state.depts:
            if d.source == LOCAL_SOURCE and d.status == DepartmentStatus.ACTIVE:
                local_by_path.setdefault(build_path_name(d, names), d)

        records = {r.external_id: r for r in snap.departments if r.active}
        path_cache: dict[str, str] = {}

        def rec_path(ext: str) -> str:
            if ext not in path_cache:
                rec = records[ext]
                parent = rec.parent_external_id if rec.parent_external_id in records else None
                prefix = f"{rec_path(parent)}{PATH_SEPARATOR}" if parent else ""
                path_cache[ext] = f"{prefix}{rec.name}"
            return path_cache[ext]

        ops: dict[str, _DeptOp] = {}
        ext_to_id: dict[str, str] = {}
        for ext in _topo(records):
            existing = by_ext.get(ext)
            adopt = False
            if existing is None:
                existing = local_by_path.pop(rec_path(ext), None)
                adopt = existing is not None
            dept_id = existing.id if existing else new_id()
            ext_to_id[ext] = dept_id
            ops[ext] = _DeptOp(
                record=records[ext],
                dept_id=dept_id,
                parent_id=None,
                path_name=rec_path(ext),
                existing=existing,
                adopt=adopt,
            )
        for op in ops.values():
            parent_ext = op.record.parent_external_id
            op.parent_id = ext_to_id[parent_ext] if parent_ext in records else None
            cur = op.existing
            if cur is None:
                op.changes.append("create")
                continue
            if op.adopt:
                op.changes.append("adopt")
            if cur.name != op.record.name:
                op.changes.append("rename")
            if cur.parent_id != op.parent_id:
                op.changes.append("move")
            if cur.sort_order != op.record.order:
                op.changes.append("order")
            if cur.status != DepartmentStatus.ACTIVE:
                op.changes.append("restore")
        archives = [
            d
            for ext, d in by_ext.items()
            if ext not in records and d.status == DepartmentStatus.ACTIVE
        ]
        return [ops[e] for e in _topo(records)], archives, ext_to_id

    async def _apply_departments(
        self, ops: list[_DeptOp], archives: list[Department], opts: SyncOptions
    ) -> None:
        for op in ops:
            if op.existing is None:
                self.session.add(
                    Department(
                        id=op.dept_id,
                        org_id=self.org_id,
                        parent_id=op.parent_id,
                        name=op.record.name,
                        sort_order=op.record.order,
                        path=f"/{op.dept_id}/",
                        source=opts.source_type,
                        external_id=op.record.external_id,
                        status=DepartmentStatus.ACTIVE.value,
                    )
                )
        await self.session.flush()
        for op in ops:
            d = op.existing
            if d is None or not op.changes:
                continue
            d.source = opts.source_type
            d.external_id = op.record.external_id
            d.name = op.record.name
            d.parent_id = op.parent_id
            d.sort_order = op.record.order
            d.status = DepartmentStatus.ACTIVE.value
        for d in archives:
            d.status = DepartmentStatus.ARCHIVED.value
        await self.session.flush()
        all_depts = (
            (await self.session.execute(select(Department).where(Department.org_id == self.org_id)))
            .scalars()
            .all()
        )
        recompute_paths(all_depts)
        await self.session.flush()

    # ---- users -------------------------------------------------------------------------

    @staticmethod
    def _match_index(users: Iterable[User]) -> dict[str, dict[str, list[User]]]:
        index: dict[str, dict[str, list[User]]] = {k: defaultdict(list) for k in MATCH_KEYS}
        for u in users:
            for key in MATCH_KEYS:
                value = getattr(u, key)
                if value:
                    index[key][str(value).strip().lower()].append(u)
        return index

    @staticmethod
    def _match(
        record: UserRecord, index: dict[str, dict[str, list[User]]], claimed: set[str]
    ) -> tuple[User | None, str | None]:
        for key in MATCH_KEYS:
            value = getattr(record, key)
            if not value:
                continue
            candidates = [
                u for u in index[key].get(str(value).strip().lower(), []) if u.id not in claimed
            ]
            if len(candidates) == 1:
                return candidates[0], key
        return None, None

    def _plan_users(
        self, snap: Snapshot, state: _State, ext_to_id: dict[str, str], opts: SyncOptions
    ) -> tuple[list[_UserOp], list[User], int]:
        stype = opts.source_type
        users_by_id = {u.id: u for u in state.users}
        claimed = {i.user_id for i in state.identities.values()}
        index = self._match_index(u for u in state.users if u.id not in claimed)
        taken_usernames = {u.username.lower() for u in state.users}
        ops: list[_UserOp] = []
        unchanged = 0
        seen_users: set[str] = set()
        for rec in snap.users:
            identity = state.identities.get(rec.external_id)
            user = users_by_id.get(identity.user_id) if identity else None
            match = None
            if user is None:
                user, match = self._match(rec, index, claimed)
                if user is not None:
                    claimed.add(user.id)
            if user is not None and user.id in seen_users:
                user, match = None, None
            dept_ids = [ext_to_id[e] for e in rec.dept_external_ids if e in ext_to_id]
            primary = ext_to_id.get(rec.primary_dept or "") or (dept_ids[0] if dept_ids else None)
            title_group = f"{TITLE_GROUP_PREFIX}{rec.title}" if rec.title else None
            values: dict[str, Any] = {
                "display_name": rec.name,
                "email": rec.email,
                "mobile": rec.mobile,
                "employee_no": rec.employee_no,
                "job_title": rec.title,
                "source": stype,
                "is_active": rec.active,
            }
            if user is None and not rec.active:
                # Departed upstream and never synced: nothing to create.
                continue
            if user is None:
                username = rec.username
                if username.lower() in taken_usernames:
                    username = f"{rec.username}.{rec.external_id}"[:128]
                taken_usernames.add(username.lower())
                values["username"] = username
                op = _UserOp(
                    record=rec,
                    user_id=new_id(),
                    existing=None,
                    values=values,
                    dept_ids=dept_ids,
                    primary_id=primary,
                    title_group=title_group,
                    new_identity=True,
                    changes=["create"],
                    depts_changed=bool(dept_ids),
                    title_changed=title_group is not None,
                )
                ops.append(op)
                continue
            seen_users.add(user.id)
            for key in KEEP_IF_EMPTY:
                if not values[key]:
                    values[key] = getattr(user, key)
            changes = [k for k, v in values.items() if getattr(user, k) != v]
            if "is_active" in changes:
                changes.remove("is_active")
                changes.append("restore" if rec.active else "disable")
            if user.source != stype:
                changes.append("adopt")
            current = state.dept_links.get(user.id, {})
            depts_changed = set(current) != set(dept_ids) or user.department_id != primary
            if depts_changed:
                changes.append("departments")
            current_titles = state.title_links.get(user.id, set())
            wanted_title = state.groups_by_name.get(title_group) if title_group else None
            if title_group and wanted_title is None:
                title_changed = True
            else:
                title_changed = current_titles != ({wanted_title.id} if wanted_title else set())
            new_identity = identity is None
            if new_identity:
                changes.append("bind")
            if not changes and not title_changed:
                unchanged += 1
                continue
            ops.append(
                _UserOp(
                    record=rec,
                    user_id=user.id,
                    existing=user,
                    values=values,
                    dept_ids=dept_ids,
                    primary_id=primary,
                    title_group=title_group,
                    match=match,
                    new_identity=new_identity,
                    changes=changes,
                    depts_changed=depts_changed,
                    title_changed=title_changed,
                )
            )
        listed = {rec.external_id for rec in snap.users}
        disables = [
            users_by_id[i.user_id]
            for ext, i in state.identities.items()
            if ext not in listed
            and i.user_id in users_by_id
            and users_by_id[i.user_id].is_active
            and users_by_id[i.user_id].source == stype
            and i.user_id not in seen_users
        ]
        return ops, disables, unchanged

    async def _apply_users(
        self, ops: list[_UserOp], disables: list[User], state: _State, opts: SyncOptions
    ) -> None:
        stype = opts.source_type
        for op in ops:
            if op.existing is None:
                self.session.add(
                    User(
                        id=op.user_id,
                        org_id=self.org_id,
                        department_id=op.primary_id,
                        **op.values,
                    )
                )
            else:
                for key, value in op.values.items():
                    setattr(op.existing, key, value)
                op.existing.department_id = op.primary_id
        for user in disables:
            user.is_active = False
        await self.session.flush()

        created = [op.user_id for op in ops if op.existing is None]
        default_roles = (
            await RoleRepository(self.session).default_role_ids(self.org_id) if created else []
        )
        for user_id in created:
            for role_id in default_roles:
                self.session.add(
                    UserRole(
                        org_id=self.org_id, user_id=user_id, role_id=role_id, source=LOCAL_SOURCE
                    )
                )

        for op in ops:
            identity = state.identities.get(op.record.external_id)
            if identity is None:
                self.session.add(
                    UserIdentity(
                        org_id=self.org_id,
                        user_id=op.user_id,
                        provider=stype,
                        external_id=op.record.external_id,
                        union_id=op.record.union_id,
                    )
                )
            elif op.record.union_id and identity.union_id != op.record.union_id:
                identity.union_id = op.record.union_id

        dept_changed = [op for op in ops if op.depts_changed]
        for i in range(0, len(dept_changed), CHUNK):
            chunk = [op.user_id for op in dept_changed[i : i + CHUNK]]
            await self.session.execute(
                delete(UserDepartment).where(
                    UserDepartment.org_id == self.org_id, UserDepartment.user_id.in_(chunk)
                )
            )
        for op in dept_changed:
            for dept_id in dict.fromkeys(op.dept_ids):
                self.session.add(
                    UserDepartment(
                        org_id=self.org_id,
                        user_id=op.user_id,
                        department_id=dept_id,
                        is_primary=dept_id == op.primary_id,
                        source=stype,
                    )
                )

        title_changed = [op for op in ops if op.title_changed]
        groups = state.groups_by_name
        for name in sorted({op.title_group for op in title_changed if op.title_group}):
            if name not in groups:
                group = Group(
                    org_id=self.org_id,
                    name=name,
                    description="职务组，由组织架构同步维护",
                    source=stype,
                )
                self.session.add(group)
                groups[name] = group
        await self.session.flush()
        for i in range(0, len(title_changed), CHUNK):
            chunk = [op.user_id for op in title_changed[i : i + CHUNK]]
            await self.session.execute(
                delete(UserGroup).where(
                    UserGroup.org_id == self.org_id,
                    UserGroup.user_id.in_(chunk),
                    UserGroup.source == stype,
                )
            )
        await self.session.flush()
        # A user may already be in the group through another source (e.g. added locally).
        remaining: set[tuple[str, str]] = set()
        for i in range(0, len(title_changed), CHUNK):
            chunk = [op.user_id for op in title_changed[i : i + CHUNK]]
            rows = await self.session.execute(
                select(UserGroup.user_id, UserGroup.group_id).where(
                    UserGroup.org_id == self.org_id, UserGroup.user_id.in_(chunk)
                )
            )
            remaining.update((r[0], r[1]) for r in rows.all())
        for op in title_changed:
            if op.title_group:
                gid = groups[op.title_group].id
                if (op.user_id, gid) not in remaining:
                    self.session.add(
                        UserGroup(
                            org_id=self.org_id, user_id=op.user_id, group_id=gid, source=stype
                        )
                    )
        await self.session.flush()

    # ---- identity-only (non-primary sources) ---------------------------------------------

    async def _run_identities(
        self, snap: Snapshot, state: _State, opts: SyncOptions, apply: bool
    ) -> SyncResult:
        users_by_id = {u.id: u for u in state.users}
        claimed = {i.user_id for i in state.identities.values()}
        index = self._match_index(u for u in state.users if u.id not in claimed)
        active = [r for r in snap.users if r.active]
        binds: list[tuple[UserRecord, User, str]] = []
        unmatched: list[UserRecord] = []
        kept = 0
        for rec in active:
            if rec.external_id in state.identities:
                kept += 1
                continue
            user, key = self._match(rec, index, claimed)
            if user is None:
                unmatched.append(rec)
                continue
            claimed.add(user.id)
            binds.append((rec, user, key or ""))
        listed = {r.external_id for r in active}
        stale = [i for ext, i in state.identities.items() if ext not in listed]
        cap = opts.max_details
        result = SyncResult(
            stats={
                "identities": {
                    "bound": len(binds),
                    "kept": kept,
                    "removed": len(stale),
                    "unmatched": len(unmatched),
                }
            },
            changes={
                "identities": [
                    {
                        "action": "bind",
                        "external_id": rec.external_id,
                        "name": rec.name,
                        "username": user.username,
                        "match": key,
                    }
                    for rec, user, key in binds[:cap]
                ]
                + [
                    {
                        "action": "remove",
                        "external_id": i.external_id,
                        "username": users_by_id[i.user_id].username
                        if i.user_id in users_by_id
                        else None,
                    }
                    for i in stale[:cap]
                ],
                "unmatched": [
                    {
                        "external_id": r.external_id,
                        "name": r.name,
                        "employee_no": r.employee_no,
                        "mobile": r.mobile,
                        "email": r.email,
                    }
                    for r in unmatched[:cap]
                ],
            },
            warnings=snap.warnings,
        )
        if apply:
            for rec, user, _ in binds:
                self.session.add(
                    UserIdentity(
                        org_id=self.org_id,
                        user_id=user.id,
                        provider=opts.source_type,
                        external_id=rec.external_id,
                        union_id=rec.union_id,
                    )
                )
            for identity in stale:
                await self.session.delete(identity)
            await self.session.flush()
            result.applied = True
        return result

    # ---- reporting -----------------------------------------------------------------------

    @staticmethod
    def _stats(
        dept_ops: list[_DeptOp],
        archives: list[Department],
        user_ops: list[_UserOp],
        disables: list[User],
        unchanged: int,
        disable_count: int,
    ) -> dict[str, dict[str, int]]:
        def count(ops: Iterable[Any], change: str) -> int:
            return sum(1 for op in ops if change in op.changes)

        dept_updates = sum(1 for op in dept_ops if {"rename", "move", "order"} & set(op.changes))
        user_updates = sum(
            1
            for op in user_ops
            if op.existing is not None
            and (set(op.changes) - {"restore", "disable", "adopt", "bind"} or op.title_changed)
        )
        return {
            "departments": {
                "total": len(dept_ops),
                "created": count(dept_ops, "create"),
                "updated": dept_updates,
                "moved": count(dept_ops, "move"),
                "adopted": count(dept_ops, "adopt"),
                "restored": count(dept_ops, "restore"),
                "archived": len(archives),
            },
            "users": {
                "total": len(user_ops) + unchanged,
                "created": count(user_ops, "create"),
                "updated": user_updates,
                "adopted": count(user_ops, "adopt"),
                "restored": count(user_ops, "restore"),
                "disabled": disable_count,
                "unchanged": unchanged,
            },
        }

    @staticmethod
    def _changes(
        dept_ops: list[_DeptOp],
        archives: list[Department],
        user_ops: list[_UserOp],
        disables: list[User],
        cap: int,
    ) -> dict[str, list[dict[str, Any]]]:
        depts: list[dict[str, Any]] = [
            {
                "action": op.changes[0],
                "changes": op.changes,
                "name": op.record.name,
                "path": op.path_name,
                "external_id": op.record.external_id,
                "before": op.existing.name if op.existing else None,
            }
            for op in dept_ops
            if op.changes
        ][:cap]
        depts += [
            {
                "action": "archive",
                "changes": ["archive"],
                "name": d.name,
                "external_id": d.external_id,
            }
            for d in archives[:cap]
        ]
        users: list[dict[str, Any]] = [
            {
                "action": "create" if op.existing is None else (op.changes or ["update"])[0],
                "changes": op.changes + (["title"] if op.title_changed else []),
                "username": op.existing.username if op.existing else op.values.get("username"),
                "name": op.record.name,
                "employee_no": op.record.employee_no,
                "title": op.record.title,
                "match": op.match,
            }
            for op in user_ops
            if op.record.active or op.existing is None
        ][:cap]
        disabled: list[dict[str, Any]] = [
            {"action": "disable", "username": op.existing.username, "name": op.record.name}
            for op in user_ops
            if op.existing and op.existing.is_active and not op.record.active
        ]
        disabled += [
            {"action": "disable", "username": u.username, "name": u.display_name} for u in disables
        ]
        return {"departments": depts, "users": users, "disabled": disabled[:cap]}
