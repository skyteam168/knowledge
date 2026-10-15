"""token metering of model calls and its daily rollup

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-15 15:00:00

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_PERMISSIONS = {"analytics:usage": "查看模型用量（含每人 token 消耗）"}


def upgrade() -> None:
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

    op.create_table(
        "llm_usage",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("user_id", sa.String(32)),
        sa.Column("feature", sa.String(32), nullable=False),
        sa.Column("stage", sa.String(32)),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("estimated", sa.Boolean(), nullable=False),
        sa.Column("input_count", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("first_token_ms", sa.Integer()),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("fallback", sa.Boolean(), nullable=False),
        sa.Column("conversation_id", sa.String(32)),
        sa.Column("message_id", sa.String(32)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_llm_usage_org_id", "llm_usage", ["org_id"])
    op.create_index("ix_llm_usage_org_created", "llm_usage", ["org_id", "created_at"])
    op.create_index(
        "ix_llm_usage_org_user_created", "llm_usage", ["org_id", "user_id", "created_at"]
    )

    op.create_table(
        "analytics_llm_usage",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("user_id", sa.String(32), nullable=False),
        sa.Column("feature", sa.String(32), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("calls", sa.Integer(), nullable=False),
        sa.Column("errors", sa.Integer(), nullable=False),
        sa.Column("estimated_calls", sa.Integer(), nullable=False),
        sa.Column("fallback_calls", sa.Integer(), nullable=False),
        sa.Column("prompt_tokens", sa.BigInteger(), nullable=False),
        sa.Column("completion_tokens", sa.BigInteger(), nullable=False),
        sa.Column("total_tokens", sa.BigInteger(), nullable=False),
        sa.Column("latency_ms", sa.BigInteger(), nullable=False),
        sa.Column(
            "refreshed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "org_id",
            "day",
            "user_id",
            "feature",
            "kind",
            "model",
            name="uq_analytics_llm_usage_org_id_day_user_id_feature_kind_model",
        ),
    )
    op.create_index("ix_analytics_llm_usage_org_id", "analytics_llm_usage", ["org_id"])
    op.create_index(
        "ix_analytics_llm_usage_user", "analytics_llm_usage", ["org_id", "user_id", "day"]
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
    op.drop_table("analytics_llm_usage")
    op.drop_table("llm_usage")
