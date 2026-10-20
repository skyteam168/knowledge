"""document protection: watermark, copy protection, download permission

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-19 17:40:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "knowledge_bases",
        sa.Column("watermark", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "knowledge_bases",
        sa.Column("copy_protect", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "knowledge_bases",
        sa.Column("download_permission", sa.String(16), server_default="read", nullable=False),
    )
    op.add_column("documents", sa.Column("watermark", sa.Boolean(), nullable=True))
    op.add_column("documents", sa.Column("copy_protect", sa.Boolean(), nullable=True))
    op.add_column("documents", sa.Column("download_permission", sa.String(16), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "download_permission")
    op.drop_column("documents", "copy_protect")
    op.drop_column("documents", "watermark")
    op.drop_column("knowledge_bases", "download_permission")
    op.drop_column("knowledge_bases", "copy_protect")
    op.drop_column("knowledge_bases", "watermark")
