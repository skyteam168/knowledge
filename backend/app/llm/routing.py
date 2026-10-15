"""Chat client whose model can be switched at runtime (model admin page).

Without a stored route the client configured at startup is used. Routes are re-read at most
every `refresh_seconds`; a failing read keeps the current client. Calls in flight keep the
client they started with.
"""

import asyncio
import logging
import math
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from app.llm.base import ChatClient, ChatMessage, ChatResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChatTarget:
    model: str
    base_url: str
    api_key: str | None = None


@dataclass(frozen=True)
class ChatRoute:
    primary: ChatTarget
    fallback: ChatTarget | None = None


RouteLoader = Callable[[], Awaitable[ChatRoute | None]]
ChatFactory = Callable[[ChatRoute], ChatClient]


class RoutedChatClient:
    def __init__(
        self,
        default: ChatClient,
        loader: RouteLoader,
        factory: ChatFactory,
        *,
        refresh_seconds: float = 5.0,
    ) -> None:
        self.default = default
        self.loader = loader
        self.factory = factory
        self.refresh_seconds = refresh_seconds
        self.route: ChatRoute | None = None
        self._active: ChatClient = default
        self._checked_at = -math.inf
        self._lock = asyncio.Lock()

    @property
    def model(self) -> str:
        return self._active.model

    @property
    def active(self) -> ChatClient:
        return self._active

    def invalidate(self) -> None:
        self._checked_at = -math.inf

    def _fresh(self) -> bool:
        return time.monotonic() - self._checked_at < self.refresh_seconds

    async def refresh(self) -> None:
        if self._fresh():
            return
        async with self._lock:
            if self._fresh():
                return
            try:
                route = await self.loader()
            except Exception:
                logger.exception("chat_route_load_failed")
                self._checked_at = time.monotonic()
                return
            self._checked_at = time.monotonic()
            if route == self.route:
                return
            self._active = self.default if route is None else self.factory(route)
            self.route = route
            logger.info("chat_route_applied", extra={"model": self._active.model})

    async def complete(self, messages: Sequence[ChatMessage], **options: Any) -> ChatResult:
        return await self._active.complete(messages, **options)

    async def stream(self, messages: Sequence[ChatMessage], **options: Any) -> AsyncIterator[str]:
        client = self._active
        async for token in client.stream(messages, **options):
            yield token
