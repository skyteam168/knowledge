"""Open API for external agents (API key auth): knowledge bases, retrieval, chat, MCP."""

import ipaddress
import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from app.api.deps import AuthzCacheDep, DbSessionDep, ResourcesDep, SettingsDep
from app.core.config import Settings
from app.core.exceptions import AppError
from app.core.resources import AppResources
from app.llm.usage import FEATURE_OPEN_API, bind_usage_scope
from app.models import ApiCallLog, ApiScope
from app.retrieval.pipeline import RetrievalPipeline
from app.schemas.open_api import (
    OpenChatIn,
    OpenChatOut,
    OpenKbOut,
    OpenRetrieveIn,
    OpenRetrieveOut,
    OpenWhoAmIOut,
)
from app.services.audit_service import AuditContext
from app.services.authz import AuthzCache
from app.services.context import RequestContext
from app.services.open_api.auth import (
    ApiCaller,
    authenticate,
    build_caller,
    caller_user,
    enforce,
    touch,
)
from app.services.open_api.mcp import PARSE_ERROR, McpServer
from app.services.open_api.open_service import ChatOutcome, OpenApiService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/open", tags=["open-api"])

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def client_ip(request: Request, settings: Settings) -> str | None:
    peer = request.client.host if request.client else None
    forwarded = request.headers.get("x-forwarded-for")
    if not forwarded or not _trusted(peer, settings.open_api_trusted_proxies):
        return peer
    hops = [h.strip() for h in forwarded.split(",") if h.strip()]
    for hop in reversed(hops):
        if not _trusted(hop, settings.open_api_trusted_proxies):
            return hop
    return hops[0] if hops else peer


def _trusted(ip: str | None, proxies: list[str]) -> bool:
    if not ip or not proxies:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for entry in proxies:
        try:
            if addr in ipaddress.ip_network(entry, strict=False):
                return True
        except ValueError:
            continue
    return False


def _secret(authorization: str | None, x_api_key: str | None) -> str | None:
    if x_api_key:
        return x_api_key.strip()
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


def call_entry(
    *,
    org_id: str,
    client_id: str,
    key_id: str | None,
    endpoint: str,
    status_code: int,
    started: float,
    ip: str | None,
    error_code: str | None = None,
    query: str | None = None,
    kb_ids: list[str] | None = None,
    result_count: int = 0,
    document_ids: list[str] | None = None,
    trace_id: str | None = None,
    settings: Settings,
) -> ApiCallLog:
    return ApiCallLog(
        org_id=org_id,
        client_id=client_id,
        key_id=key_id,
        endpoint=endpoint,
        status_code=status_code,
        error_code=error_code,
        latency_ms=int((time.perf_counter() - started) * 1000),
        ip=ip,
        query=(query or None) and query[: settings.open_api_log_query_chars],
        kb_ids=kb_ids or [],
        result_count=result_count,
        document_ids=document_ids or [],
        trace_id=trace_id,
    )


async def call_log_sink(resources: ResourcesDep) -> AsyncIterator[list[ApiCallLog]]:
    """Request-scoped: entries are written in their own transaction after the response (and any
    stream) has finished, so calls are logged even when the request's work is rolled back."""
    pending: list[ApiCallLog] = []
    try:
        yield pending
    finally:
        if pending:
            try:
                async with resources.session_factory() as session:
                    session.add_all(pending)
                    await session.commit()
            except Exception:
                logger.exception("open_api_call_log_failed")


CallLogSinkDep = Annotated[list[ApiCallLog], Depends(call_log_sink)]


async def get_api_caller(
    request: Request,
    settings: SettingsDep,
    resources: ResourcesDep,
    sink: CallLogSinkDep,
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header()] = None,
) -> ApiCaller:
    started = time.perf_counter()
    ip = client_ip(request, settings)
    async with resources.session_factory() as session:
        key, client = await authenticate(session, settings, _secret(authorization, x_api_key))
        try:
            await enforce(client, ip, resources.cache, settings)
            user = await caller_user(session, client)
        except AppError as exc:
            sink.append(
                call_entry(
                    org_id=client.org_id,
                    client_id=client.id,
                    key_id=key.id,
                    endpoint=request.url.path.rsplit("/", 1)[-1],
                    status_code=exc.status_code,
                    error_code=exc.code,
                    started=started,
                    ip=ip,
                    settings=settings,
                )
            )
            raise
        if touch(key, client, ip):
            await session.commit()
        caller = build_caller(key.id, client, user, settings)
    bind_usage_scope(org_id=caller.org_id, user_id=caller.user.id, feature=FEATURE_OPEN_API)
    request.state.current_user = caller.user
    request.state.api_ip = ip
    return caller


CallerDep = Annotated[ApiCaller, Depends(get_api_caller)]


def _context(request: Request, caller: ApiCaller, ip: str | None) -> RequestContext:
    state: dict[str, Any] = request.scope.setdefault("state", {})
    return RequestContext(
        user=caller.user,
        audit=AuditContext(
            org_id=caller.org_id,
            actor_id=caller.user.id,
            actor_name=caller.user.username,
            ip=ip,
            user_agent=request.headers.get("user-agent"),
            trace_id=getattr(request.state, "trace_id", None),
            method=request.method,
            path=request.url.path,
            request_state=state,
        ),
    )


def _service(
    session: Any,
    request: Request,
    caller: ApiCaller,
    cache: AuthzCache,
    resources: AppResources,
    settings: Settings,
) -> OpenApiService:
    return OpenApiService(
        session,
        _context(request, caller, getattr(request.state, "api_ip", None)),
        cache,
        caller=caller,
        pipeline=RetrievalPipeline.build(
            resources.indexing.backends, resources.llm, resources.cache
        ),
        gateway=resources.llm,
        settings=settings,
        storage=resources.storage,
    )


class _Call:
    def __init__(
        self,
        request: Request,
        caller: ApiCaller,
        sink: list[ApiCallLog],
        settings: Settings,
        endpoint: str,
    ) -> None:
        self.request = request
        self.caller = caller
        self.sink = sink
        self.settings = settings
        self.endpoint = endpoint
        self.started = time.perf_counter()

    async def log(self, status_code: int, **fields: Any) -> None:
        self.sink.append(
            call_entry(
                org_id=self.caller.org_id,
                client_id=self.caller.client_id,
                key_id=self.caller.key_id,
                endpoint=self.endpoint,
                status_code=status_code,
                started=self.started,
                ip=getattr(self.request.state, "api_ip", None),
                settings=self.settings,
                **fields,
            )
        )

    async def fail(self, exc: Exception, **fields: Any) -> None:
        if isinstance(exc, AppError):
            await self.log(exc.status_code, error_code=exc.code, **fields)
        else:
            await self.log(500, error_code="INTERNAL_ERROR", **fields)


@router.get("/whoami", response_model=OpenWhoAmIOut)
async def whoami(
    request: Request,
    caller: CallerDep,
    sink: CallLogSinkDep,
    session: DbSessionDep,
    cache: AuthzCacheDep,
    resources: ResourcesDep,
    settings: SettingsDep,
) -> OpenWhoAmIOut:
    call = _Call(request, caller, sink, settings, "whoami")
    kbs = await _service(session, request, caller, cache, resources, settings).knowledge_bases()
    await call.log(200, result_count=len(kbs))
    return OpenWhoAmIOut(
        client_id=caller.client_id,
        name=caller.name,
        scopes=sorted(caller.scopes),
        kbs=kbs,
        rate_limit_per_minute=caller.rate_limit_per_minute,
        daily_quota=caller.daily_quota,
    )


@router.get("/knowledge-bases", response_model=list[OpenKbOut])
async def knowledge_bases(
    request: Request,
    caller: CallerDep,
    sink: CallLogSinkDep,
    session: DbSessionDep,
    cache: AuthzCacheDep,
    resources: ResourcesDep,
    settings: SettingsDep,
) -> list[OpenKbOut]:
    call = _Call(request, caller, sink, settings, "knowledge-bases")
    kbs = await _service(session, request, caller, cache, resources, settings).knowledge_bases()
    await call.log(200, result_count=len(kbs))
    return kbs


@router.post("/retrieve", response_model=OpenRetrieveOut)
async def retrieve(
    data: OpenRetrieveIn,
    request: Request,
    caller: CallerDep,
    sink: CallLogSinkDep,
    session: DbSessionDep,
    cache: AuthzCacheDep,
    resources: ResourcesDep,
    settings: SettingsDep,
) -> OpenRetrieveOut:
    call = _Call(request, caller, sink, settings, "retrieve")
    try:
        caller.require_scope(ApiScope.RETRIEVE)
        out = await _service(session, request, caller, cache, resources, settings).retrieve(data)
    except Exception as exc:
        await call.fail(exc, query=data.query, kb_ids=data.kb_ids)
        raise
    await call.log(
        200,
        query=data.query,
        kb_ids=out.kb_ids,
        result_count=out.total,
        document_ids=list(dict.fromkeys(i.document_id for i in out.items)),
        trace_id=out.trace_id,
    )
    return out


@router.post(
    "/chat",
    response_model=OpenChatOut,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def chat(
    data: OpenChatIn,
    request: Request,
    caller: CallerDep,
    sink: CallLogSinkDep,
    session: DbSessionDep,
    cache: AuthzCacheDep,
    resources: ResourcesDep,
    settings: SettingsDep,
) -> Response:
    """`stream=false`: JSON answer. `stream=true`: SSE `meta`, `step`*, `token`*, `citations`,
    `done` (or `error`)."""
    call = _Call(request, caller, sink, settings, "chat")
    service = _service(session, request, caller, cache, resources, settings)
    try:
        caller.require_scope(ApiScope.CHAT)
        if not data.stream:
            out, outcome = await service.chat(data)
            await call.log(
                200,
                query=data.question,
                kb_ids=data.kb_ids,
                result_count=len(out.citations),
                document_ids=outcome.document_ids,
                trace_id=out.trace_id,
            )
            return JSONResponse(out.model_dump(mode="json"))
        conversation_id, ask = await service.prepare_chat(data)
    except Exception as exc:
        await call.fail(exc, query=data.question, kb_ids=data.kb_ids)
        raise

    async def events() -> AsyncIterator[str]:
        outcome = ChatOutcome()
        async with resources.session_factory() as stream_session:
            streamer = _service(stream_session, request, caller, cache, resources, settings)
            try:
                async for event in streamer.chat_events(conversation_id, ask, outcome):
                    yield event.encode()
            finally:
                await call.log(
                    502 if outcome.error else 200,
                    error_code=str(outcome.error.get("code")) if outcome.error else None,
                    query=data.question,
                    kb_ids=ask.kb_ids,
                    result_count=len(outcome.citations),
                    document_ids=outcome.document_ids,
                    trace_id=outcome.trace_id,
                )

    return StreamingResponse(events(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.post("/mcp")
async def mcp(
    request: Request,
    caller: CallerDep,
    sink: CallLogSinkDep,
    session: DbSessionDep,
    cache: AuthzCacheDep,
    resources: ResourcesDep,
    settings: SettingsDep,
) -> Response:
    """MCP Streamable HTTP endpoint (JSON responses, no server-initiated stream)."""
    caller.require_scope(ApiScope.MCP)
    try:
        payload = json.loads(await request.body())
    except (ValueError, UnicodeDecodeError):
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": PARSE_ERROR, "message": "Parse error"},
            },
            status_code=400,
        )
    service = _service(session, request, caller, cache, resources, settings)

    async def on_tool(name: str, fields: dict[str, Any]) -> None:
        call = _Call(request, caller, sink, settings, f"mcp:{name}")
        status_code = int(fields.pop("status_code", 200))
        await call.log(status_code, **fields)

    result = await McpServer(service, on_tool).handle(payload)
    if result is None:
        return Response(status_code=202)
    return JSONResponse(result)


@router.get("/mcp")
async def mcp_stream(caller: CallerDep) -> Response:
    # No server-initiated messages: per the Streamable HTTP spec, GET may return 405.
    return Response(status_code=405, headers={"Allow": "POST"})
