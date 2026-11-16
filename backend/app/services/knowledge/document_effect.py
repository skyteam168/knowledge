"""Whether a document may be used as live retrieval evidence.

Mirrors KO ``in_effect``: published lifecycle + effective window. Draft / review /
retired / archived documents stay readable via document APIs (with ACL) but must not
ground answers or search hits.
"""

from datetime import datetime

from app.models.base import utcnow
from app.models.knowledge import Document, DocumentLifecycle


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=utcnow().tzinfo)


def lifecycle_retrievable(doc: Document) -> bool:
    return doc.lifecycle_status == DocumentLifecycle.PUBLISHED.value


def in_effect(doc: Document, now: datetime | None = None) -> bool:
    """True when the document is published and inside its effective window."""
    if not lifecycle_retrievable(doc):
        return False
    moment = now or utcnow()
    if doc.effective_from is not None and _aware(doc.effective_from) > moment:
        return False
    return doc.effective_to is None or _aware(doc.effective_to) > moment


# External / open-platform export: classifications at or above this need tighter limits.
EXTERNAL_RESTRICTED = frozenset({"confidential", "restricted", "secret"})

# Retrieval / Q&A hydrate: elevated ACL required (not mere read).
RETRIEVAL_REQUIRES_EDIT = frozenset({"restricted"})
RETRIEVAL_REQUIRES_MANAGE = frozenset({"secret"})


def restricts_external_export(classification: str | None) -> bool:
    return (classification or "internal") in EXTERNAL_RESTRICTED


def retrieval_min_acl(classification: str | None) -> str | None:
    """Return required ACL permission name for retrieval, or None if read is enough."""
    value = classification or "internal"
    if value in RETRIEVAL_REQUIRES_MANAGE:
        return "manage"
    if value in RETRIEVAL_REQUIRES_EDIT:
        return "edit"
    return None
