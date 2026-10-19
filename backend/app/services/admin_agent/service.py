"""Admin assistant workflow: a fixed state machine with code gates between its stages.

    understand → clarify → (query → answer) → resolve → plan → risk → approval
    approval ─(admin confirms)→ execute → verify → report

The model is used in exactly two places: `understand` (intent + slots, schema-validated) and
`answer` (phrasing query results). Whether to continue, what the steps are, whether a change
happened, and what the report says are all decided by code. Every stage streams events.
"""

import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import AppError, NotFoundError
from app.llm import ChatMessage, LLMError, LLMGateway
from app.llm.usage import FEATURE_ADMIN_AGENT, usage_scope
from app.models import AgentRun, AgentRunStatus
from app.schemas.admin_agent import AgentChatIn
from app.services.admin_agent import prompt
from app.services.admin_agent.resolve import Planned, ResolveError, Resolver
from app.services.admin_agent.risk import assess_step, overall
from app.services.admin_agent.tasks import TASKS, TaskSpec, order_steps
from app.services.admin_agent.tools import TOOLS, AgentContext
from app.services.admin_agent.understand import understand
from app.services.admin_agent.verify import CHECKS
from app.services.authz import AuthzCache
from app.services.context import BaseService, RequestContext
from app.services.ingest.queue import TaskQueue

logger = logging.getLogger(__name__)

RUN_TTL_SECONDS = 30 * 60
MAX_PLAN_STEPS = 40
LLM_TIMEOUT_SECONDS = 60.0


@dataclass(frozen=True)
class Event:
    type: str
    data: dict[str, Any]

    def encode(self) -> str:
        payload = json.dumps(self.data, ensure_ascii=False, default=str)
        return f"event: {self.type}\ndata: {payload}\n\n"


def _ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def stage(name: str, status: str, start: float | None = None, **detail: Any) -> Event:
    data: dict[str, Any] = {"stage": name, "status": status, "detail": detail}
    if start is not None:
        data["duration_ms"] = _ms(start)
    return Event("stage", data)


def issue(exc: Exception, **extra: Any) -> dict[str, Any]:
    """A problem the admin has to resolve, as a code the UI localizes."""
    if isinstance(exc, ResolveError):
        return {"reason": exc.reason, "params": exc.params, "options": exc.options, **extra}
    if isinstance(exc, ValidationError):
        fields = sorted({str(e["loc"][0]) for e in exc.errors() if e["loc"]} or {"?"})
        return {"reason": "invalid_slot", "params": {"fields": ",".join(fields)}, **extra}
    if isinstance(exc, AppError):
        return {"reason": "error", "params": {"message": exc.message}, **extra}
    return {"reason": "error", "params": {"message": f"{type(exc).__name__}"}, **extra}


class StepFailedError(Exception):
    def __init__(self, info: dict[str, Any]) -> None:
        super().__init__(info.get("reason"))
        self.info = info


class AdminAgentService(BaseService):
    def __init__(
        self,
        session: AsyncSession,
        ctx: RequestContext,
        authz_cache: AuthzCache,
        *,
        settings: Settings,
        http: httpx.AsyncClient,
        gateway: LLMGateway,
        queue: TaskQueue | None = None,
    ) -> None:
        super().__init__(session, ctx, authz_cache)
        self.settings = settings
        self.gateway = gateway
        self.agent = AgentContext(
            session, ctx, authz_cache, settings, http, Resolver(session, ctx.org_id), queue
        )

    async def _llm(self, messages: list[ChatMessage], *, temperature: float = 0.0) -> str:
        try:
            with usage_scope(feature=FEATURE_ADMIN_AGENT):
                result = await self.gateway.complete(
                    messages,
                    time_limit=LLM_TIMEOUT_SECONDS,
                    temperature=temperature,
                    max_tokens=2000,
                )
        except LLMError as exc:
            logger.warning("admin_agent_llm_failed", extra={"error": str(exc)[:300]})
            raise AppError("模型调用失败，请稍后重试", code="AGENT_LLM_UNAVAILABLE") from exc
        return result.content

    # ---- run: understand → … → approval ------------------------------------------------

    async def run(self, data: AgentChatIn) -> AsyncIterator[Event]:
        record = AgentRun(
            org_id=self.org_id,
            user_id=self.ctx.user.id,
            user_name=self.ctx.user.username,
            message=data.message,
            status=AgentRunStatus.RUNNING,
            events=[],
            exec_events=[],
        )
        self.session.add(record)
        await self.session.flush()
        recorded: list[dict[str, Any]] = []
        async for event in self._guarded(record, data):
            recorded.append(storable(event))
            if event.type == "report":
                record.status = STATUS_OF_OUTCOME.get(event.data["outcome"], record.status)
            yield event
        record.events = recorded
        await self.session.flush()

    async def _guarded(self, record: AgentRun, data: AgentChatIn) -> AsyncIterator[Event]:
        yield Event("run", {"run_id": record.id})
        try:
            async for event in self._run(record, data):
                yield event
        except AppError as exc:
            yield Event("error", issue(exc))
            yield Event("report", {"outcome": "error"})
        yield Event("done", {})

    async def _run(self, record: AgentRun, data: AgentChatIn) -> AsyncIterator[Event]:
        run_id = record.id
        # 1. understand (model) ───────────────────────────────────────────────────────────
        t = time.perf_counter()
        yield stage("understand", "running")
        history = [ChatMessage(m.role, m.content) for m in data.history[-20:]]
        result = await understand(
            self.gateway,
            history,
            data.message,
            native_tools=self.settings.admin_agent_native_tools,
            today=datetime.now(ZoneInfo(self.settings.analytics_timezone)).date(),
        )
        u = result.understanding
        record.language, record.intent, record.understand_mode = u.language, u.intent, result.mode
        if u.thought:
            yield Event("thought", {"stage": "understand", "text": u.thought})
        yield stage(
            "understand",
            "done",
            t,
            intent=u.intent,
            language=u.language,
            tasks=[task.type for task in u.tasks],
            mode=result.mode,
        )
        if not u.tasks:
            yield Event("answer", {"text": u.reply or "", "language": u.language})
            outcome = "out_of_scope" if u.intent == "out_of_scope" else "answered"
            yield Event("report", {"outcome": outcome, "language": u.language})
            return

        # 2. clarify gate: known task, required slots present, caller allowed ──────────────
        t = time.perf_counter()
        yield stage("clarify", "running")
        tasks: list[tuple[TaskSpec, Any]] = []
        problems: list[dict[str, Any]] = []
        for i, task in enumerate(u.tasks):
            spec = TASKS.get(task.type)
            if spec is None:
                problems.append({"reason": "unsupported_task", "params": {"task": task.type}})
                continue
            if not spec.permissions_ok(self.agent):
                problems.append({"reason": "no_permission", "params": {"task": spec.name}})
                continue
            try:
                slots = spec.slots.model_validate(task.slots)
            except ValidationError as exc:
                missing = sorted(
                    {
                        str(e["loc"][0]) if e["loc"] else str(e.get("ctx", {}).get("error", "?"))
                        for e in exc.errors()
                    }
                )
                problems.append(
                    {
                        "reason": "missing_slot",
                        "params": {"task": spec.name, "fields": ",".join(missing)},
                        "index": i,
                    }
                )
                continue
            tasks.append((spec, slots))
        if problems:
            yield Event("clarify", {"items": problems})
            yield stage("clarify", "blocked", t, count=len(problems))
            yield Event("report", {"outcome": "clarify", "language": u.language})
            return
        yield stage("clarify", "done", t)

        queries = [(s, v) for s, v in tasks if s.kind == "query"]
        changes = [(s, v) for s, v in tasks if s.kind == "change"]

        # 3. queries: read tools run directly, the model only phrases the answer ──────────
        if queries:
            async for event in self._queries(queries, data.message, u.language):
                yield event

        if not changes:
            yield Event("report", {"outcome": "answered", "language": u.language})
            return

        # 4. resolve: expand templates into steps and preview each one ───────────────────
        t = time.perf_counter()
        yield stage("resolve", "running")
        steps, previews, problems = await self._prepare(changes)
        if problems:
            yield Event("clarify", {"items": problems})
            yield stage("resolve", "blocked", t, count=len(problems))
            yield Event("report", {"outcome": "clarify", "language": u.language})
            return
        yield stage("resolve", "done", t, steps=len(steps))

        # 5. plan + 6. risk ──────────────────────────────────────────────────────────────
        t = time.perf_counter()
        risks = [
            assess_step(tool, args, p["warnings"])
            for (tool, args), p in zip(steps, previews, strict=True)
        ]
        level = overall([r.level for r in risks])
        plan_steps = [
            {
                "tool": tool,
                "args": args,
                "display": p["display"],
                "warnings": p["warnings"],
                "risk": r.level,
                "risk_reasons": r.reasons,
            }
            for (tool, args), p, r in zip(steps, previews, risks, strict=True)
        ]
        record.steps = [{"tool": tool, "args": args} for tool, args in steps]
        record.risk = level
        record.expires_at = datetime.now(UTC) + timedelta(seconds=RUN_TTL_SECONDS)
        yield stage("plan", "done", t, steps=len(steps))
        yield stage("risk", "done", t, level=level)
        yield Event(
            "plan",
            {
                "run_id": run_id,
                "steps": plan_steps,
                "risk": level,
                "needs_ack": level == "high",
                "expires_in": RUN_TTL_SECONDS,
            },
        )
        # 7. approval: nothing changes until the admin confirms this exact plan.
        yield stage("approval", "waiting")
        yield Event("report", {"outcome": "awaiting_approval", "language": u.language})

    async def _queries(
        self, queries: list[tuple[TaskSpec, Any]], question: str, language: str
    ) -> AsyncIterator[Event]:
        t = time.perf_counter()
        yield stage("query", "running")
        results: list[dict[str, Any]] = []
        for spec, slots in queries:
            for tool_name, args in await spec.expand(self.agent, slots):
                call_id = uuid.uuid4().hex[:8]
                started = time.perf_counter()
                yield Event(
                    "tool", {"id": call_id, "tool": tool_name, "args": args, "status": "running"}
                )
                tool = TOOLS[tool_name]
                try:
                    async with self.session.begin_nested():
                        data = await tool.run(self.agent, tool.args.model_validate(args))
                except (AppError, ValidationError) as exc:
                    info = issue(exc)
                    results.append({"lookup": tool_name, "args": args, "error": info})
                    yield Event(
                        "tool",
                        {
                            "id": call_id,
                            "tool": tool_name,
                            "status": "failed",
                            "duration_ms": _ms(started),
                            "error": info,
                        },
                    )
                    continue
                results.append({"lookup": tool_name, "args": args, "result": data})
                count = len(data) if isinstance(data, list) else None
                yield Event(
                    "tool",
                    {
                        "id": call_id,
                        "tool": tool_name,
                        "status": "done",
                        "duration_ms": _ms(started),
                        "count": count,
                        "result": data,
                    },
                )
        yield stage("query", "done", t, lookups=len(results))
        t = time.perf_counter()
        yield stage("answer", "running")
        text = await self._llm(prompt.answer_messages(language, question, results), temperature=0.2)
        yield Event("answer", {"text": text.strip(), "language": language})
        yield stage("answer", "done", t)

    async def _prepare(
        self, changes: list[tuple[TaskSpec, Any]]
    ) -> tuple[list[tuple[str, dict[str, Any]]], list[dict[str, Any]], list[dict[str, Any]]]:
        raw: list[tuple[str, dict[str, Any]]] = []
        problems: list[dict[str, Any]] = []
        for spec, slots in changes:
            try:
                raw += await spec.expand(self.agent, slots)
            except (AppError, ValidationError) as exc:
                problems.append(issue(exc, task=spec.name))
        if problems:
            return [], [], problems
        steps = order_steps(raw)
        if len(steps) > MAX_PLAN_STEPS:
            return [], [], [{"reason": "too_many_steps", "params": {"max": str(MAX_PLAN_STEPS)}}]
        previews, problems = await self._preview(steps)
        return steps, previews, problems

    async def _preview(
        self, steps: list[tuple[str, dict[str, Any]]]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        planned = Planned()
        previews: list[dict[str, Any]] = []
        problems: list[dict[str, Any]] = []
        for i, (tool_name, args) in enumerate(steps):
            tool = TOOLS[tool_name]
            if not self.ctx.user.has_any_permission(*tool.permissions):
                problems.append(
                    {"reason": "no_permission", "params": {"task": tool_name}, "step": i}
                )
                continue
            try:
                parsed = tool.args.model_validate(args)
                assert tool.preview is not None
                p = await tool.preview(self.agent, parsed, planned)
            except (AppError, ValidationError) as exc:
                problems.append(issue(exc, step=i, tool=tool_name))
                continue
            previews.append({"display": p.display, "warnings": p.warnings})
        return previews, problems

    # ---- execute: approval → execute → verify → report ----------------------------------

    async def _own_run(self, run_id: str) -> AgentRun | None:
        row = await self.session.get(AgentRun, run_id)
        if row is None or row.org_id != self.org_id or row.user_id != self.ctx.user.id:
            return None
        return row

    async def cancel(self, run_id: str) -> None:
        await self.session.execute(
            update(AgentRun)
            .where(
                AgentRun.id == run_id,
                AgentRun.org_id == self.org_id,
                AgentRun.user_id == self.ctx.user.id,
                AgentRun.status == AgentRunStatus.AWAITING_APPROVAL,
            )
            .values(status=AgentRunStatus.CANCELLED)
        )

    async def execute(self, run_id: str, acknowledge_risk: bool) -> AsyncIterator[Event]:
        yield Event("run", {"run_id": run_id})
        row = await self._own_run(run_id)
        if (
            row is None
            or row.status != AgentRunStatus.AWAITING_APPROVAL
            or row.expires_at is None
            or _aware(row.expires_at) < datetime.now(UTC)
        ):
            yield Event("error", {"reason": "plan_expired", "params": {}})
            yield Event("report", {"outcome": "expired"})
            yield Event("done", {})
            return
        if row.risk == "high" and not acknowledge_risk:
            # Gate: the run stays approvable, so the admin can tick the acknowledgement.
            yield Event("error", {"reason": "risk_ack_required", "params": {}})
            yield Event("report", {"outcome": "blocked", "language": row.language})
            yield Event("done", {})
            return
        # Single use: claim the run atomically before touching anything.
        claimed = await self.session.execute(
            update(AgentRun)
            .where(AgentRun.id == run_id, AgentRun.status == AgentRunStatus.AWAITING_APPROVAL)
            .values(status=AgentRunStatus.EXECUTING, executed_at=datetime.now(UTC))
        )
        if getattr(claimed, "rowcount", 1) != 1:
            yield Event("error", {"reason": "plan_expired", "params": {}})
            yield Event("report", {"outcome": "expired"})
            yield Event("done", {})
            return
        await self.session.commit()
        plan_steps: list[dict[str, Any]] = list(row.steps or [])
        stored: dict[str, Any] = {
            "language": row.language,
            "message": row.message,
            "steps": plan_steps,
            "risk": row.risk,
        }
        recorded: list[dict[str, Any]] = []
        approval = stage("approval", "done", risk=row.risk, acknowledged=acknowledge_risk)
        recorded.append(storable(approval))
        yield approval
        outcome = "failed"
        steps: list[tuple[str, dict[str, Any]]] = [(s["tool"], s["args"]) for s in plan_steps]
        async for event in self._execute(run_id, stored, steps):
            recorded.append(storable(event))
            if event.type == "report":
                outcome = event.data["outcome"]
            yield event
        # The run row may have been expired by a rollback: re-read it before recording.
        row = await self.session.get(AgentRun, run_id, populate_existing=True)
        if row is not None:
            row.status = STATUS_OF_OUTCOME.get(outcome, AgentRunStatus.FAILED)
            row.exec_events = recorded
            await self.session.commit()
        yield Event("done", {})

    async def _execute(
        self, run_id: str, stored: dict[str, Any], steps: list[tuple[str, dict[str, Any]]]
    ) -> AsyncIterator[Event]:
        language = stored["language"]
        t = time.perf_counter()
        yield stage("execute", "running", total=len(steps))
        # Gate: data or permissions may have changed since the preview.
        _, problems = await self._preview(steps)
        if problems:
            yield Event("clarify", {"items": problems})
            yield stage("execute", "blocked", t)
            yield Event("report", {"outcome": "failed", "language": language})
            return
        done = 0
        try:
            for i, (tool_name, args) in enumerate(steps):
                tool = TOOLS[tool_name]
                started = time.perf_counter()
                yield Event("step", {"index": i, "tool": tool_name, "status": "running"})
                try:
                    async with self.session.begin_nested():
                        output = await tool.run(self.agent, tool.args.model_validate(args))
                        check = await CHECKS[tool_name](self.agent, args)
                except Exception as exc:
                    if not isinstance(exc, AppError | ValidationError):
                        logger.exception(
                            "admin_agent_step_crashed", extra={"run_id": run_id, "step": i}
                        )
                    raise StepFailedError({"index": i, **issue(exc)}) from exc
                yield Event(
                    "verify",
                    {"index": i, "ok": check.ok, "code": check.code, "params": check.params},
                )
                if not check.ok:
                    raise StepFailedError(
                        {"index": i, "reason": "verify_failed", "params": {"check": check.code}}
                    )
                done += 1
                yield Event(
                    "step",
                    {
                        "index": i,
                        "tool": tool_name,
                        "status": "done",
                        "duration_ms": _ms(started),
                        "output": output,
                    },
                )
        except StepFailedError as failure:
            await self.session.rollback()
            index = failure.info["index"]
            yield Event("step", {"index": index, "status": "failed", "error": failure.info})
            for j in range(index):
                yield Event("step", {"index": j, "status": "rolled_back"})
            for j in range(index + 1, len(steps)):
                yield Event("step", {"index": j, "status": "not_run"})
            yield stage("execute", "failed", t, done=done, total=len(steps))
            yield Event("report", {"outcome": "failed", "language": language, "done": 0})
            return
        await self.audit.record(
            self.audit_ctx,
            "admin_agent.execute",
            "admin_agent_run",
            run_id,
            None,
            {"message": stored.get("message"), "steps": stored["steps"]},
        )
        await self.session.flush()
        yield stage("execute", "done", t, done=done, total=len(steps))
        yield stage("verify", "done", checks=done)
        yield Event("report", {"outcome": "done", "language": language, "done": done})

    # ---- history -------------------------------------------------------------------------

    async def list_runs(self, page: int, size: int) -> tuple[list[AgentRun], int]:
        base = select(AgentRun).where(
            AgentRun.org_id == self.org_id, AgentRun.user_id == self.ctx.user.id
        )
        total = (
            await self.session.execute(select(func.count()).select_from(base.subquery()))
        ).scalar_one()
        rows = await self.session.execute(
            base.order_by(AgentRun.created_at.desc()).offset((page - 1) * size).limit(size)
        )
        return list(rows.scalars()), int(total)

    async def get_run(self, run_id: str) -> AgentRun:
        row = await self._own_run(run_id)
        if row is None:
            raise NotFoundError("Run not found", code="AGENT_RUN_NOT_FOUND")
        return row


STATUS_OF_OUTCOME = {
    "answered": AgentRunStatus.ANSWERED,
    "clarify": AgentRunStatus.CLARIFY,
    "out_of_scope": AgentRunStatus.OUT_OF_SCOPE,
    "awaiting_approval": AgentRunStatus.AWAITING_APPROVAL,
    "done": AgentRunStatus.DONE,
    "failed": AgentRunStatus.FAILED,
    "error": AgentRunStatus.ERROR,
}
SECRET_KEYS = {"temporary_password"}
MAX_STORED_ITEMS = 50


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: ("***" if k in SECRET_KEYS else _redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v) for v in value[:MAX_STORED_ITEMS]]
    return value


def storable(event: Event) -> dict[str, Any]:
    """Event as persisted: secrets (temporary passwords) never reach the database."""
    return {"type": event.type, "data": _redact(json.loads(json.dumps(event.data, default=str)))}
