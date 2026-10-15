"""What external agents can do: list granted knowledge bases, retrieve passages, ask questions.

Every call runs as the client's service user, so ACL pre-filtering, the PG re-check, traces
and audit logs behave as for a person; the client's granted knowledge bases are an extra
hard bound (SearchParams.allowed_kb_ids / AnswerService.allowed_kb_ids).
"""

import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import AppError, NotFoundError
from app.llm import LLMGateway
from app.models import Conversation, KnowledgeBase
from app.repositories.chat_repo import ConversationRepository
from app.retrieval.pipeline import RetrievalPipeline
from app.schemas.chat import AskIn
from app.schemas.open_api import (
    OpenChatIn,
    OpenChatOut,
    OpenChunkOut,
    OpenKbOut,
    OpenRetrieveIn,
    OpenRetrieveOut,
)
from app.services.authz import AuthzCache
from app.services.chat.answer_service import AnswerService, ChatEvent
from app.services.chat.conversation_service import DEFAULT_TITLE, RESOURCE_CONVERSATION
from app.services.chat.ko_source import PublishedKnowledgeObjects
from app.services.context import BaseService, RequestContext
from app.services.knowledge.access import KnowledgeAccess
from app.services.open_api.auth import ApiCaller
from app.services.search.search_service import SearchParams, SearchService
from app.services.security.pii import PiiMasker

RESOURCE_API_CLIENT = "api_client"
TITLE_CHARS = 30


class OpenChatFailedError(AppError):
    status_code = 502
    code = "CHAT_FAILED"
    message = "Answer generation failed"


@dataclass
class ChatOutcome:
    """Collected while streaming, for call logs and the non-streaming response."""

    conversation_id: str = ""
    message_id: str = ""
    answer: str = ""
    grounding: str | None = None
    citations: list[dict[str, Any]] = field(default_factory=list)
    steps: dict[str, dict[str, Any]] = field(default_factory=dict)
    trace_id: str | None = None
    error: dict[str, Any] | None = None
    tokens: list[str] = field(default_factory=list)

    def feed(self, event: ChatEvent) -> None:
        data = event.data
        if event.type == "meta":
            self.conversation_id = str(data.get("conversation_id") or "")
            self.message_id = str(data.get("message_id") or "")
            self.trace_id = data.get("trace_id")
        elif event.type == "step":
            self.steps[str(data["step"])] = dict(data)
        elif event.type == "token":
            self.tokens.append(str(data.get("text") or ""))
        elif event.type == "citations":
            self.citations = list(data.get("citations") or [])
        elif event.type == "done":
            self.answer = str(data.get("answer") or "".join(self.tokens))
            self.grounding = data.get("grounding")
            self.trace_id = data.get("trace_id") or self.trace_id
        elif event.type == "error":
            self.error = dict(data)

    @property
    def document_ids(self) -> list[str]:
        return list(dict.fromkeys(str(c.get("document_id")) for c in self.citations))


class OpenApiService(BaseService):
    def __init__(
        self,
        session: AsyncSession,
        ctx: RequestContext,
        authz_cache: AuthzCache,
        *,
        caller: ApiCaller,
        pipeline: RetrievalPipeline,
        gateway: LLMGateway,
        settings: Settings,
    ) -> None:
        super().__init__(session, ctx, authz_cache)
        self.caller = caller
        self.pipeline = pipeline
        self.gateway = gateway
        self.settings = settings

    # ---- knowledge bases ---------------------------------------------------------------

    async def knowledge_bases(self) -> list[OpenKbOut]:
        if not self.caller.kb_ids:
            return []
        stmt = (
            select(KnowledgeBase)
            .where(
                KnowledgeBase.org_id == self.org_id,
                KnowledgeBase.deleted_at.is_(None),
                KnowledgeBase.id.in_(sorted(self.caller.kb_ids)),
                KnowledgeAccess(self.session).readable_kb_clause(self.ctx.user),
            )
            .order_by(KnowledgeBase.name)
        )
        kbs = (await self.session.execute(stmt)).scalars()
        return [OpenKbOut(id=kb.id, name=kb.name, description=kb.description) for kb in kbs]

    # ---- retrieval ---------------------------------------------------------------------

    async def retrieve(self, data: OpenRetrieveIn, *, audit: bool = True) -> OpenRetrieveOut:
        started = time.perf_counter()
        kb_ids = self.caller.resolve_kbs(data.kb_ids)
        search = SearchService(
            self.session, self.ctx, self.authz_cache, pipeline=self.pipeline, settings=self.settings
        )
        run = await search.execute(
            SearchParams(
                q=data.query,
                kb_ids=tuple(kb_ids),
                top_k=min(data.top_k, self.settings.open_api_max_top_k),
                allowed_kb_ids=self.caller.kb_ids,
            )
        )
        limit = self.settings.open_api_content_max_chars
        mask: Callable[[str], str] = (
            PiiMasker(self.settings.pii_types).mask
            if self.settings.pii_mask_on_output
            else (lambda s: s)
        )
        items = [
            OpenChunkOut(
                rank=r.rank,
                chunk_id=r.passage.chunk_id,
                document_id=r.passage.document.id,
                title=r.passage.document.title,
                kb_id=r.passage.document.kb_id,
                kb_name=r.passage.document.kb_name,
                heading_path=list(r.passage.heading_path),
                content=mask(r.passage.content[:limit]),
                score=r.rerank_score,
                page_start=r.passage.page_start,
                page_end=r.passage.page_end,
                is_ko=r.passage.is_ko,
            )
            for r in (run.outcome.results if run.outcome else [])
            if r.passage.document.kb_id in self.caller.kb_ids
        ]
        if audit:
            await self.audit.record(
                self.audit_ctx,
                "openapi.retrieve",
                RESOURCE_API_CLIENT,
                self.caller.client_id,
                None,
                {
                    "query": data.query[: self.settings.open_api_log_query_chars],
                    "kb_ids": kb_ids,
                    "document_ids": list(dict.fromkeys(i.document_id for i in items)),
                    "retrieval_trace_id": run.trace.id,
                },
            )
        return OpenRetrieveOut(
            query=data.query,
            kb_ids=kb_ids,
            items=items,
            total=len(items),
            trace_id=run.trace.id,
            took_ms=round((time.perf_counter() - started) * 1000, 2),
        )

    # ---- question answering ------------------------------------------------------------

    async def prepare_chat(self, data: OpenChatIn) -> tuple[str, AskIn]:
        """Validates scope and conversation ownership before any streaming starts."""
        kb_ids = self.caller.resolve_kbs(data.kb_ids)
        repo = ConversationRepository(self.session)
        if data.conversation_id:
            conv = await repo.get_owned(self.org_id, self.ctx.user.id, data.conversation_id)
            if conv is None:
                raise NotFoundError("Conversation not found")
        else:
            conv = Conversation(
                org_id=self.org_id,
                user_id=self.ctx.user.id,
                title=data.question[:TITLE_CHARS] or DEFAULT_TITLE,
                kb_ids=kb_ids,
            )
            self.session.add(conv)
            await self.session.flush()
            await self.audit.record(
                self.audit_ctx,
                "openapi.conversation.create",
                RESOURCE_CONVERSATION,
                conv.id,
                None,
                {"client_id": self.caller.client_id, "kb_ids": kb_ids},
            )
        conversation_id = conv.id
        await self.session.commit()
        return conversation_id, AskIn(content=data.question, kb_ids=kb_ids)

    async def chat_events(
        self, conversation_id: str, ask: AskIn, outcome: ChatOutcome
    ) -> AsyncIterator[ChatEvent]:
        answer = AnswerService(
            self.session,
            self.ctx,
            self.authz_cache,
            pipeline=self.pipeline,
            gateway=self.gateway,
            settings=self.settings,
            ko_source=PublishedKnowledgeObjects(
                self.session, self.ctx.user, self.settings.chat_expand_ko_limit
            ),
            allowed_kb_ids=self.caller.kb_ids,
        )
        async for event in answer.stream(conversation_id, ask):
            outcome.feed(event)
            yield event

    async def chat(self, data: OpenChatIn) -> tuple[OpenChatOut, ChatOutcome]:
        conversation_id, ask = await self.prepare_chat(data)
        outcome = ChatOutcome()
        async for _ in self.chat_events(conversation_id, ask, outcome):
            pass
        if outcome.error is not None:
            raise OpenChatFailedError(
                str(outcome.error.get("message") or OpenChatFailedError.message),
                detail={"code": outcome.error.get("code"), "trace_id": outcome.trace_id},
            )
        return (
            OpenChatOut(
                conversation_id=outcome.conversation_id or conversation_id,
                message_id=outcome.message_id,
                answer=outcome.answer,
                grounding=outcome.grounding,
                citations=outcome.citations,
                steps=list(outcome.steps.values()),
                trace_id=outcome.trace_id,
            ),
            outcome,
        )
