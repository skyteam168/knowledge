"""Admin side of the open platform: clients, keys, call logs and usage."""

from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import NotFoundError, ValidationAppError
from app.models import (
    SERVICE_USER_PREFIX,
    ApiCallLog,
    ApiClient,
    ApiClientStatus,
    ApiKey,
    ApiKeyStatus,
    ApiScope,
    Department,
    Group,
    KnowledgeBase,
    Role,
    User,
)
from app.models.base import new_id, utcnow
from app.repositories.org_repo import DepartmentRepository
from app.schemas.common import Page
from app.schemas.open_api import (
    ApiCallLogOut,
    ApiClientCreate,
    ApiClientOut,
    ApiClientUpdate,
    ApiKeyCreate,
    ApiKeyCreatedOut,
    ApiKeyOut,
    ApiPrincipalOut,
    ApiPrincipalRef,
    ApiUsageDay,
    ApiUsageOut,
    NamedRef,
    OpenApiOptionsOut,
)
from app.services.authz import AuthzCache
from app.services.context import BaseService, RequestContext
from app.services.knowledge.directory import DirectoryService
from app.services.open_api.auth import effective_rate
from app.services.open_api.keys import display_prefix, generate_secret, hash_secret
from app.services.open_api.open_service import RESOURCE_API_CLIENT

RESOURCE_API_KEY = "api_key"
PRINCIPAL_MODELS: dict[str, Any] = {"dept": Department, "group": Group, "role": Role}


def _snapshot(client: ApiClient) -> dict[str, Any]:
    return {
        "name": client.name,
        "status": client.status,
        "kb_ids": list(client.kb_ids or []),
        "principals": list(client.principals or []),
        "scopes": list(client.scopes or []),
        "rate_limit_per_minute": client.rate_limit_per_minute,
        "daily_quota": client.daily_quota,
        "ip_allowlist": list(client.ip_allowlist or []),
        "expires_at": client.expires_at.isoformat() if client.expires_at else None,
    }


class OpenApiClientService(BaseService):
    def __init__(
        self,
        session: AsyncSession,
        ctx: RequestContext,
        authz_cache: AuthzCache,
        *,
        settings: Settings,
    ) -> None:
        super().__init__(session, ctx, authz_cache)
        self.settings = settings

    # ---- lookups -----------------------------------------------------------------------

    async def _client(self, client_id: str) -> ApiClient:
        client = await self.session.get(ApiClient, client_id)
        if client is None or client.org_id != self.org_id:
            raise NotFoundError("API client not found")
        return client

    async def _names(self, model: Any, ids: list[str]) -> dict[str, str]:
        if not ids:
            return {}
        if model is Department:
            repo = DepartmentRepository(self.session)
            return await repo.path_names(self.org_id, await repo.list_by_ids(self.org_id, ids))
        stmt = select(model.id, model.name).where(model.org_id == self.org_id, model.id.in_(ids))
        if model is KnowledgeBase:
            stmt = stmt.where(KnowledgeBase.deleted_at.is_(None))
        return {row[0]: row[1] for row in (await self.session.execute(stmt)).all()}

    async def _validate(self, kb_ids: list[str], principals: list[ApiPrincipalRef]) -> None:
        found = await self._names(KnowledgeBase, kb_ids)
        missing_kbs = [k for k in kb_ids if k not in found]
        missing: list[dict[str, str]] = []
        for kind, model in PRINCIPAL_MODELS.items():
            ids = [p.id for p in principals if p.type == kind]
            names = await self._names(model, ids)
            missing += [{"type": kind, "id": i} for i in ids if i not in names]
        if missing_kbs or missing:
            raise ValidationAppError(
                "Unknown knowledge base or principal",
                detail={"kb_ids": missing_kbs, "principals": missing},
            )

    async def _out(self, clients: list[ApiClient]) -> list[ApiClientOut]:
        kb_ids = sorted({k for c in clients for k in c.kb_ids or []})
        kb_names = await self._names(KnowledgeBase, kb_ids)
        principal_names: dict[str, dict[str, str]] = {}
        for kind, model in PRINCIPAL_MODELS.items():
            ids = sorted(
                {str(p["id"]) for c in clients for p in c.principals or [] if p.get("type") == kind}
            )
            principal_names[kind] = await self._names(model, ids)
        owners = await self._names(
            Department, sorted({c.owner_department_id for c in clients if c.owner_department_id})
        )
        ids = [c.id for c in clients]
        active_keys: dict[str, int] = {}
        calls_today: dict[str, int] = {}
        if ids:
            rows = await self.session.execute(
                select(ApiKey.client_id, func.count())
                .where(ApiKey.client_id.in_(ids), ApiKey.status == ApiKeyStatus.ACTIVE.value)
                .group_by(ApiKey.client_id)
            )
            active_keys = {r[0]: int(r[1]) for r in rows.all()}
            start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
            rows = await self.session.execute(
                select(ApiCallLog.client_id, func.count())
                .where(ApiCallLog.client_id.in_(ids), ApiCallLog.created_at >= start)
                .group_by(ApiCallLog.client_id)
            )
            calls_today = {r[0]: int(r[1]) for r in rows.all()}
        return [
            ApiClientOut(
                id=c.id,
                name=c.name,
                description=c.description,
                owner_department_id=c.owner_department_id,
                owner_department_name=owners.get(c.owner_department_id or ""),
                contact=c.contact,
                status=c.status,
                service_user_id=c.service_user_id,
                kbs=[NamedRef(id=k, name=kb_names.get(k, "（已删除）")) for k in c.kb_ids or []],
                principals=[
                    ApiPrincipalOut(
                        type=p["type"],
                        id=str(p["id"]),
                        name=principal_names.get(str(p["type"]), {}).get(str(p["id"])),
                    )
                    for p in c.principals or []
                ],
                scopes=list(c.scopes or []),
                rate_limit_per_minute=c.rate_limit_per_minute,
                effective_rate_per_minute=effective_rate(c, self.settings),
                daily_quota=c.daily_quota,
                ip_allowlist=list(c.ip_allowlist or []),
                expires_at=c.expires_at,
                last_used_at=c.last_used_at,
                created_at=c.created_at,
                updated_at=c.updated_at,
                active_keys=active_keys.get(c.id, 0),
                calls_today=calls_today.get(c.id, 0),
            )
            for c in clients
        ]

    # ---- clients -----------------------------------------------------------------------

    async def options(self) -> OpenApiOptionsOut:
        async def named(model: Any) -> list[NamedRef]:
            stmt = select(model.id, model.name).where(model.org_id == self.org_id)
            if model is KnowledgeBase:
                stmt = stmt.where(KnowledgeBase.deleted_at.is_(None))
            rows = await self.session.execute(stmt.order_by(model.name))
            return [NamedRef(id=r[0], name=r[1]) for r in rows.all()]

        dept_options = await DirectoryService(self.session, self.ctx, self.authz_cache).principals(
            "dept", None, limit=100_000
        )
        return OpenApiOptionsOut(
            kbs=await named(KnowledgeBase),
            departments=sorted(
                (NamedRef(id=d.id, name=d.description or d.name) for d in dept_options),
                key=lambda r: r.name,
            ),
            groups=await named(Group),
            roles=await named(Role),
            scopes=[s.value for s in ApiScope],
            default_rate_per_minute=self.settings.open_api_default_rate_per_minute,
            max_top_k=self.settings.open_api_max_top_k,
        )

    async def list_clients(
        self, *, page: int, size: int, keyword: str | None, status: str | None
    ) -> Page[ApiClientOut]:
        stmt = select(ApiClient).where(ApiClient.org_id == self.org_id)
        if keyword:
            like = f"%{keyword}%"
            stmt = stmt.where(or_(ApiClient.name.ilike(like), ApiClient.contact.ilike(like)))
        if status:
            stmt = stmt.where(ApiClient.status == status)
        total = int(
            (await self.session.execute(select(func.count()).select_from(stmt.subquery()))).scalar()
            or 0
        )
        rows = await self.session.execute(
            stmt.order_by(ApiClient.created_at.desc(), ApiClient.id)
            .offset((page - 1) * size)
            .limit(size)
        )
        return Page(items=await self._out(list(rows.scalars())), total=total, page=page, size=size)

    async def get(self, client_id: str) -> ApiClientOut:
        return (await self._out([await self._client(client_id)]))[0]

    async def create(self, data: ApiClientCreate) -> ApiClientOut:
        await self._validate(data.kb_ids, data.principals)
        client_id = new_id()
        user = User(
            org_id=self.org_id,
            username=f"{SERVICE_USER_PREFIX}{client_id}",
            display_name=f"[Agent] {data.name}",
            is_active=True,
        )
        self.session.add(user)
        await self.session.flush()
        client = ApiClient(
            id=client_id,
            org_id=self.org_id,
            name=data.name.strip(),
            description=data.description,
            owner_department_id=data.owner_department_id,
            contact=data.contact,
            status=ApiClientStatus.ACTIVE.value,
            service_user_id=user.id,
            kb_ids=data.kb_ids,
            principals=[p.model_dump() for p in data.principals],
            scopes=[s.value for s in data.scopes],
            rate_limit_per_minute=data.rate_limit_per_minute,
            daily_quota=data.daily_quota,
            ip_allowlist=data.ip_allowlist,
            expires_at=data.expires_at,
            created_by=self.ctx.user.id,
        )
        self.session.add(client)
        await self.session.flush()
        await self.audit.record(
            self.audit_ctx,
            "openapi.client.create",
            RESOURCE_API_CLIENT,
            client.id,
            None,
            _snapshot(client),
        )
        return await self.get(client.id)

    async def update(self, client_id: str, data: ApiClientUpdate) -> ApiClientOut:
        client = await self._client(client_id)
        before = _snapshot(client)
        kb_ids = data.kb_ids if data.kb_ids is not None else list(client.kb_ids or [])
        principals = (
            data.principals
            if data.principals is not None
            else [ApiPrincipalRef.model_validate(p) for p in client.principals or []]
        )
        if data.kb_ids is not None or data.principals is not None:
            await self._validate(kb_ids, principals)
        fields = data.model_dump(exclude_unset=True, exclude={"clear_expires_at"})
        for name in ("name", "description", "owner_department_id", "contact", "status"):
            if name in fields:
                setattr(client, name, fields[name])
        for name in ("rate_limit_per_minute", "daily_quota", "ip_allowlist"):
            if fields.get(name) is not None:
                setattr(client, name, fields[name])
        if data.kb_ids is not None:
            client.kb_ids = kb_ids
        if data.principals is not None:
            client.principals = [p.model_dump() for p in principals]
        if data.scopes is not None:
            client.scopes = [s.value for s in data.scopes]
        if data.clear_expires_at:
            client.expires_at = None
        elif data.expires_at is not None:
            client.expires_at = data.expires_at
        if data.name:
            user = await self.session.get(User, client.service_user_id)
            if user is not None:
                user.display_name = f"[Agent] {data.name}"
        client.updated_at = utcnow()
        await self.session.flush()
        await self.audit.record(
            self.audit_ctx,
            "openapi.client.update",
            RESOURCE_API_CLIENT,
            client.id,
            before,
            _snapshot(client),
        )
        return await self.get(client.id)

    async def delete(self, client_id: str) -> None:
        client = await self._client(client_id)
        before = _snapshot(client)
        user = await self.session.get(User, client.service_user_id)
        if user is not None:
            # Kept (traces / conversations reference it) but can never act again.
            user.is_active = False
        await self.session.delete(client)
        await self.session.flush()
        await self.audit.record(
            self.audit_ctx, "openapi.client.delete", RESOURCE_API_CLIENT, client_id, before, None
        )

    # ---- keys --------------------------------------------------------------------------

    async def keys(self, client_id: str) -> list[ApiKeyOut]:
        await self._client(client_id)
        rows = await self.session.execute(
            select(ApiKey)
            .where(ApiKey.client_id == client_id)
            .order_by(ApiKey.created_at.desc(), ApiKey.id)
        )
        return [ApiKeyOut.model_validate(k) for k in rows.scalars()]

    async def create_key(self, client_id: str, data: ApiKeyCreate) -> ApiKeyCreatedOut:
        client = await self._client(client_id)
        if data.expires_at is not None:
            expires = (
                data.expires_at if data.expires_at.tzinfo else data.expires_at.replace(tzinfo=UTC)
            )
            if expires <= utcnow():
                raise ValidationAppError("expires_at must be in the future")
        secret = generate_secret()
        key = ApiKey(
            org_id=self.org_id,
            client_id=client.id,
            name=data.name.strip(),
            prefix=display_prefix(secret),
            key_hash=hash_secret(secret, self.settings.open_api_key_pepper),
            status=ApiKeyStatus.ACTIVE.value,
            expires_at=data.expires_at,
            created_by=self.ctx.user.id,
        )
        self.session.add(key)
        await self.session.flush()
        await self.audit.record(
            self.audit_ctx,
            "openapi.key.create",
            RESOURCE_API_KEY,
            key.id,
            None,
            {"client_id": client.id, "name": key.name, "prefix": key.prefix},
        )
        return ApiKeyCreatedOut(**ApiKeyOut.model_validate(key).model_dump(), secret=secret)

    async def revoke_key(self, client_id: str, key_id: str) -> ApiKeyOut:
        await self._client(client_id)
        key = await self.session.get(ApiKey, key_id)
        if key is None or key.client_id != client_id:
            raise NotFoundError("API key not found")
        if key.status != ApiKeyStatus.REVOKED.value:
            key.status = ApiKeyStatus.REVOKED.value
            key.revoked_at = utcnow()
            await self.session.flush()
            await self.audit.record(
                self.audit_ctx,
                "openapi.key.revoke",
                RESOURCE_API_KEY,
                key.id,
                {"status": ApiKeyStatus.ACTIVE.value},
                {"status": key.status, "client_id": client_id},
            )
        return ApiKeyOut.model_validate(key)

    # ---- logs & usage ------------------------------------------------------------------

    async def logs(
        self, client_id: str, *, page: int, size: int, outcome: str | None
    ) -> Page[ApiCallLogOut]:
        await self._client(client_id)
        stmt = select(ApiCallLog).where(
            ApiCallLog.org_id == self.org_id, ApiCallLog.client_id == client_id
        )
        if outcome == "ok":
            stmt = stmt.where(ApiCallLog.status_code < 400)
        elif outcome == "error":
            stmt = stmt.where(ApiCallLog.status_code >= 400)
        total = int(
            (await self.session.execute(select(func.count()).select_from(stmt.subquery()))).scalar()
            or 0
        )
        rows = await self.session.execute(
            stmt.order_by(ApiCallLog.created_at.desc(), ApiCallLog.id)
            .offset((page - 1) * size)
            .limit(size)
        )
        items = [ApiCallLogOut.model_validate(r) for r in rows.scalars()]
        return Page(items=items, total=total, page=page, size=size)

    async def usage(self, client_id: str, days: int) -> ApiUsageOut:
        await self._client(client_id)
        today = datetime.now(UTC).date()
        start_day = today - timedelta(days=days - 1)
        start = datetime(start_day.year, start_day.month, start_day.day, tzinfo=UTC)
        rows = await self.session.execute(
            select(
                ApiCallLog.created_at,
                ApiCallLog.status_code,
                ApiCallLog.latency_ms,
                ApiCallLog.endpoint,
            ).where(
                ApiCallLog.org_id == self.org_id,
                ApiCallLog.client_id == client_id,
                ApiCallLog.created_at >= start,
            )
        )
        per_day: dict[str, list[tuple[int, int]]] = defaultdict(list)
        endpoints: Counter[str] = Counter()
        statuses: Counter[str] = Counter()
        for created_at, status_code, latency, endpoint in rows.all():
            stamp = created_at if created_at.tzinfo else created_at.replace(tzinfo=UTC)
            per_day[stamp.astimezone(UTC).date().isoformat()].append((status_code, latency))
            endpoints[endpoint] += 1
            statuses[str(status_code)] += 1
        out_days = []
        for i in range(days):
            day = (start_day + timedelta(days=i)).isoformat()
            entries = per_day.get(day, [])
            out_days.append(
                ApiUsageDay(
                    day=day,
                    calls=len(entries),
                    errors=sum(1 for s, _ in entries if s >= 400),
                    avg_latency_ms=round(sum(lat for _, lat in entries) / len(entries), 1)
                    if entries
                    else 0.0,
                )
            )
        return ApiUsageOut(
            days=out_days,
            total_calls=sum(d.calls for d in out_days),
            total_errors=sum(d.errors for d in out_days),
            by_endpoint=dict(endpoints),
            by_status=dict(statuses),
        )
