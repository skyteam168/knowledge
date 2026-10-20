"""document lifecycle_status and classification

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-20 14:00:00

Existing rows default to published + internal so search/chat behaviour stays unchanged
aside from effective_* window filtering added in application code.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "lifecycle_status",
            sa.String(16),
            nullable=False,
            server_default="published",
        ),
    )
    op.add_column(
        "documents",
        sa.Column(
            "classification",
            sa.String(16),
            nullable=False,
            server_default="internal",
        ),
    )
    op.create_index(
        "ix_documents_kb_lifecycle",
        "documents",
        ["org_id", "kb_id", "lifecycle_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_documents_kb_lifecycle", table_name="documents")
    op.drop_column("documents", "classification")
    op.drop_column("documents", "lifecycle_status")
