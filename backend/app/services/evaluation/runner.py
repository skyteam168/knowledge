"""Execute an evaluation run: retrieve every case with the run's config snapshot, optionally
answer it like the assistant does and let the LLM judge score the answer.

Retrieval runs with the permissions of the run's creator (resolved now), so an evaluation
never sees content its creator could not read. Questions are evaluated as given: no query
rewriting and no conversation history.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.exceptions import AppError
from app.llm import LLMError, LLMGateway
from app.llm.usage import FEATURE_EVALUATION, STAGE_GENERATE, usage_scope
from app.models import EvalCase, EvalResult, EvalRun, EvalRunStatus, Grounding, User
from app.models.base import utcnow
from app.repositories.chat_repo import ChunkRepository
from app.retrieval.config import RetrievalConfig
from app.retrieval.pipeline import RetrievalPipeline
from app.services.audit_service import AuditContext
from app.services.authz import AuthzCache, CurrentUser, PermissionResolver, PrincipalResolver
from app.services.chat import prompt
from app.services.chat.acl_check import EvidenceAclChecker
from app.services.chat.citations import CitationValidator
from app.services.chat.evidence import Evidence, EvidenceValidator, Hit, Verdict
from app.services.chat.expansion import ExpansionConfig, KnowledgeExpansion
from app.services.chat.ko_source import PublishedKnowledgeObjects
from app.services.context import RequestContext
from app.services.evaluation.judge import AnswerJudge
from app.services.evaluation.metrics import (
    RetrievedItem,
    citation_precision,
    mean_metrics,
    retrieval_metrics,
)
from app.services.search.profile_service import ResolvedProfile
from app.services.search.search_service import SearchParams, SearchService

logger = logging.getLogger(__name__)

RETRIEVAL_DEPTH = 10
MAX_ERROR_LENGTH = 2000


class EvalRunError(Exception):
    pass


@dataclass
class _CaseOutcome:
    retrieved: list[dict[str, Any]]
    metrics: dict[str, Any]
    answer: str | None = None
    citations: list[dict[str, Any]] | None = None
    grounding: str | None = None
    judge: dict[str, Any] | None = None


class EvalRunner:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        authz_cache: AuthzCache,
        pipeline: RetrievalPipeline,
        gateway: LLMGateway,
        settings: Settings,
    ) -> None:
        self.session_factory = session_factory
        self.authz_cache = authz_cache
        self.pipeline = pipeline
        self.gateway = gateway
        self.settings = settings
        self.judge = AnswerJudge(gateway, settings.eval_judge_timeout_seconds)
        self.validator = EvidenceValidator(
            min_score=settings.chat_evidence_min_score,
            confident_score=settings.chat_evidence_confident_score,
            min_count=settings.chat_min_evidence,
        )
        self.citations = CitationValidator(settings.chat_quote_max_chars)

    # ---- run --------------------------------------------------------------------------

    async def run(self, run_id: str) -> None:
        async with self.session_factory() as session:
            run = await session.get(EvalRun, run_id)
            if run is None or run.status in (EvalRunStatus.DONE.value, EvalRunStatus.FAILED.value):
                return
            # A RUNNING run here was interrupted (worker crash): start over.
            await session.execute(delete(EvalResult).where(EvalResult.run_id == run.id))
            run.status = EvalRunStatus.RUNNING.value
            run.started_at = utcnow()
            run.done_count = 0
            run.error = None
            try:
                ctx = await self._context(session, run)
            except EvalRunError as exc:
                await self._finish(session, run, failed=str(exc))
                return
            cases = list(
                (
                    await session.execute(
                        select(EvalCase)
                        .where(EvalCase.dataset_id == run.dataset_id, EvalCase.org_id == run.org_id)
                        .order_by(EvalCase.created_at, EvalCase.id)
                        .limit(self.settings.eval_max_cases_per_run)
                    )
                )
                .scalars()
                .all()
            )
            run.case_count = len(cases)
            profile = ResolvedProfile(
                run.profile_id, run.profile_name, RetrievalConfig.model_validate(run.config)
            )
            judge = run.judge_enabled
            await session.commit()

        semaphore = asyncio.Semaphore(max(1, self.settings.eval_concurrency))

        async def one(case: EvalCase) -> None:
            async with semaphore:
                with usage_scope(
                    feature=FEATURE_EVALUATION, org_id=ctx.org_id, user_id=ctx.user.id
                ):
                    await self._evaluate(run_id, ctx, profile, case, judge)

        try:
            await asyncio.gather(*(one(c) for c in cases))
        except Exception as exc:
            logger.exception("eval_run_failed", extra={"run_id": run_id})
            async with self.session_factory() as session:
                failed = await session.get(EvalRun, run_id)
                if failed is not None:
                    await self._finish(session, failed, failed=f"{type(exc).__name__}: {exc}")
            return

        async with self.session_factory() as session:
            done = await session.get(EvalRun, run_id)
            if done is not None:
                await self._finish(session, done)

    async def _finish(self, session: AsyncSession, run: EvalRun, failed: str | None = None) -> None:
        results = (
            (await session.execute(select(EvalResult).where(EvalResult.run_id == run.id)))
            .scalars()
            .all()
        )
        ok = [r for r in results if r.error is None]
        metrics: dict[str, Any] = mean_metrics(r.metrics for r in ok)
        metrics["cases"] = len(results)
        metrics["errors"] = len(results) - len(ok)
        metrics["latency_ms_avg"] = (
            round(sum(r.latency_ms for r in ok) / len(ok), 2) if ok else None
        )
        run.metrics = metrics
        run.status = EvalRunStatus.FAILED.value if failed else EvalRunStatus.DONE.value
        run.error = failed[:MAX_ERROR_LENGTH] if failed else None
        run.finished_at = utcnow()
        await session.commit()
        logger.info(
            "eval_run_finished",
            extra={"run_id": run.id, "status": run.status, "cases": len(results)},
        )

    async def _context(self, session: AsyncSession, run: EvalRun) -> RequestContext:
        user = await session.get(User, run.created_by) if run.created_by else None
        if user is None or user.org_id != run.org_id or not user.is_active:
            raise EvalRunError("The run's creator no longer exists or is disabled")
        principals = await PrincipalResolver(session, self.authz_cache).resolve(run.org_id, user.id)
        permissions = await PermissionResolver(session, self.authz_cache).resolve(principals)
        current = CurrentUser(
            id=user.id,
            org_id=run.org_id,
            username=user.username,
            display_name=user.display_name,
            principals=principals,
            permissions=permissions,
        )
        audit = AuditContext(org_id=run.org_id, actor_id=user.id, actor_name=user.username)
        return RequestContext(user=current, audit=audit)

    # ---- one case ---------------------------------------------------------------------

    async def _evaluate(
        self,
        run_id: str,
        ctx: RequestContext,
        profile: ResolvedProfile,
        case: EvalCase,
        judge: bool,
    ) -> None:
        started = time.perf_counter()
        result = EvalResult(org_id=ctx.org_id, run_id=run_id, case_id=case.id)
        async with self.session_factory() as session:
            try:
                outcome = await self._case(session, ctx, profile, case, judge)
            except (AppError, LLMError) as exc:
                await session.rollback()
                result.error = f"{type(exc).__name__}: {exc}"[:MAX_ERROR_LENGTH]
            else:
                result.retrieved = outcome.retrieved
                result.metrics = outcome.metrics
                result.answer = outcome.answer
                result.citations = outcome.citations or []
                result.grounding = outcome.grounding
                result.judge = outcome.judge or {}
            result.latency_ms = int((time.perf_counter() - started) * 1000)
            session.add(result)
            await session.execute(
                update(EvalRun)
                .where(EvalRun.id == run_id)
                .values(done_count=EvalRun.done_count + 1)
            )
            await session.commit()

    async def _case(
        self,
        session: AsyncSession,
        ctx: RequestContext,
        profile: ResolvedProfile,
        case: EvalCase,
        judge: bool,
    ) -> _CaseOutcome:
        settings = self.settings
        search = SearchService(
            session, ctx, self.authz_cache, pipeline=self.pipeline, settings=settings
        )
        run = await search.execute(
            SearchParams(
                q=case.question,
                kb_ids=tuple(case.kb_ids or ()),
                top_k=max(RETRIEVAL_DEPTH, settings.chat_retrieval_top_k),
                fresh=True,
                profile=profile,
            )
        )
        results = run.outcome.results if run.outcome else []
        expected_docs = set(case.expected_document_ids or [])
        expected_chunks = set(case.expected_chunk_ids or [])
        retrieved = [
            {
                "rank": r.rank,
                "chunk_id": r.passage.chunk_id,
                "document_id": r.passage.document.id,
                "title": r.passage.document.title,
                "score": r.rerank_score,
                "is_ko": r.passage.is_ko,
                "relevant": r.passage.document.id in expected_docs
                or r.passage.chunk_id in expected_chunks,
            }
            for r in results
        ]
        metrics: dict[str, Any] = retrieval_metrics(
            [RetrievedItem(r.rank, r.passage.chunk_id, r.passage.document.id) for r in results],
            expected_docs,
            expected_chunks,
        )
        metrics["retrieved"] = len(results)
        metrics["degraded"] = 1.0 if run.outcome and run.outcome.degraded else 0.0
        if not judge:
            return _CaseOutcome(retrieved=retrieved, metrics=metrics)

        hits = [
            Hit(r.passage, r.rerank_score, r.rank) for r in results[: settings.chat_retrieval_top_k]
        ]
        expansion = KnowledgeExpansion(
            ChunkRepository(session),
            ctx.org_id,
            ExpansionConfig(
                parent=settings.chat_expand_parent,
                neighbors=max(0, settings.chat_expand_neighbors),
                ko=settings.chat_expand_ko,
                token_budget=settings.chat_context_token_budget,
            ),
            PublishedKnowledgeObjects(session, ctx.user, settings.chat_expand_ko_limit),
        )
        expanded = await expansion.expand(hits)
        evidences: list[Evidence] = (
            await EvidenceAclChecker(session, ctx.user).check(expanded.evidences)
        ).kept
        decision = self.validator.validate(evidences)
        if decision.verdict == Verdict.REFUSE:
            metrics["answered"] = 0.0
            return _CaseOutcome(
                retrieved=retrieved,
                metrics=metrics,
                answer=prompt.NO_EVIDENCE_ANSWER,
                citations=[],
                grounding=Grounding.NO_EVIDENCE.value,
                judge={"skipped": "refused: no reliable evidence"},
            )

        uncertain = decision.verdict == Verdict.UNCERTAIN
        with usage_scope(stage=STAGE_GENERATE):
            completion = await self.gateway.complete(
                prompt.answer_messages(case.question, None, evidences, [], uncertain=uncertain),
                time_limit=settings.llm_timeout_seconds,
                temperature=settings.chat_temperature,
                max_tokens=settings.chat_max_tokens,
            )
        cited = self.citations.validate(completion.content, evidences)
        grounding = Grounding.UNCERTAIN if uncertain else Grounding.GROUNDED
        if not cited.grounded:
            grounding = Grounding.LOW_GROUNDING
        metrics["answered"] = 1.0
        metrics["grounded"] = 1.0 if cited.grounded else 0.0
        precision = citation_precision(cited.citations, expected_docs)
        if precision is not None:
            metrics["citation_precision"] = precision
        verdict = await self.judge.judge(
            case.question, case.reference_answer, evidences, cited.answer
        )
        for key, value in verdict.scores.items():
            if value is not None:
                metrics[key] = value
        return _CaseOutcome(
            retrieved=retrieved,
            metrics=metrics,
            answer=cited.answer,
            citations=cited.citations,
            grounding=grounding.value,
            judge=verdict.describe(),
        )
