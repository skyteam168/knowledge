"""resource_acl.effect allow|deny

Revision ID: 0028
Revises: 0027
Create Date: 2026-11-14 15:20:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "resource_acl",
        sa.Column("effect", sa.String(length=8), nullable=False, server_default="allow"),
    )
    op.drop_constraint("uq_resource_acl_entry", "resource_acl", type_="unique")
    op.create_unique_constraint(
        "uq_resource_acl_entry",
        "resource_acl",
        [
            "resource_type",
            "resource_id",
            "principal_type",
            "principal_id",
            "permission",
            "effect",
        ],
    )


def downgrade() -> None:
    op.drop_constraint("uq_resource_acl_entry", "resource_acl", type_="unique")
    op.create_unique_constraint(
        "uq_resource_acl_entry",
        "resource_acl",
        [
            "resource_type",
            "resource_id",
            "principal_type",
            "principal_id",
            "permission",
        ],
    )
    op.drop_column("resource_acl", "effect")
