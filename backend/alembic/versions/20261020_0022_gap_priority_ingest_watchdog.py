"""gap priority/due_at for SLA; ingest watchdog uses existing document columns

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-20 14:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "knowledge_gaps",
        sa.Column(
            "priority",
            sa.String(16),
            nullable=False,
            server_default="normal",
        ),
    )
    op.add_column(
        "knowledge_gaps",
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_knowledge_gaps_due_at",
        "knowledge_gaps",
        ["org_id", "status", "due_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_gaps_due_at", table_name="knowledge_gaps")
    op.drop_column("knowledge_gaps", "due_at")
    op.drop_column("knowledge_gaps", "priority")
