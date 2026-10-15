"""analytics summaries, offline evaluation

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-10 10:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _ts(name: str, nullable: bool = False) -> sa.Column[sa.DateTime]:
    if nullable:
        return sa.Column(name, sa.DateTime(timezone=True), nullable=True)
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def _int(name: str) -> sa.Column[sa.Integer]:
    return sa.Column(name, sa.Integer(), nullable=False)


def _tenant(table: str) -> None:
    op.create_index(f"ix_{table}_org_id", table, ["org_id"])


def upgrade() -> None:
    op.create_table(
        "analytics_daily",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("kb_id", sa.String(32), nullable=False),
        *(
            _int(name)
            for name in (
                "active_users",
                "questions",
                "grounded",
                "uncertain",
                "low_grounding",
                "no_evidence",
                "chitchat",
                "out_of_scope",
                "errors",
                "citations",
                "feedback_up",
                "feedback_down",
                "gaps_new",
                "gaps_resolved",
            )
        ),
        sa.Column("latency", JSON, nullable=False),
        _ts("refreshed_at"),
        sa.PrimaryKeyConstraint("id", name="pk_analytics_daily"),
        sa.UniqueConstraint(
            "org_id", "day", "kb_id", name="uq_analytics_daily_org_id_day_kb_id"
        ),
    )
    _tenant("analytics_daily")

    op.create_table(
        "analytics_top_questions",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("kb_id", sa.String(32), nullable=False),
        sa.Column("query_hash", sa.String(64), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        _int("count"),
        _int("unanswered"),
        sa.PrimaryKeyConstraint("id", name="pk_analytics_top_questions"),
    )
    _tenant("analytics_top_questions")
    op.create_index(
        "ix_analytics_top_questions_day", "analytics_top_questions", ["org_id", "day", "kb_id"]
    )

    op.create_table(
        "analytics_doc_citations",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("kb_id", sa.String(32), nullable=False),
        sa.Column("document_id", sa.String(32), nullable=False),
        sa.Column("is_ko", sa.Boolean(), nullable=False),
        _int("citations"),
        sa.PrimaryKeyConstraint("id", name="pk_analytics_doc_citations"),
    )
    _tenant("analytics_doc_citations")
    op.create_index(
        "ix_analytics_doc_citations_day", "analytics_doc_citations", ["org_id", "day"]
    )
    op.create_index(
        "ix_analytics_doc_citations_document",
        "analytics_doc_citations",
        ["org_id", "document_id", "day"],
    )

    op.create_table(
        "eval_datasets",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(32), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.PrimaryKeyConstraint("id", name="pk_eval_datasets"),
        sa.UniqueConstraint("org_id", "name", name="uq_eval_datasets_org_id_name"),
    )
    _tenant("eval_datasets")

    op.create_table(
        "eval_cases",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("dataset_id", sa.String(32), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("reference_answer", sa.Text(), nullable=True),
        sa.Column("expected_document_ids", JSON, nullable=False),
        sa.Column("expected_chunk_ids", JSON, nullable=False),
        sa.Column("kb_ids", JSON, nullable=False),
        sa.Column("tags", JSON, nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("source_id", sa.String(32), nullable=True),
        sa.Column("created_by", sa.String(32), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["eval_datasets.id"],
            name="fk_eval_cases_dataset_id_eval_datasets",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_eval_cases"),
        sa.UniqueConstraint(
            "dataset_id",
            "source",
            "source_id",
            name="uq_eval_cases_dataset_id_source_source_id",
        ),
    )
    _tenant("eval_cases")
    op.create_index("ix_eval_cases_dataset", "eval_cases", ["dataset_id", "created_at"])

    op.create_table(
        "eval_runs",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("dataset_id", sa.String(32), nullable=False),
        sa.Column("name", sa.String(128), nullable=True),
        sa.Column("profile_id", sa.String(32), nullable=True),
        sa.Column("profile_name", sa.String(64), nullable=False),
        sa.Column("config", JSON, nullable=False),
        sa.Column("environment", JSON, nullable=False),
        sa.Column("judge_enabled", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        _int("case_count"),
        _int("done_count"),
        sa.Column("metrics", JSON, nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        _ts("started_at", nullable=True),
        _ts("finished_at", nullable=True),
        sa.Column("created_by", sa.String(32), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["eval_datasets.id"],
            name="fk_eval_runs_dataset_id_eval_datasets",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_eval_runs"),
    )
    _tenant("eval_runs")
    op.create_index("ix_eval_runs_org_created", "eval_runs", ["org_id", "created_at"])

    op.create_table(
        "eval_results",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("run_id", sa.String(32), nullable=False),
        sa.Column("case_id", sa.String(32), nullable=False),
        sa.Column("retrieved", JSON, nullable=False),
        sa.Column("metrics", JSON, nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("citations", JSON, nullable=False),
        sa.Column("grounding", sa.String(32), nullable=True),
        sa.Column("judge", JSON, nullable=False),
        _int("latency_ms"),
        sa.Column("error", sa.Text(), nullable=True),
        _ts("created_at"),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["eval_runs.id"],
            name="fk_eval_results_run_id_eval_runs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_eval_results"),
        sa.UniqueConstraint("run_id", "case_id", name="uq_eval_results_run_id_case_id"),
    )
    _tenant("eval_results")


def downgrade() -> None:
    op.drop_table("eval_results")
    op.drop_table("eval_runs")
    op.drop_table("eval_cases")
    op.drop_table("eval_datasets")
    op.drop_table("analytics_doc_citations")
    op.drop_table("analytics_top_questions")
    op.drop_table("analytics_daily")
