"""ontology_rules / action_types / approvals / executions (Wave C)

Revision ID: 0040
Revises: 0039
Create Date: 2026-11-25 23:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0040"
down_revision: str | None = "0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JsonType = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "ontology_rules",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("org_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=512), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("condition", JsonType, nullable=False),
        sa.Column("verdict", sa.String(length=32), nullable=False),
        sa.Column("message", sa.String(length=512), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ontology_rules_org_priority", "ontology_rules", ["org_id", "priority"])
    op.create_index("ix_ontology_rules_org_enabled", "ontology_rules", ["org_id", "enabled"])

    op.create_table(
        "action_types",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("org_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=512), nullable=True),
        sa.Column("input_schema", JsonType, nullable=False),
        sa.Column("preconditions", JsonType, nullable=False),
        sa.Column("risk", sa.String(length=16), nullable=False),
        sa.Column("systems", JsonType, nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_action_types_org_name", "action_types", ["org_id", "name"], unique=True)

    op.create_table(
        "action_approvals",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("org_id", sa.String(length=32), nullable=False),
        sa.Column("action_type", sa.String(length=128), nullable=False),
        sa.Column("actor_id", sa.String(length=32), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledge_risk", sa.Boolean(), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_action_approvals_org_actor", "action_approvals", ["org_id", "actor_id"]
    )

    op.create_table(
        "action_executions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("org_id", sa.String(length=32), nullable=False),
        sa.Column("action_type", sa.String(length=128), nullable=False),
        sa.Column("actor_id", sa.String(length=32), nullable=False),
        sa.Column("on_behalf_of", sa.String(length=32), nullable=True),
        sa.Column("input", JsonType, nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("result", JsonType, nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("approval_id", sa.String(length=32), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("compensated", sa.Boolean(), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=False),
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
            ["approval_id"], ["action_approvals.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_action_executions_org_idem",
        "action_executions",
        ["org_id", "idempotency_key"],
        unique=True,
    )
    op.create_index(
        "ix_action_executions_org_type", "action_executions", ["org_id", "action_type"]
    )


def downgrade() -> None:
    op.drop_index("ix_action_executions_org_type", table_name="action_executions")
    op.drop_index("ix_action_executions_org_idem", table_name="action_executions")
    op.drop_table("action_executions")
    op.drop_index("ix_action_approvals_org_actor", table_name="action_approvals")
    op.drop_table("action_approvals")
    op.drop_index("ix_action_types_org_name", table_name="action_types")
    op.drop_table("action_types")
    op.drop_index("ix_ontology_rules_org_enabled", table_name="ontology_rules")
    op.drop_index("ix_ontology_rules_org_priority", table_name="ontology_rules")
    op.drop_table("ontology_rules")
