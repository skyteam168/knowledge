"""indexing: outbox leases / backoff / dead letters, index generations

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-08 18:00:00

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

NEW_PERMISSIONS = {"admin:index": "管理索引同步"}


def upgrade() -> None:
    with op.batch_alter_table("outbox_events") as batch:
        batch.add_column(sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ix_outbox_events_aggregate",
        "outbox_events",
        ["aggregate_type", "aggregate_id", "status"],
    )
    op.execute("UPDATE outbox_events SET status = 'dead' WHERE status = 'failed'")

    op.create_table(
        "index_generations",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("qdrant_collection", sa.String(128), nullable=False),
        sa.Column("opensearch_index", sa.String(128), nullable=False),
        sa.Column("embedding_model", sa.String(255), nullable=False),
        sa.Column("embedding_base_url", sa.String(512), nullable=False),
        sa.Column("embedding_dim", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("stats", JSON, nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_index_generations"),
        sa.UniqueConstraint("version", name="uq_index_generations_version"),
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
    op.drop_table("index_generations")
    op.execute("UPDATE outbox_events SET status = 'failed' WHERE status = 'dead'")
    op.drop_index("ix_outbox_events_aggregate", table_name="outbox_events")
    with op.batch_alter_table("outbox_events") as batch:
        batch.drop_column("locked_until")
        batch.drop_column("next_attempt_at")
