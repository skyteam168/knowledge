from collections.abc import AsyncIterator, Callable
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.api.deps import (
    AuthzCacheDep,
    RequestContextDep,
    ResourcesDep,
    SettingsDep,
    require_permission,
)
from app.schemas.admin_agent import AgentChatIn, AgentExecuteIn
from app.schemas.common import Page
from app.services.admin_agent import AGENT_ACCESS, AdminAgentService
from app.services.admin_agent.service import Event

router = APIRouter(
    prefix="/admin/agent",
    tags=["admin:agent"],
    dependencies=[Depends(require_permission(*AGENT_ACCESS))],
)
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
SSE: dict[int | str, dict[str, Any]] = {200: {"content": {"text/event-stream": {}}}}
RunFn = Callable[[AdminAgentService], AsyncIterator[Event]]


class AgentRunOut(BaseModel):
    id: str
    message: str
    status: str
    intent: str | None
    language: str | None
    understand_mode: str | None
    risk: str | None
    step_count: int
    created_at: datetime
    executed_at: datetime | None


class AgentRunDetail(AgentRunOut):
    expires_at: datetime | None
    events: list[dict[str, Any]]
    exec_events: list[dict[str, Any]]


def _service(
    session: Any,
    ctx: RequestContextDep,
    cache: AuthzCacheDep,
    settings: SettingsDep,
    resources: ResourcesDep,
) -> AdminAgentService:
    return AdminAgentService(
        session,
        ctx,
        cache,
        settings=settings,
        http=resources.http,
        gateway=resources.llm,
        queue=resources.task_queue,
    )


def _stream(
    ctx: RequestContextDep,
    cache: AuthzCacheDep,
    settings: SettingsDep,
    resources: ResourcesDep,
    run: RunFn,
) -> StreamingResponse:
    async def events() -> AsyncIterator[str]:
        # The stream owns its session (the request-scoped one closes before streaming).
        async with resources.session_factory() as session:
            async for event in run(_service(session, ctx, cache, settings, resources)):
                yield event.encode()
            await session.commit()

    return StreamingResponse(events(), media_type="text/event-stream", headers=SSE_HEADERS)


def _out(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "message": row.message,
        "status": row.status,
        "intent": row.intent,
        "language": row.language,
        "understand_mode": row.understand_mode,
        "risk": row.risk,
        "step_count": len(row.steps or []),
        "created_at": row.created_at,
        "executed_at": row.executed_at,
    }


@router.post("/runs", response_class=StreamingResponse, responses=SSE)
async def start_run(
    data: AgentChatIn,
    ctx: RequestContextDep,
    cache: AuthzCacheDep,
    settings: SettingsDep,
    resources: ResourcesDep,
) -> StreamingResponse:
    """SSE: run, stage*, thought, tool*, clarify | answer | plan, report, done (or error)."""
    return _stream(ctx, cache, settings, resources, lambda s: s.run(data))


@router.post("/runs/{run_id}/execute", response_class=StreamingResponse, responses=SSE)
async def execute_run(
    run_id: str,
    data: AgentExecuteIn,
    ctx: RequestContextDep,
    cache: AuthzCacheDep,
    settings: SettingsDep,
    resources: ResourcesDep,
) -> StreamingResponse:
    """SSE: run, stage*, step*, verify*, report, done."""
    return _stream(
        ctx, cache, settings, resources, lambda s: s.execute(run_id, data.acknowledge_risk)
    )


@router.delete("/runs/{run_id}", status_code=204)
async def cancel_run(
    run_id: str,
    ctx: RequestContextDep,
    cache: AuthzCacheDep,
    settings: SettingsDep,
    resources: ResourcesDep,
) -> None:
    async with resources.session_factory() as session:
        await _service(session, ctx, cache, settings, resources).cancel(run_id)
        await session.commit()


@router.get("/runs", response_model=Page[AgentRunOut])
async def list_runs(
    ctx: RequestContextDep,
    cache: AuthzCacheDep,
    settings: SettingsDep,
    resources: ResourcesDep,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Page[AgentRunOut]:
    async with resources.session_factory() as session:
        rows, total = await _service(session, ctx, cache, settings, resources).list_runs(page, size)
        items = [AgentRunOut(**_out(r)) for r in rows]
    return Page(items=items, total=total, page=page, size=size)


@router.get("/runs/{run_id}", response_model=AgentRunDetail)
async def get_run(
    run_id: str,
    ctx: RequestContextDep,
    cache: AuthzCacheDep,
    settings: SettingsDep,
    resources: ResourcesDep,
) -> AgentRunDetail:
    async with resources.session_factory() as session:
        row = await _service(session, ctx, cache, settings, resources).get_run(run_id)
        return AgentRunDetail(
            **_out(row),
            expires_at=row.expires_at,
            events=row.events or [],
            exec_events=row.exec_events or [],
        )
