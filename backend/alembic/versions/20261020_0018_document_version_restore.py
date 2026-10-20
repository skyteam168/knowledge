"""document versions: remember which version a restore copied

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-20 08:10:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("document_versions", sa.Column("restored_from", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("document_versions", "restored_from")
