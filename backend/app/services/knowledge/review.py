"""Periodic document review: interval (document over knowledge base), due date and state."""

from datetime import UTC, datetime, timedelta
from typing import Literal

from app.models import Document, KnowledgeBase

ReviewState = Literal["none", "ok", "due_soon", "overdue"]

REMINDER_NONE, REMINDER_SOON, REMINDER_OVERDUE = 0, 1, 2


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def review_interval(kb: KnowledgeBase, doc: Document) -> int | None:
    """Days between reviews, or None when the document needs no periodic review."""
    days = kb.review_interval_days if doc.review_interval_days is None else doc.review_interval_days
    return days or None


def refresh_due(kb: KnowledgeBase, doc: Document) -> None:
    """Recompute the due date; a new due date starts its reminders afresh."""
    days = review_interval(kb, doc)
    base = doc.reviewed_at or doc.created_at
    due = _aware(base) + timedelta(days=days) if days and base else None
    current = _aware(doc.review_due_at) if doc.review_due_at else None
    if due != current:
        doc.review_due_at = due
        doc.review_reminder = REMINDER_NONE


def mark_reviewed(kb: KnowledgeBase, doc: Document, user_id: str | None, now: datetime) -> None:
    doc.reviewed_at = now
    doc.reviewed_by = user_id
    refresh_due(kb, doc)


def review_state(doc: Document, now: datetime, notice_days: int) -> ReviewState:
    if doc.review_due_at is None:
        return "none"
    due = _aware(doc.review_due_at)
    if due <= now:
        return "overdue"
    return "due_soon" if due <= now + timedelta(days=notice_days) else "ok"


def review_recipient(doc: Document) -> str | None:
    return doc.owner_id or doc.created_by
