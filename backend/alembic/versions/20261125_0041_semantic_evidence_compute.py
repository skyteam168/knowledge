"""semantic_evidences + attribute compute_expr (semantic center gaps)

Revision ID: 0041
Revises: 0040
Create Date: 2026-11-25 16:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0041"
down_revision: str | None = "0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JsonType = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "semantic_evidences",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("org_id", sa.String(length=32), nullable=False),
        sa.Column("version_id", sa.String(length=32), nullable=False),
        sa.Column("target_kind", sa.String(length=16), nullable=False),
        sa.Column("target_id", sa.String(length=32), nullable=False),
        sa.Column("evidence_kind", sa.String(length=16), nullable=False),
        sa.Column("evidence_id", sa.String(length=64), nullable=False),
        sa.Column("note", sa.String(length=512), nullable=True),
        sa.Column("created_by", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["semantic_model_versions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "org_id",
            "version_id",
            "target_kind",
            "target_id",
            "evidence_kind",
            "evidence_id",
            name="uq_semantic_evidences_target_ref",
        ),
    )
    op.create_index(
        "ix_semantic_evidences_version",
        "semantic_evidences",
        ["org_id", "version_id"],
    )
    op.create_index(
        "ix_semantic_evidences_target",
        "semantic_evidences",
        ["org_id", "target_kind", "target_id"],
    )

    op.add_column(
        "semantic_attributes",
        sa.Column("compute_expr", sa.Text(), nullable=True),
    )
    op.add_column(
        "semantic_attributes",
        sa.Column("compute_inputs", JsonType, nullable=False, server_default=sa.text("'[]'")),
    )


def downgrade() -> None:
    op.drop_column("semantic_attributes", "compute_inputs")
    op.drop_column("semantic_attributes", "compute_expr")
    op.drop_index("ix_semantic_evidences_target", table_name="semantic_evidences")
    op.drop_index("ix_semantic_evidences_version", table_name="semantic_evidences")
    op.drop_table("semantic_evidences")
