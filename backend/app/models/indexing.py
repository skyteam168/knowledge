from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, JsonType, created_at_column


class GenerationStatus(StrEnum):
    BUILDING = "building"
    ACTIVE = "active"
    RETIRED = "retired"
    FAILED = "failed"


class IndexGeneration(IdMixin, Base):
    """One physical Qdrant collection + OpenSearch index pair behind the read aliases.

    Platform-level (shared by all tenants, filtered by org_id inside), hence no org_id.
    Writers target the active generation plus a building one (dual write during rebuild).
    """

    __tablename__ = "index_generations"

    version: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    qdrant_collection: Mapped[str] = mapped_column(String(128), nullable=False)
    opensearch_index: Mapped[str] = mapped_column(String(128), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(255), nullable=False)
    embedding_base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    embedding_dim: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    stats: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_column()
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
