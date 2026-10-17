"""Repair users duplicated by a case-only username mismatch.

Before usernames were matched case-insensitively, a user pre-provisioned as `Hien` who signed in
through Keycloak (which lowercases usernames to `hien`) got a second, auto-created user. The
pre-provisioned record carries the departments / roles / grants the admin set up, so the Keycloak
identity is moved onto it and the auto-created one is disabled (kept for its history).
"""

from dataclasses import asdict, dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Organization, User
from app.repositories.user_repo import UserRepository
from app.services.audit_service import AuditContext, AuditService
from app.services.authz.cache import AuthzCache

CLI_ACTOR = "cli:fix-duplicates"


@dataclass
class DuplicateFix:
    org_id: str
    username: str
    into_user_id: str | None = None
    from_user_id: str | None = None
    skipped: str | None = None
    users: list[str] = field(default_factory=list)


def _plan(org_id: str, group: list[User]) -> DuplicateFix:
    fix = DuplicateFix(
        org_id=org_id,
        username=group[0].username.lower(),
        users=[f"{u.username} ({u.id}, sub={'yes' if u.keycloak_sub else 'no'})" for u in group],
    )
    bound = [u for u in group if u.keycloak_sub]
    unbound = [u for u in group if not u.keycloak_sub and u.is_active]
    if len(bound) != 1 or len(unbound) != 1:
        fix.skipped = "需要恰好一个已绑定 Keycloak 的账号和一个未绑定的启用账号，请人工处理"
        return fix
    donor, target = bound[0], unbound[0]
    if donor.created_at < target.created_at:
        fix.skipped = "已绑定的账号早于未绑定的账号创建，不像登录时自动生成的重复账号，请人工处理"
        return fix
    fix.from_user_id, fix.into_user_id = donor.id, target.id
    return fix


async def fix_case_duplicates(
    session: AsyncSession, authz: AuthzCache, *, apply: bool
) -> list[dict[str, object]]:
    repo = UserRepository(session)
    audit = AuditService(session)
    results: list[dict[str, object]] = []
    for org_id in (await session.execute(select(Organization.id))).scalars():
        for group in await repo.list_case_duplicates(org_id):
            fix = _plan(org_id, group)
            if apply and fix.from_user_id and fix.into_user_id:
                by_id = {u.id: u for u in group}
                await _move_identity(
                    session, audit, by_id[fix.from_user_id], by_id[fix.into_user_id]
                )
                await authz.invalidate_user(org_id, fix.from_user_id, fix.into_user_id)
            results.append({**asdict(fix), "applied": bool(apply and fix.into_user_id)})
    return results


async def _move_identity(
    session: AsyncSession, audit: AuditService, donor: User, target: User
) -> None:
    sub = donor.keycloak_sub
    before = {"from": donor.username, "into": target.username, "keycloak_sub": sub}
    donor.keycloak_sub = None
    donor.is_active = False
    donor.username = f"{donor.username}.dup-{donor.id[:8]}"[:128]
    await session.flush()
    target.keycloak_sub = sub
    target.claims_hash = None
    await session.flush()
    ctx = AuditContext(org_id=target.org_id, actor_id=None, actor_name=CLI_ACTOR)
    await audit.record(
        ctx,
        "user.merge_identity",
        "user",
        target.id,
        before,
        {"into_user_id": target.id, "disabled_user_id": donor.id, "renamed_to": donor.username},
    )
