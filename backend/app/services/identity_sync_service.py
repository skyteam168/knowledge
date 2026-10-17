import hashlib
import json
import logging
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import ConflictError, PermissionDeniedError, UnauthorizedError
from app.core.security import TokenClaims
from app.models import LOCAL_SOURCE, Group, Organization, User
from app.repositories.group_repo import GroupRepository
from app.repositories.org_repo import OrganizationRepository
from app.repositories.role_repo import RoleRepository
from app.repositories.user_repo import UserRepository
from app.services.audit_service import AuditContext, AuditService, snapshot
from app.services.authz.cache import AuthzCache
from app.services.org_bootstrap import create_organization

logger = logging.getLogger(__name__)

KEYCLOAK_SOURCE = "keycloak"


def claims_fingerprint(claims: TokenClaims) -> str:
    payload = {
        "username": claims.username,
        "email": claims.email,
        "name": claims.name,
        "org": claims.org_code,
        "groups": list(claims.groups),
        "roles": list(claims.roles),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


class IdentitySyncService:
    """Maps a Keycloak identity onto local users/groups/roles.

    Runs on every authenticated request but only writes when the token's identity
    claims changed (tracked by `users.claims_hash`), so steady-state cost is one lookup.
    """

    def __init__(self, session: AsyncSession, settings: Settings, authz_cache: AuthzCache) -> None:
        self.session = session
        self.settings = settings
        self.authz_cache = authz_cache
        self.orgs = OrganizationRepository(session)
        self.users = UserRepository(session)
        self.groups = GroupRepository(session)
        self.roles = RoleRepository(session)
        self.audit = AuditService(session)

    async def sync(self, claims: TokenClaims) -> tuple[User, Organization]:
        fingerprint = claims_fingerprint(claims)
        user = await self.users.get_by_sub(claims.sub)
        if user is not None and user.claims_hash == fingerprint:
            org = await self.orgs.get(user.org_id)
            if org is None:
                raise UnauthorizedError("Organization not found", code="ORG_NOT_FOUND")
            self._ensure_usable(user, org)
            return user, org
        try:
            async with self.session.begin_nested():
                return await self._sync_changed(claims, fingerprint)
        except IntegrityError:
            # Concurrent first login of the same identity: the other request won the insert.
            logger.info("identity_sync_conflict_retry", extra={"sub": claims.sub})
            async with self.session.begin_nested():
                return await self._sync_changed(claims, fingerprint)

    @staticmethod
    def _ensure_usable(user: User, org: Organization) -> None:
        if org.status != "active":
            raise PermissionDeniedError("Organization is disabled", code="ORG_DISABLED")
        if not user.is_active:
            raise PermissionDeniedError("User is disabled", code="USER_DISABLED")

    async def _ensure_org(self, code: str) -> Organization:
        org = await self.orgs.get_by_code(code)
        if org is not None:
            return org
        if not self.settings.auth_auto_create_org:
            raise UnauthorizedError(
                f"Organization '{code}' is not provisioned", code="ORG_NOT_FOUND"
            )
        logger.info("organization_auto_created", extra={"org_code": code})
        return await create_organization(self.session, code=code, name=code)

    async def _sync_changed(
        self, claims: TokenClaims, fingerprint: str
    ) -> tuple[User, Organization]:
        org = await self._ensure_org(claims.org_code)
        user = await self.users.get_by_sub(claims.sub)
        created = False
        if user is None:
            user = await self.users.get_by_username(org.id, claims.username)
            if user is not None and user.keycloak_sub not in (None, claims.sub):
                raise ConflictError("Username already bound to another identity")
            if user is None:
                user = User(org_id=org.id, username=claims.username)
                created = True
            user.keycloak_sub = claims.sub
        elif user.org_id != org.id:
            raise PermissionDeniedError(
                "Identity belongs to another organization", code="ORG_MISMATCH"
            )

        if user.username.lower() != claims.username.lower():
            user.username = claims.username
        if (user.source or LOCAL_SOURCE) == LOCAL_SOURCE:
            user.email = claims.email
            user.display_name = claims.name or user.display_name or claims.username
        else:
            # Profile is owned by the directory source; the token only fills gaps.
            user.email = user.email or claims.email
            user.display_name = user.display_name or claims.name or claims.username
        user.claims_hash = fingerprint
        first_login = user.last_login_at is None
        user.last_login_at = datetime.now(UTC)
        if created:
            await self.users.add(user)
        else:
            await self.session.flush()
        self._ensure_usable(user, org)

        await self._sync_groups(org.id, user.id, list(claims.groups))
        await self._sync_roles(org.id, user.id, list(claims.roles))
        if first_login and not await self.users.list_role_links(org.id, user.id):
            # Covers pre-provisioned users too; roles mapped from the token take precedence.
            await self.users.add_roles(org.id, user.id, await self.roles.default_role_ids(org.id))
        await self.authz_cache.invalidate_user(org.id, user.id)

        if created:
            ctx = AuditContext(org_id=org.id, actor_id=user.id, actor_name=user.username)
            await self.audit.record(ctx, "user.provision", "user", user.id, None, snapshot(user))
        return user, org

    async def _sync_groups(self, org_id: str, user_id: str, names: list[str]) -> None:
        existing = {g.name: g for g in await self.groups.list_by_names(org_id, names)}
        for name in names:
            if name not in existing:
                existing[name] = await self.groups.add(
                    Group(org_id=org_id, name=name, source=KEYCLOAK_SOURCE)
                )
        await self.users.replace_groups(
            org_id, user_id, {g.id for g in existing.values()}, KEYCLOAK_SOURCE
        )

    async def _sync_roles(self, org_id: str, user_id: str, codes: list[str]) -> None:
        # Only Keycloak roles that exist locally are mapped; others (e.g. platform_admin) are
        # interpreted directly from the token.
        roles = await self.roles.list_by_codes(org_id, codes)
        await self.users.replace_roles(org_id, user_id, {r.id for r in roles}, KEYCLOAK_SOURCE)
