import asyncio
from collections.abc import Sequence

from app.llm import LLMError, LLMGateway
from app.retrieval.config import RerankConfig


class RerankUnavailableError(Exception):
    """Reranking failed or timed out; callers fall back to the fused order."""


class Reranker:
    def __init__(self, gateway: LLMGateway) -> None:
        self.gateway = gateway

    async def score(self, query: str, passages: Sequence[str], cfg: RerankConfig) -> list[float]:
        """Relevance score per passage (input order), batched with bounded concurrency."""
        if not passages:
            return []
        texts = [p[: cfg.max_chars] for p in passages]
        semaphore = asyncio.Semaphore(cfg.concurrency)
        scores = [0.0] * len(texts)

        async def run(offset: int, batch: list[str]) -> None:
            async with semaphore:
                results = await self.gateway.rerank(query, batch, None, degrade=False)
            if len(results) != len(batch):
                raise RerankUnavailableError(f"reranker returned {len(results)}/{len(batch)}")
            for r in results:
                scores[offset + r.index] = r.score

        batches = [
            run(i, texts[i : i + cfg.batch_size]) for i in range(0, len(texts), cfg.batch_size)
        ]
        try:
            await asyncio.wait_for(asyncio.gather(*batches), timeout=cfg.timeout_seconds)
        except TimeoutError as exc:
            raise RerankUnavailableError("timeout") from exc
        except LLMError as exc:
            raise RerankUnavailableError(f"error: {exc}") from exc
        return scores
