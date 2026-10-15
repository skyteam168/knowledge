"""Conflict detection for a KO draft: retrieve similar published KOs and documents (with the
reviewer's permissions), then let the LLM judge the closest ones for contradictions."""

import logging
from typing import Any

from app.core.config import Settings
from app.core.exceptions import ValidationAppError
from app.models import KnowledgeObject
from app.services.curation.compiler import KnowledgeCompiler, Verdict
from app.services.indexing.ko_indexer import ko_entry_text
from app.services.search.search_service import SearchParams, SearchService

logger = logging.getLogger(__name__)

EXCERPT_CHARS = 300


class ConflictDetector:
    def __init__(
        self, search: SearchService, compiler: KnowledgeCompiler, settings: Settings
    ) -> None:
        self.search = search
        self.compiler = compiler
        self.settings = settings

    async def detect(self, ko: KnowledgeObject) -> list[dict[str, Any]]:
        params = SearchParams(
            q=ko.question[:500],
            kb_ids=(ko.kb_id,),
            top_k=self.settings.ko_conflict_top_k,
            fresh=True,
        )
        try:
            run = await self.search.execute(params)
        except ValidationAppError:
            return []
        results = run.outcome.results if run.outcome else []
        candidates = []
        seen: set[str] = set()
        for r in results:
            p = r.passage
            if p.document.id == ko.id or p.document.id in seen:
                continue
            score = r.rerank_score
            if score is not None and score < self.settings.ko_conflict_min_score:
                continue
            seen.add(p.document.id)
            candidates.append(r)
        new_text = ko_entry_text(ko.question, ko.answer)
        found: list[dict[str, Any]] = []
        for r in candidates[: self.settings.ko_conflict_max_judgements]:
            p = r.passage
            judgement = await self.compiler.judge(new_text, p.content)
            found.append(
                {
                    "kind": "ko" if p.is_ko else "document",
                    "id": p.document.id,
                    "chunk_id": p.chunk_id,
                    "title": p.document.title,
                    "version": p.document.version,
                    "score": r.rerank_score,
                    "verdict": judgement.verdict.value,
                    "reason": judgement.reason,
                    "excerpt": p.content[:EXCERPT_CHARS],
                }
            )
        order = {Verdict.CONFLICT.value: 0, Verdict.DUPLICATE.value: 1}
        found.sort(key=lambda c: (order.get(c["verdict"], 2), -(c["score"] or 0.0)))
        logger.info(
            "ko_conflicts_checked",
            extra={
                "ko_id": ko.id,
                "candidates": len(found),
                "conflicts": sum(1 for c in found if c["verdict"] == Verdict.CONFLICT.value),
            },
        )
        return found
