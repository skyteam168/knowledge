"""Open API for external agents: registered clients, their API keys and call logs.

A client acts through a dedicated service user (users.username = "agent:<id>") whose
principals are the client's bound departments / groups / roles, so retrieval pre-filtering
and the PG re-check work exactly as for people. `kb_ids` is a hard upper bound on top of ACL.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, JsonType, TenantMixin, TimestampMixin, created_at_column

SERVICE_USER_PREFIX = "agent:"


class ApiClientStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class ApiKeyStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


class ApiScope(StrEnum):
    RETRIEVE = "retrieve"
    CHAT = "chat"
    MCP = "mcp"


class ApiClient(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "api_clients"

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    owner_department_id: Mapped[str | None] = mapped_column(String(32))
    contact: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(
        String(16), default=ApiClientStatus.ACTIVE.value, nullable=False
    )
    service_user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    # Knowledge bases the client may ever touch (hard upper bound).
    kb_ids: Mapped[list[str]] = mapped_column(JsonType, default=list, nullable=False)
    # Identity the client acts as: [{"type": "dept" | "group" | "role", "id": "..."}].
    principals: Mapped[list[dict[str, Any]]] = mapped_column(JsonType, default=list, nullable=False)
    scopes: Mapped[list[str]] = mapped_column(JsonType, default=list, nullable=False)
    # Requests per minute; 0 = platform default.
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Requests per natural day (UTC); 0 = unlimited.
    daily_quota: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # IPv4/IPv6 addresses or CIDR blocks; empty = any source.
    ip_allowlist: Mapped[list[str]] = mapped_column(JsonType, default=list, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(String(32))


class ApiKey(IdMixin, TenantMixin, Base):
    __tablename__ = "api_keys"

    client_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("api_clients.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    # First characters of the secret, for display only.
    prefix: Mapped[str] = mapped_column(String(32), nullable=False)
    # HMAC-SHA256 of the full secret; the secret itself is never stored.
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=ApiKeyStatus.ACTIVE.value, nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_ip: Mapped[str | None] = mapped_column(String(64))
    created_by: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = created_at_column()
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApiCallLog(IdMixin, TenantMixin, Base):
    __tablename__ = "api_call_logs"
    __table_args__ = (Index("ix_api_call_logs_client_created", "client_id", "created_at"),)

    client_id: Mapped[str] = mapped_column(String(32), nullable=False)
    key_id: Mapped[str | None] = mapped_column(String(32))
    endpoint: Mapped[str] = mapped_column(String(64), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64))
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ip: Mapped[str | None] = mapped_column(String(64))
    query: Mapped[str | None] = mapped_column(Text)
    kb_ids: Mapped[list[str]] = mapped_column(JsonType, default=list, nullable=False)
    result_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    document_ids: Mapped[list[str]] = mapped_column(JsonType, default=list, nullable=False)
    trace_id: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = created_at_column()
