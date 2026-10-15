import asyncio
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx
import jwt

from app.core.config import Settings
from app.core.exceptions import UnauthorizedError


@dataclass(frozen=True)
class TokenClaims:
    sub: str
    username: str
    org_code: str
    email: str | None = None
    name: str | None = None
    groups: tuple[str, ...] = ()
    roles: tuple[str, ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any], settings: Settings) -> "TokenClaims":
        sub = payload.get("sub")
        if not isinstance(sub, str) or not sub:
            raise UnauthorizedError("Token missing subject", code="INVALID_TOKEN")
        groups = tuple(
            sorted({str(g).rsplit("/", 1)[-1] for g in payload.get("groups") or [] if g})
        )
        realm_roles = (payload.get("realm_access") or {}).get("roles") or []
        ignored = set(settings.auth_ignored_roles)
        roles = tuple(
            sorted(
                {
                    str(r)
                    for r in realm_roles
                    if r not in ignored and not str(r).startswith("default-roles-")
                }
            )
        )
        org_code = payload.get(settings.auth_org_claim) or settings.auth_default_org_code
        return cls(
            sub=sub,
            username=str(payload.get("preferred_username") or sub),
            org_code=str(org_code),
            email=payload.get("email"),
            name=payload.get("name"),
            groups=groups,
            roles=roles,
            raw=dict(payload),
        )


class TokenVerifier(Protocol):
    async def verify(self, token: str) -> TokenClaims: ...


class JwksTokenVerifier:
    """Validates Keycloak-issued JWTs against a cached JWKS (refreshed on TTL or unknown kid)."""

    MIN_REFRESH_INTERVAL = 10.0

    def __init__(self, settings: Settings, http: httpx.AsyncClient) -> None:
        self._settings = settings
        self._http = http
        self._keys: dict[str, jwt.PyJWK] = {}
        self._fetched_at = 0.0
        self._lock = asyncio.Lock()

    async def _refresh(self, force: bool) -> None:
        async with self._lock:
            age = time.monotonic() - self._fetched_at
            if force and age < self.MIN_REFRESH_INTERVAL:
                return
            if not force and self._keys and age < self._settings.jwks_cache_ttl_seconds:
                return
            resp = await self._http.get(self._settings.keycloak_jwks_url)
            resp.raise_for_status()
            jwk_set = jwt.PyJWKSet.from_dict(resp.json())
            self._keys = {k.key_id: k for k in jwk_set.keys if k.key_id}
            self._fetched_at = time.monotonic()

    async def _get_key(self, kid: str) -> jwt.PyJWK:
        try:
            await self._refresh(force=False)
            if kid not in self._keys:
                await self._refresh(force=True)
        except httpx.HTTPError as exc:
            raise UnauthorizedError(
                "Unable to fetch signing keys", code="JWKS_UNAVAILABLE"
            ) from exc
        key = self._keys.get(kid)
        if key is None:
            raise UnauthorizedError("Unknown signing key", code="INVALID_TOKEN")
        return key

    async def verify(self, token: str) -> TokenClaims:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise UnauthorizedError("Malformed token", code="INVALID_TOKEN") from exc
        kid = header.get("kid")
        if not kid:
            raise UnauthorizedError("Token missing kid", code="INVALID_TOKEN")
        key = await self._get_key(kid)
        try:
            payload = jwt.decode(
                token,
                key=key.key,
                algorithms=[key.algorithm_name or "RS256"],
                audience=self._settings.keycloak_audience,
                issuer=self._settings.keycloak_issuer,
                leeway=self._settings.jwt_leeway_seconds,
                options={"require": ["exp", "iat", "sub"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise UnauthorizedError("Token expired", code="TOKEN_EXPIRED") from exc
        except jwt.PyJWTError as exc:
            raise UnauthorizedError(f"Invalid token: {exc}", code="INVALID_TOKEN") from exc
        return TokenClaims.from_payload(payload, self._settings)
