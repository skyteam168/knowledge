"""admin assistant runs (understanding, plan, events, approval window)

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-17 16:40:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "admin_agent_runs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("user_id", sa.String(32), nullable=False),
        sa.Column("user_name", sa.String(128), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("language", sa.String(16), nullable=True),
        sa.Column("intent", sa.String(32), nullable=True),
        sa.Column("understand_mode", sa.String(16), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("risk", sa.String(16), nullable=True),
        sa.Column("steps", JSON, nullable=True),
        sa.Column("events", JSON, nullable=False),
        sa.Column("exec_events", JSON, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_admin_agent_runs_org_id", "admin_agent_runs", ["org_id"])
    op.create_index(
        "ix_admin_agent_runs_user_created", "admin_agent_runs", ["org_id", "user_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_table("admin_agent_runs")
