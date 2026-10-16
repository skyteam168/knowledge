from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import NotFoundError, ValidationAppError
from app.core.storage import ObjectStorage
from app.models import (
    Chunk,
    Conversation,
    GapStatus,
    GapType,
    KnowledgeGap,
    Message,
    MessageFeedback,
    MessageRole,
    MessageStatus,
    QaTrace,
)
from app.models.base import utcnow
from app.repositories.base import paginate
from app.repositories.chat_repo import ChunkRepository, ConversationRepository
from app.repositories.knowledge_repo import (
    DocumentPageAssetRepository,
    DocumentRepository,
    KnowledgeBaseRepository,
)
from app.schemas.chat import (
    CitationOut,
    CitationSourceOut,
    ConversationCreate,
    ConversationDetailOut,
    ConversationOut,
    ConversationUpdate,
    FeedbackIn,
    FeedbackOut,
    KnowledgeGapOut,
    KnowledgeRequestIn,
    KoCitationOut,
    KoSourceRefOut,
    MessageOut,
    SourceDocumentOut,
    SourceSegmentOut,
)
from app.schemas.common import Page
from app.services.authz import AclPermission
from app.services.authz.cache import AuthzCache
from app.services.chat.expansion import overlap_len
from app.services.context import BaseService, RequestContext
from app.services.knowledge.access import RESOURCE_DOCUMENT, KnowledgeAccess
from app.services.knowledge.ko_access import KoAccess

DEFAULT_TITLE = "新对话"
RESOURCE_CONVERSATION = "conversation"
RESOURCE_MESSAGE = "message"
RESOURCE_GAP = "knowledge_gap"
PARENT_LEVEL = 1


def message_out(
    message: Message, feedback: MessageFeedback | None = None, requested: bool = False
) -> MessageOut:
    return MessageOut(
        id=message.id,
        role=message.role,
        content=message.content,
        status=message.status,
        intent=message.intent,
        rewritten_query=message.rewritten_query,
        grounding=message.grounding,
        citations=[CitationOut.model_validate(c) for c in message.citations or []],
        steps=list(message.steps or []),
        trace_id=message.trace_id,
        error=message.error,
        created_at=message.created_at,
        feedback=FeedbackOut.model_validate(feedback) if feedback else None,
        knowledge_requested=requested,
    )


def _single_kb(conv: Conversation) -> str | None:
    kb_ids = list(conv.kb_ids or [])
    return kb_ids[0] if len(kb_ids) == 1 else None


def _conversation_snapshot(conv: Conversation) -> dict[str, Any]:
    return {"title": conv.title, "kb_ids": list(conv.kb_ids or [])}


class ConversationService(BaseService):
    def __init__(
        self,
        session: AsyncSession,
        ctx: RequestContext,
        authz_cache: AuthzCache,
        *,
        storage: ObjectStorage | None = None,
        settings: Settings | None = None,
    ) -> None:
        super().__init__(session, ctx, authz_cache)
        self.storage = storage
        self.settings = settings

    @property
    def repo(self) -> ConversationRepository:
        return ConversationRepository(self.session)

    async def get(self, conversation_id: str) -> Conversation:
        conv = await self.repo.get_owned(self.org_id, self.ctx.user.id, conversation_id)
        if conv is None:
            raise NotFoundError("Conversation not found")
        return conv

    async def list(self, *, page: int, size: int, keyword: str | None) -> Page[ConversationOut]:
        stmt = ConversationRepository.list_stmt(self.org_id, self.ctx.user.id, keyword)
        rows, total = await paginate(self.session, stmt, page, size)
        return Page(
            items=[ConversationOut.model_validate(r) for r in rows],
            total=total,
            page=page,
            size=size,
        )

    async def create(self, data: ConversationCreate) -> ConversationOut:
        conv = Conversation(
            org_id=self.org_id,
            user_id=self.ctx.user.id,
            title=(data.title or "").strip() or DEFAULT_TITLE,
            kb_ids=data.kb_ids,
        )
        self.session.add(conv)
        await self.session.flush()
        await self.audit.record(
            self.audit_ctx,
            "chat.conversation.create",
            RESOURCE_CONVERSATION,
            conv.id,
            None,
            _conversation_snapshot(conv),
        )
        return ConversationOut.model_validate(conv)

    async def detail(self, conversation_id: str) -> ConversationDetailOut:
        conv = await self.get(conversation_id)
        messages = await self.repo.messages(conv.id)
        ids = [m.id for m in messages if m.role == MessageRole.ASSISTANT.value]
        feedback = await self.repo.feedback_for(ids, self.ctx.user.id)
        requested = await self.repo.requested_message_ids(
            self.org_id, ids, GapType.USER_REQUEST.value
        )
        return ConversationDetailOut(
            **ConversationOut.model_validate(conv).model_dump(),
            messages=[message_out(m, feedback.get(m.id), m.id in requested) for m in messages],
        )

    async def update(self, conversation_id: str, data: ConversationUpdate) -> ConversationOut:
        conv = await self.get(conversation_id)
        before = _conversation_snapshot(conv)
        if data.title is not None:
            conv.title = data.title.strip() or conv.title
        if data.kb_ids is not None:
            conv.kb_ids = data.kb_ids
        conv.updated_at = utcnow()
        await self.session.flush()
        await self.audit.record(
            self.audit_ctx,
            "chat.conversation.update",
            RESOURCE_CONVERSATION,
            conv.id,
            before,
            _conversation_snapshot(conv),
        )
        return ConversationOut.model_validate(conv)

    async def delete(self, conversation_id: str) -> None:
        conv = await self.get(conversation_id)
        conv.deleted_at = utcnow()
        await self.session.flush()
        await self.audit.record(
            self.audit_ctx,
            "chat.conversation.delete",
            RESOURCE_CONVERSATION,
            conv.id,
            _conversation_snapshot(conv),
            None,
        )

    # ---- answers -----------------------------------------------------------------------

    async def _answer(self, message_id: str) -> tuple[Message, Conversation]:
        found = await self.repo.owned_message(self.org_id, self.ctx.user.id, message_id)
        if found is None or found[0].role != MessageRole.ASSISTANT.value:
            raise NotFoundError("Message not found")
        return found

    async def feedback(self, message_id: str, data: FeedbackIn) -> FeedbackOut:
        message, conv = await self._answer(message_id)
        if message.status != MessageStatus.DONE.value:
            raise ValidationAppError("Only completed answers can be rated")
        user_id = self.ctx.user.id
        fb = await self.repo.feedback(message.id, user_id)
        before = {"rating": fb.rating, "reasons": fb.reasons, "comment": fb.comment} if fb else None
        if fb is None:
            fb = MessageFeedback(org_id=self.org_id, message_id=message.id, user_id=user_id)
            self.session.add(fb)
        fb.rating = data.rating.value
        # Reasons describe what was wrong; they are meaningless on a thumbs-up.
        fb.reasons = [r.value for r in data.reasons] if data.rating == "down" else []
        fb.comment = (data.comment or "").strip() or None
        fb.updated_at = utcnow()
        await self._sync_feedback_gap(message, conv, fb)
        await self.session.flush()
        await self.audit.record(
            self.audit_ctx,
            "chat.feedback",
            RESOURCE_MESSAGE,
            message.id,
            before,
            {"rating": fb.rating, "reasons": fb.reasons, "comment": fb.comment},
        )
        return FeedbackOut.model_validate(fb)

    async def _sync_feedback_gap(
        self, message: Message, conv: Conversation, fb: MessageFeedback
    ) -> None:
        """A thumbs-down is a gap signal; withdrawing it rejects the still-untouched gap."""
        gap = await self.repo.gap_for_message(
            self.org_id, message.id, GapType.NEGATIVE_FEEDBACK.value
        )
        if fb.rating != "down":
            if gap is not None and gap.status == GapStatus.OPEN.value and not gap.assignee_id:
                gap.status = GapStatus.REJECTED.value
                gap.resolution = {"action": "rejected", "note": "用户撤回差评"}
                gap.resolved_at = utcnow()
            return
        if gap is None:
            question = await self.repo.message_before(message)
            gap = KnowledgeGap(
                org_id=self.org_id,
                gap_type=GapType.NEGATIVE_FEEDBACK.value,
                status=GapStatus.OPEN.value,
                query=question.content if question else (message.rewritten_query or ""),
                rewritten_query=message.rewritten_query,
                user_id=self.ctx.user.id,
                conversation_id=conv.id,
                message_id=message.id,
                trace_id=message.trace_id,
                kb_ids=list(conv.kb_ids or []),
                kb_id=_single_kb(conv),
            )
            self.session.add(gap)
        elif (
            gap.status == GapStatus.REJECTED.value and gap.resolution.get("note") == "用户撤回差评"
        ):
            gap.status = GapStatus.OPEN.value
            gap.resolution = {}
            gap.resolved_at = None
        gap.description = fb.comment
        gap.details = {
            "grounding": message.grounding,
            "reasons": list(fb.reasons or []),
            "citations": len(message.citations or []),
        }

    async def request_knowledge(self, message_id: str, data: KnowledgeRequestIn) -> KnowledgeGapOut:
        message, conv = await self._answer(message_id)
        description = (data.description or "").strip() or None
        gap = await self.repo.gap_for_message(self.org_id, message.id, GapType.USER_REQUEST.value)
        if gap is None:
            question = await self.repo.message_before(message)
            detected = await self.repo.gap_for_message(
                self.org_id, message.id, GapType.NO_EVIDENCE.value
            ) or await self.repo.gap_for_message(
                self.org_id, message.id, GapType.LOW_GROUNDING.value
            )
            gap = KnowledgeGap(
                org_id=self.org_id,
                gap_type=GapType.USER_REQUEST.value,
                status=GapStatus.OPEN.value,
                query=question.content if question else (message.rewritten_query or ""),
                rewritten_query=message.rewritten_query,
                user_id=self.ctx.user.id,
                conversation_id=conv.id,
                message_id=message.id,
                trace_id=message.trace_id,
                kb_ids=list(conv.kb_ids or []),
                kb_id=_single_kb(conv),
                top_score=detected.top_score if detected else None,
                description=description,
                details={
                    "grounding": message.grounding,
                    "related_gap_id": detected.id if detected else None,
                },
            )
            self.session.add(gap)
        elif description:
            gap.description = description
        await self.session.flush()
        await self.audit.record(
            self.audit_ctx,
            "chat.knowledge_request",
            RESOURCE_GAP,
            gap.id,
            None,
            {"message_id": message.id, "query": gap.query, "description": gap.description},
        )
        return KnowledgeGapOut.model_validate(gap)

    async def citation_source(self, message_id: str, n: int) -> CitationSourceOut:
        message, _ = await self._answer(message_id)
        citation = next((c for c in message.citations or [] if c.get("n") == n), None)
        if citation is None:
            raise NotFoundError("Citation not found")
        cited = CitationOut.model_validate(citation)
        if cited.is_ko:
            return await self._ko_citation_source(n, cited)

        # The cited document must still exist and be readable by the caller *now*.
        doc = await DocumentRepository(self.session).get(self.org_id, cited.document_id)
        kb = (
            await KnowledgeBaseRepository(self.session).get(self.org_id, doc.kb_id) if doc else None
        )
        if doc is None or kb is None:
            raise NotFoundError("Document not found")
        await KnowledgeAccess(self.session).require_document(
            self.ctx.user, doc, kb, AclPermission.READ
        )
        await self.audit.record(
            self.audit_ctx,
            "document.view_citation",
            RESOURCE_DOCUMENT,
            doc.id,
            None,
            {"message_id": message.id, "n": n, "chunk_id": cited.chunk_id},
        )

        chunks_repo = ChunkRepository(self.session)
        hits = set(cited.hit_chunk_ids or [cited.chunk_id])
        stored = await chunks_repo.by_ids(self.org_id, cited.chunk_ids or [cited.chunk_id])
        ordered: list[Chunk] = []
        for cid in cited.chunk_ids or [cited.chunk_id]:
            chunk = stored.get(cid)
            if chunk is None or chunk.document_id != doc.id:
                continue
            if chunk.level == PARENT_LEVEL:
                ordered += await chunks_repo.children_of(self.org_id, chunk.id)
            else:
                ordered.append(chunk)

        segments: list[SourceSegmentOut] = []
        previous = ""
        for chunk in ordered:
            text = chunk.content
            cut = overlap_len(previous, text) if previous else 0
            segments.append(
                SourceSegmentOut(chunk_id=chunk.id, content=text[cut:], highlight=chunk.id in hits)
            )
            previous = text
        if not segments:
            # Chunks of the cited version are gone: show the quote stored with the answer.
            segments = [
                SourceSegmentOut(chunk_id=cited.chunk_id, content=cited.quote, highlight=True)
            ]
        image_url, image_mime = await self._citation_image(
            doc.id,
            cited.doc_version or doc.version,
            slide_number=cited.slide_number,
            page_start=cited.page_start,
        )
        return CitationSourceOut(
            n=n,
            document=SourceDocumentOut(
                id=doc.id,
                title=doc.title,
                filename=doc.filename,
                kb_id=kb.id,
                kb_name=kb.name,
                version=doc.version,
            ),
            outdated=cited.doc_version is not None and cited.doc_version != doc.version,
            heading_path=cited.heading_path,
            page_start=cited.page_start,
            page_end=cited.page_end,
            sheet_name=cited.sheet_name,
            slide_number=cited.slide_number,
            image_url=image_url,
            image_mime_type=image_mime,
            anchor_chunk_id=cited.chunk_id,
            quote=cited.quote,
            segments=segments,
        )

    async def _citation_image(
        self,
        document_id: str,
        version: int,
        *,
        slide_number: int | None,
        page_start: int | None,
    ) -> tuple[str | None, str | None]:
        if self.storage is None or self.settings is None:
            return None, None
        asset = await DocumentPageAssetRepository(self.session).find_for_citation(
            document_id,
            version,
            slide_number=slide_number,
            page_start=page_start,
        )
        if asset is None:
            return None, None
        expires = self.settings.presign_expiry_seconds
        url = self.storage.presign_get(
            asset.minio_key,
            expires,
            filename=f"{asset.kind}-{asset.page_index}.png",
            content_type=asset.mime_type,
            attachment=False,
        )
        return url, asset.mime_type

    async def _ko_citation_source(self, n: int, cited: CitationOut) -> CitationSourceOut:
        live = await KoAccess(self.session).live_objects(self.ctx.user, [cited.document_id])
        obj = live.objects.get(cited.document_id)
        if obj is None:
            raise NotFoundError("Knowledge object not found")
        ko, snap, kb = obj.ko, obj.snapshot, obj.kb
        readable = await KnowledgeAccess(self.session).readable_documents(
            self.ctx.user, [s.get("document_id", "") for s in snap.sources]
        )
        sources = [
            KoSourceRefOut(
                document_id=s["document_id"],
                title=readable[s["document_id"]][0].title,
                chunk_id=s.get("chunk_id"),
                heading_path=list(s.get("heading_path") or []),
                quote=s.get("quote"),
            )
            for s in snap.sources
            if s.get("document_id") in readable
        ]
        content = f"问题：{snap.question}\n\n{snap.answer}"
        return CitationSourceOut(
            n=n,
            document=SourceDocumentOut(
                id=ko.id,
                title=snap.title,
                filename="",
                kb_id=kb.id,
                kb_name=kb.name,
                version=snap.version,
            ),
            outdated=cited.doc_version is not None and cited.doc_version != snap.version,
            heading_path=[],
            page_start=None,
            page_end=None,
            anchor_chunk_id=cited.chunk_id,
            quote=cited.quote,
            segments=[SourceSegmentOut(chunk_id=cited.chunk_id, content=content, highlight=True)],
            is_ko=True,
            ko=KoCitationOut(
                id=ko.id,
                ko_type=snap.ko_type,
                question=snap.question,
                variants=list(snap.variants or []),
                answer=snap.answer,
                sources=sources,
                effective_from=snap.effective_from,
                effective_to=snap.effective_to,
            ),
        )

    async def qa_trace(self, trace_id: str) -> QaTrace:
        trace = await self.repo.qa_trace(self.org_id, trace_id)
        if trace is None:
            raise NotFoundError("QA trace not found")
        return trace
