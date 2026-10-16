"""Answer context: evidence units and the gate deciding whether the LLM may answer."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.retrieval.pipeline import DocumentInfo, Passage


@dataclass(frozen=True)
class Hit:
    """A retrieval result merged over (sub-)queries; `score` is the best rerank score."""

    passage: Passage
    score: float | None
    rank: int

    @property
    def chunk_id(self) -> str:
        return self.passage.chunk_id


class EvidenceKind(StrEnum):
    PARENT = "parent"
    CHUNKS = "chunks"
    KO = "ko"


@dataclass(frozen=True)
class MaterialImage:
    """Presigned page/slide image the model may embed via Markdown."""

    url: str
    caption: str
    mime_type: str | None = None


@dataclass
class Evidence:
    """One numbered material [n] of the prompt."""

    kind: EvidenceKind
    document: DocumentInfo
    # PG chunks whose text makes up `content`, in document order.
    chunk_ids: list[str]
    # Retrieval hits covered by this evidence, best first.
    hit_chunk_ids: list[str]
    content: str
    heading_path: list[str]
    score: float | None
    best_rank: int
    # Text of the best hit (citation snippet).
    quote: str
    page_start: int | None = None
    page_end: int | None = None
    sheet_name: str | None = None
    slide_number: int | None = None
    is_ko: bool = False
    tokens: int = 0
    truncated: bool = False
    # Presigned page/slide URLs attached after ACL (answer phase 2).
    images: list[MaterialImage] = field(default_factory=list)

    @property
    def anchor_chunk_id(self) -> str:
        return self.hit_chunk_ids[0] if self.hit_chunk_ids else self.chunk_ids[0]

    def describe(self, *, with_content: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = {
            "kind": self.kind.value,
            "document_id": self.document.id,
            "title": self.document.title,
            "chunk_ids": self.chunk_ids,
            "hit_chunk_ids": self.hit_chunk_ids,
            "heading_path": self.heading_path,
            "score": self.score,
            "best_rank": self.best_rank,
            "tokens": self.tokens,
            "truncated": self.truncated,
            "is_ko": self.is_ko,
            "images": [
                {"caption": img.caption, "url": img.url, "mime_type": img.mime_type}
                for img in self.images
            ],
        }
        if with_content:
            data["content"] = self.content
        return data


class Verdict(StrEnum):
    REFUSE = "refuse"
    UNCERTAIN = "uncertain"
    CONFIDENT = "confident"


@dataclass(frozen=True)
class EvidenceDecision:
    verdict: Verdict
    reason: str
    top_score: float | None
    count: int
    thresholds: dict[str, float] = field(default_factory=dict)

    def describe(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "reason": self.reason,
            "top_score": self.top_score,
            "count": self.count,
            "thresholds": self.thresholds,
        }


class EvidenceValidator:
    def __init__(self, *, min_score: float, confident_score: float, min_count: int = 1) -> None:
        self.min_score = min_score
        self.confident_score = max(confident_score, min_score)
        self.min_count = max(1, min_count)

    def validate(self, evidences: list[Evidence]) -> EvidenceDecision:
        thresholds = {"min_score": self.min_score, "confident_score": self.confident_score}
        scores = [e.score for e in evidences if e.score is not None]
        top = max(scores) if scores else None
        count = len(evidences)

        def decide(verdict: Verdict, reason: str) -> EvidenceDecision:
            return EvidenceDecision(verdict, reason, top, count, thresholds)

        if count < self.min_count:
            return decide(Verdict.REFUSE, "no_evidence")
        if top is None:
            # Reranker disabled / degraded: relevance unknown, answer with caveats.
            return decide(Verdict.UNCERTAIN, "no_rerank_score")
        if top < self.min_score:
            return decide(Verdict.REFUSE, "low_score")
        if top < self.confident_score:
            return decide(Verdict.UNCERTAIN, "mid_score")
        return decide(Verdict.CONFIDENT, "ok")
