"""Per-process wiring of the chat routing stored by the model admin page."""

import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.crypto import decrypt_json, encrypt_json
from app.llm import LLMGateway
from app.llm.gateway import routed_chat_factory
from app.llm.instrumented import InstrumentedChatClient
from app.llm.routing import ChatFactory, ChatRoute, ChatTarget, RoutedChatClient
from app.models import ChatScene, LlmModel, LlmProvider, ModelKind
from app.repositories.llm_config_repo import LlmConfigRepository

logger = logging.getLogger(__name__)


def model_secret(settings: Settings) -> str:
    return settings.llm_secret_key or settings.directory_secret_key


def encrypt_api_key(settings: Settings, api_key: str) -> str:
    return encrypt_json(model_secret(settings), {"api_key": api_key})


def decrypt_api_key(settings: Settings, provider: LlmProvider) -> str | None:
    if not provider.api_key_encrypted:
        return None
    value = decrypt_json(model_secret(settings), provider.api_key_encrypted).get("api_key")
    return str(value) if value else None


def key_hint(api_key: str) -> str:
    if len(api_key) <= 8:
        return "****"
    return f"{api_key[:3]}****{api_key[-4:]}"


def model_base_url(model: LlmModel, provider: LlmProvider) -> str:
    return (model.base_url or provider.base_url).rstrip("/")


def chat_target(settings: Settings, model: LlmModel, provider: LlmProvider) -> ChatTarget:
    return ChatTarget(
        model=model.name,
        base_url=model_base_url(model, provider),
        api_key=decrypt_api_key(settings, provider),
    )


def usable(model: LlmModel, provider: LlmProvider) -> bool:
    return provider.enabled and model.kind == ModelKind.CHAT


async def load_chat_route(
    session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> ChatRoute | None:
    """The stored chat route, or None (use the startup configuration)."""
    async with session_factory() as session:
        rows = await LlmConfigRepository(session).route_rows()
    targets = {
        route.scene: chat_target(settings, model, provider)
        for route, model, provider in rows
        if usable(model, provider)
    }
    primary = targets.get(ChatScene.CHAT.value)
    if primary is None:
        return None
    return ChatRoute(primary=primary, fallback=targets.get(ChatScene.CHAT_FALLBACK.value))


def attach_chat_routing(
    gateway: LLMGateway,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    *,
    factory: ChatFactory | None = None,
) -> RoutedChatClient | None:
    """Routes the gateway's chat through the stored configuration (real providers only)."""
    if factory is None:
        if gateway.http is None:
            return None
        factory = routed_chat_factory(settings, gateway.http)

    async def loader() -> ChatRoute | None:
        return await load_chat_route(session_factory, settings)

    instrumented = gateway.chat if isinstance(gateway.chat, InstrumentedChatClient) else None
    routed = RoutedChatClient(
        instrumented.inner if instrumented else gateway.chat,
        loader,
        factory,
        refresh_seconds=settings.llm_route_refresh_seconds,
    )
    if instrumented is not None:
        instrumented.inner = routed
    else:
        gateway.chat = routed
    gateway.chat_refresh = routed.refresh
    return routed
