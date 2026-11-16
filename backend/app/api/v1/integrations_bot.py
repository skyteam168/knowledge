"""WeCom / DingTalk group-bot callbacks → Open API chat → plain-text reply.

Stage 1: shared callback token + configured Open API key; no enterprise crypto.
Local mock bodies `{question}` work on both routes; WeCom GET echo is stubbed.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Header, Query, Request, Response
from fastapi.responses import PlainTextResponse

from app.api.deps import AuthzCacheDep, DbSessionDep, ResourcesDep, SettingsDep
from app.api.v1 import open_api as open_api_routes
from app.core.config import Settings
from app.core.exceptions import UnauthorizedError, ValidationAppError
from app.core.resources import AppResources
from app.llm.usage import FEATURE_OPEN_API, bind_usage_scope
from app.models import ApiScope
from app.schemas.integrations_bot import BotAskOut
from app.schemas.open_api import OpenChatIn
from app.services.authz import AuthzCache
from app.services.integrations.bot_qa import (
    format_bot_reply,
    open_chat_in,
    parse_dingtalk_question,
    parse_wecom_question,
)
from app.services.open_api.auth import (
    ApiCaller,
    authenticate,
    build_caller,
    caller_user,
    enforce,
    touch,
)
from app.services.open_api.open_service import OpenApiService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations", tags=["integrations-bot"])


def _require_bot(settings: Settings) -> None:
    if not settings.integrations_bot_enabled:
        raise ValidationAppError(
            "Group bot integrations are disabled",
            code="BOT_DISABLED",
            status_code=404,
        )
    if not (settings.integrations_bot_token or "").strip():
        raise ValidationAppError(
            "INTEGRATIONS_BOT_TOKEN is not configured",
            code="BOT_NOT_CONFIGURED",
            status_code=503,
        )
    if not (settings.integrations_bot_open_api_key or "").strip():
        raise ValidationAppError(
            "INTEGRATIONS_BOT_OPEN_API_KEY is not configured",
            code="BOT_NOT_CONFIGURED",
            status_code=503,
        )


def _check_token(
    settings: Settings,
    *,
    x_bot_token: str | None,
    authorization: str | None,
    query_token: str | None = None,
) -> None:
    expected = settings.integrations_bot_token.strip()
    candidates = [
        (x_bot_token or "").strip(),
        (query_token or "").strip(),
    ]
    if authorization and authorization.lower().startswith("bearer "):
        candidates.append(authorization[7:].strip())
    if not any(c and c == expected for c in candidates):
        raise UnauthorizedError("Invalid bot token", code="INVALID_BOT_TOKEN")


async def _bot_caller(
    request: Request,
    session: Any,
    settings: Settings,
    resources: AppResources,
) -> ApiCaller:
    ip = open_api_routes.client_ip(request, settings)
    key, client = await authenticate(session, settings, settings.integrations_bot_open_api_key)
    await enforce(client, ip, resources.cache, settings)
    user = await caller_user(session, client)
    if touch(key, client, ip):
        await session.commit()
    caller = build_caller(key.id, client, user, settings)
    bind_usage_scope(org_id=caller.org_id, user_id=caller.user.id, feature=FEATURE_OPEN_API)
    request.state.current_user = caller.user
    request.state.api_ip = ip
    return caller


def _service(
    session: Any,
    request: Request,
    caller: ApiCaller,
    cache: AuthzCache,
    resources: AppResources,
    settings: Settings,
) -> OpenApiService:
    return open_api_routes._service(session, request, caller, cache, resources, settings)


async def _answer(
    *,
    provider: str,
    question: str,
    kb_ids: list[str],
    request: Request,
    session: Any,
    cache: AuthzCache,
    resources: AppResources,
    settings: Settings,
) -> BotAskOut:
    caller = await _bot_caller(request, session, settings, resources)
    caller.require_scope(ApiScope.CHAT)
    data: OpenChatIn = open_chat_in(question, kb_ids)
    out, _outcome = await _service(session, request, caller, cache, resources, settings).chat(data)
    reply = format_bot_reply(
        out.answer,
        out.citations,
        max_answer_chars=settings.integrations_bot_max_answer_chars,
        max_citations=settings.integrations_bot_max_citations,
    )
    return BotAskOut(
        reply=reply,
        conversation_id=out.conversation_id,
        message_id=out.message_id,
        grounding=out.grounding,
        citation_count=len(out.citations),
        trace_id=out.trace_id,
        provider=provider,
    )


def _kb_ids(payload: dict[str, Any]) -> list[str]:
    raw = payload.get("kb_ids") or []
    if not isinstance(raw, list):
        return []
    return [str(x) for x in raw if x]


@router.get("/wecom/bot")
async def wecom_bot_verify(
    settings: SettingsDep,
    msg_signature: str | None = Query(default=None, alias="msg_signature"),
    timestamp: str | None = Query(default=None),
    nonce: str | None = Query(default=None),
    echostr: str | None = Query(default=None),
    token: str | None = Query(default=None),
    x_bot_token: str | None = Header(default=None, alias="X-Bot-Token"),
    authorization: str | None = Header(default=None),
) -> Response:
    """URL verification stub: echo `echostr` when the bot token matches.

    Real WeCom crypto (msg_signature decrypt) is out of scope for stage 1;
    local/mock gateways can pass `token` or `X-Bot-Token` instead.
    """
    del msg_signature, timestamp, nonce  # reserved for future crypto
    _require_bot(settings)
    _check_token(settings, x_bot_token=x_bot_token, authorization=authorization, query_token=token)
    if echostr is None:
        raise ValidationAppError("echostr is required for WeCom URL verification")
    return PlainTextResponse(echostr)


@router.post("/wecom/bot", response_model=BotAskOut)
async def wecom_bot_ask(
    payload: dict[str, Any],
    request: Request,
    session: DbSessionDep,
    cache: AuthzCacheDep,
    resources: ResourcesDep,
    settings: SettingsDep,
    x_bot_token: str | None = Header(default=None, alias="X-Bot-Token"),
    authorization: str | None = Header(default=None),
) -> BotAskOut:
    _require_bot(settings)
    _check_token(settings, x_bot_token=x_bot_token, authorization=authorization)
    question = parse_wecom_question(payload)
    if not question:
        raise ValidationAppError("No text question in WeCom payload", code="BOT_EMPTY_QUESTION")
    return await _answer(
        provider="wecom",
        question=question,
        kb_ids=_kb_ids(payload),
        request=request,
        session=session,
        cache=cache,
        resources=resources,
        settings=settings,
    )


@router.post("/dingtalk/bot", response_model=BotAskOut)
async def dingtalk_bot_ask(
    payload: dict[str, Any],
    request: Request,
    session: DbSessionDep,
    cache: AuthzCacheDep,
    resources: ResourcesDep,
    settings: SettingsDep,
    x_bot_token: str | None = Header(default=None, alias="X-Bot-Token"),
    authorization: str | None = Header(default=None),
) -> BotAskOut:
    _require_bot(settings)
    _check_token(settings, x_bot_token=x_bot_token, authorization=authorization)
    question = parse_dingtalk_question(payload)
    if not question:
        raise ValidationAppError("No text question in DingTalk payload", code="BOT_EMPTY_QUESTION")
    return await _answer(
        provider="dingtalk",
        question=question,
        kb_ids=_kb_ids(payload),
        request=request,
        session=session,
        cache=cache,
        resources=resources,
        settings=settings,
    )
