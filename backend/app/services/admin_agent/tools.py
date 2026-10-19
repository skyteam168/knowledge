"""Tools of the admin assistant.

Read tools run as soon as the model calls them. Write tools never run from the model: they are
previewed (resolved + validated) into a plan, and only run after the admin confirms it. Every
write calls the regular admin services, so their permission checks and audit records apply.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import PermissionDeniedError
from app.core.permissions import PERMISSION_CATALOG, is_privileged
from app.models import LOCAL_SOURCE, Department, KbVisibility, KnowledgeBase, ResourceAcl, UserRole
from app.repositories.acl_repo import principal_clause
from app.repositories.group_repo import GroupRepository
from app.repositories.role_repo import RoleRepository
from app.repositories.user_repo import UserRepository
from app.schemas.identity import (
    DepartmentCreate,
    DepartmentUpdate,
    GroupCreate,
    RoleCreate,
    UserCreate,
    UserUpdate,
)
from app.schemas.knowledge import AclEntryIn, AclEntryOut, KbAclUpdate, KnowledgeBaseCreate
from app.services.admin.department_service import DepartmentService
from app.services.admin.group_service import GroupService
from app.services.admin.password_login import PasswordLoginService
from app.services.admin.role_service import RoleService
from app.services.admin.user_service import UserService
from app.services.admin_agent.resolve import Planned, ResolveError, Resolver, user_label
from app.services.authz import AclPermission, AuthzCache, PermissionResolver, PrincipalResolver
from app.services.context import RequestContext
from app.services.ingest.queue import TaskQueue
from app.services.knowledge.access import RESOURCE_KB, KnowledgeAccess
from app.services.knowledge.directory import PrincipalDirectory
from app.services.knowledge.kb_service import KnowledgeBaseService

PermissionName = Literal["read", "edit", "manage"]
PrincipalKind = Literal["user", "group", "role", "dept"]
LEVELS = {"read": 1, "edit": 2, "manage": 3}


@dataclass
class AgentContext:
    session: AsyncSession
    ctx: RequestContext
    authz_cache: AuthzCache
    settings: Settings
    http: httpx.AsyncClient
    resolver: Resolver
    queue: TaskQueue | None = None

    def users(self) -> UserService:
        return UserService(self.session, self.ctx, self.authz_cache)

    def groups(self) -> GroupService:
        return GroupService(self.session, self.ctx, self.authz_cache)

    def kbs(self) -> KnowledgeBaseService:
        return KnowledgeBaseService(self.session, self.ctx, self.authz_cache)

    def departments(self) -> DepartmentService:
        return DepartmentService(self.session, self.ctx, self.authz_cache)

    def roles(self) -> RoleService:
        return RoleService(self.session, self.ctx, self.authz_cache)


@dataclass
class StepPreview:
    """What the admin sees before confirming. `display` values are names or raw codes
    (permission / visibility / principal type) that the UI localizes; warnings are coded."""

    display: dict[str, str]
    warnings: list[dict[str, str]] = field(default_factory=list)


class Args(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


ReadFn = Callable[[AgentContext, Any], Awaitable[Any]]
PreviewFn = Callable[[AgentContext, Any, Planned], Awaitable[StepPreview]]
RunFn = Callable[[AgentContext, Any], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class Tool:
    name: str
    kind: Literal["read", "write"]
    description: str
    args: type[Args]
    permissions: tuple[str, ...]
    run: ReadFn | RunFn
    preview: PreviewFn | None = None

    def args_schema(self) -> dict[str, Any]:
        """Compact JSON schema for the prompt (optional fields unwrapped from anyOf/null)."""
        schema = self.args.model_json_schema()
        props: dict[str, Any] = {}
        for name, spec in schema.get("properties", {}).items():
            variants = [s for s in spec.get("anyOf", [spec]) if s.get("type") != "null"]
            merged = {**(variants[0] if variants else {}), **spec}
            props[name] = {
                k: v for k, v in merged.items() if k in ("type", "description", "enum", "items")
            }
        return {"properties": props, "required": schema.get("required", [])}


# ---- read tools -------------------------------------------------------------------------


class SearchUsersArgs(Args):
    keyword: str | None = Field(None, description="账号 / 姓名 / 邮箱 / 工号，模糊匹配")
    department: str | None = Field(None, description="部门完整路径或唯一名称，含下级部门")
    include_inactive: bool = Field(False, description="是否包含已停用账号")
    limit: int = Field(10, ge=1, le=30)


async def search_users(a: AgentContext, args: SearchUsersArgs) -> list[dict[str, Any]]:
    dept_id = (await a.resolver.department(args.department))[0].id if args.department else None
    page = await a.users().search(
        page=1,
        size=args.limit,
        keyword=args.keyword,
        department_id=dept_id,
        is_active=None if args.include_inactive else True,
    )
    users = {u.id: u for u in page.items}
    if args.keyword and not dept_id:
        for exact in await a.resolver.users_matching(args.keyword):
            if exact.id not in users and (exact.is_active or args.include_inactive):
                users[exact.id] = await a.users().out(exact)
    repo = UserRepository(a.session)
    result = []
    for u in list(users.values())[: args.limit]:
        roles = await repo.list_roles(a.ctx.org_id, u.id)
        result.append(
            {
                "username": u.username,
                "display_name": u.display_name,
                "employee_no": u.employee_no,
                "departments": [d.path_name for d in u.departments],
                "active": u.is_active,
                "keycloak_bound": u.keycloak_bound,
                "roles": [f"{r.name}({r.code})" for r in roles],
            }
        )
    return result


class SearchDepartmentsArgs(Args):
    keyword: str = Field(description="部门名称或路径片段")
    limit: int = Field(20, ge=1, le=50)


async def search_departments(a: AgentContext, args: SearchDepartmentsArgs) -> list[str]:
    paths = await a.resolver.department_paths()
    kw = args.keyword.lower()
    return sorted(p for p in paths.values() if kw in p.lower())[: args.limit]


class KeywordArgs(Args):
    keyword: str | None = Field(None, description="名称关键词，留空列出全部")


async def list_groups(a: AgentContext, args: KeywordArgs) -> list[dict[str, Any]]:
    page = await a.groups().search(page=1, size=50, keyword=args.keyword)
    return [
        {"name": g.name, "description": g.description, "member_count": g.member_count}
        for g in page.items
    ]


class GroupArgs(Args):
    group: str = Field(description="用户组名称")


async def list_group_members(a: AgentContext, args: GroupArgs) -> list[str]:
    group = await a.resolver.group(args.group)
    members = await GroupRepository(a.session).list_members(a.ctx.org_id, group.id)
    return [user_label(u) for u in members]


class NoArgs(Args):
    pass


async def list_roles(a: AgentContext, _: NoArgs) -> list[dict[str, Any]]:
    roles = await RoleService(a.session, a.ctx, a.authz_cache).list_roles()
    return [
        {
            "code": r.code,
            "name": r.name,
            "default": r.is_default,
            "permissions": r.permissions,
        }
        for r in roles
    ]


async def search_knowledge_bases(a: AgentContext, args: KeywordArgs) -> list[dict[str, Any]]:
    page = await a.kbs().search(page=1, size=50, keyword=args.keyword)
    return [
        {
            "name": kb.name,
            "visibility": kb.visibility,
            "description": kb.description,
            "documents": kb.document_count,
        }
        for kb in page.items
    ]


class KbArgs(Args):
    knowledge_base: str = Field(description="知识库名称")


async def get_kb_access(a: AgentContext, args: KbArgs) -> dict[str, Any]:
    kb = await a.resolver.knowledge_base(args.knowledge_base)
    acl = await a.kbs().get_acl(kb.id)
    return {
        "knowledge_base": kb.name,
        "visibility": acl.visibility,
        "entries": [
            {
                "type": e.principal_type,
                "name": e.principal_name,
                "account": e.principal_detail,
                "permission": e.permission,
                "active": e.principal_active,
            }
            for e in acl.entries
        ],
    }


class UserArgs(Args):
    user: str = Field(description="账号（username）或工号")


async def explain_user_access(a: AgentContext, args: UserArgs) -> dict[str, Any]:
    matches = await a.resolver.users_matching(args.user)
    if len(matches) != 1:
        user = await a.resolver.user(args.user)
    else:
        user = matches[0]
    org_id = a.ctx.org_id
    principals = await PrincipalResolver(a.session, a.authz_cache).resolve(org_id, user.id)
    perms = await PermissionResolver(a.session, a.authz_cache).resolve(principals)
    roles = await UserRepository(a.session).list_roles(org_id, user.id)
    base = {
        "user": user_label(user),
        "active": user.is_active,
        "roles": [f"{r.name}({r.code})" for r in roles],
        "feature_permissions": sorted(perms),
    }
    if "*" in perms:
        return {**base, "knowledge_bases": "超级权限：可访问全部知识库"}
    rows = list(
        (
            await a.session.execute(
                select(ResourceAcl).where(
                    ResourceAcl.org_id == org_id,
                    ResourceAcl.resource_type == RESOURCE_KB,
                    principal_clause(principals.pairs()),
                )
            )
        ).scalars()
    )
    names = await PrincipalDirectory(a.session, org_id).names(
        (r.principal_type, r.principal_id) for r in rows
    )
    kbs = list(
        (
            await a.session.execute(
                select(KnowledgeBase).where(
                    KnowledgeBase.org_id == org_id, KnowledgeBase.deleted_at.is_(None)
                )
            )
        ).scalars()
    )
    access: dict[str, dict[str, Any]] = {}
    for kb in kbs:
        if kb.visibility == KbVisibility.ORG.value:
            access[kb.id] = {
                "name": kb.name,
                "permission": "read",
                "via": [{"type": "org", "name": "组织内所有人", "permission": "read"}],
            }
    by_id = {kb.id: kb for kb in kbs}
    for row in rows:
        granted = by_id.get(row.resource_id)
        if granted is None:
            continue
        entry = access.setdefault(
            granted.id, {"name": granted.name, "permission": "read", "via": []}
        )
        if not entry["via"] or LEVELS[row.permission] > LEVELS[entry["permission"]]:
            entry["permission"] = row.permission
        who = names.get((row.principal_type, row.principal_id), row.principal_id)
        entry["via"].append({"type": row.principal_type, "name": who, "permission": row.permission})
    return {**base, "knowledge_bases": sorted(access.values(), key=lambda e: e["name"])}


# ---- write tools ------------------------------------------------------------------------


class CreateUserArgs(Args):
    username: str = Field(min_length=1, max_length=128, description="登录账号，建议小写")
    display_name: str = Field(min_length=1, max_length=128, description="姓名")
    employee_no: str | None = Field(None, max_length=64, description="工号")
    email: str | None = None
    mobile: str | None = None
    job_title: str | None = None
    department: str | None = Field(None, description="主部门完整路径")


async def preview_create_user(
    a: AgentContext, args: CreateUserArgs, planned: Planned
) -> StepPreview:
    key = args.username.lower()
    if key in planned.usernames or await a.resolver.users_matching(args.username):
        raise ResolveError("username_taken", args.username)
    warnings = []
    if args.employee_no:
        for other in await a.resolver.users_matching(args.employee_no):
            if other.employee_no == args.employee_no:
                warnings.append({"code": "employee_no_taken", "user": user_label(other)})
    dept_path = "-"
    if args.department:
        dept_path = await a.resolver.department_or_planned(args.department, planned)
    label = args.display_name
    detail = " · ".join(p for p in (args.username, args.employee_no) if p)
    label = f"{label}（{detail}）"
    planned.usernames[key] = label
    if args.employee_no:
        planned.usernames.setdefault(args.employee_no.lower(), label)
    return StepPreview({"user": label, "department": dept_path}, warnings)


async def run_create_user(a: AgentContext, args: CreateUserArgs) -> dict[str, Any]:
    dept_id = (await a.resolver.department(args.department))[0].id if args.department else None
    user = await a.users().create(
        UserCreate(
            username=args.username,
            display_name=args.display_name,
            employee_no=args.employee_no,
            email=args.email or None,
            mobile=args.mobile,
            job_title=args.job_title,
            department_id=dept_id,
        )
    )
    return {"user": user_label(user)}


async def preview_password_login(a: AgentContext, args: UserArgs, planned: Planned) -> StepPreview:
    _, label = await a.resolver.user_or_planned(args.user, planned)
    return StepPreview({"user": label})


async def run_password_login(a: AgentContext, args: UserArgs) -> dict[str, Any]:
    user = await a.resolver.user(args.user)
    result = await PasswordLoginService(
        a.session, a.ctx, a.authz_cache, settings=a.settings, http=a.http
    ).open(user.id)
    return {
        "user": user_label(user),
        "username": result.username,
        "temporary_password": result.temporary_password,
    }


class GroupUsersArgs(Args):
    group: str = Field(description="用户组名称")
    users: list[str] = Field(min_length=1, max_length=200, description="账号或工号列表")


async def _group_label(a: AgentContext, key: str, planned: Planned) -> tuple[str | None, str]:
    if key.strip() in planned.groups:
        return None, key.strip()
    group = await a.resolver.group(key)
    return group.id, group.name


async def preview_add_to_group(
    a: AgentContext, args: GroupUsersArgs, planned: Planned
) -> StepPreview:
    group_id, group_name = await _group_label(a, args.group, planned)
    members = (
        set(await GroupRepository(a.session).list_member_ids(a.ctx.org_id, group_id))
        if group_id
        else set()
    )
    labels: list[str] = []
    already: list[str] = []
    for key in args.users:
        user, label = await a.resolver.user_or_planned(key, planned)
        (already if user and user.id in members else labels).append(label)
    warnings = [{"code": "already_member", "users": "、".join(already)}] if already else []
    if not labels:
        raise ResolveError("all_already_members", group_name)
    return StepPreview({"group": group_name, "users": "、".join(labels)}, warnings)


async def run_add_to_group(a: AgentContext, args: GroupUsersArgs) -> dict[str, Any]:
    group = await a.resolver.group(args.group)
    repo = GroupRepository(a.session)
    current = set(await repo.list_member_ids(a.ctx.org_id, group.id))
    added = [await a.resolver.user(k) for k in args.users]
    await a.groups().set_members(group.id, sorted(current | {u.id for u in added}))
    return {"group": group.name, "users": "、".join(user_label(u) for u in added)}


async def preview_remove_from_group(
    a: AgentContext, args: GroupUsersArgs, planned: Planned
) -> StepPreview:
    group = await a.resolver.group(args.group)
    members = set(await GroupRepository(a.session).list_member_ids(a.ctx.org_id, group.id))
    labels: list[str] = []
    missing: list[str] = []
    for key in args.users:
        user = await a.resolver.user(key)
        (labels if user.id in members else missing).append(user_label(user))
    if not labels:
        raise ResolveError("none_members", group.name)
    warnings = [{"code": "not_member", "users": "、".join(missing)}] if missing else []
    return StepPreview({"group": group.name, "users": "、".join(labels)}, warnings)


async def run_remove_from_group(a: AgentContext, args: GroupUsersArgs) -> dict[str, Any]:
    group = await a.resolver.group(args.group)
    current = set(await GroupRepository(a.session).list_member_ids(a.ctx.org_id, group.id))
    removed = [await a.resolver.user(k) for k in args.users]
    await a.groups().set_members(group.id, sorted(current - {u.id for u in removed}))
    return {"group": group.name, "users": "、".join(user_label(u) for u in removed)}


class AssignRolesArgs(Args):
    users: list[str] = Field(min_length=1, max_length=200, description="账号或工号列表")
    roles: list[str] = Field(min_length=1, max_length=10, description="角色代码，如 kb_editor")


async def _roles_or_planned(
    a: AgentContext, keys: list[str], planned: Planned
) -> list[tuple[str, list[str]]]:
    """(label, permission codes) of existing roles or roles created earlier in the plan."""
    out: list[tuple[str, list[str]]] = []
    existing = []
    for key in keys:
        hit = planned.roles.get(key.strip().lower())
        if hit is not None:
            out.append(hit)
        else:
            existing.append(await a.resolver.role(key))
    perms = await RoleRepository(a.session).permission_codes_by_role(
        a.ctx.org_id, [r.id for r in existing]
    )
    return out + [(f"{r.name}({r.code})", perms[r.id]) for r in existing]


async def preview_assign_roles(
    a: AgentContext, args: AssignRolesArgs, planned: Planned
) -> StepPreview:
    roles = await _roles_or_planned(a, args.roles, planned)
    users = [(await a.resolver.user_or_planned(k, planned))[1] for k in args.users]
    warnings = [
        {"code": "privileged_role", "role": label} for label, perms in roles if is_privileged(perms)
    ]
    return StepPreview(
        {"users": "、".join(users), "roles": "、".join(label for label, _ in roles)}, warnings
    )


async def run_assign_roles(a: AgentContext, args: AssignRolesArgs) -> dict[str, Any]:
    roles = [await a.resolver.role(r) for r in args.roles]
    repo = UserRepository(a.session)
    labels = []
    for key in args.users:
        user = await a.resolver.user(key)
        current = {r.id for r in await repo.list_roles(a.ctx.org_id, user.id)}
        await a.users().set_roles(user.id, sorted(current | {r.id for r in roles}))
        labels.append(user_label(user))
    return {"users": "、".join(labels), "roles": "、".join(r.name for r in roles)}


class CreateGroupArgs(Args):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None


async def preview_create_group(
    a: AgentContext, args: CreateGroupArgs, planned: Planned
) -> StepPreview:
    if args.name in planned.groups or await a.resolver.group_exists(args.name):
        raise ResolveError("group_exists", args.name)
    planned.groups.add(args.name)
    return StepPreview({"group": args.name, "description": args.description or "-"})


async def run_create_group(a: AgentContext, args: CreateGroupArgs) -> dict[str, Any]:
    group = await a.groups().create(GroupCreate(name=args.name, description=args.description))
    return {"group": group.name}


class CreateKbArgs(Args):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None
    visibility: Literal["restricted", "org"] = Field(
        "restricted", description="restricted=仅授权成员，org=组织内所有人可读"
    )


async def preview_create_kb(a: AgentContext, args: CreateKbArgs, planned: Planned) -> StepPreview:
    if args.name in planned.kbs or await a.resolver.knowledge_base_exists(args.name):
        raise ResolveError("kb_exists", args.name)
    planned.kbs.add(args.name)
    return StepPreview({"knowledge_base": args.name, "visibility": args.visibility})


async def run_create_kb(a: AgentContext, args: CreateKbArgs) -> dict[str, Any]:
    kb = await a.kbs().create(
        KnowledgeBaseCreate(
            name=args.name, description=args.description, visibility=args.visibility
        )
    )
    return {"knowledge_base": kb.name}


class GrantKbArgs(Args):
    knowledge_base: str = Field(description="知识库名称")
    principal_type: PrincipalKind = Field(description="user / group / role / dept")
    principal: str = Field(description="账号或工号 / 用户组名称 / 角色代码 / 部门完整路径")
    permission: PermissionName = Field(description="read=只读，edit=编辑，manage=管理")


async def resolve_principal(
    a: AgentContext,
    ptype: str,
    key: str,
    planned: Planned | None,
    *,
    include_inactive: bool = False,
) -> tuple[str | None, str]:
    if ptype == "user":
        if planned is not None:
            user, label = await a.resolver.user_or_planned(key, planned)
            return (user.id if user else None), label
        user = await a.resolver.user(key, include_inactive=include_inactive)
        return user.id, user_label(user)
    if ptype == "group":
        if planned is not None and key.strip() in planned.groups:
            return None, key.strip()
        group = await a.resolver.group(key)
        return group.id, group.name
    if ptype == "role":
        if planned is not None and (hit := planned.roles.get(key.strip().lower())):
            return None, hit[0]
        role = await a.resolver.role(key)
        return role.id, f"{role.name}({role.code})"
    if planned is not None and key.strip() in planned.departments:
        return None, planned.departments[key.strip()]
    dept, path = await a.resolver.department(key)
    return dept.id, path


def _live_entries(
    entries: list[AclEntryOut], skip: tuple[str, str] | None = None
) -> list[AclEntryIn]:
    """Current grants minus those whose principal was deleted (they block ACL validation)."""
    return [
        AclEntryIn(
            principal_type=e.principal_type, principal_id=e.principal_id, permission=e.permission
        )
        for e in entries
        if e.principal_name is not None and (e.principal_type, e.principal_id) != skip
    ]


def _stale_warning(entries: list[AclEntryOut]) -> list[dict[str, str]]:
    stale = sum(1 for e in entries if e.principal_name is None)
    return [{"code": "stale_grants", "count": str(stale)}] if stale else []


async def _require_manage(a: AgentContext, kb: KnowledgeBase) -> None:
    try:
        await KnowledgeAccess(a.session).require_kb(a.ctx.user, kb, AclPermission.MANAGE)
    except PermissionDeniedError as exc:
        raise ResolveError("no_manage_permission", kb.name) from exc


async def preview_grant_kb(a: AgentContext, args: GrantKbArgs, planned: Planned) -> StepPreview:
    warnings: list[dict[str, str]] = []
    pid, label = await resolve_principal(a, args.principal_type, args.principal, planned)
    if args.knowledge_base.strip() in planned.kbs:
        kb_name = args.knowledge_base.strip()
    else:
        kb = await a.resolver.knowledge_base(args.knowledge_base)
        await _require_manage(a, kb)
        kb_name = kb.name
        acl = await a.kbs().get_acl(kb.id)
        warnings += _stale_warning(acl.entries)
        if pid:
            for e in acl.entries:
                if (e.principal_type, e.principal_id) == (args.principal_type, pid):
                    if e.permission == args.permission:
                        raise ResolveError("same_permission", kb.name, principal=label)
                    warnings.append(
                        {"code": "permission_change", "from": e.permission, "to": args.permission}
                    )
    return StepPreview(
        {
            "knowledge_base": kb_name,
            "principal_type": args.principal_type,
            "principal": label,
            "permission": args.permission,
        },
        warnings,
    )


async def run_grant_kb(a: AgentContext, args: GrantKbArgs) -> dict[str, Any]:
    kb = await a.resolver.knowledge_base(args.knowledge_base)
    pid, label = await resolve_principal(a, args.principal_type, args.principal, None)
    assert pid is not None
    svc = a.kbs()
    acl = await svc.get_acl(kb.id)
    entries = _live_entries(acl.entries, skip=(args.principal_type, pid))
    entries.append(
        AclEntryIn(principal_type=args.principal_type, principal_id=pid, permission=args.permission)
    )
    await svc.set_acl(kb.id, KbAclUpdate(visibility=acl.visibility, entries=entries))
    return {"knowledge_base": kb.name, "principal": label, "permission": args.permission}


class KbVisibilityArgs(Args):
    knowledge_base: str = Field(description="知识库名称")
    visibility: Literal["restricted", "org"] = Field(
        description="restricted=仅授权成员，org=组织内所有人可读"
    )


async def preview_kb_visibility(
    a: AgentContext, args: KbVisibilityArgs, planned: Planned
) -> StepPreview:
    if args.knowledge_base.strip() in planned.kbs:
        return StepPreview(
            {"knowledge_base": args.knowledge_base.strip(), "visibility": args.visibility}
        )
    kb = await a.resolver.knowledge_base(args.knowledge_base)
    await _require_manage(a, kb)
    if kb.visibility == args.visibility:
        raise ResolveError("same_visibility", kb.name)
    acl = await a.kbs().get_acl(kb.id)
    return StepPreview(
        {"knowledge_base": kb.name, "visibility": args.visibility}, _stale_warning(acl.entries)
    )


async def run_kb_visibility(a: AgentContext, args: KbVisibilityArgs) -> dict[str, Any]:
    kb = await a.resolver.knowledge_base(args.knowledge_base)
    svc = a.kbs()
    acl = await svc.get_acl(kb.id)
    entries = _live_entries(acl.entries)
    await svc.set_acl(kb.id, KbAclUpdate(visibility=args.visibility, entries=entries))
    return {"knowledge_base": kb.name, "visibility": args.visibility}


class RevokeKbArgs(Args):
    knowledge_base: str = Field(description="知识库名称")
    principal_type: PrincipalKind = Field(description="user / group / role / dept")
    principal: str = Field(description="账号或工号 / 用户组名称 / 角色代码 / 部门完整路径")


async def preview_revoke_kb(a: AgentContext, args: RevokeKbArgs, planned: Planned) -> StepPreview:
    kb = await a.resolver.knowledge_base(args.knowledge_base)
    await _require_manage(a, kb)
    pid, label = await resolve_principal(
        a, args.principal_type, args.principal, None, include_inactive=True
    )
    acl = await a.kbs().get_acl(kb.id)
    entry = next(
        (
            e
            for e in acl.entries
            if (e.principal_type, e.principal_id) == (args.principal_type, pid)
        ),
        None,
    )
    if entry is None:
        raise ResolveError("no_grant", kb.name, principal=label)
    warnings = _stale_warning(acl.entries)
    if acl.visibility == KbVisibility.ORG.value:
        warnings.append({"code": "still_org_readable"})
    if pid == a.ctx.user.id and entry.permission == "manage":
        warnings.append({"code": "self_manage_revoke"})
    return StepPreview(
        {
            "knowledge_base": kb.name,
            "principal_type": args.principal_type,
            "principal": label,
            "permission": entry.permission,
        },
        warnings,
    )


async def run_revoke_kb(a: AgentContext, args: RevokeKbArgs) -> dict[str, Any]:
    kb = await a.resolver.knowledge_base(args.knowledge_base)
    pid, label = await resolve_principal(
        a, args.principal_type, args.principal, None, include_inactive=True
    )
    assert pid is not None
    svc = a.kbs()
    acl = await svc.get_acl(kb.id)
    entries = _live_entries(acl.entries, skip=(args.principal_type, pid))
    await svc.set_acl(kb.id, KbAclUpdate(visibility=acl.visibility, entries=entries))
    return {"knowledge_base": kb.name, "principal": label}


async def preview_remove_roles(
    a: AgentContext, args: AssignRolesArgs, planned: Planned
) -> StepPreview:
    roles = [await a.resolver.role(r) for r in args.roles]
    wanted = {r.id for r in roles}
    roles_label = "、".join(f"{r.name}({r.code})" for r in roles)
    perms = await RoleRepository(a.session).permission_codes_by_role(
        a.ctx.org_id, [r.id for r in roles]
    )
    repo = UserRepository(a.session)
    labels: list[str] = []
    without: list[str] = []
    warnings: list[dict[str, str]] = []
    for key in args.users:
        user = await a.resolver.user(key, include_inactive=True)
        have = {r.id for r in await repo.list_roles(a.ctx.org_id, user.id)}
        (labels if have & wanted else without).append(user_label(user))
        if user.id == a.ctx.user.id and any(is_privileged(perms[i]) for i in have & wanted):
            warnings.append({"code": "self_privilege_removal"})
    if not labels:
        raise ResolveError("none_have_roles", roles_label)
    if without:
        warnings.append({"code": "not_have_roles", "users": "、".join(without)})
    return StepPreview({"users": "、".join(labels), "roles": roles_label}, warnings)


async def run_remove_roles(a: AgentContext, args: AssignRolesArgs) -> dict[str, Any]:
    roles = [await a.resolver.role(r) for r in args.roles]
    wanted = {r.id for r in roles}
    repo = UserRepository(a.session)
    labels = []
    for key in args.users:
        user = await a.resolver.user(key, include_inactive=True)
        current = {r.id for r in await repo.list_roles(a.ctx.org_id, user.id)}
        if current & wanted:
            await a.users().set_roles(user.id, sorted(current - wanted))
            labels.append(user_label(user))
    return {"users": "、".join(labels), "roles": "、".join(r.name for r in roles)}


class UsersArgs(Args):
    users: list[str] = Field(min_length=1, max_length=200, description="账号或工号列表")


def _preview_active(active: bool) -> PreviewFn:
    async def preview(a: AgentContext, args: UsersArgs, planned: Planned) -> StepPreview:
        labels: list[str] = []
        unchanged: list[str] = []
        for key in args.users:
            user = await a.resolver.user(key, include_inactive=True)
            if not active and user.id == a.ctx.user.id:
                raise ResolveError("cannot_disable_self", user_label(user))
            (unchanged if user.is_active == active else labels).append(user_label(user))
        if not labels:
            raise ResolveError(
                "already_enabled" if active else "already_disabled", "、".join(unchanged)
            )
        warnings = (
            [{"code": "already_in_state", "users": "、".join(unchanged)}] if unchanged else []
        )
        return StepPreview({"users": "、".join(labels)}, warnings)

    return preview


def _run_active(active: bool) -> RunFn:
    async def run(a: AgentContext, args: UsersArgs) -> dict[str, Any]:
        svc = a.users()
        labels = []
        for key in args.users:
            user = await a.resolver.user(key, include_inactive=True)
            if user.is_active == active:
                continue
            if active:
                await svc.update(user.id, UserUpdate(is_active=True))
            else:
                await svc.disable(user.id)
            labels.append(user_label(user))
        return {"users": "、".join(labels)}

    return run


class CreateDeptArgs(Args):
    name: str = Field(min_length=1, max_length=128, description="部门名称")
    parent: str | None = Field(None, description="上级部门完整路径或唯一名称；留空为顶级部门")


def _child_path(parent_path: str | None, name: str) -> str:
    return f"{parent_path} / {name}" if parent_path else name


async def preview_create_dept(
    a: AgentContext, args: CreateDeptArgs, planned: Planned
) -> StepPreview:
    parent_path = (
        await a.resolver.department_or_planned(args.parent, planned) if args.parent else None
    )
    path = _child_path(parent_path, args.name)
    if (
        path in planned.departments.values()
        or path in (await a.resolver.department_paths()).values()
    ):
        raise ResolveError("dept_exists", path)
    planned.departments[path] = path
    planned.departments.setdefault(args.name, path)
    synced = await a.session.scalar(
        select(Department.id)
        .where(Department.org_id == a.ctx.org_id, Department.source != LOCAL_SOURCE)
        .limit(1)
    )
    warnings = [{"code": "directory_synced_org"}] if synced else []
    return StepPreview({"department": path, "parent": parent_path or "-"}, warnings)


async def run_create_dept(a: AgentContext, args: CreateDeptArgs) -> dict[str, Any]:
    parent_id = (await a.resolver.department(args.parent))[0].id if args.parent else None
    await a.departments().create(DepartmentCreate(name=args.name, parent_id=parent_id))
    a.resolver.reset_departments()
    parent_path = (await a.resolver.department(args.parent))[1] if args.parent else None
    return {"department": _child_path(parent_path, args.name)}


class RenameDeptArgs(Args):
    department: str = Field(description="部门完整路径或唯一名称")
    name: str = Field(min_length=1, max_length=128, description="新名称")


async def _local_department(a: AgentContext, key: str) -> tuple[Department, str]:
    dept, path = await a.resolver.department(key)
    if dept.source != LOCAL_SOURCE:
        raise ResolveError("dept_managed", path)
    return dept, path


async def preview_rename_dept(
    a: AgentContext, args: RenameDeptArgs, planned: Planned
) -> StepPreview:
    dept, path = await _local_department(a, args.department)
    if dept.name == args.name:
        raise ResolveError("dept_no_change", path)
    parent = path.rsplit(" / ", 1)[0] if " / " in path else None
    if _child_path(parent, args.name) in (await a.resolver.department_paths()).values():
        raise ResolveError("dept_exists", _child_path(parent, args.name))
    return StepPreview({"department": path, "name": args.name})


async def run_rename_dept(a: AgentContext, args: RenameDeptArgs) -> dict[str, Any]:
    dept, path = await a.resolver.department(args.department)
    await a.departments().update(dept.id, DepartmentUpdate(name=args.name))
    a.resolver.reset_departments()
    return {"department": path, "name": args.name}


class MoveDeptArgs(Args):
    department: str = Field(description="要移动的部门完整路径或唯一名称")
    parent: str | None = Field(None, description="新的上级部门；留空表示移为顶级部门")


async def preview_move_dept(a: AgentContext, args: MoveDeptArgs, planned: Planned) -> StepPreview:
    dept, path = await _local_department(a, args.department)
    parent: Department | None = None
    parent_path = None
    if args.parent:
        parent, parent_path = await a.resolver.department(args.parent)
        if parent.path.startswith(dept.path):
            raise ResolveError("dept_cycle", path)
    if (parent.id if parent else None) == dept.parent_id:
        raise ResolveError("dept_no_change", path)
    subtree = [d.id for d in await a.departments().repo.list_subtree(a.ctx.org_id, dept.path)]
    users = await UserRepository(a.session).count_in_departments(a.ctx.org_id, subtree)
    return StepPreview(
        {"department": path, "parent": parent_path or "-"},
        [{"code": "dept_move_users", "count": str(users)}] if users else [],
    )


async def run_move_dept(a: AgentContext, args: MoveDeptArgs) -> dict[str, Any]:
    dept, path = await a.resolver.department(args.department)
    parent_id = (await a.resolver.department(args.parent))[0].id if args.parent else None
    await a.departments().update(dept.id, DepartmentUpdate.model_validate({"parent_id": parent_id}))
    a.resolver.reset_departments()
    return {"department": path}


PERMISSION_HELP = "，".join(f"{code}={label}" for code, label in PERMISSION_CATALOG.items())


def _check_codes(codes: list[str]) -> list[str]:
    for code in codes:
        if code not in PERMISSION_CATALOG:
            close = [c for c in PERMISSION_CATALOG if code.split(":")[0] in c][:8]
            raise ResolveError("permission_unknown", code, close or list(PERMISSION_CATALOG)[:8])
    return sorted(set(codes))


class CreateRoleArgs(Args):
    code: str = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z0-9_\-:]+$")
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None
    permissions: list[str] = Field(default_factory=list, max_length=40)


async def preview_create_role(
    a: AgentContext, args: CreateRoleArgs, planned: Planned
) -> StepPreview:
    if args.code.lower() in planned.roles or await a.resolver.role_exists(args.code):
        raise ResolveError("role_exists", args.code)
    codes = _check_codes(args.permissions)
    label = f"{args.name}({args.code})"
    planned.roles[args.code.lower()] = (label, codes)
    planned.roles.setdefault(args.name.lower(), (label, codes))
    privileged = [c for c in codes if is_privileged([c])]
    warnings = (
        [{"code": "privileged_permission", "permissions": "、".join(privileged)}]
        if privileged
        else []
    )
    return StepPreview({"role": label, "permissions": "、".join(codes) or "-"}, warnings)


async def run_create_role(a: AgentContext, args: CreateRoleArgs) -> dict[str, Any]:
    svc = a.roles()
    role = await svc.create(
        RoleCreate(code=args.code, name=args.name, description=args.description)
    )
    if args.permissions:
        await svc.set_permissions(role.id, _check_codes(args.permissions))
    return {"role": f"{role.name}({role.code})"}


class RolePermissionsArgs(Args):
    role: str = Field(description="角色代码或名称")
    add: list[str] = Field(default_factory=list, max_length=40)
    remove: list[str] = Field(default_factory=list, max_length=40)


async def _role_users(a: AgentContext, role_id: str) -> int:
    count = await a.session.scalar(
        select(func.count()).where(UserRole.org_id == a.ctx.org_id, UserRole.role_id == role_id)
    )
    return int(count or 0)


async def preview_role_permissions(
    a: AgentContext, args: RolePermissionsArgs, planned: Planned
) -> StepPreview:
    role = await a.resolver.role(args.role)
    label = f"{role.name}({role.code})"
    add, remove = _check_codes(args.add), _check_codes(args.remove)
    before = set(await a.roles().permission_codes(role))
    after = (before | set(add)) - set(remove)
    if after == before:
        raise ResolveError("same_permissions", label)
    if role.is_default and is_privileged(after):
        raise ResolveError("default_role_privileged", label)
    added, removed = sorted(after - before), sorted(before - after)
    users = await _role_users(a, role.id)
    warnings: list[dict[str, str]] = []
    if users:
        warnings.append({"code": "role_users", "count": str(users)})
    privileged = [c for c in added if is_privileged([c])]
    if privileged:
        warnings.append({"code": "privileged_permission", "permissions": "、".join(privileged)})
    return StepPreview(
        {
            "role": label,
            "added": "、".join(added) or "-",
            "removed": "、".join(removed) or "-",
            "users": str(users),
        },
        warnings,
    )


async def run_role_permissions(a: AgentContext, args: RolePermissionsArgs) -> dict[str, Any]:
    role = await a.resolver.role(args.role)
    svc = a.roles()
    before = set(await svc.permission_codes(role))
    after = (before | set(_check_codes(args.add))) - set(_check_codes(args.remove))
    await svc.set_permissions(role.id, sorted(after))
    return {"role": f"{role.name}({role.code})"}


ADMIN_ANY = ("admin:user", "admin:group", "admin:role", "admin:dept")
# Who may open the assistant at all; each task still checks its own tool permissions.
AGENT_ACCESS = (
    *ADMIN_ANY,
    "admin:audit",
    "admin:model",
    "admin:retrieval",
    "admin:openapi",
    "admin:index",
)

TOOLS: dict[str, Tool] = {
    t.name: t
    for t in (
        Tool(
            "search_users",
            "read",
            "查询用户：返回账号、姓名、工号、部门、角色、是否停用。",
            SearchUsersArgs,
            ("admin:user", "admin:group"),
            search_users,
        ),
        Tool(
            "search_departments",
            "read",
            "按名称查询部门，返回完整路径（同名部门用路径区分）。",
            SearchDepartmentsArgs,
            ADMIN_ANY,
            search_departments,
        ),
        Tool("list_groups", "read", "列出用户组及成员数。", KeywordArgs, ADMIN_ANY, list_groups),
        Tool(
            "list_group_members",
            "read",
            "列出某个用户组的成员。",
            GroupArgs,
            ("admin:group", "admin:user"),
            list_group_members,
        ),
        Tool(
            "list_roles",
            "read",
            "列出角色（代码、名称、功能权限、是否默认角色）。",
            NoArgs,
            ADMIN_ANY,
            list_roles,
        ),
        Tool(
            "search_knowledge_bases",
            "read",
            "查询知识库（名称、可见范围、文档数）。",
            KeywordArgs,
            ("kb:read",),
            search_knowledge_bases,
        ),
        Tool(
            "get_kb_access",
            "read",
            "查看某个知识库的可见范围和授权列表（谁有只读 / 编辑 / 管理）。",
            KbArgs,
            ("kb:update",),
            get_kb_access,
        ),
        Tool(
            "explain_user_access",
            "read",
            "说明某个用户的角色、功能权限，以及能访问哪些知识库、权限来自哪里。",
            UserArgs,
            ("admin:user",),
            explain_user_access,
        ),
        Tool(
            "create_user",
            "write",
            "预建用户（首次登录时自动关联 Keycloak 账号）。",
            CreateUserArgs,
            ("admin:user",),
            run_create_user,
            preview_create_user,
        ),
        Tool(
            "open_password_login",
            "write",
            "为用户开通账号密码登录并生成临时密码（首次登录须修改）。",
            UserArgs,
            ("admin:user",),
            run_password_login,
            preview_password_login,
        ),
        Tool(
            "add_to_group",
            "write",
            "把用户加入用户组。",
            GroupUsersArgs,
            ("admin:group",),
            run_add_to_group,
            preview_add_to_group,
        ),
        Tool(
            "remove_from_group",
            "write",
            "把用户移出用户组。",
            GroupUsersArgs,
            ("admin:group",),
            run_remove_from_group,
            preview_remove_from_group,
        ),
        Tool(
            "assign_roles",
            "write",
            "给用户追加角色（保留已有角色）。",
            AssignRolesArgs,
            ("admin:role",),
            run_assign_roles,
            preview_assign_roles,
        ),
        Tool(
            "create_group",
            "write",
            "新建用户组。",
            CreateGroupArgs,
            ("admin:group",),
            run_create_group,
            preview_create_group,
        ),
        Tool(
            "create_knowledge_base",
            "write",
            "新建知识库（创建者自动获得管理权限）。",
            CreateKbArgs,
            ("kb:create",),
            run_create_kb,
            preview_create_kb,
        ),
        Tool(
            "grant_kb_access",
            "write",
            "给用户 / 用户组 / 角色 / 部门授予知识库权限，或调整已有权限级别。部门授权含下级部门。",
            GrantKbArgs,
            ("kb:update",),
            run_grant_kb,
            preview_grant_kb,
        ),
        Tool(
            "set_kb_visibility",
            "write",
            "修改知识库可见范围（restricted 仅授权成员 / org 组织内所有人可读）。",
            KbVisibilityArgs,
            ("kb:update",),
            run_kb_visibility,
            preview_kb_visibility,
        ),
        Tool(
            "revoke_kb_access",
            "write",
            "撤销用户 / 用户组 / 角色 / 部门在知识库上的单独授权。",
            RevokeKbArgs,
            ("kb:update",),
            run_revoke_kb,
            preview_revoke_kb,
        ),
        Tool(
            "remove_roles",
            "write",
            "移除用户的角色（保留其他角色）。",
            AssignRolesArgs,
            ("admin:role",),
            run_remove_roles,
            preview_remove_roles,
        ),
        Tool(
            "disable_users",
            "write",
            "停用账号（停用后无法登录，授权保留）。",
            UsersArgs,
            ("admin:user",),
            _run_active(False),
            _preview_active(False),
        ),
        Tool(
            "enable_users",
            "write",
            "重新启用已停用的账号。",
            UsersArgs,
            ("admin:user",),
            _run_active(True),
            _preview_active(True),
        ),
        Tool(
            "create_department",
            "write",
            "新建部门（本地维护）。",
            CreateDeptArgs,
            ("admin:dept",),
            run_create_dept,
            preview_create_dept,
        ),
        Tool(
            "rename_department",
            "write",
            "修改本地部门的名称。",
            RenameDeptArgs,
            ("admin:dept",),
            run_rename_dept,
            preview_rename_dept,
        ),
        Tool(
            "move_department",
            "write",
            "把本地部门移到另一个上级部门下（含下级部门与成员）。",
            MoveDeptArgs,
            ("admin:dept",),
            run_move_dept,
            preview_move_dept,
        ),
        Tool(
            "create_role",
            "write",
            "新建角色，可同时设置功能权限。",
            CreateRoleArgs,
            ("admin:role",),
            run_create_role,
            preview_create_role,
        ),
        Tool(
            "set_role_permissions",
            "write",
            "为角色增加或去掉功能权限（影响拥有该角色的所有用户）。",
            RolePermissionsArgs,
            ("admin:role",),
            run_role_permissions,
            preview_role_permissions,
        ),
    )
}
