"""Turn the names an admin writes (username, group name, department path…) into records.

Every lookup is scoped to the caller's org. Nothing is guessed: a missing or ambiguous name raises
`ResolveError` with a reason code, parameters and candidate options, which the workflow turns
into a clarification the admin answers (the UI localizes the reason).
"""

import difflib
from dataclasses import dataclass, field

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationAppError
from app.models import SERVICE_USER_PREFIX, Department, Group, KnowledgeBase, Role, User
from app.repositories.org_repo import DepartmentRepository
from app.services.knowledge.directory import user_detail

# Server-side wording (logs, audit, API error body); the UI renders `reason` itself.
REASONS = {
    "user_not_found": "找不到启用状态的用户「{mention}」",
    "user_ambiguous": "「{mention}」对应多个用户",
    "dept_not_found": "找不到部门「{mention}」",
    "dept_ambiguous": "「{mention}」对应多个部门",
    "group_not_found": "找不到用户组「{mention}」",
    "role_not_found": "找不到角色「{mention}」",
    "role_ambiguous": "「{mention}」对应多个角色",
    "kb_not_found": "找不到知识库「{mention}」",
    "username_taken": "账号「{mention}」已存在",
    "group_exists": "用户组「{mention}」已存在",
    "kb_exists": "知识库「{mention}」已存在",
    "all_already_members": "这些用户都已在用户组「{mention}」中",
    "none_members": "这些用户都不在用户组「{mention}」中",
    "same_permission": "{principal} 在「{mention}」上已经是该权限",
    "same_visibility": "知识库「{mention}」已经是该可见范围",
    "no_manage_permission": "你对知识库「{mention}」没有管理权限",
    "department_empty": "部门「{mention}」下没有启用的用户",
    "no_grant": "{principal} 在知识库「{mention}」上没有单独授权",
    "none_have_roles": "这些用户都没有角色 {mention}",
    "cannot_disable_self": "不能停用你自己的账号（{mention}）",
    "already_disabled": "{mention} 已是停用状态",
    "already_enabled": "{mention} 已是启用状态",
    "dept_exists": "部门「{mention}」已存在",
    "dept_managed": "部门「{mention}」由组织同步管理，不能在本地修改名称或位置",
    "dept_cycle": "不能把部门「{mention}」移到它自己或下级部门下面",
    "dept_no_change": "部门「{mention}」没有需要修改的内容",
    "role_exists": "角色代码「{mention}」已存在",
    "permission_unknown": "未知的功能权限「{mention}」",
    "same_permissions": "角色「{mention}」的功能权限没有变化",
    "default_role_privileged": "默认角色「{mention}」不能包含超级或管理权限",
    "dataset_not_found": "找不到评测集「{mention}」",
    "dataset_empty": "评测集「{mention}」还没有用例",
    "profile_not_found": "找不到检索策略「{mention}」",
    "target_not_found": "找不到对象「{mention}」",
}


class ResolveError(ValidationAppError):
    code = "AGENT_RESOLVE_FAILED"

    def __init__(self, reason: str, mention: str, options: list[str] | None = None, **params: str):
        self.reason = reason
        self.params = {"mention": mention, **params}
        self.options = options or []
        super().__init__(REASONS[reason].format(**self.params))


@dataclass
class Planned:
    """Entities created by earlier steps of the same plan (referenced by name before they exist)."""

    # lower(username) and lower(employee no.) -> label
    usernames: dict[str, str] = field(default_factory=dict)
    groups: set[str] = field(default_factory=set)
    kbs: set[str] = field(default_factory=set)
    # full path ("A / B") and leaf name -> full path
    departments: dict[str, str] = field(default_factory=dict)
    # lower(code) and lower(name) -> (label, permission codes)
    roles: dict[str, tuple[str, list[str]]] = field(default_factory=dict)


def user_label(user: User) -> str:
    detail = user_detail(user)
    name = user.display_name or user.username
    return f"{name}（{detail}）" if detail and detail != name else name


def similar_names(mention: str, names: list[str], limit: int = 5) -> list[str]:
    low = mention.lower()
    contains = [n for n in names if low in n.lower() or n.lower() in low]
    close = difflib.get_close_matches(mention, names, n=limit, cutoff=0.4)
    return list(dict.fromkeys(contains + close))[:limit]


class Resolver:
    def __init__(self, session: AsyncSession, org_id: str) -> None:
        self.session = session
        self.org_id = org_id
        self._dept_paths: dict[str, str] | None = None

    # ---- users ------------------------------------------------------------------------

    async def users_matching(self, key: str) -> list[User]:
        key = key.strip()
        stmt = select(User).where(
            User.org_id == self.org_id,
            ~User.username.startswith(SERVICE_USER_PREFIX),
            or_(
                User.id == key,
                func.lower(User.username) == key.lower(),
                User.employee_no == key,
            ),
        )
        return list((await self.session.execute(stmt)).scalars())

    async def _users_by_name(self, key: str, include_inactive: bool) -> list[User]:
        stmt = select(User).where(
            User.org_id == self.org_id,
            ~User.username.startswith(SERVICE_USER_PREFIX),
            func.lower(User.display_name) == key.strip().lower(),
        )
        if not include_inactive:
            stmt = stmt.where(User.is_active.is_(True))
        return list((await self.session.execute(stmt)).scalars())

    async def user(self, key: str, *, include_inactive: bool = False) -> User:
        matches = [u for u in await self.users_matching(key) if include_inactive or u.is_active]
        if not matches:
            # A display name is accepted only when it is unique; otherwise offer the candidates.
            by_name = await self._users_by_name(key, include_inactive)
            if len(by_name) == 1:
                return by_name[0]
            if by_name:
                raise ResolveError("user_ambiguous", key, [user_label(u) for u in by_name])
            raise ResolveError("user_not_found", key)
        if len(matches) > 1:
            raise ResolveError("user_ambiguous", key, [user_label(u) for u in matches])
        return matches[0]

    async def user_or_planned(self, key: str, planned: Planned) -> tuple[User | None, str]:
        label = planned.usernames.get(key.strip().lower())
        if label is not None:
            return None, label
        user = await self.user(key)
        return user, user_label(user)

    # ---- departments ------------------------------------------------------------------

    async def department_paths(self) -> dict[str, str]:
        if self._dept_paths is None:
            repo = DepartmentRepository(self.session)
            self._dept_paths = await repo.path_names(self.org_id, await repo.list_all(self.org_id))
        return self._dept_paths

    def reset_departments(self) -> None:
        """Departments were created / renamed / moved: re-read paths on the next lookup."""
        self._dept_paths = None

    async def department_or_planned(self, key: str, planned: Planned) -> str:
        """Full path of an existing department or of one created earlier in the plan."""
        path = planned.departments.get(key.strip())
        if path is not None:
            return path
        return (await self.department(key))[1]

    async def department(self, key: str) -> tuple[Department, str]:
        key = key.strip()
        paths = await self.department_paths()
        ids = [i for i, p in paths.items() if key in (i, p)]
        if not ids:
            ids = [i for i, p in paths.items() if p.rsplit(" / ", 1)[-1] == key]
        if not ids:
            leaves = {p.rsplit(" / ", 1)[-1]: p for p in paths.values()}
            suggestions = [leaves[n] for n in similar_names(key, list(leaves))]
            raise ResolveError("dept_not_found", key, suggestions)
        if len(ids) > 1:
            raise ResolveError("dept_ambiguous", key, sorted(paths[i] for i in ids))
        dept = await self.session.get(Department, ids[0])
        assert dept is not None
        return dept, paths[dept.id]

    # ---- groups / roles / knowledge bases ---------------------------------------------

    async def _group_names(self) -> list[str]:
        stmt = select(Group.name).where(Group.org_id == self.org_id)
        return list((await self.session.execute(stmt)).scalars())

    async def group(self, key: str) -> Group:
        key = key.strip()
        stmt = select(Group).where(
            Group.org_id == self.org_id, or_(Group.id == key, Group.name == key)
        )
        group = (await self.session.execute(stmt)).scalars().first()
        if group is None:
            raise ResolveError(
                "group_not_found", key, similar_names(key, await self._group_names())
            )
        return group

    async def group_exists(self, name: str) -> bool:
        stmt = select(Group.id).where(Group.org_id == self.org_id, Group.name == name.strip())
        return (await self.session.execute(stmt)).first() is not None

    async def role(self, key: str) -> Role:
        key = key.strip()
        stmt = select(Role).where(
            Role.org_id == self.org_id,
            or_(Role.id == key, Role.code == key, Role.name == key),
        )
        roles = list((await self.session.execute(stmt)).scalars())
        if not roles:
            all_roles = list(
                (
                    await self.session.execute(select(Role).where(Role.org_id == self.org_id))
                ).scalars()
            )
            raise ResolveError(
                "role_not_found", key, [f"{r.name}({r.code})" for r in all_roles][:10]
            )
        if len(roles) > 1:
            raise ResolveError("role_ambiguous", key, [f"{r.name}({r.code})" for r in roles])
        return roles[0]

    async def role_exists(self, code: str) -> bool:
        stmt = select(Role.id).where(
            Role.org_id == self.org_id, func.lower(Role.code) == code.strip().lower()
        )
        return (await self.session.execute(stmt)).first() is not None

    async def _kb_names(self) -> list[str]:
        stmt = select(KnowledgeBase.name).where(
            KnowledgeBase.org_id == self.org_id, KnowledgeBase.deleted_at.is_(None)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def knowledge_base(self, key: str) -> KnowledgeBase:
        key = key.strip()
        stmt = select(KnowledgeBase).where(
            KnowledgeBase.org_id == self.org_id,
            KnowledgeBase.deleted_at.is_(None),
            or_(KnowledgeBase.id == key, KnowledgeBase.name == key),
        )
        kb = (await self.session.execute(stmt)).scalars().first()
        if kb is None:
            raise ResolveError("kb_not_found", key, similar_names(key, await self._kb_names()))
        return kb

    async def knowledge_base_exists(self, name: str) -> bool:
        stmt = select(KnowledgeBase.id).where(
            KnowledgeBase.org_id == self.org_id,
            KnowledgeBase.deleted_at.is_(None),
            KnowledgeBase.name == name.strip(),
        )
        return (await self.session.execute(stmt)).first() is not None
