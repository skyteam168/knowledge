"""Minimal Keycloak Admin REST client (users, identity providers, flows, service account)."""

import logging
from typing import Any

import httpx

from app.core.config import Settings
from app.core.exceptions import AppError

logger = logging.getLogger(__name__)

BROKER_FLOW_ALIAS = "ekb-broker-login"
BRIDGE_PROVIDERS = {"wecom": "企业微信", "dingtalk": "钉钉"}


class KeycloakAdminError(AppError):
    status_code = 502
    code = "KEYCLOAK_ADMIN_ERROR"
    message = "Keycloak admin request failed"


class KeycloakAdmin:
    def __init__(
        self,
        http: httpx.AsyncClient,
        base_url: str,
        realm: str,
        token_form: dict[str, str],
        token_realm: str,
    ) -> None:
        self.http = http
        self.base = base_url.rstrip("/")
        self.realm = realm
        self._token_form = token_form
        self._token_realm = token_realm
        self._token: str | None = None

    @classmethod
    def service_account(cls, http: httpx.AsyncClient, settings: Settings) -> "KeycloakAdmin":
        if not settings.keycloak_admin_client_secret:
            raise KeycloakAdminError(
                "未配置 KEYCLOAK_ADMIN_CLIENT_SECRET，无法调用 Keycloak 管理接口",
                code="KEYCLOAK_ADMIN_NOT_CONFIGURED",
                status_code=503,
            )
        return cls(
            http,
            settings.keycloak_url,
            settings.keycloak_realm,
            {
                "grant_type": "client_credentials",
                "client_id": settings.keycloak_admin_client_id,
                "client_secret": settings.keycloak_admin_client_secret,
            },
            settings.keycloak_realm,
        )

    @classmethod
    def master_admin(
        cls, http: httpx.AsyncClient, settings: Settings, username: str, password: str
    ) -> "KeycloakAdmin":
        return cls(
            http,
            settings.keycloak_url,
            settings.keycloak_realm,
            {
                "grant_type": "password",
                "client_id": "admin-cli",
                "username": username,
                "password": password,
            },
            "master",
        )

    async def _access_token(self) -> str:
        if self._token is None:
            resp = await self.http.post(
                f"{self.base}/realms/{self._token_realm}/protocol/openid-connect/token",
                data=self._token_form,
            )
            if resp.status_code >= 400:
                raise KeycloakAdminError(
                    f"Keycloak 管理账号认证失败（HTTP {resp.status_code}）",
                    detail={"body": resp.text[:300]},
                )
            self._token = str(resp.json()["access_token"])
        return self._token

    async def request(
        self, method: str, path: str, *, ok404: bool = False, **kwargs: Any
    ) -> httpx.Response:
        token = await self._access_token()
        resp = await self.http.request(
            method,
            f"{self.base}/admin/realms/{self.realm}{path}",
            headers={"Authorization": f"Bearer {token}"},
            **kwargs,
        )
        if resp.status_code == 404 and ok404:
            return resp
        if resp.status_code == 403:
            raise KeycloakAdminError(
                "Keycloak 管理账号权限不足（需要 realm-management 的 manage-users / view-users）",
                code="KEYCLOAK_ADMIN_FORBIDDEN",
                detail={"path": path},
            )
        if resp.status_code >= 400:
            raise KeycloakAdminError(
                f"Keycloak 管理接口错误 HTTP {resp.status_code}",
                detail={"path": path, "body": resp.text[:300]},
            )
        return resp

    # ---- users ------------------------------------------------------------------------

    async def get_user(self, user_id: str) -> dict[str, Any] | None:
        resp = await self.request("GET", f"/users/{user_id}", ok404=True)
        return None if resp.status_code == 404 else dict(resp.json())

    async def find_user(self, username: str) -> dict[str, Any] | None:
        resp = await self.request("GET", "/users", params={"username": username, "exact": "true"})
        users = [u for u in resp.json() if u.get("username") == username.lower()]
        return users[0] if users else None

    async def create_user(self, payload: dict[str, Any]) -> str:
        resp = await self.request("POST", "/users", json=payload)
        location = str(resp.headers.get("location", ""))
        user_id = location.rstrip("/").rsplit("/", 1)[-1]
        if not user_id:
            found = await self.find_user(str(payload["username"]))
            if not found:
                raise KeycloakAdminError("Keycloak 创建用户后未返回 ID")
            user_id = str(found["id"])
        return user_id

    async def update_user(self, user_id: str, payload: dict[str, Any]) -> None:
        await self.request("PUT", f"/users/{user_id}", json=payload)

    async def reset_password(self, user_id: str, value: str, temporary: bool = True) -> None:
        await self.request(
            "PUT",
            f"/users/{user_id}/reset-password",
            json={"type": "password", "value": value, "temporary": temporary},
        )

    # ---- realm setup (CLI) ------------------------------------------------------------

    async def relax_user_profile(self) -> list[str]:
        """Email / first / last name optional: synced factory staff often have no email."""
        profile = (await self.request("GET", "/users/profile")).json()
        changed = []
        for attr in profile.get("attributes", []):
            if attr.get("name") in {"email", "firstName", "lastName"} and attr.get("required"):
                attr.pop("required")
                changed.append(attr["name"])
        if changed:
            await self.request("PUT", "/users/profile", json=profile)
        return changed

    async def ensure_broker_flow(self) -> bool:
        """First-login flow: create the Keycloak user, or link to an existing one silently."""
        flows = (await self.request("GET", "/authentication/flows")).json()
        if any(f.get("alias") == BROKER_FLOW_ALIAS for f in flows):
            return False
        await self.request(
            "POST",
            "/authentication/flows",
            json={
                "alias": BROKER_FLOW_ALIAS,
                "description": "EKB: 企业微信/钉钉首次登录自动创建或关联账号",
                "providerId": "basic-flow",
                "topLevel": True,
                "builtIn": False,
            },
        )
        for provider in ("idp-create-user-if-unique", "idp-auto-link"):
            await self.request(
                "POST",
                f"/authentication/flows/{BROKER_FLOW_ALIAS}/executions/execution",
                json={"provider": provider},
            )
        executions = (
            await self.request("GET", f"/authentication/flows/{BROKER_FLOW_ALIAS}/executions")
        ).json()
        for execution in executions:
            execution["requirement"] = "ALTERNATIVE"
            await self.request(
                "PUT", f"/authentication/flows/{BROKER_FLOW_ALIAS}/executions", json=execution
            )
        return True

    async def upsert_identity_provider(self, payload: dict[str, Any]) -> str:
        alias = payload["alias"]
        resp = await self.request("GET", f"/identity-provider/instances/{alias}", ok404=True)
        if resp.status_code == 404:
            await self.request("POST", "/identity-provider/instances", json=payload)
            action = "created"
        else:
            current = resp.json()
            current.update({k: v for k, v in payload.items() if k != "config"})
            current.setdefault("config", {}).update(payload["config"])
            await self.request("PUT", f"/identity-provider/instances/{alias}", json=current)
            action = "updated"
        existing = {
            m["name"]: m
            for m in (
                await self.request("GET", f"/identity-provider/instances/{alias}/mappers")
            ).json()
        }
        for mapper in idp_mappers(alias):
            if mapper["name"] in existing:
                body = {**existing[mapper["name"]], "config": mapper["config"]}
                await self.request(
                    "PUT",
                    f"/identity-provider/instances/{alias}/mappers/{body['id']}",
                    json=body,
                )
            else:
                await self.request(
                    "POST", f"/identity-provider/instances/{alias}/mappers", json=mapper
                )
        return action

    async def grant_service_account(self, client_id: str, roles: list[str]) -> list[str]:
        clients = (await self.request("GET", "/clients", params={"clientId": client_id})).json()
        if not clients:
            raise KeycloakAdminError(f"Keycloak 中不存在客户端 {client_id}")
        client = clients[0]
        if not client.get("serviceAccountsEnabled"):
            client["serviceAccountsEnabled"] = True
            await self.request("PUT", f"/clients/{client['id']}", json=client)
        sa = (await self.request("GET", f"/clients/{client['id']}/service-account-user")).json()
        rm = (
            await self.request("GET", "/clients", params={"clientId": "realm-management"})
        ).json()[0]
        current = {
            r["name"]
            for r in (
                await self.request("GET", f"/users/{sa['id']}/role-mappings/clients/{rm['id']}")
            ).json()
        }
        missing = [r for r in roles if r not in current]
        if missing:
            reps = [
                (await self.request("GET", f"/clients/{rm['id']}/roles/{r}")).json()
                for r in missing
            ]
            await self.request(
                "POST", f"/users/{sa['id']}/role-mappings/clients/{rm['id']}", json=reps
            )
        return missing


def identity_provider(
    alias: str,
    *,
    public_base_url: str,
    internal_base_url: str,
    client_id: str,
    client_secret: str,
    flow_alias: str = BROKER_FLOW_ALIAS,
) -> dict[str, Any]:
    public = f"{public_base_url.rstrip('/')}/oidc/{alias}"
    internal = f"{internal_base_url.rstrip('/')}/oidc/{alias}"
    return {
        "alias": alias,
        "displayName": BRIDGE_PROVIDERS[alias],
        "providerId": "oidc",
        "enabled": True,
        "trustEmail": True,
        "storeToken": False,
        "linkOnly": False,
        "hideOnLogin": False,
        "firstBrokerLoginFlowAlias": flow_alias,
        "config": {
            # Browser-facing.
            "authorizationUrl": f"{public}/authorize",
            "issuer": public,
            # Keycloak -> backend (container network).
            "tokenUrl": f"{internal}/token",
            "userInfoUrl": f"{internal}/userinfo",
            "jwksUrl": f"{internal}/jwks",
            "useJwksUrl": "true",
            "validateSignature": "true",
            "clientId": client_id,
            "clientSecret": client_secret,
            "clientAuthMethod": "client_secret_post",
            "defaultScope": "openid profile email",
            "disableUserInfo": "true",
            "pkceEnabled": "false",
            "syncMode": "FORCE",
            "guiOrder": "1" if alias == "wecom" else "2",
        },
    }


def idp_mappers(alias: str) -> list[dict[str, Any]]:
    def attribute(name: str, claim: str, user_attribute: str) -> dict[str, Any]:
        return {
            "name": name,
            "identityProviderAlias": alias,
            "identityProviderMapper": "oidc-user-attribute-idp-mapper",
            "config": {"syncMode": "FORCE", "claim": claim, "user.attribute": user_attribute},
        }

    return [
        attribute("org_id", "org_id", "org_id"),
        attribute("display-name", "name", "firstName"),
    ]
