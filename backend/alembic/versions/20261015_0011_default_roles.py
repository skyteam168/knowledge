"""default roles for users created by directory sync or first login

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-15 11:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "roles",
        sa.Column("is_default", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.execute("UPDATE roles SET is_default = true WHERE code = 'kb_viewer' AND is_system = true")


def downgrade() -> None:
    op.drop_column("roles", "is_default")
