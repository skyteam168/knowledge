"""Post-conditions: after each write, re-read the system and check the intended state holds.

"The service call did not raise" is not success; these checks are. A failed check fails the step
and rolls the whole plan back.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select

from app.models import EvalDataset, EvalRun, EvalRunStatus, ResourceAcl
from app.repositories.group_repo import GroupRepository
from app.repositories.user_repo import UserRepository
from app.services.admin_agent.resolve import ResolveError
from app.services.admin_agent.tools import LEVELS, AgentContext, resolve_principal
from app.services.authz import PrincipalResolver, ResourceRef
from app.services.knowledge.access import RESOURCE_KB, KnowledgeAccess


@dataclass
class Check:
    ok: bool
    code: str
    params: dict[str, str] = field(default_factory=dict)


CheckFn = Callable[[AgentContext, dict[str, Any]], Awaitable[Check]]


async def _user_exists(a: AgentContext, args: dict[str, Any]) -> Check:
    users = await a.resolver.users_matching(args["username"])
    if not users:
        return Check(False, "user_missing", {"user": args["username"]})
    if args.get("department"):
        dept, path = await a.resolver.department(args["department"])
        ids = await UserRepository(a.session).department_ids(a.ctx.org_id, users[0])
        if dept.id not in ids:
            return Check(False, "department_not_set", {"department": path})
    return Check(True, "user_created", {"user": users[0].username})


async def _password_ready(a: AgentContext, args: dict[str, Any]) -> Check:
    user = await a.resolver.user(args["user"])
    if not user.keycloak_sub:
        return Check(False, "keycloak_not_bound", {"user": user.username})
    return Check(True, "password_login_ready", {"user": user.username})


async def _membership(a: AgentContext, args: dict[str, Any], present: bool) -> Check:
    group = await a.resolver.group(args["group"])
    members = set(await GroupRepository(a.session).list_member_ids(a.ctx.org_id, group.id))
    wrong = []
    for key in args["users"]:
        user = await a.resolver.user(key)
        if (user.id in members) != present:
            wrong.append(user.username)
    if wrong:
        code = "not_in_group" if present else "still_in_group"
        return Check(False, code, {"group": group.name, "users": "、".join(wrong)})
    return Check(True, "membership_ok", {"group": group.name, "count": str(len(args["users"]))})


async def _added(a: AgentContext, args: dict[str, Any]) -> Check:
    return await _membership(a, args, True)


async def _removed(a: AgentContext, args: dict[str, Any]) -> Check:
    return await _membership(a, args, False)


async def _roles(a: AgentContext, args: dict[str, Any]) -> Check:
    roles = {(await a.resolver.role(r)).id for r in args["roles"]}
    repo = UserRepository(a.session)
    missing = []
    for key in args["users"]:
        user = await a.resolver.user(key)
        have = {r.id for r in await repo.list_roles(a.ctx.org_id, user.id)}
        if not roles <= have:
            missing.append(user.username)
    if missing:
        return Check(False, "roles_missing", {"users": "、".join(missing)})
    return Check(True, "roles_ok", {"count": str(len(args["users"]))})


async def _group_exists(a: AgentContext, args: dict[str, Any]) -> Check:
    if not await a.resolver.group_exists(args["name"]):
        return Check(False, "group_missing", {"group": args["name"]})
    return Check(True, "group_created", {"group": args["name"]})


async def _kb_exists(a: AgentContext, args: dict[str, Any]) -> Check:
    kb = await a.resolver.knowledge_base(args["name"])
    perm = await KnowledgeAccess(a.session).kb_permission(a.ctx.user, kb)
    if perm is None or perm.value != "manage":
        return Check(False, "kb_owner_missing", {"knowledge_base": kb.name})
    return Check(True, "kb_created", {"knowledge_base": kb.name})


async def _granted(a: AgentContext, args: dict[str, Any]) -> Check:
    kb = await a.resolver.knowledge_base(args["knowledge_base"])
    pid, label = await resolve_principal(a, args["principal_type"], args["principal"], None)
    row = (
        await a.session.execute(
            select(ResourceAcl.permission).where(
                ResourceAcl.org_id == a.ctx.org_id,
                ResourceAcl.resource_type == RESOURCE_KB,
                ResourceAcl.resource_id == kb.id,
                ResourceAcl.principal_type == args["principal_type"],
                ResourceAcl.principal_id == pid,
            )
        )
    ).scalar_one_or_none()
    if row != args["permission"]:
        return Check(False, "grant_missing", {"knowledge_base": kb.name, "principal": label})
    if args["principal_type"] == "user" and pid:
        # The effective permission (all grants combined) must reach at least what was granted.
        principals = await PrincipalResolver(a.session, a.authz_cache).resolve(a.ctx.org_id, pid)
        effective = await KnowledgeAccess(a.session).acl.effective_permission(
            principals, ResourceRef(RESOURCE_KB, kb.id)
        )
        if effective is None or LEVELS[effective.value] < LEVELS[args["permission"]]:
            return Check(
                False, "effective_too_low", {"knowledge_base": kb.name, "principal": label}
            )
    return Check(
        True,
        "grant_ok",
        {"knowledge_base": kb.name, "principal": label, "permission": args["permission"]},
    )


async def _visibility(a: AgentContext, args: dict[str, Any]) -> Check:
    kb = await a.resolver.knowledge_base(args["knowledge_base"])
    await a.session.refresh(kb)
    if kb.visibility != args["visibility"]:
        return Check(False, "visibility_not_set", {"knowledge_base": kb.name})
    return Check(True, "visibility_ok", {"knowledge_base": kb.name, "visibility": kb.visibility})


async def _revoked(a: AgentContext, args: dict[str, Any]) -> Check:
    kb = await a.resolver.knowledge_base(args["knowledge_base"])
    pid, label = await resolve_principal(
        a, args["principal_type"], args["principal"], None, include_inactive=True
    )
    row = await a.session.scalar(
        select(ResourceAcl.id).where(
            ResourceAcl.org_id == a.ctx.org_id,
            ResourceAcl.resource_type == RESOURCE_KB,
            ResourceAcl.resource_id == kb.id,
            ResourceAcl.principal_type == args["principal_type"],
            ResourceAcl.principal_id == pid,
        )
    )
    if row is not None:
        return Check(False, "grant_still_present", {"knowledge_base": kb.name, "principal": label})
    return Check(True, "revoke_ok", {"knowledge_base": kb.name, "principal": label})


async def _roles_removed(a: AgentContext, args: dict[str, Any]) -> Check:
    roles = {(await a.resolver.role(r)).id for r in args["roles"]}
    repo = UserRepository(a.session)
    still = []
    for key in args["users"]:
        user = await a.resolver.user(key, include_inactive=True)
        if roles & {r.id for r in await repo.list_roles(a.ctx.org_id, user.id)}:
            still.append(user.username)
    if still:
        return Check(False, "roles_still_present", {"users": "、".join(still)})
    return Check(True, "roles_removed", {"count": str(len(args["users"]))})


def _active_state(active: bool) -> CheckFn:
    async def check(a: AgentContext, args: dict[str, Any]) -> Check:
        wrong = []
        for key in args["users"]:
            user = await a.resolver.user(key, include_inactive=True)
            await a.session.refresh(user)
            if user.is_active != active:
                wrong.append(user.username)
        if wrong:
            return Check(False, "user_state_wrong", {"users": "、".join(wrong)})
        code = "users_enabled" if active else "users_disabled"
        return Check(True, code, {"count": str(len(args["users"]))})

    return check


async def _dept_created(a: AgentContext, args: dict[str, Any]) -> Check:
    a.resolver.reset_departments()
    parent = (await a.resolver.department(args["parent"]))[1] if args.get("parent") else None
    path = f"{parent} / {args['name']}" if parent else args["name"]
    try:
        await a.resolver.department(path)
    except ResolveError:
        return Check(False, "dept_missing", {"department": path})
    return Check(True, "dept_created", {"department": path})


async def _dept_renamed(a: AgentContext, args: dict[str, Any]) -> Check:
    a.resolver.reset_departments()
    paths = await a.resolver.department_paths()
    if not any(p.rsplit(" / ", 1)[-1] == args["name"] for p in paths.values()):
        return Check(False, "dept_missing", {"department": args["name"]})
    return Check(True, "dept_renamed", {"department": args["name"]})


async def _dept_moved(a: AgentContext, args: dict[str, Any]) -> Check:
    a.resolver.reset_departments()
    dept, path = await a.resolver.department(args["department"])
    await a.session.refresh(dept)
    parent_id = (await a.resolver.department(args["parent"]))[0].id if args.get("parent") else None
    if dept.parent_id != parent_id:
        return Check(False, "dept_not_moved", {"department": path})
    return Check(True, "dept_moved", {"department": path})


async def _role_created(a: AgentContext, args: dict[str, Any]) -> Check:
    if not await a.resolver.role_exists(args["code"]):
        return Check(False, "role_missing", {"role": args["code"]})
    role = await a.resolver.role(args["code"])
    have = set(await a.roles().permission_codes(role))
    if have != set(args.get("permissions") or []):
        return Check(False, "role_permissions_wrong", {"role": role.name})
    return Check(True, "role_created", {"role": f"{role.name}({role.code})"})


async def _role_permissions(a: AgentContext, args: dict[str, Any]) -> Check:
    role = await a.resolver.role(args["role"])
    have = set(await a.roles().permission_codes(role))
    if not set(args.get("add") or []) <= have or have & set(args.get("remove") or []):
        return Check(False, "role_permissions_wrong", {"role": role.name})
    return Check(True, "role_permissions_ok", {"role": f"{role.name}({role.code})"})


async def _eval_queued(a: AgentContext, args: dict[str, Any]) -> Check:
    run = await a.session.scalar(
        select(EvalRun)
        .join(EvalDataset, EvalDataset.id == EvalRun.dataset_id)
        .where(
            EvalRun.org_id == a.ctx.org_id,
            EvalRun.created_by == a.ctx.user.id,
            EvalDataset.name == args["dataset"].strip(),
        )
        .order_by(EvalRun.created_at.desc())
        .limit(1)
    )
    if run is None or run.status != EvalRunStatus.PENDING.value:
        return Check(False, "eval_not_queued", {"dataset": args["dataset"]})
    return Check(True, "eval_queued", {"dataset": args["dataset"], "cases": str(run.case_count)})


CHECKS: dict[str, CheckFn] = {
    "revoke_kb_access": _revoked,
    "remove_roles": _roles_removed,
    "disable_users": _active_state(False),
    "enable_users": _active_state(True),
    "create_department": _dept_created,
    "rename_department": _dept_renamed,
    "move_department": _dept_moved,
    "create_role": _role_created,
    "set_role_permissions": _role_permissions,
    "start_eval_run": _eval_queued,
    "create_user": _user_exists,
    "open_password_login": _password_ready,
    "add_to_group": _added,
    "remove_from_group": _removed,
    "assign_roles": _roles,
    "create_group": _group_exists,
    "create_knowledge_base": _kb_exists,
    "grant_kb_access": _granted,
    "set_kb_visibility": _visibility,
}
