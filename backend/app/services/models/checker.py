"""Connectivity checks of a single model and model listing (GET /models) of a provider."""

import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import Settings
from app.llm.base import ChatMessage, LLMError
from app.llm.openai_compat import HttpCaller, OpenAIChatClient, OpenAIRerankClient
from app.models import ModelKind

CHECK_PROMPT = "这是一次连通性检测，请只回复：OK"
CHECK_EMBED_TEXT = "飞织知识库连通性检测"
CHECK_QUERY = "飞织鞋面"
CHECK_DOCUMENTS = ["飞织鞋面的编织工艺介绍", "注塑模具的日常保养"]
MESSAGE_LIMIT = 500


@dataclass
class CheckOutcome:
    ok: bool
    latency_ms: int
    message: str
    sample: str | None = None
    dim: int | None = None
    first_token_ms: int | None = None


def guess_kind(name: str) -> ModelKind:
    lowered = name.lower()
    if "rerank" in lowered or "rank" in lowered:
        return ModelKind.RERANK
    if "embed" in lowered:
        return ModelKind.EMBEDDING
    return ModelKind.CHAT


class ModelChecker:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self.transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=self.transport)

    def _caller(self, http: httpx.AsyncClient, base_url: str, api_key: str | None) -> HttpCaller:
        return HttpCaller(
            http,
            base_url,
            api_key=api_key,
            timeout=self.settings.llm_check_timeout_seconds,
            max_retries=0,
            backoff_seconds=0,
        )

    async def list_models(self, base_url: str, api_key: str | None) -> list[str]:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        async with self._client() as http:
            try:
                resp = await http.get(
                    f"{base_url.rstrip('/')}/models",
                    headers=headers,
                    timeout=self.settings.llm_check_timeout_seconds,
                )
            except httpx.HTTPError as exc:
                raise LLMError(f"/models: {type(exc).__name__}: {exc}") from exc
        if resp.status_code >= 400:
            raise LLMError(f"/models: HTTP {resp.status_code}: {resp.text[:300]}")
        try:
            data: Any = resp.json()
            items = data.get("data", []) if isinstance(data, dict) else data
            names = [str(item["id"]) for item in items]
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise LLMError("/models: malformed response") from exc
        return sorted(set(names))

    async def check(
        self,
        kind: str,
        model: str,
        base_url: str,
        api_key: str | None,
        *,
        path: str | None = None,
    ) -> CheckOutcome:
        started = time.perf_counter()
        try:
            async with self._client() as http:
                caller = self._caller(http, base_url, api_key)
                if kind == ModelKind.CHAT:
                    outcome = await self._chat(caller, model, started)
                elif kind == ModelKind.EMBEDDING:
                    outcome = await self._embedding(caller, model)
                else:
                    outcome = await self._rerank(caller, model, path)
        except LLMError as exc:
            outcome = CheckOutcome(ok=False, latency_ms=0, message=str(exc)[:MESSAGE_LIMIT])
        except httpx.HTTPError as exc:
            outcome = CheckOutcome(
                ok=False, latency_ms=0, message=f"{type(exc).__name__}: {exc}"[:MESSAGE_LIMIT]
            )
        outcome.latency_ms = round((time.perf_counter() - started) * 1000)
        return outcome

    async def _chat(self, caller: HttpCaller, model: str, started: float) -> CheckOutcome:
        client = OpenAIChatClient(
            caller,
            model,
            extra_body=self.settings.chat_extra_body,
            stream_usage=self.settings.chat_stream_include_usage,
        )
        parts: list[str] = []
        first_token_ms: int | None = None
        async for token in client.stream(
            [ChatMessage(role="user", content=CHECK_PROMPT)], max_tokens=32, temperature=0
        ):
            if first_token_ms is None:
                first_token_ms = round((time.perf_counter() - started) * 1000)
            parts.append(token)
        text = "".join(parts).strip()
        if not text:
            return CheckOutcome(ok=False, latency_ms=0, message="模型没有返回内容")
        return CheckOutcome(
            ok=True, latency_ms=0, message="ok", sample=text[:200], first_token_ms=first_token_ms
        )

    async def _embedding(self, caller: HttpCaller, model: str) -> CheckOutcome:
        data = await caller.post_json(
            "/embeddings",
            {"model": model, "input": [CHECK_EMBED_TEXT], "encoding_format": "float"},
        )
        try:
            vector = data["data"][0]["embedding"]
            dim = len(vector)
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("/embeddings: malformed response") from exc
        if not dim:
            return CheckOutcome(ok=False, latency_ms=0, message="返回了空向量")
        return CheckOutcome(ok=True, latency_ms=0, message="ok", dim=dim, sample=f"{dim} 维向量")

    async def _rerank(self, caller: HttpCaller, model: str, path: str | None) -> CheckOutcome:
        client = OpenAIRerankClient(caller, model, path=path or self.settings.rerank_path)
        results = await client.rerank(CHECK_QUERY, CHECK_DOCUMENTS)
        if not results:
            return CheckOutcome(ok=False, latency_ms=0, message="没有返回打分结果")
        best = results[0]
        if not 0 <= best.index < len(CHECK_DOCUMENTS):
            return CheckOutcome(ok=False, latency_ms=0, message=f"返回了无效的序号 {best.index}")
        sample = f"最相关：{CHECK_DOCUMENTS[best.index]}（{best.score:.3f}）"
        return CheckOutcome(ok=True, latency_ms=0, message="ok", sample=sample)
