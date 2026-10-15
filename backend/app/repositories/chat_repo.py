from collections.abc import Sequence

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Chunk,
    Conversation,
    KnowledgeGap,
    Message,
    MessageFeedback,
    MessageStatus,
    QaTrace,
)
from app.repositories.indexing_repo import INDEXED_CHUNK_LEVEL


class ConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def list_stmt(org_id: str, user_id: str, keyword: str | None = None) -> Select[Conversation]:
        stmt = select(Conversation).where(
            Conversation.org_id == org_id,
            Conversation.user_id == user_id,
            Conversation.deleted_at.is_(None),
        )
        if keyword:
            stmt = stmt.where(Conversation.title.ilike(f"%{keyword.strip()}%"))
        return stmt.order_by(Conversation.updated_at.desc(), Conversation.id)

    async def get_owned(
        self, org_id: str, user_id: str, conversation_id: str
    ) -> Conversation | None:
        stmt = select(Conversation).where(
            Conversation.org_id == org_id,
            Conversation.user_id == user_id,
            Conversation.id == conversation_id,
            Conversation.deleted_at.is_(None),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def messages(self, conversation_id: str) -> list[Message]:
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at, Message.id)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def recent_finished(self, conversation_id: str, limit: int) -> list[Message]:
        """The latest `limit` completed messages, oldest first."""
        if limit <= 0:
            return []
        stmt = (
            select(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.status == MessageStatus.DONE.value,
            )
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(limit)
        )
        return list(reversed(list((await self.session.execute(stmt)).scalars())))

    async def owned_message(
        self, org_id: str, user_id: str, message_id: str
    ) -> tuple[Message, Conversation] | None:
        stmt = (
            select(Message, Conversation)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Message.org_id == org_id,
                Message.id == message_id,
                Conversation.user_id == user_id,
                Conversation.deleted_at.is_(None),
            )
        )
        row = (await self.session.execute(stmt)).first()
        return (row[0], row[1]) if row else None

    async def message_before(self, message: Message) -> Message | None:
        """The message preceding `message` in its conversation (the question of an answer)."""
        stmt = (
            select(Message)
            .where(
                Message.conversation_id == message.conversation_id,
                Message.created_at <= message.created_at,
                Message.id != message.id,
            )
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def feedback(self, message_id: str, user_id: str) -> MessageFeedback | None:
        stmt = select(MessageFeedback).where(
            MessageFeedback.message_id == message_id, MessageFeedback.user_id == user_id
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def feedback_for(
        self, message_ids: Sequence[str], user_id: str
    ) -> dict[str, MessageFeedback]:
        if not message_ids:
            return {}
        stmt = select(MessageFeedback).where(
            MessageFeedback.message_id.in_(list(message_ids)),
            MessageFeedback.user_id == user_id,
        )
        return {f.message_id: f for f in (await self.session.execute(stmt)).scalars()}

    async def gap_for_message(
        self, org_id: str, message_id: str, gap_type: str
    ) -> KnowledgeGap | None:
        stmt = select(KnowledgeGap).where(
            KnowledgeGap.org_id == org_id,
            KnowledgeGap.message_id == message_id,
            KnowledgeGap.gap_type == gap_type,
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def requested_message_ids(
        self, org_id: str, message_ids: Sequence[str], gap_type: str
    ) -> set[str]:
        if not message_ids:
            return set()
        stmt = select(KnowledgeGap.message_id).where(
            KnowledgeGap.org_id == org_id,
            KnowledgeGap.message_id.in_(list(message_ids)),
            KnowledgeGap.gap_type == gap_type,
        )
        return {m for m in (await self.session.execute(stmt)).scalars() if m}

    async def qa_trace(self, org_id: str, trace_id: str) -> QaTrace | None:
        stmt = select(QaTrace).where(QaTrace.org_id == org_id, QaTrace.id == trace_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()


class ChunkRepository:
    """Chunk lookups used to expand retrieval hits into answer context."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def by_ids(self, org_id: str, chunk_ids: Sequence[str]) -> dict[str, Chunk]:
        if not chunk_ids:
            return {}
        stmt = select(Chunk).where(Chunk.org_id == org_id, Chunk.id.in_(list(set(chunk_ids))))
        return {c.id: c for c in (await self.session.execute(stmt)).scalars()}

    async def children_between(
        self, org_id: str, document_id: str, version: int, seq_from: int, seq_to: int
    ) -> list[Chunk]:
        stmt = (
            select(Chunk)
            .where(
                Chunk.org_id == org_id,
                Chunk.document_id == document_id,
                Chunk.document_version == version,
                Chunk.level == INDEXED_CHUNK_LEVEL,
                Chunk.seq >= seq_from,
                Chunk.seq <= seq_to,
            )
            .order_by(Chunk.seq)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def children_of(self, org_id: str, parent_id: str) -> list[Chunk]:
        stmt = (
            select(Chunk)
            .where(
                Chunk.org_id == org_id,
                Chunk.parent_id == parent_id,
                Chunk.level == INDEXED_CHUNK_LEVEL,
            )
            .order_by(Chunk.seq)
        )
        return list((await self.session.execute(stmt)).scalars())
