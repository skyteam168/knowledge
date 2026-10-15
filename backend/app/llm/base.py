from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

ChatRole = Literal["system", "user", "assistant", "tool"]


class LLMError(Exception):
    """A model call failed after retries (or with a non-retryable error)."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True)
class EmbeddingSpec:
    """Identifies an embedding space: vectors from different specs are not comparable."""

    model: str
    dim: int
    base_url: str


@dataclass(frozen=True)
class RerankResult:
    index: int
    score: float


@dataclass(frozen=True)
class ChatMessage:
    role: ChatRole
    content: str


@dataclass(frozen=True)
class ChatResult:
    content: str
    model: str
    finish_reason: str | None = None
    usage: dict[str, int] = field(default_factory=dict)


class EmbeddingClient(Protocol):
    @property
    def spec(self) -> EmbeddingSpec: ...

    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class RerankClient(Protocol):
    @property
    def model(self) -> str: ...

    async def rerank(
        self, query: str, documents: Sequence[str], top_n: int | None = None
    ) -> list[RerankResult]: ...


class ChatClient(Protocol):
    @property
    def model(self) -> str: ...

    async def complete(self, messages: Sequence[ChatMessage], **options: Any) -> ChatResult: ...

    def stream(self, messages: Sequence[ChatMessage], **options: Any) -> AsyncIterator[str]: ...
