"""collaboration: favorites, recent views, document comments

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-20 10:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _user_resource_table(name: str, time_column: str) -> None:
    op.create_table(
        name,
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("user_id", sa.String(32), nullable=False),
        sa.Column("resource_type", sa.String(16), nullable=False),
        sa.Column("resource_id", sa.String(32), nullable=False),
        sa.Column(
            time_column,
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=f"pk_{name}"),
        sa.UniqueConstraint(
            "user_id",
            "resource_type",
            "resource_id",
            name=f"uq_{name}_user_id_resource_type_resource_id",
        ),
    )
    op.create_index(f"ix_{name}_org_id", name, ["org_id"])
    op.create_index(f"ix_{name}_user", name, ["org_id", "user_id", time_column])


def upgrade() -> None:
    _user_resource_table("favorites", "created_at")
    _user_resource_table("recent_views", "viewed_at")
    op.create_table(
        "document_comments",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column(
            "document_id",
            sa.String(32),
            sa.ForeignKey(
                "documents.id",
                ondelete="CASCADE",
                name="fk_document_comments_document_id_documents",
            ),
            nullable=False,
        ),
        sa.Column("kb_id", sa.String(32), nullable=False),
        sa.Column("parent_id", sa.String(32), nullable=True),
        sa.Column("author_id", sa.String(32), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("mentions", JSON, nullable=False),
        sa.Column("document_version", sa.Integer(), nullable=False),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.String(32), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_document_comments"),
    )
    op.create_index("ix_document_comments_org_id", "document_comments", ["org_id"])
    op.create_index(
        "ix_document_comments_doc", "document_comments", ["document_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_table("document_comments")
    op.drop_table("recent_views")
    op.drop_table("favorites")
