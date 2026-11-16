"""Question answering over the knowledge base, streamed as server-sent events.

  question ─ rewrite/intent ─┬─ chitchat / out_of_scope ─────────────────────────┐
                             └─ retrieve (per sub-query) ─ expand ─ ACL re-check ─ evidence gate
                                  ├─ refuse: standard answer + knowledge gap ──────┤
                                  └─ prompt ─ LLM stream ─ citation validation ────┴─ persist

Every step is recorded in a qa_traces row; the answer message links to it.
"""

import json
import logging
import math
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field, replace
from datetime import timedelta
from typing import Any

import anyio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import AppError, NotFoundError, ValidationAppError
from app.core.storage import ObjectStorage
from app.llm import ChatMessage, LLMError, LLMGateway
from app.llm.usage import FEATURE_ASSISTANT, STAGE_GENERATE, iterate_in_scope, scope_with
from app.models import (
    Conversation,
    GapStatus,
    GapType,
    Grounding,
    KnowledgeGap,
    Message,
    MessageRole,
    MessageStatus,
    QaTrace,
)
from app.models.base import new_id, utcnow
from app.repositories.chat_repo import ChunkRepository, ConversationRepository
from app.retrieval.pipeline import RetrievalPipeline
from app.schemas.chat import AskIn
from app.services.authz import AuthzCache
from app.services.chat import prompt
from app.services.chat.acl_check import AclCheckResult, EvidenceAclChecker
from app.services.chat.answer_images import (
    answer_image_targets,
    attach_material_images,
    resolve_page_image,
)
from app.services.chat.citations import CitationResult, CitationValidator
from app.services.chat.concepts import related_concepts_from_matches
from app.services.chat.conversation_service import DEFAULT_TITLE, RESOURCE_MESSAGE
from app.services.chat.evidence import Evidence, EvidenceValidator, Hit, Verdict
from app.services.chat.expansion import (
    ExpansionConfig,
    KnowledgeExpansion,
    KnowledgeObjectSource,
)
from app.services.chat.rewriter import Intent, QueryRewriter, RewriteResult
from app.services.context import BaseService, RequestContext
from app.services.knowledge.access import KnowledgeAccess
from app.services.knowledge.ko_access import KoAccess
from app.services.knowledge.protection import limit_export_text, protection_of
from app.services.search.search_service import SearchParams, SearchService
from app.services.security.pii import PiiMasker, StreamMasker
from app.services.terminology.service import TerminologyService

logger = logging.getLogger(__name__)

TITLE_MAX_CHARS = 30
ANSWER_EXCERPT_CHARS = 500
AUDIT_QUESTION_CHARS = 2000


@dataclass(frozen=True)
class ChatEvent:
    """One SSE event: meta | step | token | citations | done | error."""

    type: str
    data: dict[str, Any]

    def encode(self) -> str:
        return f"event: {self.type}\ndata: {json.dumps(self.data, ensure_ascii=False)}\n\n"


@dataclass
class _Run:
    conversation: Conversation
    question: Message
    answer: Message
    history: list[ChatMessage]
    kb_ids: list[str]
    started: float
    # Plain copies: ORM attributes expire on rollback and must not be lazily reloaded.
    conversation_id: str = ""
    question_id: str = ""
    answer_id: str = ""
    query: str = ""
    trace_id: str = field(default_factory=new_id)
    steps: dict[str, Any] = field(default_factory=dict)
    timings: dict[str, float] = field(default_factory=dict)
    retrieval_trace_ids: list[str] = field(default_factory=list)
    # Documents whose content was given to the model.
    context_document_ids: list[str] = field(default_factory=list)
    rewrite: RewriteResult | None = None
    gap: KnowledgeGap | None = None
    # User-facing progress, streamed as `step` events and kept on the answer message.
    progress: list[dict[str, Any]] = field(default_factory=list)
    # Lightweight terminology cards (SSE `concepts`); also persisted into message.steps.
    concepts: list[dict[str, Any]] = field(default_factory=list)

    def mark(self, name: str, since: float) -> None:
        self.timings[f"{name}_ms"] = round((time.perf_counter() - since) * 1000, 2)

    def step(
        self,
        name: str,
        status: str,
        *,
        ms: float | None = None,
        detail: dict[str, Any] | None = None,
    ) -> ChatEvent:
        entry: dict[str, Any] = {"step": name, "status": status}
        if ms is not None:
            entry["ms"] = round(ms)
        if detail:
            entry["detail"] = detail
        for i, existing in enumerate(self.progress):
            if existing["step"] == name:
                self.progress[i] = entry
                break
        else:
            self.progress.append(entry)
        return ChatEvent("step", entry)


class AnswerService(BaseService):
    def __init__(
        self,
        session: AsyncSession,
        ctx: RequestContext,
        authz_cache: AuthzCache,
        *,
        pipeline: RetrievalPipeline,
        gateway: LLMGateway,
        settings: Settings,
        ko_source: KnowledgeObjectSource | None = None,
        allowed_kb_ids: frozenset[str] | None = None,
        storage: ObjectStorage | None = None,
        absolute_links: bool = False,
    ) -> None:
        super().__init__(session, ctx, authz_cache)
        self.settings = settings
        self.allowed_kb_ids = allowed_kb_ids
        self.storage = storage
        # External callers (Open API / MCP) need absolute image URLs.
        self.absolute_links = absolute_links
        self.gateway = gateway
        self.repo = ConversationRepository(session)
        self.search = SearchService(session, ctx, authz_cache, pipeline=pipeline, settings=settings)
        self.rewriter = QueryRewriter(
            gateway,
            enabled=settings.chat_rewrite_enabled,
            max_subqueries=settings.chat_max_subqueries,
            timeout_seconds=settings.chat_rewrite_timeout_seconds,
        )
        self.expansion = KnowledgeExpansion(
            ChunkRepository(session),
            ctx.org_id,
            ExpansionConfig(
                parent=settings.chat_expand_parent,
                neighbors=max(0, settings.chat_expand_neighbors),
                ko=settings.chat_expand_ko,
                entity_limit=max(0, settings.chat_expand_entity_limit),
                token_budget=settings.chat_context_token_budget,
            ),
            ko_source,
        )
        self.acl = EvidenceAclChecker(session, ctx.user)
        self.validator = EvidenceValidator(
            min_score=settings.chat_evidence_min_score,
            confident_score=settings.chat_evidence_confident_score,
            min_count=settings.chat_min_evidence,
        )
        self.citations = CitationValidator(settings.chat_quote_max_chars)
        self.masker = PiiMasker(settings.pii_types) if settings.pii_mask_on_output else None

    # ---- entry point -------------------------------------------------------------------

    async def stream(self, conversation_id: str, data: AskIn) -> AsyncIterator[ChatEvent]:
        run = await self._start(conversation_id, data)
        yield ChatEvent(
            "meta",
            {
                "conversation_id": run.conversation_id,
                "title": run.conversation.title,
                "kb_ids": run.kb_ids,
                "user_message_id": run.question_id,
                "message_id": run.answer_id,
                "trace_id": run.trace_id,
            },
        )
        scope = scope_with(
            feature=FEATURE_ASSISTANT,
            org_id=self.org_id,
            user_id=self.ctx.user.id,
            conversation_id=run.conversation_id,
            message_id=run.answer_id,
        )
        try:
            async for event in iterate_in_scope(self._answer(run), scope):
                yield event
        except (AppError, LLMError) as exc:
            code = exc.code if isinstance(exc, AppError) else "LLM_UNAVAILABLE"
            message = exc.message if isinstance(exc, AppError) else "模型服务暂时不可用，请稍后重试"
            logger.warning("qa_failed", extra={"code": code, "error": str(exc)[:500]})
            await self._fail(run, code, str(exc))
            yield self._error_event(run, code, message)
        except Exception as exc:
            logger.exception("qa_internal_error")
            await self._fail(run, "INTERNAL_ERROR", f"{type(exc).__name__}: {exc}")
            yield self._error_event(run, "INTERNAL_ERROR", "回答生成失败，请稍后重试")
        except BaseException:
            # Client went away (cancelled) or the stream was closed: keep what we have.
            with anyio.CancelScope(shield=True):
                await self._fail(run, "CLIENT_DISCONNECTED", "stream closed by client")
            raise

    @staticmethod
    def _error_event(run: _Run, code: str, message: str) -> ChatEvent:
        return ChatEvent(
            "error",
            {
                "code": code,
                "message": message,
                "message_id": run.answer_id,
                "trace_id": run.trace_id,
            },
        )

    async def _start(self, conversation_id: str, data: AskIn) -> _Run:
        user = self.ctx.user
        conv = await self.repo.get_owned(self.org_id, user.id, conversation_id)
        if conv is None:
            raise NotFoundError("Conversation not found")
        if data.kb_ids is not None:
            conv.kb_ids = data.kb_ids
        turns = max(0, self.settings.chat_history_turns)
        previous = await self.repo.recent_finished(conv.id, turns * 2)
        history = [
            ChatMessage(
                role="user" if m.role == MessageRole.USER.value else "assistant", content=m.content
            )
            for m in previous
            if m.content
        ]
        if conv.title == DEFAULT_TITLE and not previous:
            conv.title = data.content[:TITLE_MAX_CHARS]
        now = utcnow()
        conv.updated_at = now
        question = Message(
            org_id=self.org_id,
            conversation_id=conv.id,
            role=MessageRole.USER.value,
            content=data.content,
            status=MessageStatus.DONE.value,
            created_at=now,
        )
        run = _Run(
            conversation=conv,
            question=question,
            answer=Message(
                org_id=self.org_id,
                conversation_id=conv.id,
                role=MessageRole.ASSISTANT.value,
                content="",
                status=MessageStatus.STREAMING.value,
                created_at=now + timedelta(microseconds=1),
            ),
            history=history,
            kb_ids=list(conv.kb_ids or []),
            started=time.perf_counter(),
        )
        run.answer.trace_id = run.trace_id
        self.session.add_all([question, run.answer])
        await self.session.flush()
        run.conversation_id = conv.id
        run.question_id = question.id
        run.answer_id = run.answer.id
        run.query = data.content
        await self.session.commit()
        return run

    # ---- pipeline ----------------------------------------------------------------------

    async def _answer(self, run: _Run) -> AsyncIterator[ChatEvent]:
        yield run.step("rewrite", "running")
        t = time.perf_counter()
        rewrite = run.rewrite = await self.rewriter.rewrite(run.query, run.history)
        run.mark("rewrite", t)
        run.steps["rewrite"] = rewrite.describe()
        run.answer.intent = rewrite.intent.value
        run.answer.rewritten_query = rewrite.query
        yield run.step(
            "rewrite",
            "done",
            ms=run.timings["rewrite_ms"],
            detail={
                "intent": rewrite.intent.value,
                "query": rewrite.query,
                "sub_queries": rewrite.queries[1:],
            },
        )

        if rewrite.intent == Intent.CHITCHAT:
            messages = prompt.chitchat_messages(run.query, run.history)
            run.steps["prompt"] = {"type": "chitchat", "messages": len(messages)}
            parts: list[str] = []
            async for event in self._generate(run, messages, parts):
                yield event
            result = self.citations.validate("".join(parts), [])
            async for event in self._finish(run, result, Grounding.CHITCHAT):
                yield event
            return
        if rewrite.intent == Intent.OUT_OF_SCOPE:
            yield ChatEvent("token", {"text": prompt.OUT_OF_SCOPE_ANSWER})
            result = CitationResult(answer=prompt.OUT_OF_SCOPE_ANSWER, citations=[])
            async for event in self._finish(run, result, Grounding.OUT_OF_SCOPE):
                yield event
            return

        yield run.step("retrieve", "running")
        hits = await self._retrieve(run, rewrite)
        scores = [h.score for h in hits if h.score is not None]
        yield run.step(
            "retrieve",
            "done",
            ms=run.timings["retrieval_ms"],
            detail={
                "queries": len(run.steps["retrieval"]["queries"]),
                "hits": len(hits),
                "documents": len({h.passage.document.id for h in hits}),
                "top_score": round(max(scores), 4) if scores else None,
            },
        )

        term_meta = run.steps.get("terminology") or {}
        raw_matches = term_meta.get("matches") if isinstance(term_meta, dict) else None
        if isinstance(raw_matches, list) and raw_matches:
            run.concepts = await related_concepts_from_matches(
                self.session,
                org_id=self.ctx.user.org_id,
                user=self.ctx.user,
                matches=[m for m in raw_matches if isinstance(m, dict)],
                allowed_kb_ids=self.allowed_kb_ids,
            )
            if run.concepts:
                yield ChatEvent("concepts", {"items": run.concepts})

        yield run.step("evidence", "running")
        t = time.perf_counter()
        expansion = await self.expansion.expand(hits)
        run.mark("expansion", t)
        run.steps["expansion"] = {
            **expansion.stats,
            "evidences": [e.describe() for e in expansion.evidences],
        }

        t = time.perf_counter()
        acl = await self.acl.check(expansion.evidences)
        run.mark("acl", t)
        run.steps["acl"] = {
            "checked": len(expansion.evidences),
            "kept": len(acl.kept),
            "dropped": acl.dropped,
        }
        evidences = acl.kept
        if self.allowed_kb_ids is not None:
            allowed = self.allowed_kb_ids
            outside = [e for e in evidences if e.document.kb_id not in allowed]
            if outside:
                evidences = [e for e in evidences if e.document.kb_id in allowed]
                run.steps["acl"]["outside_grant"] = [e.document.id for e in outside]

        decision = self.validator.validate(evidences)
        run.steps["evidence"] = decision.describe()
        yield run.step(
            "evidence",
            "done",
            ms=run.timings["expansion_ms"] + run.timings["acl_ms"],
            detail={
                "kept": len(evidences),
                "dropped": len(acl.dropped),
                "verdict": decision.verdict.value,
                "top_score": round(decision.top_score, 4)
                if decision.top_score is not None
                else None,
            },
        )
        if decision.verdict == Verdict.REFUSE:
            yield ChatEvent("token", {"text": prompt.NO_EVIDENCE_ANSWER})
            run.gap = self._gap(
                run,
                GapType.NO_EVIDENCE,
                decision.top_score,
                {
                    "reason": decision.reason,
                    "hits": len(hits),
                    "acl_dropped": len(acl.dropped),
                    "retrieval_trace_ids": run.retrieval_trace_ids,
                },
            )
            result = CitationResult(answer=prompt.NO_EVIDENCE_ANSWER, citations=[])
            async for event in self._finish(run, result, Grounding.NO_EVIDENCE):
                yield event
            return

        uncertain = decision.verdict == Verdict.UNCERTAIN
        await attach_material_images(
            self.session,
            evidences,
            self.storage,
            self.settings,
            viewer_id=self.ctx.user.id,
            absolute=self.absolute_links,
        )
        messages = prompt.answer_messages(
            run.query, rewrite.query, evidences, run.history, uncertain=uncertain
        )
        run.context_document_ids = list(dict.fromkeys(e.document.id for e in evidences))
        run.steps["prompt"] = {
            "type": "answer",
            "uncertain": uncertain,
            "history_messages": len(run.history),
            "chars": sum(len(m.content) for m in messages),
            "answer_images": sum(len(e.images) for e in evidences),
            # The final context exactly as given to the model.
            "materials": [
                {"n": i, **e.describe(with_content=True)} for i, e in enumerate(evidences, start=1)
            ],
        }
        parts: list[str] = []
        async for event in self._generate(run, messages, parts, evidences=evidences):
            yield event

        # Post-generate ACL gate: catch revoke that landed after the last mid-stream check.
        post = await self._recheck_evidences(evidences)
        if post.dropped:
            prev = run.steps.get("acl_midstream") or {}
            run.steps["acl_poststream"] = {
                "kept": len(post.kept),
                "dropped": post.dropped,
                "midstream": bool(prev),
            }
            evidences[:] = post.kept
        if not evidences:
            # All context revoked: replace streamed answer with a safe refusal.
            parts.clear()
            parts.append(prompt.ACL_REVOKED_ANSWER)
            yield ChatEvent("token", {"text": "\n\n" + prompt.ACL_REVOKED_ANSWER})
            result = CitationResult(answer=prompt.ACL_REVOKED_ANSWER, citations=[])
            async for event in self._finish(run, result, Grounding.NO_EVIDENCE):
                yield event
            return

        result = self.citations.validate("".join(parts), evidences)
        image_targets = answer_image_targets(evidences)
        filtered = prompt.filter_answer_images(result.answer, image_targets)
        if filtered != result.answer:
            if filtered.count("![") < result.answer.count("!["):
                run.steps["prompt"]["stripped_unauthorized_images"] = True
            result = replace(result, answer=filtered)
        await self._enrich_citation_images(result.citations)
        grounding = Grounding.UNCERTAIN if uncertain else Grounding.GROUNDED
        if not result.grounded:
            grounding = Grounding.LOW_GROUNDING
            run.gap = self._gap(
                run,
                GapType.LOW_GROUNDING,
                decision.top_score,
                {
                    "invalid_citations": result.invalid,
                    "answer_excerpt": result.answer[:ANSWER_EXCERPT_CHARS],
                    "retrieval_trace_ids": run.retrieval_trace_ids,
                },
            )
        async for event in self._finish(run, result, grounding):
            yield event

    async def _enrich_citation_images(self, citations: list[dict[str, Any]]) -> None:
        """Ensure citations carry a fresh page/slide preview URL when assets exist."""
        if self.storage is None or not self.settings.page_image_enabled:
            return
        for cite in citations:
            if cite.get("image_url") or cite.get("is_ko"):
                continue
            doc_id = cite.get("document_id")
            version = cite.get("doc_version")
            if not isinstance(doc_id, str) or not isinstance(version, int):
                continue
            url, mime = await resolve_page_image(
                self.session,
                self.storage,
                self.settings,
                document_id=doc_id,
                version=version,
                slide_number=cite.get("slide_number")
                if isinstance(cite.get("slide_number"), int)
                else None,
                page_start=cite.get("page_start")
                if isinstance(cite.get("page_start"), int)
                else None,
                viewer_id=self.ctx.user.id,
                absolute=self.absolute_links,
            )
            cite["image_url"] = url
            cite["image_mime_type"] = mime

    async def _retrieve(self, run: _Run, rewrite: RewriteResult) -> list[Hit]:
        t = time.perf_counter()
        base_queries = rewrite.queries[: 1 + max(0, self.settings.chat_max_subqueries)]
        terminology = TerminologyService(
            self.session, self.ctx, self.authz_cache, self.settings
        )
        expansion = await terminology.expand_for_org(base_queries)
        run.steps["terminology"] = expansion.describe()
        # Cap total retrieval fan-out: originals + alias extras, still bounded by max_subqueries
        # plus terminology_expand_max_extra.
        max_queries = 1 + max(0, self.settings.chat_max_subqueries) + max(
            0, self.settings.terminology_expand_max_extra
        )
        queries = expansion.queries[:max_queries]
        merged: dict[str, Hit] = {}
        order: list[str] = []
        per_query: list[dict[str, Any]] = []
        for query in queries:
            params = SearchParams(
                q=query,
                kb_ids=tuple(run.kb_ids),
                top_k=self.settings.chat_retrieval_top_k,
                allowed_kb_ids=self.allowed_kb_ids,
            )
            try:
                search = await self.search.execute(params)
            except ValidationAppError as exc:
                per_query.append({"query": query, "skipped": exc.message})
                continue
            run.retrieval_trace_ids.append(search.trace.id)
            results = search.outcome.results if search.outcome else []
            per_query.append(
                {
                    "query": query,
                    "retrieval_trace_id": search.trace.id,
                    "degraded": search.outcome.degraded if search.outcome else [],
                    "unresolved_kbs": search.scope.unresolved,
                    "results": [
                        {
                            "chunk_id": r.passage.chunk_id,
                            "document_id": r.passage.document.id,
                            "rank": r.rank,
                            "rerank_score": r.rerank_score,
                        }
                        for r in results
                    ],
                }
            )
            for r in results:
                existing = merged.get(r.passage.chunk_id)
                if existing is None:
                    order.append(r.passage.chunk_id)
                    merged[r.passage.chunk_id] = Hit(r.passage, r.rerank_score, r.rank)
                elif r.rerank_score is not None and (
                    existing.score is None or r.rerank_score > existing.score
                ):
                    merged[r.passage.chunk_id] = Hit(r.passage, r.rerank_score, existing.rank)

        def key(cid: str) -> tuple[float, int]:
            score = merged[cid].score
            return (-(score if score is not None else -math.inf), order.index(cid))

        hits = [
            Hit(merged[cid].passage, merged[cid].score, rank)
            for rank, cid in enumerate(sorted(order, key=key), start=1)
        ]
        run.mark("retrieval", t)
        run.steps["retrieval"] = {
            "kb_ids": run.kb_ids,
            "queries": per_query,
            "merged": [{"chunk_id": h.chunk_id, "score": h.score, "rank": h.rank} for h in hits],
        }
        # Retrieval traces are kept even if answering fails later.
        await self.session.commit()
        return hits

    async def _recheck_evidences(self, evidences: list[Evidence]) -> AclCheckResult:
        """Re-run Evidence ACL (PG queries; do not expire_all — ORM messages are mid-stream)."""
        return await self.acl.check(evidences)

    async def _generate(
        self,
        run: _Run,
        messages: list[ChatMessage],
        parts: list[str],
        *,
        evidences: list[Evidence] | None = None,
    ) -> AsyncIterator[ChatEvent]:
        yield run.step("generate", "running")
        t = time.perf_counter()
        first: float | None = None
        stream_mask = StreamMasker(self.masker) if self.masker else None
        interval = max(0, int(self.settings.chat_acl_recheck_every_chars))
        next_check = interval
        streamed_chars = 0
        revoked_midstream = False
        tokens = self.gateway.stream(
            messages,
            temperature=self.settings.chat_temperature,
            max_tokens=self.settings.chat_max_tokens,
        )
        try:
            async for token in iterate_in_scope(tokens, scope_with(stage=STAGE_GENERATE)):
                if first is None:
                    first = time.perf_counter()
                    run.timings["first_token_ms"] = round((first - t) * 1000, 2)
                parts.append(token)
                streamed_chars += len(token)
                text = stream_mask.feed(token) if stream_mask else token
                if text:
                    yield ChatEvent("token", {"text": text})
                if (
                    evidences is not None
                    and interval > 0
                    and streamed_chars >= next_check
                ):
                    next_check = streamed_chars + interval
                    mid = await self._recheck_evidences(evidences)
                    if mid.dropped:
                        revoked_midstream = True
                        run.steps["acl_midstream"] = {
                            "chars": streamed_chars,
                            "kept": len(mid.kept),
                            "dropped": mid.dropped,
                        }
                        evidences[:] = mid.kept
                        break
            if stream_mask and not revoked_midstream:
                rest = stream_mask.flush()
                if rest:
                    yield ChatEvent("token", {"text": rest})
            detail: dict[str, Any] = {
                "model": self.gateway.chat.model,
                "first_token_ms": run.timings.get("first_token_ms"),
            }
            if revoked_midstream:
                detail["acl_revoked"] = True
            yield run.step(
                "generate",
                "done",
                ms=(time.perf_counter() - t) * 1000,
                detail=detail,
            )
        finally:
            run.mark("generation", t)
            run.steps["generation"] = {
                "model": self.gateway.chat.model,
                "chars": sum(len(p) for p in parts),
                "acl_revoked": revoked_midstream,
            }

    def _gap(
        self,
        run: _Run,
        gap_type: GapType,
        top_score: float | None,
        details: dict[str, Any],
    ) -> KnowledgeGap:
        gap = KnowledgeGap(
            id=new_id(),
            org_id=self.org_id,
            gap_type=gap_type.value,
            status=GapStatus.OPEN.value,
            query=run.query,
            rewritten_query=run.rewrite.query if run.rewrite else None,
            user_id=self.ctx.user.id,
            conversation_id=run.conversation_id,
            message_id=run.answer_id,
            trace_id=run.trace_id,
            kb_ids=run.kb_ids,
            kb_id=run.kb_ids[0] if len(run.kb_ids) == 1 else None,
            top_score=top_score,
            details=details,
        )
        from app.services.curation.sla import apply_gap_sla

        apply_gap_sla(gap, self.settings)
        self.session.add(gap)
        return gap

    # ---- persistence -------------------------------------------------------------------

    def _trace(self, run: _Run, status: str, grounding: str | None) -> QaTrace:
        run.timings["total_ms"] = round((time.perf_counter() - run.started) * 1000, 2)
        if run.gap is not None:
            run.steps["gap"] = {"id": run.gap.id, "type": run.gap.gap_type}
        return QaTrace(
            id=run.trace_id,
            org_id=self.org_id,
            user_id=self.ctx.user.id,
            conversation_id=run.conversation_id,
            message_id=run.answer_id,
            query=run.query,
            rewritten_query=run.rewrite.query if run.rewrite else None,
            intent=run.rewrite.intent.value if run.rewrite else None,
            grounding=grounding,
            status=status,
            retrieval_trace_ids=run.retrieval_trace_ids,
            steps=run.steps,
            timings=run.timings,
            total_ms=int(run.timings["total_ms"]),
        )

    async def _apply_controlled_citations(
        self, citations: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], bool]:
        """Mark / shorten citations from copy-protected or download-restricted sources."""
        if not citations:
            return citations, False
        access = KnowledgeAccess(self.session)
        doc_ids = [str(c["document_id"]) for c in citations if not c.get("is_ko")]
        ko_ids = [str(c["document_id"]) for c in citations if c.get("is_ko")]
        readable = await access.readable_documents(self.ctx.user, doc_ids) if doc_ids else {}
        ko_live = (
            await KoAccess(self.session).live_objects(self.ctx.user, ko_ids) if ko_ids else None
        )
        quote_cap = self.settings.controlled_quote_max_chars
        out: list[dict[str, Any]] = []
        any_protect = False
        for cite in citations:
            item = dict(cite)
            protected = False
            if cite.get("is_ko"):
                obj = ko_live.objects.get(str(cite["document_id"])) if ko_live else None
                if obj is not None and protection_of(obj.kb).copy_protect:
                    protected = True
            else:
                pair = readable.get(str(cite["document_id"]))
                if pair is not None:
                    doc, kb = pair
                    perm = await access.document_permission(self.ctx.user, doc, kb)
                    protection = protection_of(kb, doc)
                    if protection.limits_export(perm.value if perm else None):
                        protected = True
            if protected:
                any_protect = True
                item["copy_protect"] = True
                item["quote"] = limit_export_text(str(item.get("quote") or ""), quote_cap)
            else:
                item["copy_protect"] = False
            out.append(item)
        return out, any_protect

    async def _finish(
        self, run: _Run, result: CitationResult, grounding: Grounding
    ) -> AsyncIterator[ChatEvent]:
        run.steps["citations"] = {
            "used": result.used,
            "invalid": result.invalid,
            "count": len(result.citations),
        }
        citations, copy_protect = await self._apply_controlled_citations(result.citations)
        result = replace(result, citations=citations)
        if self.masker:
            masker = self.masker
            result = replace(
                result,
                answer=masker.mask(result.answer),
                citations=[
                    {**c, "quote": masker.mask(str(c.get("quote") or ""))} for c in result.citations
                ],
            )
        yield ChatEvent("citations", {"citations": result.citations})

        answer = run.answer
        answer.content = result.answer
        answer.citations = result.citations
        steps = list(run.progress)
        if run.concepts:
            steps.append(
                {"step": "concepts", "status": "done", "detail": {"items": run.concepts}}
            )
        answer.steps = steps
        answer.grounding = grounding.value
        answer.status = MessageStatus.DONE.value
        self.session.add(self._trace(run, "ok", grounding.value))
        await self.audit.record(
            self.audit_ctx,
            "chat.ask",
            RESOURCE_MESSAGE,
            answer.id,
            None,
            {
                "conversation_id": run.conversation_id,
                "question": run.query[:AUDIT_QUESTION_CHARS],
                "grounding": grounding.value,
                "trace_id": run.trace_id,
                "gap_id": run.gap.id if run.gap else None,
                "kb_ids": run.kb_ids,
                "cited_document_ids": list(
                    dict.fromkeys(str(c["document_id"]) for c in result.citations)
                ),
                "context_document_ids": run.context_document_ids,
                "copy_protect": copy_protect,
                "concepts": len(run.concepts),
            },
        )
        await self.session.commit()
        done: dict[str, Any] = {
            "message_id": answer.id,
            "conversation_id": run.conversation_id,
            "answer": result.answer,
            "grounding": grounding.value,
            "intent": answer.intent,
            "rewritten_query": answer.rewritten_query,
            "trace_id": run.trace_id,
            "gap_id": run.gap.id if run.gap else None,
            "copy_protect": copy_protect,
        }
        if run.concepts:
            done["concepts"] = run.concepts
        yield ChatEvent("done", done)

    async def _fail(self, run: _Run, code: str, error: str) -> None:
        """Roll back the unfinished work, then persist the error state and the trace."""
        try:
            await self.session.rollback()
            answer = await self.session.get(Message, run.answer_id)
            if answer is None or answer.status == MessageStatus.DONE.value:
                return
            answer.status = MessageStatus.ERROR.value
            answer.error = f"{code}: {error}"[:2000]
            answer.steps = [
                {**s, "status": "failed"} if s["status"] == "running" else s for s in run.progress
            ]
            answer.intent = run.rewrite.intent.value if run.rewrite else None
            answer.rewritten_query = run.rewrite.query if run.rewrite else None
            run.gap = None
            run.steps["error"] = {"code": code, "message": error[:2000]}
            self.session.add(self._trace(run, "error", None))
            await self.session.commit()
        except Exception:
            logger.exception("qa_fail_persist_failed")
