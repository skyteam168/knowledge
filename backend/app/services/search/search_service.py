import logging
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import ColumnElement, or_, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import AppError, PermissionDeniedError, ValidationAppError
from app.llm import EmbeddingSpec
from app.llm.usage import FEATURE_SEARCH, STAGE_RETRIEVAL, usage_scope
from app.models import Document, GenerationStatus, RetrievalTrace
from app.repositories.acl_repo import ResourceAclRepository
from app.repositories.indexing_repo import IndexGenerationRepository
from app.repositories.search_repo import RetrievalTraceRepository, SearchRepository
from app.retrieval.cache import principals_hash
from app.retrieval.config import Route
from app.retrieval.filters import SearchFilter
from app.retrieval.highlight import mark, query_terms, snippet
from app.retrieval.pipeline import (
    RankedResult,
    RetrievalOutcome,
    RetrievalPipeline,
    RetrievalRequest,
    RetrievalUnavailableError,
)
from app.retrieval.query import DOC_TYPES, ParsedQuery, QueryFilters, QueryPreprocessor
from app.retrieval.retrievers import SearchTarget
from app.retrieval.trace import truncate_stages
from app.schemas.search import (
    AppliedFiltersOut,
    AppliedKbOut,
    SearchDebugOut,
    SearchDocumentOut,
    SearchHitOut,
    SearchOptionsOut,
    SearchProfileRef,
    SearchResponse,
    StageRanks,
    StageScores,
)
from app.services.authz import AclService, AuthzCache
from app.services.context import BaseService, RequestContext
from app.services.indexing.indexer import document_type
from app.services.knowledge.access import RESOURCE_DOCUMENT, KnowledgeAccess
from app.services.search.hydrator import PassageHydrator
from app.services.search.profile_service import ResolvedProfile, RetrievalProfileService
from app.services.security.pii import PiiMasker

logger = logging.getLogger(__name__)

DEBUG_PERMISSION = "admin:retrieval"
FACET_DOCUMENT_LIMIT = 5000
FACET_TAG_LIMIT = 200


class SearchUnavailableError(AppError):
    status_code = 503
    code = "SEARCH_UNAVAILABLE"
    message = "Search is temporarily unavailable"


@dataclass(frozen=True)
class SearchParams:
    q: str
    kb_ids: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    doc_types: tuple[str, ...] = ()
    date_from: datetime | None = None
    date_to: datetime | None = None
    top_k: int | None = None
    profile_id: str | None = None
    debug: bool = False
    # Skip the result cache (callers that must see just-published content).
    fresh: bool = False
    # A fixed strategy (offline evaluation replays a run's config snapshot).
    profile: ResolvedProfile | None = None
    # Hard upper bound on the knowledge bases searched (open API clients), applied on top of
    # ACL and of any kb filter in the params or written inline in the query.
    allowed_kb_ids: frozenset[str] | None = None


@dataclass
class _Scope:
    kbs: list[AppliedKbOut] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    # A kb restriction was requested but nothing readable matched: search nothing.
    empty: bool = False


@dataclass
class SearchRun:
    parsed: ParsedQuery
    scope: _Scope
    filter: SearchFilter
    profile: ResolvedProfile
    target: SearchTarget | None
    # None: nothing searchable (no active generation / no readable knowledge base).
    outcome: RetrievalOutcome | None
    trace: RetrievalTrace
    started: float


class SearchService(BaseService):
    def __init__(
        self,
        session: AsyncSession,
        ctx: RequestContext,
        authz_cache: AuthzCache,
        *,
        pipeline: RetrievalPipeline,
        settings: Settings,
    ) -> None:
        super().__init__(session, ctx, authz_cache)
        self.pipeline = pipeline
        self.settings = settings
        self.repo = SearchRepository(session)
        self.traces = RetrievalTraceRepository(session)
        self.access = KnowledgeAccess(session)
        self.profiles = RetrievalProfileService(session, ctx, authz_cache, settings=settings)
        self.preprocessor = QueryPreprocessor()

    @property
    def can_debug(self) -> bool:
        return self.ctx.user.has_permission(DEBUG_PERMISSION)

    # ---- helpers ------------------------------------------------------------------

    async def _target(self) -> SearchTarget | None:
        gens = await IndexGenerationRepository(self.session).by_status(GenerationStatus.ACTIVE)
        if not gens:
            return None
        gen = gens[-1]
        return SearchTarget(
            generation=gen.version,
            collection=gen.qdrant_collection,
            index=gen.opensearch_index,
            embedding=EmbeddingSpec(
                model=gen.embedding_model, dim=gen.embedding_dim, base_url=gen.embedding_base_url
            ),
        )

    async def _scope(self, filters: QueryFilters, allowed: frozenset[str] | None = None) -> _Scope:
        requested = bool(filters.kb_ids or filters.kb_names)
        if not requested and allowed is None:
            return _Scope()
        if not requested:
            kbs = await self.repo.readable_kbs(
                self.org_id,
                self.access.readable_kb_clause(self.ctx.user),
                ids=tuple(sorted(allowed or ())),
                names=(),
            )
            return _Scope(kbs=[AppliedKbOut(id=kb.id, name=kb.name) for kb in kbs], empty=not kbs)
        kbs = await self.repo.readable_kbs(
            self.org_id,
            self.access.readable_kb_clause(self.ctx.user),
            ids=filters.kb_ids,
            names=filters.kb_names,
        )
        if allowed is not None:
            kbs = [kb for kb in kbs if kb.id in allowed]
        found_ids = {kb.id for kb in kbs}
        found_names = {kb.name for kb in kbs}
        unresolved = [i for i in filters.kb_ids if i not in found_ids] + [
            n for n in filters.kb_names if n not in found_names
        ]
        return _Scope(
            kbs=[AppliedKbOut(id=kb.id, name=kb.name) for kb in kbs],
            unresolved=unresolved,
            empty=not kbs,
        )

    # ---- search -------------------------------------------------------------------

    async def search(self, params: SearchParams) -> SearchResponse:
        if (params.debug or params.profile_id) and not self.can_debug:
            raise PermissionDeniedError(detail={"required": DEBUG_PERMISSION})
        run = await self.execute(params)
        parsed, scope, search_filter, outcome = run.parsed, run.scope, run.filter, run.outcome
        terms = query_terms(" ".join([parsed.text, *parsed.exact_terms]))
        items = [self._hit(r, terms) for r in (outcome.results if outcome else [])]
        if self.settings.pii_mask_on_output:
            masker = PiiMasker(self.settings.pii_types)
            items = [
                h.model_copy(
                    update={
                        "content": masker.mask(h.content),
                        "snippet": masker.mask(h.snippet),
                        "highlights": [masker.mask(f) for f in h.highlights],
                    }
                )
                for h in items
            ]
        return SearchResponse(
            query=params.q,
            normalized_query=parsed.text,
            exact_terms=list(parsed.exact_terms),
            ignored_operators=list(parsed.ignored),
            filters=AppliedFiltersOut(
                kbs=scope.kbs,
                unresolved_kbs=scope.unresolved,
                tags=list(search_filter.tags),
                doc_types=list(search_filter.doc_types),
                date_from=search_filter.date_from,
                date_to=search_filter.date_to,
            ),
            items=items,
            total=len(items),
            took_ms=round((time.perf_counter() - run.started) * 1000, 2),
            trace_id=run.trace.id,
            profile=SearchProfileRef(id=run.profile.id, name=run.profile.name),
            degraded=outcome.degraded if outcome else [],
            cache_hit=outcome.cache_hit if outcome else False,
            debug=(
                SearchDebugOut(
                    config=run.profile.config.model_dump(mode="json"),
                    stages=outcome.stages if outcome else {"note": self._empty_reason(run.target)},
                    timings=outcome.timings if outcome else {},
                )
                if params.debug
                else None
            ),
        )

    async def execute(self, params: SearchParams) -> SearchRun:
        """Parse, scope, retrieve (with PG re-check) and record a retrieval trace."""
        with usage_scope(feature=FEATURE_SEARCH, stage=STAGE_RETRIEVAL):
            return await self._execute(params)

    async def _execute(self, params: SearchParams) -> SearchRun:
        started = time.perf_counter()
        user = self.ctx.user
        profile = params.profile or await self.profiles.resolve(params.profile_id)
        parsed = self.preprocessor.parse(
            params.q,
            QueryFilters(
                kb_ids=params.kb_ids,
                tags=params.tags,
                doc_types=params.doc_types,
                date_from=params.date_from,
                date_to=params.date_to,
            ),
        )
        if not parsed.text:
            raise ValidationAppError("请输入检索内容", detail={"query": params.q})
        unknown_types = sorted(set(parsed.filters.doc_types) - set(DOC_TYPES))
        if unknown_types:
            raise ValidationAppError(
                "Unknown document type", detail={"doc_types": unknown_types, "allowed": DOC_TYPES}
            )

        scope = await self._scope(parsed.filters, params.allowed_kb_ids)
        acl = AclService.build_filter(
            user.principals,
            kb_ids=[kb.id for kb in scope.kbs],
            bypass_acl=user.is_superuser,
        )
        search_filter = SearchFilter.of(acl, parsed.filters)
        scope_hash = principals_hash(acl.principals, bypass_acl=acl.bypass_acl)
        target = await self._target()

        outcome: RetrievalOutcome | None = None
        if target is not None and not scope.empty:
            request = RetrievalRequest(
                query=parsed,
                filter=search_filter,
                config=(
                    profile.config.model_copy(
                        update={
                            "cache": profile.config.cache.model_copy(
                                update={"result_ttl_seconds": 0}
                            )
                        }
                    )
                    if params.fresh
                    else profile.config
                ),
                target=target,
                scope_hash=scope_hash,
                top_k=params.top_k,
            )
            try:
                outcome = await self.pipeline.run(request, PassageHydrator(self.session, user))
            except RetrievalUnavailableError as exc:
                await self._record_trace(
                    params,
                    parsed,
                    profile,
                    search_filter,
                    scope_hash,
                    target,
                    None,
                    started,
                    error=exc.reasons,
                )
                await self.session.commit()
                raise SearchUnavailableError(detail={"reasons": exc.reasons}) from exc

        trace = await self._record_trace(
            params, parsed, profile, search_filter, scope_hash, target, outcome, started
        )
        return SearchRun(
            parsed=parsed,
            scope=scope,
            filter=search_filter,
            profile=profile,
            target=target,
            outcome=outcome,
            trace=trace,
            started=started,
        )

    @staticmethod
    def _empty_reason(target: SearchTarget | None) -> str:
        return "no active index generation" if target is None else "no readable knowledge base"

    @staticmethod
    def _hit(result: RankedResult, terms: list[str]) -> SearchHitOut:
        p, c = result.passage, result.candidate
        fragments = result.highlight.get("content") or []
        if not fragments:
            fragments = [snippet(p.content, terms)]
        doc = p.document
        return SearchHitOut(
            rank=result.rank,
            chunk_id=p.chunk_id,
            content=p.content,
            snippet=fragments[0],
            highlights=fragments,
            title_html=mark(doc.title, terms),
            heading_path=p.heading_path,
            chunk_type=p.chunk_type,
            page_start=p.page_start,
            page_end=p.page_end,
            sheet_name=p.sheet_name,
            slide_number=p.slide_number,
            is_ko=p.is_ko,
            document=SearchDocumentOut(
                id=doc.id,
                title=doc.title,
                filename=doc.filename,
                kb_id=doc.kb_id,
                kb_name=doc.kb_name,
                version=doc.version,
                doc_type=doc.doc_type,
                tags=doc.tags,
                updated_at=doc.updated_at,
            ),
            scores=StageScores(
                dense=c.scores.get(Route.DENSE),
                bm25=c.scores.get(Route.SPARSE),
                rrf=round(c.rrf_score, 6),
                rerank=result.rerank_score,
            ),
            ranks=StageRanks(
                dense=c.ranks.get(Route.DENSE),
                bm25=c.ranks.get(Route.SPARSE),
                rrf=c.rrf_rank,
                rerank=result.rerank_rank,
            ),
        )

    async def _record_trace(
        self,
        params: SearchParams,
        parsed: ParsedQuery,
        profile: ResolvedProfile,
        search_filter: SearchFilter,
        scope_hash: str,
        target: SearchTarget | None,
        outcome: RetrievalOutcome | None,
        started: float,
        *,
        error: list[str] | None = None,
    ) -> RetrievalTrace:
        raw_stages = outcome.stages if outcome else {"error": error or self._empty_reason(target)}
        stages, truncated = truncate_stages(raw_stages, self.settings.retrieval_trace_max_bytes)
        total_ms = (time.perf_counter() - started) * 1000
        return await self.traces.add(
            RetrievalTrace(
                org_id=self.org_id,
                user_id=self.ctx.user.id,
                query=params.q[:2000],
                normalized_query=parsed.text[:2000],
                filters=search_filter.describe(),
                profile_id=profile.id,
                profile_name=profile.name,
                config=profile.config.model_dump(mode="json"),
                principals_hash=scope_hash,
                generation=target.generation if target else None,
                cache_hit=outcome.cache_hit if outcome else False,
                degraded=list(error or (outcome.degraded if outcome else [])),
                result_count=len(outcome.results) if outcome else 0,
                timings=outcome.timings if outcome else {"total_ms": round(total_ms, 2)},
                stages=stages,
                truncated=truncated,
                total_ms=int(total_ms),
            )
        )

    # ---- filter options -------------------------------------------------------------

    async def options(self) -> SearchOptionsOut:
        user = self.ctx.user
        visible: ColumnElement[bool]
        if user.is_superuser:
            visible = true()
        else:
            # Inherited documents of readable KBs, plus documents granted individually.
            granted = ResourceAclRepository.granted_ids_stmt(
                self.org_id, RESOURCE_DOCUMENT, user.principals.pairs()
            )
            visible = or_(
                Document.acl_inherit.is_(True) & self.access.readable_kb_clause(user),
                Document.id.in_(granted),
            )
        rows = await self.repo.visible_document_facets(self.org_id, visible, FACET_DOCUMENT_LIMIT)
        tags: Counter[str] = Counter()
        types: set[str] = set()
        for doc_tags, filename, mime in rows:
            tags.update(doc_tags)
            types.add(document_type(filename, mime))
        return SearchOptionsOut(
            doc_types=[t for t in DOC_TYPES if t in types],
            tags=[t for t, _ in tags.most_common(FACET_TAG_LIMIT)],
            can_debug=self.can_debug,
        )
