import secrets
import string

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationAppError
from app.models import Organization
from app.repositories.user_repo import UserRepository
from app.schemas.identity import PasswordLoginOut
from app.services.authz.cache import AuthzCache
from app.services.context import BaseService, RequestContext
from app.services.keycloak_admin import KeycloakAdmin

PASSWORD_ALPHABET = string.ascii_letters + string.digits


def temporary_password(length: int = 12) -> str:
    while True:
        value = "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(length))
        if any(c.isdigit() for c in value) and any(c.isalpha() for c in value):
            return value


class PasswordLoginService(BaseService):
    """Fallback for people without WeCom / DingTalk: Keycloak account + temporary password."""

    def __init__(
        self,
        session: AsyncSession,
        ctx: RequestContext,
        authz_cache: AuthzCache,
        *,
        settings: Settings,
        http: httpx.AsyncClient,
    ) -> None:
        super().__init__(session, ctx, authz_cache)
        self.settings = settings
        self.http = http

    async def open(self, user_id: str) -> PasswordLoginOut:
        user = await UserRepository(self.session).get(self.org_id, user_id)
        if user is None:
            raise NotFoundError("User not found")
        if not user.is_active:
            raise ValidationAppError("用户已停用，不能开通密码登录")
        org = await self.session.get(Organization, self.org_id)
        if org is None:
            raise NotFoundError("Organization not found")

        admin = KeycloakAdmin.service_account(self.http, self.settings)
        account = await admin.get_user(user.keycloak_sub) if user.keycloak_sub else None
        account = account or await admin.find_user(user.username)
        created = account is None
        if account is None:
            payload: dict[str, object] = {
                "username": user.username,
                "enabled": True,
                "firstName": user.display_name or user.username,
                "attributes": {"org_id": [org.code]},
            }
            if user.email:
                payload.update(email=user.email, emailVerified=True)
            account_id = await admin.create_user(payload)
        else:
            account_id = str(account["id"])
            orgs = (account.get("attributes") or {}).get("org_id") or []
            if orgs and orgs[0] != org.code:
                raise ConflictError(
                    f"Keycloak 账号 {user.username} 属于其他组织（{orgs[0]}）",
                    code="KEYCLOAK_ORG_MISMATCH",
                )
            if not orgs or not account.get("enabled", True):
                account.setdefault("attributes", {})["org_id"] = [org.code]
                account["enabled"] = True
                await admin.update_user(account_id, account)

        password = temporary_password()
        await admin.reset_password(account_id, password, temporary=True)
        await self.audit.record(
            self.audit_ctx,
            "user.password_login",
            "user",
            user.id,
            after={"keycloak_user_id": account_id, "created": created},
        )
        return PasswordLoginOut(
            username=user.username, created=created, temporary_password=password
        )
