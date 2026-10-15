from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OutboxEvent

# Event types consumed by later phases (indexing workers).
DOCUMENT_CHUNKS_READY = "document.chunks_ready"
DOCUMENT_DELETED = "document.deleted"
ACL_CHANGED = "acl.changed"
KO_PUBLISHED = "ko.published"
KO_DEPRECATED = "ko.deprecated"


class OutboxService:
    """Writes integration events inside the caller's business transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def publish(
        self,
        org_id: str,
        aggregate_type: str,
        aggregate_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> OutboxEvent:
        event = OutboxEvent(
            org_id=org_id,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            event_type=event_type,
            payload=payload,
        )
        self.session.add(event)
        await self.session.flush()
        return event
