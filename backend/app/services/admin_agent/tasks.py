"""Task templates of the admin assistant.

The model only recognizes *which* tasks the admin asked for and fills their slots. The steps of
every change are expanded here by code, in a fixed order; the model never composes plans.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import Field, model_validator

from app.services.admin_agent.ops import (
    AuditArgs,
    ClientArgs,
    EvalCompareArgs,
    EvalRunsArgs,
    StartEvalArgs,
)
from app.services.admin_agent.resolve import ResolveError
from app.services.admin_agent.tools import (
    PERMISSION_HELP,
    TOOLS,
    AgentContext,
    Args,
    CreateDeptArgs,
    MoveDeptArgs,
    PermissionName,
    PrincipalKind,
    RenameDeptArgs,
)


def _as_list(data: Any, plural: str, *singulars: str) -> Any:
    """Accept `user: "x"` / `users: "x"` for `users: ["x"]` (deterministic, not a guess)."""
    if not isinstance(data, dict):
        return data
    data = dict(data)
    for singular in singulars:
        if singular in data and plural not in data:
            data[plural] = data.pop(singular)
    if isinstance(data.get(plural), str):
        data[plural] = [data[plural]]
    return data


class KbGrant(Args):
    knowledge_base: str
    permission: PermissionName = "read"


class PrincipalGrant(Args):
    principal_type: PrincipalKind
    principal: str
    permission: PermissionName


# ---- query slots --------------------------------------------------------------------------


class FindUsersSlots(Args):
    keyword: str | None = Field(None, description="username / name / email / employee no.")
    department: str | None = Field(None, description="department name or full path")


class FindDepartmentsSlots(Args):
    keyword: str = Field(description="department name or part of its path")


class KeywordSlots(Args):
    keyword: str | None = None


class GroupSlots(Args):
    group: str


class NoSlots(Args):
    pass


class KbSlots(Args):
    knowledge_base: str


class UserSlots(Args):
    user: str = Field(description="username, employee no. or (unique) display name")


# ---- change slots -------------------------------------------------------------------------


class OnboardUserSlots(Args):
    username: str = Field(description="login account; required, never invent it")
    display_name: str = Field(description="person's name; required")
    employee_no: str | None = None
    email: str | None = None
    mobile: str | None = None
    job_title: str | None = None
    department: str | None = None
    groups: list[str] = Field(default_factory=list, description="existing user groups to join")
    roles: list[str] = Field(default_factory=list, description="role codes or names")
    kb_grants: list[KbGrant] = Field(default_factory=list)
    password_login: bool = Field(False, description="also enable password sign-in")


class MembersSlots(Args):
    group: str
    users: list[str] = Field(default_factory=list, description="usernames / employee nos / names")
    departments: list[str] = Field(
        default_factory=list, description="add every active member of these departments"
    )

    @model_validator(mode="before")
    @classmethod
    def _lists(cls, data: Any) -> Any:
        return _as_list(_as_list(data, "users", "user"), "departments", "department")

    @model_validator(mode="after")
    def _someone(self) -> "MembersSlots":
        if not self.users and not self.departments:
            raise ValueError("users")
        return self


class AddToGroupSlots(MembersSlots):
    create_group: bool = Field(False, description="the admin asked to create the group")


class AssignRolesSlots(Args):
    roles: list[str] = Field(min_length=1)
    users: list[str] = Field(default_factory=list)
    departments: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _lists(cls, data: Any) -> Any:
        data = _as_list(_as_list(data, "users", "user"), "departments", "department")
        return _as_list(data, "roles", "role")

    @model_validator(mode="after")
    def _someone(self) -> "AssignRolesSlots":
        if not self.users and not self.departments:
            raise ValueError("users")
        return self


class CreateGroupSlots(Args):
    name: str
    description: str | None = None


class CreateKbSlots(Args):
    name: str
    description: str | None = None
    visibility: Literal["restricted", "org"] = "restricted"


class GrantKbSlots(Args):
    knowledge_base: str
    grants: list[PrincipalGrant] = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def _flat(cls, data: Any) -> Any:
        """A single flat grant ({principal_type, principal, permission}) becomes a list of one."""
        if isinstance(data, dict) and "grants" not in data and "principal" in data:
            data = dict(data)
            data["grants"] = [
                {k: data.pop(k) for k in ("principal_type", "principal", "permission") if k in data}
            ]
        if isinstance(data, dict) and isinstance(data.get("grants"), dict):
            data = {**data, "grants": [data["grants"]]}
        return data


class KbVisibilitySlots(Args):
    knowledge_base: str
    visibility: Literal["restricted", "org"]


class PasswordLoginSlots(Args):
    users: list[str] = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def _lists(cls, data: Any) -> Any:
        return _as_list(data, "users", "user")


class UsersSlots(PasswordLoginSlots):
    pass


class PrincipalRef(Args):
    principal_type: PrincipalKind
    principal: str


class RevokeKbSlots(Args):
    knowledge_base: str
    principals: list[PrincipalRef] = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def _flat(cls, data: Any) -> Any:
        """A single flat principal ({principal_type, principal}) becomes a list of one."""
        if isinstance(data, dict) and "principals" not in data and "principal" in data:
            data = dict(data)
            data["principals"] = [
                {k: data.pop(k) for k in ("principal_type", "principal") if k in data}
            ]
        if isinstance(data, dict) and isinstance(data.get("principals"), dict):
            data = {**data, "principals": [data["principals"]]}
        return data


class CreateRoleSlots(Args):
    code: str = Field(description="role code: letters, digits, _ - : (never invent it)")
    name: str
    description: str | None = None
    permissions: list[str] = Field(
        default_factory=list, description=f"permission codes: {PERMISSION_HELP}"
    )

    @model_validator(mode="before")
    @classmethod
    def _lists(cls, data: Any) -> Any:
        return _as_list(data, "permissions", "permission")


class RolePermissionSlots(Args):
    role: str = Field(description="role code or name")
    add: list[str] = Field(default_factory=list, description=f"codes to add: {PERMISSION_HELP}")
    remove: list[str] = Field(default_factory=list, description="codes to remove (same codes)")

    @model_validator(mode="before")
    @classmethod
    def _lists(cls, data: Any) -> Any:
        return _as_list(_as_list(data, "add"), "remove")

    @model_validator(mode="after")
    def _change(self) -> "RolePermissionSlots":
        if not self.add and not self.remove:
            raise ValueError("add")
        return self


Step = tuple[str, dict[str, Any]]
Expander = Callable[[AgentContext, Any], Awaitable[list[Step]]]


@dataclass(frozen=True)
class TaskSpec:
    name: str
    kind: Literal["query", "change"]
    description: str
    slots: type[Args]
    tools: tuple[str, ...]
    # query: (tool, args) to run; change: steps to preview / execute
    expand: Expander

    def permissions_ok(self, a: AgentContext) -> bool:
        return all(a.ctx.user.has_any_permission(*TOOLS[t].permissions) for t in self.tools)


async def _department_members(a: AgentContext, departments: list[str]) -> list[str]:
    usernames: list[str] = []
    for key in departments:
        dept, path = await a.resolver.department(key)
        page = await a.users().search(page=1, size=500, department_id=dept.id, is_active=True)
        if not page.items:
            raise ResolveError("department_empty", path)
        usernames += [u.username for u in page.items]
    return usernames


def _query(tool: str, mapping: Callable[[Any], dict[str, Any]]) -> Expander:
    async def expand(_: AgentContext, slots: Any) -> list[Step]:
        return [(tool, mapping(slots))]

    return expand


async def _onboard(a: AgentContext, s: OnboardUserSlots) -> list[Step]:
    steps: list[Step] = [
        (
            "create_user",
            s.model_dump(
                include={
                    "username",
                    "display_name",
                    "employee_no",
                    "email",
                    "mobile",
                    "job_title",
                    "department",
                },
                exclude_none=True,
            ),
        )
    ]
    steps += [("add_to_group", {"group": g, "users": [s.username]}) for g in s.groups]
    if s.roles:
        steps.append(("assign_roles", {"users": [s.username], "roles": s.roles}))
    steps += [
        (
            "grant_kb_access",
            {
                "knowledge_base": g.knowledge_base,
                "principal_type": "user",
                "principal": s.username,
                "permission": g.permission,
            },
        )
        for g in s.kb_grants
    ]
    if s.password_login:
        steps.append(("open_password_login", {"user": s.username}))
    return steps


async def _members(a: AgentContext, s: MembersSlots) -> list[str]:
    users = list(s.users) + await _department_members(a, s.departments)
    return list(dict.fromkeys(users))


async def _add_to_group(a: AgentContext, s: AddToGroupSlots) -> list[Step]:
    steps: list[Step] = []
    if s.create_group and not await a.resolver.group_exists(s.group):
        steps.append(("create_group", {"name": s.group}))
    steps.append(("add_to_group", {"group": s.group, "users": await _members(a, s)}))
    return steps


async def _remove_from_group(a: AgentContext, s: MembersSlots) -> list[Step]:
    return [("remove_from_group", {"group": s.group, "users": await _members(a, s)})]


async def _assign_roles(a: AgentContext, s: AssignRolesSlots) -> list[Step]:
    users = list(dict.fromkeys(list(s.users) + await _department_members(a, s.departments)))
    return [("assign_roles", {"users": users, "roles": s.roles})]


async def _create_group(_: AgentContext, s: CreateGroupSlots) -> list[Step]:
    return [("create_group", s.model_dump(exclude_none=True))]


async def _create_kb(_: AgentContext, s: CreateKbSlots) -> list[Step]:
    return [("create_knowledge_base", s.model_dump(exclude_none=True))]


async def _grant(_: AgentContext, s: GrantKbSlots) -> list[Step]:
    return [
        ("grant_kb_access", {"knowledge_base": s.knowledge_base, **g.model_dump()})
        for g in s.grants
    ]


async def _visibility(_: AgentContext, s: KbVisibilitySlots) -> list[Step]:
    return [("set_kb_visibility", s.model_dump())]


async def _password(_: AgentContext, s: PasswordLoginSlots) -> list[Step]:
    return [("open_password_login", {"user": u}) for u in dict.fromkeys(s.users)]


async def _revoke(_: AgentContext, s: RevokeKbSlots) -> list[Step]:
    return [
        ("revoke_kb_access", {"knowledge_base": s.knowledge_base, **p.model_dump()})
        for p in s.principals
    ]


async def _remove_roles(a: AgentContext, s: AssignRolesSlots) -> list[Step]:
    users = list(dict.fromkeys(list(s.users) + await _department_members(a, s.departments)))
    return [("remove_roles", {"users": users, "roles": s.roles})]


def _users_step(tool: str) -> Expander:
    async def expand(_: AgentContext, s: UsersSlots) -> list[Step]:
        return [(tool, {"users": list(dict.fromkeys(s.users))})]

    return expand


def _single(tool: str) -> Expander:
    async def expand(_: AgentContext, s: Args) -> list[Step]:
        return [(tool, s.model_dump(exclude_none=True))]

    return expand


TASKS: dict[str, TaskSpec] = {
    t.name: t
    for t in (
        # ---- queries
        TaskSpec(
            "find_users",
            "query",
            "Look up users (account, name, employee no., departments, roles, status).",
            FindUsersSlots,
            ("search_users",),
            _query("search_users", lambda s: s.model_dump(exclude_none=True)),
        ),
        TaskSpec(
            "find_departments",
            "query",
            "Look up departments by name; returns full paths.",
            FindDepartmentsSlots,
            ("search_departments",),
            _query("search_departments", lambda s: s.model_dump()),
        ),
        TaskSpec(
            "list_groups",
            "query",
            "List user groups with member counts.",
            KeywordSlots,
            ("list_groups",),
            _query("list_groups", lambda s: s.model_dump(exclude_none=True)),
        ),
        TaskSpec(
            "group_members",
            "query",
            "List the members of a user group.",
            GroupSlots,
            ("list_group_members",),
            _query("list_group_members", lambda s: s.model_dump()),
        ),
        TaskSpec(
            "list_roles",
            "query",
            "List roles and their feature permissions.",
            NoSlots,
            ("list_roles",),
            _query("list_roles", lambda s: {}),
        ),
        TaskSpec(
            "list_knowledge_bases",
            "query",
            "List knowledge bases (visibility, document count).",
            KeywordSlots,
            ("search_knowledge_bases",),
            _query("search_knowledge_bases", lambda s: s.model_dump(exclude_none=True)),
        ),
        TaskSpec(
            "kb_access",
            "query",
            "Who can access a knowledge base, with which permission.",
            KbSlots,
            ("get_kb_access",),
            _query("get_kb_access", lambda s: s.model_dump()),
        ),
        TaskSpec(
            "user_access",
            "query",
            "What a user can access and where each permission comes from (can they upload?).",
            UserSlots,
            ("explain_user_access",),
            _query("explain_user_access", lambda s: s.model_dump()),
        ),
        TaskSpec(
            "audit_logs",
            "query",
            "Search the audit log: who changed what and when (default: last 7 days). Convert "
            "relative dates (yesterday, last week) to YYYY-MM-DD.",
            AuditArgs,
            ("search_audit_logs",),
            _query("search_audit_logs", lambda s: s.model_dump(mode="json", exclude_none=True)),
        ),
        TaskSpec(
            "model_status",
            "query",
            "Which chat / embedding / rerank models are in use and their latest health check.",
            NoSlots,
            ("model_status",),
            _query("model_status", lambda s: {}),
        ),
        TaskSpec(
            "api_clients",
            "query",
            "Open platform (external agent) applications: status, knowledge bases, scopes, "
            "limits, calls today.",
            ClientArgs,
            ("list_api_clients",),
            _query("list_api_clients", lambda s: s.model_dump(exclude_none=True)),
        ),
        TaskSpec(
            "index_status",
            "query",
            "Index sync status: outbox queue counts (pending / dead letters) and generations.",
            NoSlots,
            ("index_status",),
            _query("index_status", lambda s: {}),
        ),
        TaskSpec(
            "eval_datasets",
            "query",
            "List offline evaluation datasets with their case counts.",
            NoSlots,
            ("list_eval_datasets",),
            _query("list_eval_datasets", lambda s: {}),
        ),
        TaskSpec(
            "eval_runs",
            "query",
            "Recent offline evaluation runs with status, progress and metrics.",
            EvalRunsArgs,
            ("list_eval_runs",),
            _query("list_eval_runs", lambda s: s.model_dump(exclude_none=True)),
        ),
        TaskSpec(
            "compare_eval",
            "query",
            "Compare the two latest finished evaluation runs (metrics and config differences).",
            EvalCompareArgs,
            ("compare_eval_runs",),
            _query("compare_eval_runs", lambda s: s.model_dump(exclude_none=True)),
        ),
        # ---- changes
        TaskSpec(
            "onboard_user",
            "change",
            "Create (pre-provision) a user, optionally with department, groups, roles, "
            "knowledge base access and password sign-in.",
            OnboardUserSlots,
            ("create_user",),
            _onboard,
        ),
        TaskSpec(
            "add_to_group",
            "change",
            "Add users (or everyone in departments) to a user group; create_group=true only if "
            "the admin asked to create it.",
            AddToGroupSlots,
            ("add_to_group",),
            _add_to_group,
        ),
        TaskSpec(
            "remove_from_group",
            "change",
            "Remove users from a user group.",
            MembersSlots,
            ("remove_from_group",),
            _remove_from_group,
        ),
        TaskSpec(
            "assign_roles",
            "change",
            "Add roles to users (existing roles are kept).",
            AssignRolesSlots,
            ("assign_roles",),
            _assign_roles,
        ),
        TaskSpec(
            "create_group",
            "change",
            "Create a user group.",
            CreateGroupSlots,
            ("create_group",),
            _create_group,
        ),
        TaskSpec(
            "create_knowledge_base",
            "change",
            "Create a knowledge base.",
            CreateKbSlots,
            ("create_knowledge_base",),
            _create_kb,
        ),
        TaskSpec(
            "grant_kb_access",
            "change",
            "Grant (or change) read / edit / manage on a knowledge base for users, groups, "
            "roles or departments (department grants include sub-departments).",
            GrantKbSlots,
            ("grant_kb_access",),
            _grant,
        ),
        TaskSpec(
            "set_kb_visibility",
            "change",
            "Change knowledge base visibility: restricted (granted members only) or org "
            "(everyone in the organization can read).",
            KbVisibilitySlots,
            ("set_kb_visibility",),
            _visibility,
        ),
        TaskSpec(
            "open_password_login",
            "change",
            "Enable password sign-in (temporary password) for existing users.",
            PasswordLoginSlots,
            ("open_password_login",),
            _password,
        ),
        TaskSpec(
            "revoke_kb_access",
            "change",
            "Remove the knowledge base grants of users, groups, roles or departments.",
            RevokeKbSlots,
            ("revoke_kb_access",),
            _revoke,
        ),
        TaskSpec(
            "remove_roles",
            "change",
            "Remove roles from users (other roles are kept).",
            AssignRolesSlots,
            ("remove_roles",),
            _remove_roles,
        ),
        TaskSpec(
            "disable_users",
            "change",
            "Disable user accounts (they can no longer sign in; grants are kept).",
            UsersSlots,
            ("disable_users",),
            _users_step("disable_users"),
        ),
        TaskSpec(
            "enable_users",
            "change",
            "Re-enable disabled user accounts.",
            UsersSlots,
            ("enable_users",),
            _users_step("enable_users"),
        ),
        TaskSpec(
            "create_department",
            "change",
            "Create a department (optionally under a parent department).",
            CreateDeptArgs,
            ("create_department",),
            _single("create_department"),
        ),
        TaskSpec(
            "rename_department",
            "change",
            "Rename a department.",
            RenameDeptArgs,
            ("rename_department",),
            _single("rename_department"),
        ),
        TaskSpec(
            "move_department",
            "change",
            "Move a department under another parent (no parent = top level).",
            MoveDeptArgs,
            ("move_department",),
            _single("move_department"),
        ),
        TaskSpec(
            "create_role",
            "change",
            "Create a role, optionally with feature permissions.",
            CreateRoleSlots,
            ("create_role",),
            _single("create_role"),
        ),
        TaskSpec(
            "update_role_permissions",
            "change",
            "Add or remove feature permissions of an existing role.",
            RolePermissionSlots,
            ("set_role_permissions",),
            _single("set_role_permissions"),
        ),
        TaskSpec(
            "start_eval",
            "change",
            "Start an offline evaluation run of a dataset (runs in the background).",
            StartEvalArgs,
            ("start_eval_run",),
            _single("start_eval_run"),
        ),
    )
}

# Creations first, then memberships / grants, credentials last (they touch Keycloak).
STEP_ORDER = {
    "create_department": 0,
    "rename_department": 0,
    "move_department": 0,
    "create_role": 0,
    "create_group": 0,
    "create_knowledge_base": 0,
    "create_user": 1,
    "enable_users": 1,
    "add_to_group": 2,
    "remove_from_group": 2,
    "set_role_permissions": 3,
    "assign_roles": 3,
    "remove_roles": 3,
    "grant_kb_access": 4,
    "revoke_kb_access": 4,
    "set_kb_visibility": 4,
    "disable_users": 8,
    "open_password_login": 9,
    "start_eval_run": 9,
}


def order_steps(steps: list[Step]) -> list[Step]:
    """Stable phase order + de-duplication of identical steps."""
    seen: set[str] = set()
    unique: list[Step] = []
    for tool, args in steps:
        key = f"{tool}:{sorted(args.items())!r}"
        if key not in seen:
            seen.add(key)
            unique.append((tool, args))
    return sorted(unique, key=lambda s: STEP_ORDER.get(s[0], 5))
