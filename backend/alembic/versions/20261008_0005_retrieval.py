"""retrieval: strategy profiles and retrieval traces

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-08 20:00:00

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

NEW_PERMISSIONS = {"admin:retrieval": "管理检索策略与检索调试"}


def _ts(name: str) -> sa.Column[sa.DateTime]:
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "retrieval_profiles",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("config", JSON, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("updated_by", sa.String(32), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.PrimaryKeyConstraint("id", name="pk_retrieval_profiles"),
        sa.UniqueConstraint("org_id", "name", name="uq_retrieval_profiles_org_id_name"),
    )
    op.create_index("ix_retrieval_profiles_org_id", "retrieval_profiles", ["org_id"])
    op.create_index(
        "uq_retrieval_profiles_active",
        "retrieval_profiles",
        ["org_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
        sqlite_where=sa.text("is_active"),
    )

    op.create_table(
        "retrieval_traces",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("user_id", sa.String(32), nullable=True),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("normalized_query", sa.Text(), nullable=False),
        sa.Column("filters", JSON, nullable=False),
        sa.Column("profile_id", sa.String(32), nullable=True),
        sa.Column("profile_name", sa.String(64), nullable=False),
        sa.Column("config", JSON, nullable=False),
        sa.Column("principals_hash", sa.String(64), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=True),
        sa.Column("cache_hit", sa.Boolean(), nullable=False),
        sa.Column("degraded", JSON, nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("timings", JSON, nullable=False),
        sa.Column("stages", JSON, nullable=False),
        sa.Column("truncated", sa.Boolean(), nullable=False),
        sa.Column("total_ms", sa.Integer(), nullable=False),
        _ts("created_at"),
        sa.PrimaryKeyConstraint("id", name="pk_retrieval_traces"),
    )
    op.create_index("ix_retrieval_traces_org_id", "retrieval_traces", ["org_id"])
    op.create_index(
        "ix_retrieval_traces_org_created", "retrieval_traces", ["org_id", "created_at"]
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
        conn.execute(sa.text("DELETE FROM permissions WHERE code = :code"), {"code": code})
    op.drop_table("retrieval_traces")
    op.drop_table("retrieval_profiles")
