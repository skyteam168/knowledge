"""Clients for OpenAI-compatible model servers (vLLM, TEI, Xinference, ...)."""

import asyncio
import json
import logging
import random
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx

from app.llm.base import ChatMessage, ChatResult, EmbeddingSpec, LLMError, RerankResult
from app.llm.usage import report_usage

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})


class HttpCaller:
    """POSTs JSON with a per-call timeout and exponential-backoff retries."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        base_url: str,
        *,
        api_key: str | None,
        timeout: float,
        max_retries: int,
        backoff_seconds: float,
        pool_timeout: float | None = None,
    ) -> None:
        self.http = http
        self.base_url = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.timeout = httpx.Timeout(timeout, pool=pool_timeout if pool_timeout else timeout)
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds

    def _delay(self, attempt: int) -> float:
        base = self.backoff_seconds * (2**attempt)
        return float(base + random.uniform(0, self.backoff_seconds))

    async def _retry_wait(self, attempt: int, path: str, error: str) -> None:
        logger.warning(
            "llm_call_retry", extra={"path": path, "attempt": attempt + 1, "error": error[:300]}
        )
        await asyncio.sleep(self._delay(attempt))

    async def post_json(self, path: str, body: dict[str, Any]) -> Any:
        url = f"{self.base_url}{path}"
        last_error = ""
        for attempt in range(self.max_retries + 1):
            try:
                resp = await self.http.post(
                    url, json=body, headers=self.headers, timeout=self.timeout
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            else:
                if resp.status_code < 400:
                    try:
                        return resp.json()
                    except ValueError as exc:
                        raise LLMError(f"{path}: invalid JSON response") from exc
                last_error = f"HTTP {resp.status_code}: {resp.text[:300]}"
                if resp.status_code not in RETRYABLE_STATUS:
                    raise LLMError(f"{path}: {last_error}")
            if attempt < self.max_retries:
                await self._retry_wait(attempt, path, last_error)
        raise LLMError(f"{path}: {last_error}", retryable=True)

    async def stream_sse(self, path: str, body: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        """Yields `data:` JSON payloads; retries only until the first event arrives."""
        url = f"{self.base_url}{path}"
        last_error = ""
        for attempt in range(self.max_retries + 1):
            started = False
            try:
                async with self.http.stream(
                    "POST", url, json=body, headers=self.headers, timeout=self.timeout
                ) as resp:
                    if resp.status_code >= 400:
                        text = (await resp.aread()).decode("utf-8", "replace")
                        last_error = f"HTTP {resp.status_code}: {text[:300]}"
                        if resp.status_code not in RETRYABLE_STATUS:
                            raise LLMError(f"{path}: {last_error}")
                    else:
                        async for line in resp.aiter_lines():
                            if not line.startswith("data:"):
                                continue
                            data = line[5:].strip()
                            if data == "[DONE]":
                                return
                            started = True
                            yield json.loads(data)
                        return
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if started:
                    raise LLMError(f"{path}: stream interrupted: {exc}", retryable=True) from exc
                last_error = f"{type(exc).__name__}: {exc}"
            if attempt < self.max_retries:
                await self._retry_wait(attempt, path, last_error)
        raise LLMError(f"{path}: {last_error}", retryable=True)


class OpenAIEmbeddingClient:
    def __init__(
        self,
        caller: HttpCaller,
        spec: EmbeddingSpec,
        *,
        batch_size: int,
        concurrency: int,
        send_dimensions: bool = False,
    ) -> None:
        self.caller = caller
        self._spec = spec
        self.batch_size = max(1, batch_size)
        self.send_dimensions = send_dimensions
        # Shared by every call on this client: caps in-flight requests per process.
        self._semaphore = asyncio.Semaphore(max(1, concurrency))

    @property
    def spec(self) -> EmbeddingSpec:
        return self._spec

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        batches = [
            list(texts[i : i + self.batch_size]) for i in range(0, len(texts), self.batch_size)
        ]
        results = await asyncio.gather(*(self._embed_batch(b) for b in batches))
        return [vec for batch in results for vec in batch]

    async def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        body: dict[str, Any] = {
            "model": self._spec.model,
            "input": batch,
            "encoding_format": "float",
        }
        if self.send_dimensions:
            body["dimensions"] = self._spec.dim
        async with self._semaphore:
            data = await self.caller.post_json("/embeddings", body)
        try:
            items = sorted(data["data"], key=lambda d: d.get("index", 0))
            vectors = [[float(x) for x in item["embedding"]] for item in items]
        except (KeyError, TypeError, ValueError) as exc:
            raise LLMError("/embeddings: malformed response") from exc
        report_usage(self._spec.model, data.get("usage"))
        if len(vectors) != len(batch):
            raise LLMError(f"/embeddings: expected {len(batch)} vectors, got {len(vectors)}")
        for vec in vectors:
            if len(vec) != self._spec.dim:
                raise LLMError(
                    f"/embeddings: model {self._spec.model} returned dim {len(vec)}, "
                    f"configured {self._spec.dim}"
                )
        return vectors


class OpenAIRerankClient:
    """Jina / Cohere style rerank (vLLM `/rerank`, DashScope `/reranks`); also accepts TEI's
    list response."""

    def __init__(
        self,
        caller: HttpCaller,
        model: str,
        *,
        path: str = "/rerank",
        instruct: str | None = None,
    ) -> None:
        self.caller = caller
        self._model = model
        self.path = "/" + path.lstrip("/")
        self.instruct = instruct

    @property
    def model(self) -> str:
        return self._model

    async def rerank(
        self, query: str, documents: Sequence[str], top_n: int | None = None
    ) -> list[RerankResult]:
        if not documents:
            return []
        body: dict[str, Any] = {
            "model": self._model,
            "query": query,
            "documents": list(documents),
            "return_documents": False,
        }
        if top_n is not None:
            body["top_n"] = top_n
        if self.instruct:
            body["instruct"] = self.instruct
        data = await self.caller.post_json(self.path, body)
        rows = data if isinstance(data, list) else data.get("results", [])
        try:
            results = [
                RerankResult(
                    index=int(r["index"]), score=float(r.get("relevance_score", r.get("score")))
                )
                for r in rows
            ]
        except (KeyError, TypeError, ValueError) as exc:
            raise LLMError(f"{self.path}: malformed response") from exc
        report_usage(self._model, data.get("usage") if isinstance(data, dict) else None)
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_n] if top_n is not None else results


class OpenAIChatClient:
    def __init__(
        self,
        caller: HttpCaller,
        model: str,
        *,
        extra_body: dict[str, Any] | None = None,
        stream_usage: bool = True,
    ) -> None:
        self.caller = caller
        self._model = model
        # Provider-specific request fields (e.g. DashScope `enable_thinking`).
        self.extra_body = dict(extra_body or {})
        # Ask for the usage chunk at the end of streams (`stream_options.include_usage`).
        self.stream_usage = stream_usage

    @property
    def model(self) -> str:
        return self._model

    def _body(
        self, messages: Sequence[ChatMessage], stream: bool, **options: Any
    ) -> dict[str, Any]:
        return {
            **self.extra_body,
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": stream,
            **{k: v for k, v in options.items() if v is not None},
        }

    async def complete(self, messages: Sequence[ChatMessage], **options: Any) -> ChatResult:
        data = await self.caller.post_json(
            "/chat/completions", self._body(messages, False, **options)
        )
        try:
            choice = data["choices"][0]
            result = ChatResult(
                content=choice["message"].get("content") or "",
                model=data.get("model", self._model),
                finish_reason=choice.get("finish_reason"),
                usage={
                    k: int(v) for k, v in (data.get("usage") or {}).items() if isinstance(v, int)
                },
            )
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("/chat/completions: malformed response") from exc
        report_usage(self._model, result.usage)
        return result

    async def stream(self, messages: Sequence[ChatMessage], **options: Any) -> AsyncIterator[str]:
        body = self._body(messages, True, **options)
        if self.stream_usage:
            body.setdefault("stream_options", {"include_usage": True})
        usage: dict[str, Any] | None = None
        async for event in self.caller.stream_sse("/chat/completions", body):
            if isinstance(event.get("usage"), dict):
                usage = event["usage"]
            for choice in event.get("choices") or []:
                content = (choice.get("delta") or {}).get("content")
                if content:
                    yield content
        report_usage(self._model, usage)
