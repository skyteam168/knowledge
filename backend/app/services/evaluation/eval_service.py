"""Evaluation datasets, one-click imports, runs and run comparison (API side).

Runs are executed by the `run_evaluation` worker actor (app.services.evaluation.runner).
"""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.db import run_after_commit
from app.core.exceptions import ConflictError, NotFoundError, ValidationAppError
from app.models import (
    Conversation,
    EvalCase,
    EvalCaseSource,
    EvalDataset,
    EvalResult,
    EvalRun,
    EvalRunStatus,
    GapStatus,
    GenerationStatus,
    KnowledgeGap,
    KnowledgeObject,
    KoVersion,
    Message,
    MessageFeedback,
    MessageRole,
    MessageStatus,
    QaTrace,
)
from app.repositories.base import paginate
from app.repositories.indexing_repo import IndexGenerationRepository
from app.schemas.common import Page
from app.schemas.evaluation import (
    EvalCandidateOut,
    EvalCaseCreate,
    EvalCaseOut,
    EvalCaseUpdate,
    EvalCompareCaseOut,
    EvalCompareOut,
    EvalConfigDiffOut,
    EvalDatasetCreate,
    EvalDatasetOut,
    EvalDatasetUpdate,
    EvalImportIn,
    EvalImportOut,
    EvalResultOut,
    EvalRunCreate,
    EvalRunOut,
    ImportSource,
)
from app.services.authz import AuthzCache
from app.services.context import BaseService, RequestContext
from app.services.ingest.queue import TaskQueue
from app.services.search.profile_service import RetrievalProfileService

RESOURCE_DATASET = "eval_dataset"
RESOURCE_RUN = "eval_run"
MAX_COMPARE_RUNS = 4
ACTIVE_RUN = (EvalRunStatus.PENDING.value, EvalRunStatus.RUNNING.value)


def _flatten(data: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(data, dict):
        out: dict[str, Any] = {}
        for key, value in data.items():
            out.update(_flatten(value, f"{prefix}{key}."))
        return out
    return {prefix.rstrip("."): data}


def _cited(citations: Sequence[dict[str, Any]] | None) -> tuple[list[str], list[str]]:
    docs: list[str] = []
    chunks: list[str] = []
    for c in citations or []:
        if c.get("document_id"):
            docs.append(str(c["document_id"]))
        if not c.get("is_ko"):
            chunks.extend(str(i) for i in (c.get("hit_chunk_ids") or [c.get("chunk_id")]) if i)
    return list(dict.fromkeys(docs)), list(dict.fromkeys(chunks))


class EvalService(BaseService):
    def __init__(
        self,
        session: AsyncSession,
        ctx: RequestContext,
        authz_cache: AuthzCache,
        *,
        settings: Settings,
        queue: TaskQueue,
    ) -> None:
        super().__init__(session, ctx, authz_cache)
        self.settings = settings
        self.queue = queue

    # ---- datasets ---------------------------------------------------------------------

    async def _dataset(self, dataset_id: str) -> EvalDataset:
        ds = await self.session.get(EvalDataset, dataset_id)
        if ds is None or ds.org_id != self.org_id:
            raise NotFoundError("Evaluation dataset not found")
        return ds

    async def _dataset_out(self, ds: EvalDataset) -> EvalDatasetOut:
        count = await self.session.scalar(select(func.count()).where(EvalCase.dataset_id == ds.id))
        return EvalDatasetOut.model_validate(ds).model_copy(update={"case_count": int(count or 0)})

    async def list_datasets(self, page: int, size: int) -> Page[EvalDatasetOut]:
        stmt = (
            select(EvalDataset)
            .where(EvalDataset.org_id == self.org_id)
            .order_by(EvalDataset.created_at.desc())
        )
        rows, total = await paginate(self.session, stmt, page, size)
        counts: dict[str, int] = {}
        if rows:
            counts = {
                ds_id: int(n)
                for ds_id, n in (
                    await self.session.execute(
                        select(EvalCase.dataset_id, func.count())
                        .where(EvalCase.dataset_id.in_([d.id for d in rows]))
                        .group_by(EvalCase.dataset_id)
                    )
                ).all()
            }
        items = [
            EvalDatasetOut.model_validate(d).model_copy(update={"case_count": counts.get(d.id, 0)})
            for d in rows
        ]
        return Page(items=items, total=total, page=page, size=size)

    async def _unique_name(self, name: str, exclude_id: str | None = None) -> None:
        existing = await self.session.scalar(
            select(EvalDataset.id).where(
                EvalDataset.org_id == self.org_id, EvalDataset.name == name
            )
        )
        if existing is not None and existing != exclude_id:
            raise ConflictError("A dataset with this name already exists")

    async def create_dataset(self, data: EvalDatasetCreate) -> EvalDatasetOut:
        name = data.name.strip()
        await self._unique_name(name)
        ds = EvalDataset(
            org_id=self.org_id,
            name=name,
            description=data.description,
            created_by=self.ctx.user.id,
        )
        self.session.add(ds)
        await self.session.flush()
        await self.audit.record(
            self.audit_ctx, "eval.dataset.create", RESOURCE_DATASET, ds.id, None, {"name": name}
        )
        return await self._dataset_out(ds)

    async def get_dataset(self, dataset_id: str) -> EvalDatasetOut:
        return await self._dataset_out(await self._dataset(dataset_id))

    async def update_dataset(self, dataset_id: str, data: EvalDatasetUpdate) -> EvalDatasetOut:
        ds = await self._dataset(dataset_id)
        before = {"name": ds.name, "description": ds.description}
        if data.name is not None and data.name.strip() != ds.name:
            await self._unique_name(data.name.strip(), exclude_id=ds.id)
            ds.name = data.name.strip()
        if "description" in data.model_fields_set:
            ds.description = data.description
        await self.session.flush()
        await self.audit.record(
            self.audit_ctx,
            "eval.dataset.update",
            RESOURCE_DATASET,
            ds.id,
            before,
            {"name": ds.name, "description": ds.description},
        )
        return await self._dataset_out(ds)

    async def delete_dataset(self, dataset_id: str) -> None:
        ds = await self._dataset(dataset_id)
        running = await self.session.scalar(
            select(func.count()).where(EvalRun.dataset_id == ds.id, EvalRun.status.in_(ACTIVE_RUN))
        )
        if running:
            raise ConflictError("The dataset has runs in progress")
        await self.session.delete(ds)
        await self.session.flush()
        await self.audit.record(
            self.audit_ctx, "eval.dataset.delete", RESOURCE_DATASET, dataset_id, {"name": ds.name}
        )

    # ---- cases ------------------------------------------------------------------------

    async def _case(self, case_id: str) -> EvalCase:
        case = await self.session.get(EvalCase, case_id)
        if case is None or case.org_id != self.org_id:
            raise NotFoundError("Evaluation case not found")
        return case

    async def list_cases(
        self, dataset_id: str, page: int, size: int, keyword: str | None
    ) -> Page[EvalCaseOut]:
        ds = await self._dataset(dataset_id)
        stmt = select(EvalCase).where(EvalCase.dataset_id == ds.id)
        if keyword:
            stmt = stmt.where(EvalCase.question.contains(keyword))
        rows, total = await paginate(
            self.session, stmt.order_by(EvalCase.created_at.desc(), EvalCase.id), page, size
        )
        return Page(
            items=[EvalCaseOut.model_validate(r) for r in rows], total=total, page=page, size=size
        )

    async def create_case(self, dataset_id: str, data: EvalCaseCreate) -> EvalCaseOut:
        ds = await self._dataset(dataset_id)
        case = EvalCase(
            org_id=self.org_id,
            dataset_id=ds.id,
            question=data.question.strip(),
            reference_answer=data.reference_answer,
            expected_document_ids=data.expected_document_ids,
            expected_chunk_ids=data.expected_chunk_ids,
            kb_ids=data.kb_ids,
            tags=data.tags,
            source=EvalCaseSource.MANUAL.value,
            created_by=self.ctx.user.id,
        )
        self.session.add(case)
        await self.session.flush()
        await self.audit.record(
            self.audit_ctx,
            "eval.case.create",
            RESOURCE_DATASET,
            ds.id,
            None,
            {"case_id": case.id, "question": case.question},
        )
        return EvalCaseOut.model_validate(case)

    async def update_case(self, case_id: str, data: EvalCaseUpdate) -> EvalCaseOut:
        case = await self._case(case_id)
        before = EvalCaseOut.model_validate(case).model_dump(mode="json")
        for name in data.model_fields_set:
            value = getattr(data, name)
            if name == "question":
                if value is None:
                    continue
                value = value.strip()
            elif name != "reference_answer" and value is None:
                value = []
            setattr(case, name, value)
        await self.session.flush()
        after = EvalCaseOut.model_validate(case)
        await self.audit.record(
            self.audit_ctx,
            "eval.case.update",
            RESOURCE_DATASET,
            case.dataset_id,
            before,
            after.model_dump(mode="json"),
        )
        return after

    async def delete_case(self, case_id: str) -> None:
        case = await self._case(case_id)
        await self.session.delete(case)
        await self.session.flush()
        await self.audit.record(
            self.audit_ctx,
            "eval.case.delete",
            RESOURCE_DATASET,
            case.dataset_id,
            {"case_id": case.id, "question": case.question},
        )

    # ---- one-click import -------------------------------------------------------------

    async def candidates(
        self,
        source: ImportSource,
        page: int,
        size: int,
        dataset_id: str | None = None,
        keyword: str | None = None,
    ) -> Page[EvalCandidateOut]:
        if source == "feedback":
            items, total = await self._feedback_candidates(page, size, keyword)
        else:
            items, total = await self._gap_candidates(page, size, keyword)
        if dataset_id and items:
            ds = await self._dataset(dataset_id)
            imported = set(
                (
                    await self.session.execute(
                        select(EvalCase.source_id).where(
                            EvalCase.dataset_id == ds.id,
                            EvalCase.source == source,
                            EvalCase.source_id.in_([c.source_id for c in items]),
                        )
                    )
                ).scalars()
            )
            items = [c.model_copy(update={"imported": c.source_id in imported}) for c in items]
        return Page(items=items, total=total, page=page, size=size)

    def _feedback_stmt(self, keyword: str | None = None) -> Any:
        upvoted = select(MessageFeedback.message_id).where(
            MessageFeedback.org_id == self.org_id, MessageFeedback.rating == "up"
        )
        stmt = (
            select(Message, QaTrace.query, Conversation.kb_ids)
            .outerjoin(QaTrace, QaTrace.id == Message.trace_id)
            .outerjoin(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Message.org_id == self.org_id,
                Message.role == MessageRole.ASSISTANT.value,
                Message.status == MessageStatus.DONE.value,
                Message.id.in_(upvoted),
            )
        )
        if keyword:
            stmt = stmt.where(QaTrace.query.contains(keyword))
        return stmt

    @staticmethod
    def _feedback_candidate(
        message: Message, query: str | None, kb_ids: list[str] | None
    ) -> EvalCandidateOut:
        docs, chunks = _cited(message.citations)
        return EvalCandidateOut(
            source="feedback",
            source_id=message.id,
            question=query or message.rewritten_query or "",
            reference_answer=message.content,
            expected_document_ids=docs,
            expected_chunk_ids=chunks,
            kb_ids=list(kb_ids or []),
            created_at=message.created_at,
        )

    async def _feedback_candidates(
        self, page: int, size: int, keyword: str | None
    ) -> tuple[list[EvalCandidateOut], int]:
        stmt = self._feedback_stmt(keyword)
        total = int(
            await self.session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        )
        rows = (
            await self.session.execute(
                stmt.order_by(Message.created_at.desc()).offset((page - 1) * size).limit(size)
            )
        ).all()
        return [self._feedback_candidate(m, q, k) for m, q, k in rows], total

    def _gap_stmt(self, keyword: str | None = None) -> Any:
        stmt = select(KnowledgeGap).where(
            KnowledgeGap.org_id == self.org_id, KnowledgeGap.status == GapStatus.RESOLVED.value
        )
        if keyword:
            stmt = stmt.where(KnowledgeGap.query.contains(keyword))
        return stmt

    async def _gap_candidate_list(self, gaps: Sequence[KnowledgeGap]) -> list[EvalCandidateOut]:
        ko_ids = sorted({str(g.resolution["ko_id"]) for g in gaps if g.resolution.get("ko_id")})
        answers: dict[str, str] = {}
        if ko_ids:
            rows = await self.session.execute(
                select(KoVersion.ko_id, KoVersion.answer)
                .join(KnowledgeObject, KnowledgeObject.id == KoVersion.ko_id)
                .where(
                    KnowledgeObject.org_id == self.org_id,
                    KoVersion.ko_id.in_(ko_ids),
                    KoVersion.version == KnowledgeObject.published_version,
                )
            )
            answers = {k: a for k, a in rows.all()}
        out = []
        for g in gaps:
            ko_id = g.resolution.get("ko_id")
            docs = (
                [str(ko_id)] if ko_id else [str(d) for d in g.resolution.get("document_ids") or []]
            )
            out.append(
                EvalCandidateOut(
                    source="gap",
                    source_id=g.id,
                    question=g.query,
                    reference_answer=answers.get(str(ko_id)) if ko_id else None,
                    expected_document_ids=docs,
                    expected_chunk_ids=[],
                    kb_ids=[g.kb_id] if g.kb_id else list(g.kb_ids or []),
                    created_at=g.resolved_at or g.created_at,
                )
            )
        return out

    async def _gap_candidates(
        self, page: int, size: int, keyword: str | None
    ) -> tuple[list[EvalCandidateOut], int]:
        stmt = self._gap_stmt(keyword).order_by(KnowledgeGap.resolved_at.desc(), KnowledgeGap.id)
        gaps, total = await paginate(self.session, stmt, page, size)
        return await self._gap_candidate_list(gaps), total

    async def import_cases(self, dataset_id: str, data: EvalImportIn) -> EvalImportOut:
        ds = await self._dataset(dataset_id)
        ids = list(dict.fromkeys(data.source_ids))
        if data.source == "feedback":
            rows = (
                await self.session.execute(self._feedback_stmt().where(Message.id.in_(ids)))
            ).all()
            found = [self._feedback_candidate(m, q, k) for m, q, k in rows]
        else:
            gaps = (
                (await self.session.execute(self._gap_stmt().where(KnowledgeGap.id.in_(ids))))
                .scalars()
                .all()
            )
            found = await self._gap_candidate_list(gaps)
        existing = set(
            (
                await self.session.execute(
                    select(EvalCase.source_id).where(
                        EvalCase.dataset_id == ds.id,
                        EvalCase.source == data.source,
                        EvalCase.source_id.in_(ids),
                    )
                )
            ).scalars()
        )
        created = 0
        for c in found:
            if c.source_id in existing or not c.question.strip():
                continue
            self.session.add(
                EvalCase(
                    org_id=self.org_id,
                    dataset_id=ds.id,
                    question=c.question.strip()[:2000],
                    reference_answer=c.reference_answer,
                    expected_document_ids=c.expected_document_ids,
                    expected_chunk_ids=c.expected_chunk_ids,
                    kb_ids=c.kb_ids,
                    source=data.source,
                    source_id=c.source_id,
                    created_by=self.ctx.user.id,
                )
            )
            created += 1
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise ConflictError("Concurrent import of the same items; retry") from exc
        await self.audit.record(
            self.audit_ctx,
            "eval.case.import",
            RESOURCE_DATASET,
            ds.id,
            None,
            {"source": data.source, "requested": len(ids), "created": created},
        )
        return EvalImportOut(created=created, skipped=len(ids) - created)

    # ---- runs -------------------------------------------------------------------------

    async def _run(self, run_id: str) -> EvalRun:
        run = await self.session.get(EvalRun, run_id)
        if run is None or run.org_id != self.org_id:
            raise NotFoundError("Evaluation run not found")
        return run

    async def _run_outs(self, runs: Sequence[EvalRun]) -> list[EvalRunOut]:
        names: dict[str, str] = {}
        if runs:
            names = {
                i: n
                for i, n in (
                    await self.session.execute(
                        select(EvalDataset.id, EvalDataset.name).where(
                            EvalDataset.id.in_({r.dataset_id for r in runs})
                        )
                    )
                ).all()
            }
        return [
            EvalRunOut.model_validate(r).model_copy(
                update={"dataset_name": names.get(r.dataset_id, "")}
            )
            for r in runs
        ]

    async def _environment(self, judge: bool) -> dict[str, Any]:
        s = self.settings
        gens = await IndexGenerationRepository(self.session).by_status(GenerationStatus.ACTIVE)
        gen = gens[-1] if gens else None
        return {
            "index_generation": gen.version if gen else None,
            "embedding_model": gen.embedding_model if gen else s.embedding_model,
            "embedding_dim": gen.embedding_dim if gen else s.embedding_dim,
            "rerank_model": s.rerank_model,
            "chat_model": s.chat_model,
            "judge_model": s.chat_model if judge else None,
            "chunking": {
                "parent_target_tokens": s.chunk_parent_target_tokens,
                "child_target_tokens": s.chunk_child_target_tokens,
                "child_max_tokens": s.chunk_child_max_tokens,
                "child_overlap_tokens": s.chunk_child_overlap_tokens,
            },
            "answer": {
                "retrieval_top_k": s.chat_retrieval_top_k,
                "evidence_min_score": s.chat_evidence_min_score,
                "evidence_confident_score": s.chat_evidence_confident_score,
                "context_token_budget": s.chat_context_token_budget,
            },
        }

    async def create_run(self, data: EvalRunCreate) -> EvalRunOut:
        ds = await self._dataset(data.dataset_id)
        cases = int(
            await self.session.scalar(select(func.count()).where(EvalCase.dataset_id == ds.id)) or 0
        )
        if cases == 0:
            raise ValidationAppError("The dataset has no cases")
        profile = await RetrievalProfileService(
            self.session, self.ctx, self.authz_cache, settings=self.settings
        ).resolve(data.profile_id)
        judge = data.judge_enabled and self.settings.eval_judge_enabled
        run = EvalRun(
            org_id=self.org_id,
            dataset_id=ds.id,
            name=data.name,
            profile_id=profile.id,
            profile_name=profile.name,
            config=profile.config.model_dump(mode="json"),
            environment=await self._environment(judge),
            judge_enabled=judge,
            status=EvalRunStatus.PENDING.value,
            case_count=min(cases, self.settings.eval_max_cases_per_run),
            created_by=self.ctx.user.id,
        )
        self.session.add(run)
        await self.session.flush()
        await self.audit.record(
            self.audit_ctx,
            "eval.run.create",
            RESOURCE_RUN,
            run.id,
            None,
            {"dataset_id": ds.id, "profile": profile.name, "judge_enabled": judge},
        )
        run_id, queue = run.id, self.queue
        run_after_commit(self.session, lambda: queue.enqueue_eval_run(run_id))
        (out,) = await self._run_outs([run])
        return out

    async def list_runs(
        self, page: int, size: int, dataset_id: str | None = None
    ) -> Page[EvalRunOut]:
        stmt = select(EvalRun).where(EvalRun.org_id == self.org_id)
        if dataset_id:
            stmt = stmt.where(EvalRun.dataset_id == dataset_id)
        rows, total = await paginate(
            self.session, stmt.order_by(EvalRun.created_at.desc()), page, size
        )
        return Page(items=await self._run_outs(rows), total=total, page=page, size=size)

    async def get_run(self, run_id: str) -> EvalRunOut:
        (out,) = await self._run_outs([await self._run(run_id)])
        return out

    async def delete_run(self, run_id: str) -> None:
        run = await self._run(run_id)
        if run.status in ACTIVE_RUN:
            raise ConflictError("The run is still in progress")
        await self.session.delete(run)
        await self.session.flush()
        await self.audit.record(
            self.audit_ctx, "eval.run.delete", RESOURCE_RUN, run_id, {"profile": run.profile_name}
        )

    async def run_results(
        self, run_id: str, page: int, size: int, only_failed: bool = False
    ) -> Page[EvalResultOut]:
        run = await self._run(run_id)
        stmt = (
            select(EvalResult, EvalCase)
            .outerjoin(EvalCase, EvalCase.id == EvalResult.case_id)
            .where(EvalResult.run_id == run.id)
        )
        if only_failed:
            stmt = stmt.where(EvalResult.error.is_not(None))
        total = int(
            await self.session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        )
        rows = (
            await self.session.execute(
                stmt.order_by(EvalCase.created_at, EvalResult.case_id)
                .offset((page - 1) * size)
                .limit(size)
            )
        ).all()
        items = [
            EvalResultOut.model_validate(r).model_copy(
                update={
                    "question": c.question if c else "",
                    "reference_answer": c.reference_answer if c else None,
                    "expected_document_ids": list(c.expected_document_ids) if c else [],
                }
            )
            for r, c in rows
        ]
        return Page(items=items, total=total, page=page, size=size)

    async def compare(self, run_ids: Sequence[str]) -> EvalCompareOut:
        ids = list(dict.fromkeys(run_ids))
        if not 2 <= len(ids) <= MAX_COMPARE_RUNS:
            raise ValidationAppError(f"Compare 2 to {MAX_COMPARE_RUNS} runs")
        runs = [await self._run(i) for i in ids]
        metric_keys = sorted({k for r in runs for k in r.metrics})
        # Environment too: index generation, models and chunking explain metric changes as well.
        flat = {
            r.id: {**_flatten(r.config), **_flatten(r.environment or {}, "environment.")}
            for r in runs
        }
        keys = sorted({k for f in flat.values() for k in f})
        config_diff = [
            EvalConfigDiffOut(key=k, values={rid: f.get(k) for rid, f in flat.items()})
            for k in keys
            if len({repr(f.get(k)) for f in flat.values()}) > 1
        ]
        results = (
            await self.session.execute(
                select(EvalResult.run_id, EvalResult.case_id, EvalResult.metrics).where(
                    EvalResult.run_id.in_(ids)
                )
            )
        ).all()
        per_case: dict[str, dict[str, dict[str, Any]]] = {}
        for run_id, case_id, metrics in results:
            per_case.setdefault(case_id, {})[run_id] = dict(metrics or {})
        questions = {
            i: q
            for i, q in (
                await self.session.execute(
                    select(EvalCase.id, EvalCase.question).where(EvalCase.id.in_(list(per_case)))
                )
            ).all()
        }
        cases = [
            EvalCompareCaseOut(case_id=cid, question=questions.get(cid, ""), metrics=m)
            for cid, m in sorted(per_case.items(), key=lambda kv: questions.get(kv[0], ""))
        ]
        return EvalCompareOut(
            runs=await self._run_outs(runs),
            metric_keys=metric_keys,
            config_diff=config_diff,
            cases=cases,
        )
