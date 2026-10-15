"""First start: register the models of the deployment configuration in the model admin page.

Only providers and models are created; no chat route is stored, so the startup configuration
stays in effect until an administrator picks a model.
"""

import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.models import LlmModel, LlmProvider, ModelKind
from app.repositories.llm_config_repo import LlmConfigRepository
from app.services.models.runtime import encrypt_api_key, key_hint

logger = logging.getLogger(__name__)

ENV_PROVIDER_NAME = "默认提供方（部署配置）"
NO_KEY = {"", "EMPTY"}


def _override(url: str | None, provider_url: str) -> str | None:
    if not url:
        return None
    url = url.rstrip("/")
    return None if url == provider_url else url


async def import_env_config(
    session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> bool:
    if settings.llm_provider != "openai":
        return False
    async with session_factory() as session:
        if await LlmConfigRepository(session).has_providers():
            return False
        base_url = settings.chat_base_url.rstrip("/")
        api_key = settings.llm_api_key
        provider = LlmProvider(
            name=ENV_PROVIDER_NAME,
            base_url=base_url,
            enabled=True,
            source="env",
        )
        if api_key not in NO_KEY:
            provider.api_key_encrypted = encrypt_api_key(settings, api_key)
            provider.api_key_hint = key_hint(api_key)
        session.add(provider)
        try:
            await session.flush()
        except IntegrityError:
            # Another process imported concurrently.
            await session.rollback()
            return False

        models: dict[str, LlmModel] = {}

        def add(name: str | None, kind: ModelKind, **extra: str | int | None) -> None:
            if name and name not in models:
                models[name] = LlmModel(
                    provider_id=provider.id, name=name, kind=kind.value, origin="manual", **extra
                )

        add(settings.chat_model, ModelKind.CHAT)
        add(
            settings.chat_fallback_model,
            ModelKind.CHAT,
            base_url=_override(settings.chat_fallback_base_url, base_url),
        )
        add(
            settings.embedding_model,
            ModelKind.EMBEDDING,
            base_url=_override(settings.embedding_base_url, base_url),
            detected_dim=settings.embedding_dim,
        )
        add(
            settings.rerank_model,
            ModelKind.RERANK,
            base_url=_override(settings.rerank_base_url, base_url),
            path=settings.rerank_path,
        )
        session.add_all(models.values())
        await session.commit()
    logger.info("llm_config_imported", extra={"models": len(models)})
    return True
