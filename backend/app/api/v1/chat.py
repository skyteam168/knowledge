from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response
from fastapi.responses import StreamingResponse

from app.api.deps import (
    AuthzCacheDep,
    RequestContextDep,
    ResourcesDep,
    SettingsDep,
    get_conversation_service,
    require_permission,
)
from app.retrieval.pipeline import RetrievalPipeline
from app.schemas.chat import (
    AskIn,
    CitationSourceOut,
    ConversationCreate,
    ConversationDetailOut,
    ConversationOut,
    ConversationUpdate,
    FeedbackIn,
    FeedbackOut,
    KnowledgeGapOut,
    KnowledgeRequestIn,
)
from app.schemas.common import Page
from app.services.chat.answer_service import AnswerService
from app.services.chat.conversation_service import ConversationService
from app.services.chat.ko_source import PublishedKnowledgeObjects

router = APIRouter(
    prefix="/chat",
    tags=["chat"],
    dependencies=[Depends(require_permission("chat:use"))],
)

ServiceDep = Annotated[ConversationService, Depends(get_conversation_service)]

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


@router.get("/conversations", response_model=Page[ConversationOut])
async def list_conversations(
    service: ServiceDep,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 30,
    keyword: Annotated[str | None, Query(max_length=100)] = None,
) -> Page[ConversationOut]:
    return await service.list(page=page, size=size, keyword=keyword)


@router.post("/conversations", response_model=ConversationOut, status_code=201)
async def create_conversation(data: ConversationCreate, service: ServiceDep) -> ConversationOut:
    return await service.create(data)


@router.get("/conversations/{conversation_id}", response_model=ConversationDetailOut)
async def get_conversation(conversation_id: str, service: ServiceDep) -> ConversationDetailOut:
    return await service.detail(conversation_id)


@router.put("/conversations/{conversation_id}", response_model=ConversationOut)
async def update_conversation(
    conversation_id: str, data: ConversationUpdate, service: ServiceDep
) -> ConversationOut:
    return await service.update(conversation_id, data)


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: str, service: ServiceDep) -> Response:
    await service.delete(conversation_id)
    return Response(status_code=204)


@router.post(
    "/conversations/{conversation_id}/messages",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def ask(
    conversation_id: str,
    data: AskIn,
    service: ServiceDep,
    ctx: RequestContextDep,
    cache: AuthzCacheDep,
    resources: ResourcesDep,
    settings: SettingsDep,
) -> StreamingResponse:
    """Server-sent events: `meta`, `step`*, `token`*, `citations`, `done` (or `error`)."""
    # Fail with a regular JSON error before the stream starts.
    await service.get(conversation_id)

    async def events() -> AsyncIterator[str]:
        # The request-scoped session is closed before streaming; the stream owns its own.
        async with resources.session_factory() as session:
            answer = AnswerService(
                session,
                ctx,
                cache,
                pipeline=RetrievalPipeline.build(
                    resources.indexing.backends, resources.llm, resources.cache
                ),
                gateway=resources.llm,
                settings=settings,
                ko_source=PublishedKnowledgeObjects(
                    session, ctx.user, settings.chat_expand_ko_limit
                ),
                storage=resources.storage,
            )
            async for event in answer.stream(conversation_id, data):
                yield event.encode()

    return StreamingResponse(events(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.post("/messages/{message_id}/feedback", response_model=FeedbackOut)
async def feedback(message_id: str, data: FeedbackIn, service: ServiceDep) -> FeedbackOut:
    return await service.feedback(message_id, data)


@router.post(
    "/messages/{message_id}/knowledge-request", response_model=KnowledgeGapOut, status_code=201
)
async def request_knowledge(
    message_id: str, data: KnowledgeRequestIn, service: ServiceDep
) -> KnowledgeGapOut:
    return await service.request_knowledge(message_id, data)


@router.get("/messages/{message_id}/citations/{n}", response_model=CitationSourceOut)
async def citation_source(
    message_id: str, n: Annotated[int, Path(ge=1)], service: ServiceDep
) -> CitationSourceOut:
    return await service.citation_source(message_id, n)
