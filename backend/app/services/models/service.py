"""Model admin: providers, their models, connectivity checks and the chat routing.

Only the chat scenes can be switched. Embedding is pinned by the active index generation and
rerank by the deployment configuration; both are shown read-only.
"""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationAppError,
)
from app.llm.base import LLMError
from app.llm.routing import RoutedChatClient
from app.models import (
    ChatScene,
    GenerationStatus,
    LlmModel,
    LlmProvider,
    LlmRoute,
    ModelKind,
    Organization,
)
from app.models.base import utcnow
from app.repositories.base import apply_updates, paginate
from app.repositories.indexing_repo import IndexGenerationRepository
from app.repositories.llm_config_repo import LlmConfigRepository
from app.schemas.common import Page
from app.schemas.models_admin import (
    CheckOut,
    ModelCreate,
    ModelOut,
    ModelUpdate,
    OverviewOut,
    ProviderCreate,
    ProviderOut,
    ProviderUpdate,
    RoutesIn,
    SceneOut,
    SyncResultOut,
)
from app.services.authz.cache import AuthzCache
from app.services.context import BaseService, RequestContext
from app.services.models.checker import CheckOutcome, ModelChecker, guess_kind
from app.services.models.runtime import (
    decrypt_api_key,
    encrypt_api_key,
    key_hint,
    model_base_url,
    usable,
)

CHAT_SCENES = (ChatScene.CHAT.value, ChatScene.CHAT_FALLBACK.value)


class ModelAdminService(BaseService):
    def __init__(
        self,
        session: AsyncSession,
        ctx: RequestContext,
        authz_cache: AuthzCache,
        *,
        settings: Settings,
        router: RoutedChatClient | None,
        checker: ModelChecker | None = None,
    ) -> None:
        super().__init__(session, ctx, authz_cache)
        self.settings = settings
        self.router = router
        self.checker = checker or ModelChecker(settings)
        self.repo = LlmConfigRepository(session)

    # ---- access -------------------------------------------------------------------------

    async def guard(self) -> None:
        """Platform-wide settings: platform admins, or org admins of a single-org deployment."""
        if self.ctx.user.is_platform_admin:
            return
        orgs = (await self.session.execute(select(func.count(Organization.id)))).scalar_one()
        if orgs > 1:
            raise PermissionDeniedError("Only platform administrators can manage models")

    # ---- helpers ------------------------------------------------------------------------

    async def _provider(self, provider_id: str) -> LlmProvider:
        provider = await self.repo.provider(provider_id)
        if provider is None:
            raise NotFoundError("Provider not found")
        return provider

    async def _model(self, model_id: str) -> tuple[LlmModel, LlmProvider]:
        model = await self.repo.model(model_id)
        if model is None:
            raise NotFoundError("Model not found")
        return model, await self._provider(model.provider_id)

    @staticmethod
    def _provider_view(provider: LlmProvider) -> dict[str, Any]:
        return {
            "name": provider.name,
            "base_url": provider.base_url,
            "enabled": provider.enabled,
            "has_api_key": provider.api_key_encrypted is not None,
            "api_key_hint": provider.api_key_hint,
        }

    @staticmethod
    def _model_view(model: LlmModel) -> dict[str, Any]:
        return {
            "provider_id": model.provider_id,
            "name": model.name,
            "kind": model.kind,
            "base_url": model.base_url,
            "path": model.path,
        }

    def _provider_out(self, provider: LlmProvider, count: int, in_use: bool) -> ProviderOut:
        return ProviderOut(
            id=provider.id,
            name=provider.name,
            base_url=provider.base_url,
            has_api_key=provider.api_key_encrypted is not None,
            api_key_hint=provider.api_key_hint,
            enabled=provider.enabled,
            source=provider.source,
            model_count=count,
            in_use=in_use,
            last_synced_at=provider.last_synced_at,
            created_at=provider.created_at,
        )

    async def _scenes_by_model(self) -> dict[str, list[str]]:
        scenes: dict[str, list[str]] = {}
        for route in await self.repo.routes():
            scenes.setdefault(route.model_id, []).append(route.scene)
        return scenes

    def _model_out(
        self, model: LlmModel, provider: LlmProvider, scenes: list[str] | None = None
    ) -> ModelOut:
        return ModelOut(
            id=model.id,
            provider_id=provider.id,
            provider_name=provider.name,
            provider_enabled=provider.enabled,
            name=model.name,
            kind=model.kind,
            origin=model.origin,
            base_url=model.base_url,
            path=model.path,
            effective_base_url=model_base_url(model, provider),
            detected_dim=model.detected_dim,
            scenes=sorted(scenes or []),
            last_check_status=model.last_check_status,
            last_check_at=model.last_check_at,
            last_check_latency_ms=model.last_check_latency_ms,
            last_check_message=model.last_check_message,
        )

    def _invalidate(self) -> None:
        if self.router is not None:
            self.router.invalidate()

    async def _commit_and_apply(self) -> None:
        await self.session.commit()
        self._invalidate()

    # ---- overview -----------------------------------------------------------------------

    async def _match(self, name: str | None, *urls: str | None) -> LlmModel | None:
        if not name:
            return None
        candidates = [u.rstrip("/") for u in urls if u]
        return await self.repo.find_model(name, candidates) if candidates else None

    async def overview(self) -> OverviewOut:
        await self.guard()
        s = self.settings
        routed = {
            route.scene: (model, provider)
            for route, model, provider in await self.repo.route_rows()
            if usable(model, provider)
        }
        page_routing = ChatScene.CHAT.value in routed
        scenes: list[SceneOut] = []

        for scene, cfg_model, cfg_url in (
            (ChatScene.CHAT.value, s.chat_model, s.chat_base_url),
            (
                ChatScene.CHAT_FALLBACK.value,
                s.chat_fallback_model,
                s.chat_fallback_base_url or s.chat_base_url,
            ),
        ):
            if page_routing:
                pair = routed.get(scene)
                model = pair[0] if pair else None
                scenes.append(
                    SceneOut(
                        scene=scene,
                        kind="chat",
                        model=model.name if model else None,
                        base_url=model_base_url(*pair) if pair else None,
                        provider_name=pair[1].name if pair else None,
                        model_id=model.id if model else None,
                        source="page",
                        editable=True,
                        last_check_status=model.last_check_status if model else None,
                        last_check_at=model.last_check_at if model else None,
                    )
                )
                continue
            matched = await self._match(cfg_model, cfg_url)
            scenes.append(
                SceneOut(
                    scene=scene,
                    kind="chat",
                    model=cfg_model or None,
                    base_url=cfg_url.rstrip("/") if cfg_model else None,
                    provider_name=None,
                    model_id=matched.id if matched else None,
                    source="config",
                    editable=True,
                    last_check_status=matched.last_check_status if matched else None,
                    last_check_at=matched.last_check_at if matched else None,
                )
            )

        active = await IndexGenerationRepository(self.session).by_status(GenerationStatus.ACTIVE)
        gen = active[-1] if active else None
        emb_model = gen.embedding_model if gen else s.embedding_model
        emb_url = gen.embedding_base_url if gen else s.embedding_base_url
        emb = await self._match(emb_model, emb_url)
        scenes.append(
            SceneOut(
                scene="embedding",
                kind="embedding",
                model=emb_model,
                base_url=emb_url.rstrip("/"),
                provider_name=None,
                model_id=emb.id if emb else None,
                source="index" if gen else "config",
                editable=False,
                dim=gen.embedding_dim if gen else s.embedding_dim,
                note=(
                    f"由当前生效的第 {gen.version} 代索引固定，切换需全量重建索引"
                    if gen
                    else "尚未建立索引"
                ),
                last_check_status=emb.last_check_status if emb else None,
                last_check_at=emb.last_check_at if emb else None,
            )
        )
        rerank = await self._match(s.rerank_model, s.rerank_base_url)
        scenes.append(
            SceneOut(
                scene="rerank",
                kind="rerank",
                model=s.rerank_model,
                base_url=s.rerank_base_url.rstrip("/"),
                provider_name=None,
                model_id=rerank.id if rerank else None,
                source="config",
                editable=False,
                note="位于检索链路中，只读；如需更换请修改部署配置",
                last_check_status=rerank.last_check_status if rerank else None,
                last_check_at=rerank.last_check_at if rerank else None,
            )
        )
        return OverviewOut(scenes=scenes, refresh_seconds=s.llm_route_refresh_seconds)

    # ---- providers ----------------------------------------------------------------------

    async def list_providers(self) -> list[ProviderOut]:
        await self.guard()
        counts = await self.repo.model_counts()
        used = await self.repo.routed_provider_ids()
        return [
            self._provider_out(p, counts.get(p.id, 0), p.id in used)
            for p in await self.repo.providers()
        ]

    async def _unique_name(self, name: str, provider_id: str | None = None) -> str:
        name = name.strip()
        existing = await self.repo.provider_by_name(name)
        if existing is not None and existing.id != provider_id:
            raise ConflictError("A provider with this name already exists")
        return name

    async def create_provider(self, data: ProviderCreate) -> ProviderOut:
        await self.guard()
        provider = LlmProvider(
            name=await self._unique_name(data.name),
            base_url=data.base_url,
            enabled=data.enabled,
            source="manual",
            created_by=self.ctx.user.id,
        )
        if data.api_key and data.api_key.strip():
            key = data.api_key.strip()
            provider.api_key_encrypted = encrypt_api_key(self.settings, key)
            provider.api_key_hint = key_hint(key)
        self.session.add(provider)
        await self.session.flush()
        await self.audit.record(
            self.audit_ctx,
            "llm_provider.create",
            "llm_provider",
            provider.id,
            None,
            self._provider_view(provider),
        )
        return self._provider_out(provider, 0, False)

    async def update_provider(self, provider_id: str, data: ProviderUpdate) -> ProviderOut:
        await self.guard()
        provider = await self._provider(provider_id)
        before = self._provider_view(provider)
        in_use = provider.id in await self.repo.routed_provider_ids()
        if data.enabled is False and in_use:
            raise ConflictError("此提供方的模型正在用于对话，请先在场景路由中切换到其他模型")
        if data.name is not None:
            provider.name = await self._unique_name(data.name, provider.id)
        if data.base_url is not None:
            provider.base_url = data.base_url
        if data.enabled is not None:
            provider.enabled = data.enabled
        if data.clear_api_key:
            provider.api_key_encrypted = None
            provider.api_key_hint = None
        elif data.api_key and data.api_key.strip():
            key = data.api_key.strip()
            provider.api_key_encrypted = encrypt_api_key(self.settings, key)
            provider.api_key_hint = key_hint(key)
        await self.session.flush()
        await self.audit.record(
            self.audit_ctx,
            "llm_provider.update",
            "llm_provider",
            provider.id,
            before,
            self._provider_view(provider),
        )
        if in_use:
            await self._commit_and_apply()
        count = (await self.repo.model_counts()).get(provider.id, 0)
        return self._provider_out(provider, count, in_use)

    async def delete_provider(self, provider_id: str) -> None:
        await self.guard()
        provider = await self._provider(provider_id)
        if provider.id in await self.repo.routed_provider_ids():
            raise ConflictError("此提供方的模型正在用于对话，请先在场景路由中切换到其他模型")
        before = self._provider_view(provider)
        await self.session.delete(provider)
        await self.session.flush()
        await self.audit.record(
            self.audit_ctx, "llm_provider.delete", "llm_provider", provider_id, before, None
        )

    async def sync_models(self, provider_id: str) -> SyncResultOut:
        await self.guard()
        provider = await self._provider(provider_id)
        try:
            names = await self.checker.list_models(
                provider.base_url, decrypt_api_key(self.settings, provider)
            )
        except LLMError as exc:
            raise ValidationAppError(
                f"获取模型列表失败：{str(exc)[:300]}", code="MODEL_LIST_FAILED"
            ) from exc
        existing = {m.name: m for m in await self.repo.models_of(provider.id)}
        added = [n for n in names if n not in existing]
        for name in added:
            self.session.add(
                LlmModel(
                    provider_id=provider.id,
                    name=name,
                    kind=guess_kind(name).value,
                    origin="synced",
                )
            )
        listed = set(names)
        missing = sorted(n for n, m in existing.items() if m.origin == "synced" and n not in listed)
        provider.last_synced_at = utcnow()
        await self.session.flush()
        await self.audit.record(
            self.audit_ctx,
            "llm_provider.sync",
            "llm_provider",
            provider.id,
            None,
            {"listed": len(names), "added": len(added), "missing": len(missing)},
        )
        return SyncResultOut(listed=len(names), added=len(added), missing=missing)

    # ---- models -------------------------------------------------------------------------

    async def list_models(
        self,
        provider_id: str | None,
        kind: str | None,
        keyword: str | None,
        page: int,
        size: int,
    ) -> Page[ModelOut]:
        await self.guard()
        rows, total = await paginate(
            self.session, self.repo.models_stmt(provider_id, kind, keyword), page, size
        )
        providers = {p.id: p for p in await self.repo.providers()}
        scenes = await self._scenes_by_model()
        items = [self._model_out(m, providers[m.provider_id], scenes.get(m.id)) for m in rows]
        return Page(items=items, total=total, page=page, size=size)

    async def create_model(self, data: ModelCreate) -> ModelOut:
        await self.guard()
        provider = await self._provider(data.provider_id)
        name = data.name.strip()
        if any(m.name == name for m in await self.repo.models_of(provider.id)):
            raise ConflictError("该提供方下已存在同名模型")
        model = LlmModel(
            provider_id=provider.id,
            name=name,
            kind=data.kind,
            origin="manual",
            base_url=data.base_url,
            path=(data.path or "").strip() or None,
        )
        self.session.add(model)
        await self.session.flush()
        await self.audit.record(
            self.audit_ctx, "llm_model.create", "llm_model", model.id, None, self._model_view(model)
        )
        return self._model_out(model, provider)

    async def update_model(self, model_id: str, data: ModelUpdate) -> ModelOut:
        await self.guard()
        model, provider = await self._model(model_id)
        scenes = (await self._scenes_by_model()).get(model.id, [])
        values = data.model_dump(exclude_unset=True)
        if "path" in values:
            values["path"] = (values["path"] or "").strip() or None
        if scenes and values.get("kind", model.kind) != ModelKind.CHAT:
            raise ConflictError("该模型正在用于对话，不能修改类型")
        before = self._model_view(model)
        apply_updates(model, values)
        await self.session.flush()
        await self.audit.record(
            self.audit_ctx,
            "llm_model.update",
            "llm_model",
            model.id,
            before,
            self._model_view(model),
        )
        if scenes:
            await self._commit_and_apply()
        return self._model_out(model, provider, scenes)

    async def delete_model(self, model_id: str) -> None:
        await self.guard()
        model, _ = await self._model(model_id)
        if model.id in await self.repo.routed_model_ids():
            raise ConflictError("该模型正在用于对话，请先在场景路由中切换到其他模型")
        before = self._model_view(model)
        await self.session.delete(model)
        await self.session.flush()
        await self.audit.record(
            self.audit_ctx, "llm_model.delete", "llm_model", model_id, before, None
        )

    async def _run_check(self, model: LlmModel, provider: LlmProvider) -> CheckOutcome:
        outcome = await self.checker.check(
            model.kind,
            model.name,
            model_base_url(model, provider),
            decrypt_api_key(self.settings, provider),
            path=model.path,
        )
        model.last_check_status = "ok" if outcome.ok else "error"
        model.last_check_at = utcnow()
        model.last_check_latency_ms = outcome.latency_ms
        model.last_check_message = outcome.sample if outcome.ok else outcome.message
        if outcome.dim:
            model.detected_dim = outcome.dim
        await self.session.flush()
        return outcome

    async def check_model(self, model_id: str) -> CheckOut:
        await self.guard()
        model, provider = await self._model(model_id)
        outcome = await self._run_check(model, provider)
        warning = None
        if outcome.ok and model.kind == ModelKind.EMBEDDING and outcome.dim:
            active = await IndexGenerationRepository(self.session).by_status(
                GenerationStatus.ACTIVE
            )
            if active and active[-1].embedding_dim != outcome.dim:
                warning = (
                    f"维度 {outcome.dim} 与当前索引的 {active[-1].embedding_dim} 维不一致，"
                    "不能用于现有索引"
                )
        return CheckOut(
            ok=outcome.ok,
            latency_ms=outcome.latency_ms,
            first_token_ms=outcome.first_token_ms,
            message=outcome.message,
            sample=outcome.sample,
            dim=outcome.dim,
            warning=warning,
            checked_at=model.last_check_at or utcnow(),
        )

    # ---- routes -------------------------------------------------------------------------

    async def _chat_model(self, model_id: str) -> tuple[LlmModel, LlmProvider]:
        model, provider = await self._model(model_id)
        if model.kind != ModelKind.CHAT:
            raise ValidationAppError("只能选择类型为「对话」的模型")
        if not provider.enabled:
            raise ValidationAppError("该模型所属的提供方已停用")
        return model, provider

    async def save_routes(self, data: RoutesIn) -> OverviewOut:
        await self.guard()
        before = {r.scene: r.model_id for r in await self.repo.routes()}
        chosen: dict[str, tuple[LlmModel, LlmProvider]] = {}
        if data.chat_model_id is None:
            if data.chat_fallback_model_id is not None:
                raise ValidationAppError("请先选择对话模型")
        else:
            chosen[ChatScene.CHAT.value] = await self._chat_model(data.chat_model_id)
            if data.chat_fallback_model_id is not None:
                if data.chat_fallback_model_id == data.chat_model_id:
                    raise ValidationAppError("备用对话模型不能与对话模型相同")
                chosen[ChatScene.CHAT_FALLBACK.value] = await self._chat_model(
                    data.chat_fallback_model_id
                )

        if chosen and not data.force:
            failures = []
            for scene, (model, provider) in chosen.items():
                outcome = await self._run_check(model, provider)
                if not outcome.ok:
                    failures.append(
                        {"scene": scene, "model": model.name, "message": outcome.message}
                    )
            if failures:
                # Keep the check results even though nothing is switched.
                await self.session.commit()
                raise ValidationAppError(
                    "模型检测未通过，未切换", code="MODEL_CHECK_FAILED", detail=failures
                )

        for scene in CHAT_SCENES:
            pair = chosen.get(scene)
            if pair is None:
                await self.repo.clear_route(scene)
                continue
            route = await self.session.get(LlmRoute, scene)
            if route is None:
                self.session.add(
                    LlmRoute(scene=scene, model_id=pair[0].id, updated_by=self.ctx.user.id)
                )
            else:
                route.model_id = pair[0].id
                route.updated_by = self.ctx.user.id
        await self.session.flush()
        after = {scene: pair[0].id for scene, pair in chosen.items()}
        await self.audit.record(
            self.audit_ctx,
            "llm_route.update",
            "llm_route",
            "chat",
            {"routes": before},
            {
                "routes": after,
                "models": {scene: pair[0].name for scene, pair in chosen.items()},
                "forced": data.force,
            },
        )
        await self._commit_and_apply()
        return await self.overview()
