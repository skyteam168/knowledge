"""document owner and periodic review

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-20 09:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("knowledge_bases", sa.Column("review_interval_days", sa.Integer(), nullable=True))
    op.add_column("documents", sa.Column("owner_id", sa.String(32), nullable=True))
    op.add_column("documents", sa.Column("review_interval_days", sa.Integer(), nullable=True))
    op.add_column("documents", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("documents", sa.Column("reviewed_by", sa.String(32), nullable=True))
    op.add_column(
        "documents", sa.Column("review_due_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "documents",
        sa.Column("review_reminder", sa.SmallInteger(), server_default="0", nullable=False),
    )
    op.create_index("ix_documents_review_due", "documents", ["review_due_at"])


def downgrade() -> None:
    op.drop_index("ix_documents_review_due", table_name="documents")
    for column in (
        "review_reminder",
        "review_due_at",
        "reviewed_by",
        "reviewed_at",
        "review_interval_days",
        "owner_id",
    ):
        op.drop_column("documents", column)
    op.drop_column("knowledge_bases", "review_interval_days")
