"""chat: conversations, messages, feedback, knowledge gaps, qa traces

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-08 23:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _ts(name: str) -> sa.Column[sa.DateTime]:
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("user_id", sa.String(32), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("kb_ids", JSON, nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.PrimaryKeyConstraint("id", name="pk_conversations"),
    )
    op.create_index("ix_conversations_org_id", "conversations", ["org_id"])
    op.create_index(
        "ix_conversations_user_updated", "conversations", ["org_id", "user_id", "updated_at"]
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("conversation_id", sa.String(32), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("intent", sa.String(32), nullable=True),
        sa.Column("rewritten_query", sa.Text(), nullable=True),
        sa.Column("grounding", sa.String(32), nullable=True),
        sa.Column("citations", JSON, nullable=False),
        sa.Column("trace_id", sa.String(32), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        _ts("created_at"),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name="fk_messages_conversation_id_conversations",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_messages"),
    )
    op.create_index("ix_messages_org_id", "messages", ["org_id"])
    op.create_index(
        "ix_messages_conversation_created", "messages", ["conversation_id", "created_at"]
    )

    op.create_table(
        "message_feedback",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("message_id", sa.String(32), nullable=False),
        sa.Column("user_id", sa.String(32), nullable=False),
        sa.Column("rating", sa.String(8), nullable=False),
        sa.Column("reasons", JSON, nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["messages.id"],
            name="fk_message_feedback_message_id_messages",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_message_feedback"),
        sa.UniqueConstraint(
            "message_id", "user_id", name="uq_message_feedback_message_id_user_id"
        ),
    )
    op.create_index("ix_message_feedback_org_id", "message_feedback", ["org_id"])

    op.create_table(
        "knowledge_gaps",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("gap_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("rewritten_query", sa.Text(), nullable=True),
        sa.Column("user_id", sa.String(32), nullable=True),
        sa.Column("conversation_id", sa.String(32), nullable=True),
        sa.Column("message_id", sa.String(32), nullable=True),
        sa.Column("kb_ids", JSON, nullable=False),
        sa.Column("top_score", sa.Float(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("details", JSON, nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_gaps"),
    )
    op.create_index("ix_knowledge_gaps_org_id", "knowledge_gaps", ["org_id"])
    op.create_index("ix_knowledge_gaps_message_id", "knowledge_gaps", ["message_id"])
    op.create_index(
        "ix_knowledge_gaps_org_status", "knowledge_gaps", ["org_id", "status", "created_at"]
    )

    op.create_table(
        "qa_traces",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("user_id", sa.String(32), nullable=True),
        sa.Column("conversation_id", sa.String(32), nullable=True),
        sa.Column("message_id", sa.String(32), nullable=True),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("rewritten_query", sa.Text(), nullable=True),
        sa.Column("intent", sa.String(32), nullable=True),
        sa.Column("grounding", sa.String(32), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("retrieval_trace_ids", JSON, nullable=False),
        sa.Column("steps", JSON, nullable=False),
        sa.Column("timings", JSON, nullable=False),
        sa.Column("total_ms", sa.Integer(), nullable=False),
        _ts("created_at"),
        sa.PrimaryKeyConstraint("id", name="pk_qa_traces"),
    )
    op.create_index("ix_qa_traces_org_id", "qa_traces", ["org_id"])
    op.create_index("ix_qa_traces_org_created", "qa_traces", ["org_id", "created_at"])


def downgrade() -> None:
    op.drop_table("qa_traces")
    op.drop_table("knowledge_gaps")
    op.drop_table("message_feedback")
    op.drop_table("messages")
    op.drop_table("conversations")
