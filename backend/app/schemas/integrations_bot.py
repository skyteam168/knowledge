"""Request/response models for group-bot integrations (stage 1)."""

from typing import Any

from pydantic import BaseModel, Field


class BotAskIn(BaseModel):
    """Local mock / gateway-normalized ask body (provider-specific fields also accepted)."""

    question: str | None = Field(default=None, max_length=4000)
    text: str | None = Field(default=None, max_length=4000)
    content: str | None = Field(default=None, max_length=4000)
    kb_ids: list[str] = Field(default_factory=list, max_length=100)
    # Extra IM fields (MsgType, text:{content}, …) are allowed and ignored here.
    model_config = {"extra": "allow"}


class BotAskOut(BaseModel):
    reply: str
    conversation_id: str | None = None
    message_id: str | None = None
    grounding: str | None = None
    citation_count: int = 0
    trace_id: str | None = None
    provider: str
    raw: dict[str, Any] | None = None
