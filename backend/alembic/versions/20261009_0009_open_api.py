"""open API for external agents, answer progress steps

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-09 09:00:00

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

NEW_PERMISSIONS = {"admin:openapi": "管理开放平台（外部 Agent 接入）"}


def _ts(name: str, nullable: bool = False) -> sa.Column[sa.DateTime]:
    if nullable:
        return sa.Column(name, sa.DateTime(timezone=True), nullable=True)
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def _json_list(name: str) -> sa.Column[sa.JSON]:
    return sa.Column(name, JSON, server_default=sa.text("'[]'"), nullable=False)


def upgrade() -> None:
    op.add_column("messages", _json_list("steps"))

    op.create_table(
        "api_clients",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("owner_department_id", sa.String(32), nullable=True),
        sa.Column("contact", sa.String(255), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("service_user_id", sa.String(32), nullable=False),
        _json_list("kb_ids"),
        _json_list("principals"),
        _json_list("scopes"),
        sa.Column("rate_limit_per_minute", sa.Integer(), nullable=False),
        sa.Column("daily_quota", sa.Integer(), nullable=False),
        _json_list("ip_allowlist"),
        _ts("expires_at", nullable=True),
        _ts("last_used_at", nullable=True),
        sa.Column("created_by", sa.String(32), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.PrimaryKeyConstraint("id", name="pk_api_clients"),
        sa.ForeignKeyConstraint(
            ["service_user_id"],
            ["users.id"],
            name="fk_api_clients_service_user_id_users",
            ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_api_clients_org_id", "api_clients", ["org_id"])

    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("client_id", sa.String(32), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("prefix", sa.String(32), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        _ts("expires_at", nullable=True),
        _ts("last_used_at", nullable=True),
        sa.Column("last_used_ip", sa.String(64), nullable=True),
        sa.Column("created_by", sa.String(32), nullable=True),
        _ts("created_at"),
        _ts("revoked_at", nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_api_keys"),
        sa.UniqueConstraint("key_hash", name="uq_api_keys_key_hash"),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["api_clients.id"],
            name="fk_api_keys_client_id_api_clients",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_api_keys_org_id", "api_keys", ["org_id"])
    op.create_index("ix_api_keys_client_id", "api_keys", ["client_id"])

    op.create_table(
        "api_call_logs",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("client_id", sa.String(32), nullable=False),
        sa.Column("key_id", sa.String(32), nullable=True),
        sa.Column("endpoint", sa.String(64), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.Column("query", sa.Text(), nullable=True),
        _json_list("kb_ids"),
        sa.Column("result_count", sa.Integer(), nullable=False),
        _json_list("document_ids"),
        sa.Column("trace_id", sa.String(32), nullable=True),
        _ts("created_at"),
        sa.PrimaryKeyConstraint("id", name="pk_api_call_logs"),
    )
    op.create_index("ix_api_call_logs_org_id", "api_call_logs", ["org_id"])
    op.create_index(
        "ix_api_call_logs_client_created", "api_call_logs", ["client_id", "created_at"]
    )

    conn = op.get_bind()
    for code, name in NEW_PERMISSIONS.items():
        exists = conn.execute(
            sa.text("SELECT 1 FROM permissions WHERE code = :code"), {"code": code}
        ).first()
        if exists is None:
            conn.execute(
                sa.text("INSERT INTO permissions (id, code, name) VALUES (:id, :code, :name)"),
                {"id": uuid.uuid4().hex, "code": code, "name": name},
            )


def downgrade() -> None:
    conn = op.get_bind()
    for code in NEW_PERMISSIONS:
        conn.execute(
            sa.text(
                "DELETE FROM role_permissions WHERE permission_id IN "
                "(SELECT id FROM permissions WHERE code = :code)"
            ),
            {"code": code},
        )
        conn.execute(sa.text("DELETE FROM permissions WHERE code = :code"), {"code": code})
    op.drop_table("api_call_logs")
    op.drop_table("api_keys")
    op.drop_table("api_clients")
    op.drop_column("messages", "steps")
