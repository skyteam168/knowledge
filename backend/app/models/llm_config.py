"""Model providers, their models and the chat routing chosen in the model admin page.

Platform-wide configuration (no org_id), like index generations. Only the chat scenes are
routed from here; embedding stays pinned by the active index generation and rerank by config.
"""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin, utcnow


class ModelKind(StrEnum):
    CHAT = "chat"
    EMBEDDING = "embedding"
    RERANK = "rerank"


class ChatScene(StrEnum):
    CHAT = "chat"
    CHAT_FALLBACK = "chat_fallback"


class LlmProvider(IdMixin, TimestampMixin, Base):
    __tablename__ = "llm_providers"

    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    # Fernet token of {"api_key": ...}; NULL = no key.
    api_key_encrypted: Mapped[str | None] = mapped_column(Text)
    api_key_hint: Mapped[str | None] = mapped_column(String(32))
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    # "env" = imported from the deployment configuration, "manual" = added in the page.
    source: Mapped[str] = mapped_column(String(16), default="manual", nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(String(32))


class LlmModel(IdMixin, TimestampMixin, Base):
    __tablename__ = "llm_models"
    __table_args__ = (UniqueConstraint("provider_id", "name"),)

    provider_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("llm_providers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    # "synced" from GET /models, "manual" when added by hand (e.g. rerank models not listed).
    origin: Mapped[str] = mapped_column(String(16), default="manual", nullable=False)
    # Overrides of the provider address (rerank often lives under another path prefix).
    base_url: Mapped[str | None] = mapped_column(String(512))
    path: Mapped[str | None] = mapped_column(String(128))
    last_check_status: Mapped[str | None] = mapped_column(String(16))
    last_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_check_latency_ms: Mapped[int | None] = mapped_column(Integer)
    last_check_message: Mapped[str | None] = mapped_column(Text)
    detected_dim: Mapped[int | None] = mapped_column(Integer)


class LlmRoute(Base):
    __tablename__ = "llm_routes"

    scene: Mapped[str] = mapped_column(String(32), primary_key=True)
    model_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("llm_models.id", ondelete="RESTRICT"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
    updated_by: Mapped[str | None] = mapped_column(String(32))
