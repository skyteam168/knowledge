"""Token metering of model calls.

Clients report the provider's `usage` with `report_usage`; the gateway collects those reports
around each call and hands a `UsageEvent` to its recorder. Who and what a call is for comes
from the ambient `UsageScope` (set by request dependencies, services and workers).
"""

import math
import re
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from typing import Any, Protocol, TypeVar

T = TypeVar("T")

KIND_CHAT = "chat"
KIND_EMBEDDING = "embedding"
KIND_RERANK = "rerank"

FEATURE_ASSISTANT = "assistant"
FEATURE_SEARCH = "search"
FEATURE_OPEN_API = "open_api"
FEATURE_EVALUATION = "evaluation"
FEATURE_CURATION = "curation"
FEATURE_INDEXING = "indexing"
FEATURE_OTHER = "other"

STAGE_REWRITE = "rewrite"
STAGE_RETRIEVAL = "retrieval"
STAGE_GENERATE = "generate"
STAGE_JUDGE = "judge"
STAGE_COMPILE = "compile"
STAGE_CLUSTER = "cluster"
STAGE_INDEX = "index"

# Per chat message framing overhead of OpenAI-style templates.
MESSAGE_OVERHEAD_TOKENS = 4
_CJK = re.compile(r"[\u2e80-\u9fff\uac00-\ud7af\uf900-\ufaff\uff00-\uffef]")


@dataclass(frozen=True)
class UsageScope:
    org_id: str | None = None
    user_id: str | None = None
    # Business entry point (assistant / search / open_api / ...): the outermost scope wins.
    feature: str | None = None
    # Step inside the feature (rewrite / generate / retrieval / ...): the innermost wins.
    stage: str | None = None
    conversation_id: str | None = None
    message_id: str | None = None


@dataclass(frozen=True)
class UsageReport:
    model: str
    usage: dict[str, int]


@dataclass(frozen=True)
class UsageEvent:
    kind: str
    model: str
    scope: UsageScope
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    # No provider usage was returned: tokens are a character-based estimate.
    estimated: bool = False
    input_count: int = 0
    latency_ms: int = 0
    first_token_ms: int | None = None
    status: str = "ok"
    # A fallback model served the call instead of the configured one.
    fallback: bool = False


class UsageRecorder(Protocol):
    def record(self, event: UsageEvent) -> None: ...


EMPTY_SCOPE = UsageScope()
_scope: ContextVar[UsageScope | None] = ContextVar("llm_usage_scope", default=None)
_collector: ContextVar[list[UsageReport] | None] = ContextVar("llm_usage_collector", default=None)


def current_scope() -> UsageScope:
    return _scope.get() or EMPTY_SCOPE


def _merged(
    base: UsageScope, feature: str | None, stage: str | None, identity: Mapping[str, str | None]
) -> UsageScope:
    return replace(
        base,
        **{k: v for k, v in identity.items() if v is not None},
        feature=base.feature or feature,
        stage=stage or base.stage,
    )


def scope_with(
    *,
    feature: str | None = None,
    stage: str | None = None,
    org_id: str | None = None,
    user_id: str | None = None,
    conversation_id: str | None = None,
    message_id: str | None = None,
) -> UsageScope:
    """The current scope refined with the given fields (not activated)."""
    identity = {
        "org_id": org_id,
        "user_id": user_id,
        "conversation_id": conversation_id,
        "message_id": message_id,
    }
    return _merged(current_scope(), feature, stage, identity)


@contextmanager
def usage_scope(
    *,
    feature: str | None = None,
    stage: str | None = None,
    org_id: str | None = None,
    user_id: str | None = None,
    conversation_id: str | None = None,
    message_id: str | None = None,
) -> Iterator[UsageScope]:
    """Not for use across `yield` of an async generator: see `iterate_in_scope`."""
    scope = scope_with(
        feature=feature,
        stage=stage,
        org_id=org_id,
        user_id=user_id,
        conversation_id=conversation_id,
        message_id=message_id,
    )
    token = _scope.set(scope)
    try:
        yield scope
    finally:
        _scope.reset(token)


def bind_usage_scope(
    *, org_id: str | None = None, user_id: str | None = None, feature: str | None = None
) -> None:
    """Set the identity for the rest of the current task (one HTTP request = one task)."""
    _scope.set(scope_with(org_id=org_id, user_id=user_id, feature=feature))


async def iterate_in_scope(source: AsyncIterator[T], scope: UsageScope) -> AsyncIterator[T]:
    """Run each step of `source` under `scope` without leaking it into the consumer."""
    try:
        while True:
            token = _scope.set(scope)
            try:
                item = await anext(source)
            except StopAsyncIteration:
                return
            finally:
                _scope.reset(token)
            yield item
    finally:
        close = getattr(source, "aclose", None)
        if close is not None:
            token = _scope.set(scope)
            try:
                await close()
            finally:
                _scope.reset(token)


@contextmanager
def collect_usage(reports: list[UsageReport]) -> Iterator[list[UsageReport]]:
    token = _collector.set(reports)
    try:
        yield reports
    finally:
        _collector.reset(token)


def report_usage(model: str, usage: Mapping[str, Any] | None) -> None:
    """Called by clients after each provider response (an empty `usage` still names the
    model that served the call)."""
    reports = _collector.get()
    if reports is None:
        return
    ints = {k: int(v) for k, v in (usage or {}).items() if isinstance(v, int | float)}
    reports.append(UsageReport(model, ints))


def estimate_tokens(text: str) -> int:
    """Rough count: one token per CJK character, four characters per token otherwise."""
    if not text:
        return 0
    cjk = len(_CJK.findall(text))
    other = len(text) - cjk - text.count(" ")
    return cjk + math.ceil(max(0, other) / 4)


def estimate_messages(contents: Sequence[str]) -> int:
    return sum(estimate_tokens(c) + MESSAGE_OVERHEAD_TOKENS for c in contents)


@dataclass
class TokenCount:
    prompt: int = 0
    completion: int = 0
    total: int = 0
    estimated: bool = False
    models: list[str] = field(default_factory=list)


def count_tokens(
    reports: Sequence[UsageReport], prompt_estimate: int, completion_estimate: int = 0
) -> TokenCount:
    """Provider usage summed over `reports`; the estimates when the provider gave none."""
    count = TokenCount(models=[r.model for r in reports])
    for r in reports:
        u = r.usage
        prompt = u.get("prompt_tokens", u.get("input_tokens", 0))
        completion = u.get("completion_tokens", u.get("output_tokens", 0))
        count.prompt += prompt
        count.completion += completion
        count.total += u.get("total_tokens", prompt + completion)
    if count.total <= 0:
        count.prompt, count.completion = prompt_estimate, completion_estimate
        count.total = prompt_estimate + completion_estimate
        count.estimated = True
    elif count.prompt == 0 and count.completion == 0:
        # Rerank providers often report only `total_tokens`; all of it is input.
        count.prompt = count.total
    return count
