"""Directory sources (CRUD, test connection) and sync runs (preview / apply)."""

import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import KeyValueCache
from app.core.config import Settings
from app.core.crypto import decrypt_json, encrypt_json
from app.core.exceptions import AppError, ConflictError, NotFoundError, ValidationAppError
from app.models import (
    LOCAL_SOURCE,
    Department,
    DirectorySource,
    DirectorySourceType,
    DirectorySyncRun,
    SyncMode,
    SyncStatus,
    User,
)
from app.models.base import utcnow
from app.repositories.base import paginate
from app.retrieval.cache import ResultCache
from app.schemas.common import Page
from app.schemas.directory import (
    DirectorySourceCreate,
    DirectorySourceOut,
    DirectorySourceUpdate,
    DirectoryTestRequest,
    DirectoryTestResult,
    SyncRunDetail,
    SyncRunOut,
)
from app.services.audit_service import AuditContext, AuditService
from app.services.authz.cache import AuthzCache
from app.services.context import BaseService, RequestContext
from app.services.directory.connectors import CONFIG_MODELS, CONNECTORS, build_connector
from app.services.ingest.queue import TaskQueue

logger = logging.getLogger(__name__)

LOGIN_PROVIDERS = {DirectorySourceType.WECOM.value, DirectorySourceType.DINGTALK.value}
# A run still "running" after this long is considered lost (worker crash / restart).
STALE_RUN_AFTER = timedelta(minutes=30)
MIN_INTERVAL_MINUTES = 10


def secret_fields(source_type: str) -> tuple[str, ...]:
    return CONNECTORS[source_type].secret_fields


def login_configured(source_type: str, config: dict[str, Any]) -> bool:
    if source_type == DirectorySourceType.WECOM:
        return bool(config.get("agent_id") and config.get("agent_secret"))
    if source_type == DirectorySourceType.DINGTALK:
        return bool(config.get("app_key") and config.get("app_secret"))
    return False


def validate_config(source_type: str, config: dict[str, Any]) -> dict[str, Any]:
    try:
        model = CONFIG_MODELS[source_type].model_validate(config)
    except ValidationError as exc:
        errors = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
        raise ValidationAppError("Invalid source configuration", detail=errors) from exc
    return model.model_dump(mode="json", exclude_none=True)


def next_sync_at(source: DirectorySource) -> datetime | None:
    if not source.enabled or source.sync_interval_minutes <= 0:
        return None
    if source.type == DirectorySourceType.EXCEL:
        return None
    if source.last_sync_at is None:
        return utcnow()
    last = source.last_sync_at
    if last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    return last + timedelta(minutes=source.sync_interval_minutes)


class DirectorySyncExecutor:
    """Runs one sync (used by the API for Excel uploads and by the worker for the rest)."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        authz_cache: AuthzCache,
        cache: KeyValueCache,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.authz_cache = authz_cache
        self.cache = cache
        self.transport = transport

    async def execute(
        self,
        run: DirectorySyncRun,
        source: DirectorySource,
        audit_ctx: AuditContext,
        *,
        upload: bytes | None = None,
    ) -> DirectorySyncRun:
        from app.services.directory.reconciler import DirectoryReconciler, SyncOptions

        started = time.perf_counter()
        apply = run.mode == SyncMode.APPLY
        applied = False
        try:
            config = decrypt_json(self.settings.directory_secret_key, source.config_encrypted)
            connector = build_connector(
                source.type, config, self.settings, transport=self.transport, upload=upload
            )
            snapshot = await connector.fetch()
            opts = SyncOptions(
                source_type=source.type,
                is_primary=source.is_primary,
                max_disable_ratio=self.settings.directory_sync_max_disable_ratio,
                guard_min_disables=self.settings.directory_sync_guard_min_disables,
                force=run.forced,
                max_details=self.settings.directory_sync_max_change_details,
            )
            async with self.session.begin_nested():
                result = await DirectoryReconciler(self.session, source.org_id).run(
                    snapshot, opts, apply=apply
                )
            run.stats = result.summary()
            run.changes = result.changes
            if result.aborted:
                run.status = SyncStatus.ABORTED.value
                run.error = result.abort_reason
            else:
                run.status = SyncStatus.SUCCEEDED.value
            applied = result.applied
        except AppError as exc:
            run.status = SyncStatus.FAILED.value
            run.error = exc.message
            if exc.detail:
                run.stats = {"error_detail": exc.detail}
        except Exception as exc:
            logger.exception("directory_sync_failed", extra={"run_id": run.id})
            run.status = SyncStatus.FAILED.value
            run.error = f"{type(exc).__name__}: {str(exc)[:500]}"
        run.finished_at = utcnow()
        run.duration_ms = int((time.perf_counter() - started) * 1000)
        if apply:
            source.last_sync_at = run.finished_at
            source.last_status = run.status
            source.last_run_id = run.id
        if applied:
            await AuditService(self.session).record(
                audit_ctx,
                "directory.sync",
                "directory_source",
                source.id,
                None,
                {"run_id": run.id, "forced": run.forced, **run.stats},
            )
        await self.session.commit()
        if applied:
            # After commit: a request racing the sync must not re-cache the old principals.
            await self.authz_cache.invalidate_org(source.org_id)
            await ResultCache(self.cache).invalidate_org(source.org_id)
        return run


class DirectorySourceService(BaseService):
    def __init__(
        self,
        session: AsyncSession,
        ctx: RequestContext,
        authz_cache: AuthzCache,
        *,
        settings: Settings,
        queue: TaskQueue,
        cache: KeyValueCache,
    ) -> None:
        super().__init__(session, ctx, authz_cache)
        self.settings = settings
        self.queue = queue
        self.cache = cache

    # ---- helpers -------------------------------------------------------------------------

    def _decrypt(self, source: DirectorySource) -> dict[str, Any]:
        return decrypt_json(self.settings.directory_secret_key, source.config_encrypted)

    def _encrypt(self, config: dict[str, Any]) -> str:
        return encrypt_json(self.settings.directory_secret_key, config)

    def out(self, source: DirectorySource) -> DirectorySourceOut:
        config = self._decrypt(source)
        secrets = secret_fields(source.type)
        return DirectorySourceOut(
            id=source.id,
            type=source.type,
            name=source.name,
            is_primary=source.is_primary,
            enabled=source.enabled,
            sync_interval_minutes=source.sync_interval_minutes,
            config={k: v for k, v in config.items() if k not in secrets},
            secrets_set=[k for k in secrets if config.get(k)],
            login_supported=source.type in LOGIN_PROVIDERS,
            login_configured=login_configured(source.type, config),
            last_sync_at=source.last_sync_at,
            last_status=source.last_status,
            last_run_id=source.last_run_id,
            next_sync_at=next_sync_at(source),
            created_at=source.created_at,
            updated_at=source.updated_at,
        )

    async def get(self, source_id: str) -> DirectorySource:
        source = await self.session.get(DirectorySource, source_id)
        if source is None or source.org_id != self.org_id:
            raise NotFoundError("Directory source not found")
        return source

    async def _sources(self) -> list[DirectorySource]:
        rows = await self.session.execute(
            select(DirectorySource)
            .where(DirectorySource.org_id == self.org_id)
            .order_by(DirectorySource.is_primary.desc(), DirectorySource.created_at)
        )
        return list(rows.scalars())

    async def _set_primary(self, source: DirectorySource) -> None:
        for other in await self._sources():
            if other.id != source.id and other.is_primary:
                other.is_primary = False
                await self._release(other)
        source.is_primary = True

    async def _release(self, source: DirectorySource) -> None:
        """Data of a source that is no longer primary becomes locally editable."""
        await self.session.execute(
            update(Department)
            .where(Department.org_id == self.org_id, Department.source == source.type)
            .values(source=LOCAL_SOURCE, external_id=None)
        )
        await self.session.execute(
            update(User)
            .where(User.org_id == self.org_id, User.source == source.type)
            .values(source=LOCAL_SOURCE)
        )

    @staticmethod
    def _check_interval(minutes: int) -> None:
        if 0 < minutes < MIN_INTERVAL_MINUTES:
            raise ValidationAppError(f"Sync interval must be 0 or at least {MIN_INTERVAL_MINUTES}")

    # ---- sources -------------------------------------------------------------------------

    async def list_sources(self) -> list[DirectorySourceOut]:
        return [self.out(s) for s in await self._sources()]

    async def create(self, data: DirectorySourceCreate) -> DirectorySourceOut:
        self._check_interval(data.sync_interval_minutes)
        if any(s.type == data.type for s in await self._sources()):
            raise ConflictError(f"A {data.type} source already exists")
        config = validate_config(data.type, data.config)
        source = DirectorySource(
            org_id=self.org_id,
            type=data.type,
            name=data.name.strip(),
            is_primary=False,
            enabled=data.enabled,
            sync_interval_minutes=data.sync_interval_minutes,
            config_encrypted=self._encrypt(config),
            created_by=self.ctx.user.id,
        )
        self.session.add(source)
        await self.session.flush()
        if data.is_primary:
            await self._set_primary(source)
        await self.audit.record(
            self.audit_ctx,
            "directory_source.create",
            "directory_source",
            source.id,
            None,
            self._audit_view(source, config),
        )
        await self.session.flush()
        return self.out(source)

    def _audit_view(self, source: DirectorySource, config: dict[str, Any]) -> dict[str, Any]:
        secrets = secret_fields(source.type)
        return {
            "type": source.type,
            "name": source.name,
            "is_primary": source.is_primary,
            "enabled": source.enabled,
            "sync_interval_minutes": source.sync_interval_minutes,
            "config": {k: ("***" if k in secrets else v) for k, v in config.items()},
        }

    def _merge_secrets(
        self, source_type: str, new: dict[str, Any], old: dict[str, Any]
    ) -> dict[str, Any]:
        merged = dict(new)
        for key in secret_fields(source_type):
            if not merged.get(key) and old.get(key):
                merged[key] = old[key]
        return merged

    async def update(self, source_id: str, data: DirectorySourceUpdate) -> DirectorySourceOut:
        source = await self.get(source_id)
        old_config = self._decrypt(source)
        before = self._audit_view(source, old_config)
        config = old_config
        if data.config is not None:
            config = validate_config(
                source.type, self._merge_secrets(source.type, data.config, old_config)
            )
            source.config_encrypted = self._encrypt(config)
        if data.name is not None:
            source.name = data.name.strip()
        if data.enabled is not None:
            source.enabled = data.enabled
        if data.sync_interval_minutes is not None:
            self._check_interval(data.sync_interval_minutes)
            source.sync_interval_minutes = data.sync_interval_minutes
        if data.is_primary is True and not source.is_primary:
            await self._set_primary(source)
        elif data.is_primary is False and source.is_primary:
            source.is_primary = False
            await self._release(source)
        await self.session.flush()
        await self.audit.record(
            self.audit_ctx,
            "directory_source.update",
            "directory_source",
            source.id,
            before,
            self._audit_view(source, config),
        )
        return self.out(source)

    async def delete(self, source_id: str) -> None:
        source = await self.get(source_id)
        before = self._audit_view(source, self._decrypt(source))
        if source.is_primary:
            await self._release(source)
        await self.session.delete(source)
        await self.session.flush()
        await self.audit.record(
            self.audit_ctx, "directory_source.delete", "directory_source", source_id, before, None
        )

    # ---- test connection -----------------------------------------------------------------

    async def test(
        self,
        data: DirectoryTestRequest,
        *,
        upload: bytes | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> DirectoryTestResult:
        config = dict(data.config)
        if data.source_id:
            source = await self.get(data.source_id)
            if source.type != data.type:
                raise ValidationAppError("Source type mismatch")
            config = self._merge_secrets(data.type, config, self._decrypt(source))
        config = validate_config(data.type, config)
        started = time.perf_counter()
        connector = build_connector(
            data.type, config, self.settings, transport=transport, upload=upload
        )
        try:
            info = await connector.test()
        except AppError as exc:
            return DirectoryTestResult(
                ok=False,
                error=exc.message,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
        except Exception as exc:
            logger.warning("directory_test_failed", exc_info=True)
            return DirectoryTestResult(
                ok=False,
                error=f"{type(exc).__name__}: {str(exc)[:300]}",
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
        return DirectoryTestResult(
            ok=True, duration_ms=int((time.perf_counter() - started) * 1000), **info
        )

    # ---- runs ----------------------------------------------------------------------------

    async def _new_run(self, source: DirectorySource, mode: str, force: bool) -> DirectorySyncRun:
        await expire_stale_runs(self.session, source.id)
        running = await self.session.scalar(
            select(func.count())
            .select_from(DirectorySyncRun)
            .where(
                DirectorySyncRun.source_id == source.id,
                DirectorySyncRun.status == SyncStatus.RUNNING.value,
            )
        )
        if running:
            raise ConflictError("A sync of this source is already running", code="SYNC_RUNNING")
        run = DirectorySyncRun(
            org_id=self.org_id,
            source_id=source.id,
            mode=mode,
            status=SyncStatus.RUNNING.value,
            forced=force and mode == SyncMode.APPLY,
            stats={},
            changes={},
            triggered_by=self.ctx.user.username,
        )
        self.session.add(run)
        await self.session.flush()
        return run

    async def start(self, source_id: str, mode: str, force: bool) -> DirectorySyncRun:
        source = await self.get(source_id)
        if source.type == DirectorySourceType.EXCEL:
            raise ValidationAppError(
                "Excel sources are synced by uploading a file", code="DIRECTORY_UPLOAD_REQUIRED"
            )
        if not source.enabled:
            raise AppError("Source is disabled", code="DIRECTORY_SOURCE_DISABLED")
        run = await self._new_run(source, mode, force)
        await self.session.commit()
        self.queue.enqueue_directory_sync(run.id)
        return run

    async def run_upload(
        self, source_id: str, mode: str, force: bool, content: bytes
    ) -> DirectorySyncRun:
        source = await self.get(source_id)
        if source.type != DirectorySourceType.EXCEL:
            raise ValidationAppError("Only Excel sources accept uploads")
        run = await self._new_run(source, mode, force)
        executor = DirectorySyncExecutor(self.session, self.settings, self.authz_cache, self.cache)
        return await executor.execute(run, source, self.audit_ctx, upload=content)

    async def runs(self, source_id: str | None, page: int, size: int) -> Page[SyncRunOut]:
        stmt = select(DirectorySyncRun).where(DirectorySyncRun.org_id == self.org_id)
        if source_id:
            stmt = stmt.where(DirectorySyncRun.source_id == source_id)
        stmt = stmt.order_by(DirectorySyncRun.started_at.desc(), DirectorySyncRun.id)
        items, total = await paginate(self.session, stmt, page, size)
        return Page(
            items=[SyncRunOut.model_validate(r) for r in items], total=total, page=page, size=size
        )

    async def run_detail(self, run_id: str) -> SyncRunDetail:
        run = await self.session.get(DirectorySyncRun, run_id)
        if run is None or run.org_id != self.org_id:
            raise NotFoundError("Sync run not found")
        return SyncRunDetail.model_validate(run)


async def expire_stale_runs(session: AsyncSession, source_id: str) -> None:
    await session.execute(
        update(DirectorySyncRun)
        .where(
            DirectorySyncRun.source_id == source_id,
            DirectorySyncRun.status == SyncStatus.RUNNING.value,
            DirectorySyncRun.started_at < utcnow() - STALE_RUN_AFTER,
        )
        .values(status=SyncStatus.FAILED.value, error="Run lost (worker restarted?)")
    )


async def due_sources(session: AsyncSession) -> list[DirectorySource]:
    rows = await session.execute(
        select(DirectorySource).where(
            DirectorySource.enabled.is_(True),
            DirectorySource.sync_interval_minutes > 0,
            DirectorySource.type != DirectorySourceType.EXCEL.value,
        )
    )
    now = utcnow()
    return [s for s in rows.scalars() if (due := next_sync_at(s)) is not None and due <= now]
