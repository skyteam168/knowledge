"""Turn retrieval hits (child chunks) into answer context within a token budget.

Strategies (configurable):
- parent: hits are replaced by their parent (section) chunk; several hits under one parent
  yield a single evidence;
- neighbors: hits not covered by a parent get +/- N adjacent child chunks; overlapping
  windows of one document are merged into one evidence;
- ko: published knowledge objects citing the hit documents are added.
Retrieved KO entries (is_ko=true) are used as they are. Evidences are then ordered (KO
first, then rerank score) and cut to the token budget.
"""

import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.models import Chunk
from app.repositories.chat_repo import ChunkRepository
from app.services.chat.evidence import Evidence, EvidenceKind, Hit
from app.services.ingest.tokens import count_tokens

MAX_OVERLAP_CHARS = 800
# Envelope of one material in the prompt (tags, title, heading lines).
MATERIAL_OVERHEAD_TOKENS = 24
# Do not bother squeezing a truncated evidence into less than this.
MIN_TRUNCATED_TOKENS = 200


@dataclass(frozen=True)
class ExpansionConfig:
    parent: bool = True
    neighbors: int = 1
    ko: bool = False
    token_budget: int = 6000


class KnowledgeObjectSource(Protocol):
    async def related(self, hits: Sequence[Hit], exclude: set[str]) -> list[Evidence]:
        """KO evidences linked to the documents of `hits`, except the KO ids in `exclude`."""
        ...


class NoKnowledgeObjects:
    async def related(self, hits: Sequence[Hit], exclude: set[str]) -> list[Evidence]:
        return []


def ko_evidence(hit: Hit) -> Evidence:
    p = hit.passage
    return Evidence(
        kind=EvidenceKind.KO,
        document=p.document,
        chunk_ids=[p.chunk_id],
        hit_chunk_ids=[p.chunk_id],
        content=p.content,
        heading_path=[],
        score=hit.score,
        best_rank=hit.rank,
        quote=p.content,
        is_ko=True,
    )


@dataclass
class ExpansionResult:
    evidences: list[Evidence]
    stats: dict[str, Any] = field(default_factory=dict)


def overlap_len(a: str, b: str, max_chars: int = MAX_OVERLAP_CHARS) -> int:
    """Length of the longest suffix of `a` that is a prefix of `b` (child chunk overlap)."""
    for k in range(min(len(a), len(b), max_chars), 7, -1):
        if a.endswith(b[:k]):
            return k
    return 0


def join_chunks(parts: Sequence[str]) -> str:
    if not parts:
        return ""
    text = parts[0]
    for nxt in parts[1:]:
        k = overlap_len(text, nxt)
        text = text + nxt[k:] if k else f"{text}\n{nxt}"
    return text


def _pages(chunks: Sequence[Chunk]) -> tuple[int | None, int | None]:
    starts = [c.page_start for c in chunks if c.page_start is not None]
    ends = [c.page_end if c.page_end is not None else c.page_start for c in chunks]
    ends_known = [e for e in ends if e is not None]
    return (min(starts) if starts else None, max(ends_known) if ends_known else None)


def _truncate(text: str, tokens: int, target_tokens: int) -> str:
    keep = max(1, math.floor(len(text) * target_tokens / max(tokens, 1)))
    return text[:keep].rstrip() + "…"


class KnowledgeExpansion:
    def __init__(
        self,
        repo: ChunkRepository,
        org_id: str,
        config: ExpansionConfig,
        ko_source: KnowledgeObjectSource | None = None,
    ) -> None:
        self.repo = repo
        self.org_id = org_id
        self.config = config
        self.ko_source = ko_source or NoKnowledgeObjects()

    async def expand(self, hits: Sequence[Hit]) -> ExpansionResult:
        cfg = self.config
        stats: dict[str, Any] = {"hits": len(hits), "config": cfg.__dict__.copy()}
        if not hits:
            stats.update(selected=0, tokens=0)
            return ExpansionResult([], stats)
        ko_hits = [h for h in hits if h.passage.is_ko]
        hits = [h for h in hits if not h.passage.is_ko]
        rows = await self.repo.by_ids(self.org_id, [h.chunk_id for h in hits])

        evidences: list[Evidence] = []
        seen_kos: set[str] = set()
        for hit in ko_hits:
            if hit.passage.document.id not in seen_kos:
                seen_kos.add(hit.passage.document.id)
                evidences.append(ko_evidence(hit))
        stats["ko_hits"] = len(evidences)
        covered: set[str] = set()
        if cfg.parent:
            parent_evidences = await self._parents(hits, rows)
            for ev in parent_evidences:
                covered.update(ev.hit_chunk_ids)
            evidences += parent_evidences
            stats["parents"] = len(parent_evidences)

        rest = [h for h in hits if h.chunk_id not in covered]
        if rest:
            if cfg.neighbors > 0:
                runs = await self._neighbor_runs(rest, rows)
                stats["neighbor_runs"] = len(runs)
            else:
                runs = [self._single(h, rows.get(h.chunk_id)) for h in rest]
                stats["singles"] = len(runs)
            evidences += runs

        if cfg.ko and hits:
            kos = await self.ko_source.related(hits, seen_kos)
            for ko in kos:
                ko.is_ko = True
            evidences = kos + evidences
            stats["ko"] = len(kos)

        selected, dropped = self._fit(evidences)
        stats.update(
            candidates=len(evidences),
            selected=len(selected),
            dropped_over_budget=dropped,
            tokens=sum(e.tokens for e in selected),
        )
        return ExpansionResult(selected, stats)

    # ---- strategies ------------------------------------------------------------------

    async def _parents(self, hits: Sequence[Hit], rows: dict[str, Chunk]) -> list[Evidence]:
        parent_ids = {c.parent_id for c in rows.values() if c.parent_id}
        parents = await self.repo.by_ids(self.org_id, list(parent_ids))
        groups: dict[str, list[Hit]] = {}
        for hit in hits:
            child = rows.get(hit.chunk_id)
            parent = parents.get(child.parent_id) if child and child.parent_id else None
            if (
                child is None
                or parent is None
                or parent.document_id != child.document_id
                or parent.document_version != child.document_version
                # A parent larger than the whole budget falls back to neighbor expansion.
                or parent.token_count + MATERIAL_OVERHEAD_TOKENS > self.config.token_budget
            ):
                continue
            groups.setdefault(parent.id, []).append(hit)

        evidences = []
        for parent_id, group in groups.items():
            parent, best = parents[parent_id], group[0]
            evidences.append(
                Evidence(
                    kind=EvidenceKind.PARENT,
                    document=best.passage.document,
                    chunk_ids=[parent_id],
                    hit_chunk_ids=[h.chunk_id for h in group],
                    content=parent.content,
                    heading_path=list(parent.heading_path or best.passage.heading_path),
                    score=_best_score(group),
                    best_rank=best.rank,
                    quote=best.passage.content,
                    page_start=parent.page_start,
                    page_end=parent.page_end,
                    sheet_name=parent.sheet_name or best.passage.sheet_name,
                    slide_number=(
                        parent.slide_number
                        if parent.slide_number is not None
                        else best.passage.slide_number
                    ),
                )
            )
        return evidences

    async def _neighbor_runs(self, hits: Sequence[Hit], rows: dict[str, Chunk]) -> list[Evidence]:
        n = self.config.neighbors
        by_doc: dict[tuple[str, int], list[Hit]] = defaultdict(list)
        singles: list[Evidence] = []
        for hit in hits:
            chunk = rows.get(hit.chunk_id)
            if chunk is None:
                singles.append(self._single(hit, None))
                continue
            by_doc[(chunk.document_id, chunk.document_version)].append(hit)

        evidences: list[Evidence] = []
        for (doc_id, version), doc_hits in by_doc.items():
            loaded: dict[str, Chunk] = {}
            for hit in doc_hits:
                seq = rows[hit.chunk_id].seq
                # Children of different parents are separated by one parent seq.
                span = 2 * n + 1
                for c in await self.repo.children_between(
                    self.org_id, doc_id, version, seq - span, seq + span
                ):
                    loaded[c.id] = c
            ordered = sorted(loaded.values(), key=lambda c: c.seq)
            pos = {c.id: i for i, c in enumerate(ordered)}
            selected: set[int] = set()
            for hit in doc_hits:
                i = pos.get(hit.chunk_id)
                if i is None:
                    continue
                selected.update(range(max(0, i - n), min(len(ordered), i + n + 1)))

            # Contiguous runs: consecutive loaded children with no other child in between.
            runs: list[list[Chunk]] = []
            for i in sorted(selected):
                chunk = ordered[i]
                if runs and runs[-1][-1].seq + 2 >= chunk.seq and pos[runs[-1][-1].id] == i - 1:
                    runs[-1].append(chunk)
                else:
                    runs.append([chunk])
            hit_by_id = {h.chunk_id: h for h in doc_hits}
            for run in runs:
                run_hits = sorted(
                    (hit_by_id[c.id] for c in run if c.id in hit_by_id), key=lambda h: h.rank
                )
                if not run_hits:
                    continue
                best = run_hits[0]
                start, end = _pages(run)
                evidences.append(
                    Evidence(
                        kind=EvidenceKind.CHUNKS,
                        document=best.passage.document,
                        chunk_ids=[c.id for c in run],
                        hit_chunk_ids=[h.chunk_id for h in run_hits],
                        content=join_chunks([c.content for c in run]),
                        heading_path=list(best.passage.heading_path),
                        score=_best_score(run_hits),
                        best_rank=best.rank,
                        quote=best.passage.content,
                        page_start=start,
                        page_end=end,
                        sheet_name=best.passage.sheet_name,
                        slide_number=best.passage.slide_number,
                    )
                )
        return evidences + singles

    @staticmethod
    def _single(hit: Hit, chunk: Chunk | None) -> Evidence:
        p = hit.passage
        return Evidence(
            kind=EvidenceKind.CHUNKS,
            document=p.document,
            chunk_ids=[p.chunk_id],
            hit_chunk_ids=[p.chunk_id],
            content=p.content,
            heading_path=list(p.heading_path),
            score=hit.score,
            best_rank=hit.rank,
            quote=p.content,
            page_start=p.page_start,
            page_end=p.page_end,
            sheet_name=p.sheet_name,
            slide_number=p.slide_number,
        )

    # ---- budget ----------------------------------------------------------------------

    def _fit(self, evidences: list[Evidence]) -> tuple[list[Evidence], int]:
        ordered = sorted(
            evidences,
            key=lambda e: (
                not e.is_ko,
                -(e.score if e.score is not None else -math.inf),
                e.best_rank,
            ),
        )
        budget = self.config.token_budget
        used = 0
        selected: list[Evidence] = []
        dropped = 0
        for ev in ordered:
            header = count_tokens(" ".join([ev.document.title, *ev.heading_path]))
            content_tokens = count_tokens(ev.content)
            cost = content_tokens + header + MATERIAL_OVERHEAD_TOKENS
            if used + cost <= budget:
                ev.tokens = cost
            elif not selected and budget - used - header - MATERIAL_OVERHEAD_TOKENS >= min(
                MIN_TRUNCATED_TOKENS, content_tokens
            ):
                # The best evidence alone exceeds the budget: keep its beginning.
                target = budget - used - header - MATERIAL_OVERHEAD_TOKENS
                ev.content = _truncate(ev.content, content_tokens, target)
                ev.truncated = True
                ev.tokens = count_tokens(ev.content) + header + MATERIAL_OVERHEAD_TOKENS
            else:
                dropped += 1
                continue
            used += ev.tokens
            selected.append(ev)
        return selected, dropped


def _best_score(hits: Sequence[Hit]) -> float | None:
    scores = [h.score for h in hits if h.score is not None]
    return max(scores) if scores else None
