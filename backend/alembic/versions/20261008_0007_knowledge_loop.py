"""knowledge loop: gap triage + clusters, knowledge objects, versions, reviews, notifications

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-09 10:00:00

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

NEW_PERMISSIONS = {"gap:review": "处理知识缺口", "ko:edit": "编辑知识条目"}
EDITOR_ROLE = "kb_editor"


def _ts(name: str, nullable: bool = False) -> sa.Column[sa.DateTime]:
    if nullable:
        return sa.Column(name, sa.DateTime(timezone=True), nullable=True)
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def _tenant(table: str) -> None:
    op.create_index(f"ix_{table}_org_id", table, ["org_id"])


def upgrade() -> None:
    with op.batch_alter_table("knowledge_gaps") as batch:
        batch.add_column(sa.Column("trace_id", sa.String(32), nullable=True))
        batch.add_column(sa.Column("kb_id", sa.String(32), nullable=True))
        batch.add_column(sa.Column("cluster_id", sa.String(32), nullable=True))
        batch.add_column(sa.Column("query_hash", sa.String(64), nullable=True))
        batch.add_column(
            sa.Column("occurrences", sa.Integer(), server_default=sa.text("1"), nullable=False)
        )
        batch.add_column(_ts("last_seen_at"))
        batch.add_column(sa.Column("assignee_id", sa.String(32), nullable=True))
        batch.add_column(sa.Column("duplicate_of_id", sa.String(32), nullable=True))
        batch.add_column(
            sa.Column("resolution", JSON, server_default=sa.text("'{}'"), nullable=False)
        )
        batch.add_column(sa.Column("resolved_by", sa.String(32), nullable=True))
        batch.add_column(_ts("resolved_at", nullable=True))
        batch.create_index("ix_knowledge_gaps_kb_id", ["kb_id"])
        batch.create_index("ix_knowledge_gaps_assignee_id", ["assignee_id"])
        batch.create_index("ix_knowledge_gaps_duplicate_of_id", ["duplicate_of_id"])
        batch.create_index("ix_knowledge_gaps_cluster_hash", ["cluster_id", "query_hash"])
    op.execute("UPDATE knowledge_gaps SET status = 'open' WHERE status = 'candidate'")
    op.execute("UPDATE knowledge_gaps SET status = 'rejected' WHERE status = 'ignored'")
    op.execute("UPDATE knowledge_gaps SET last_seen_at = created_at")
    op.execute(
        "UPDATE knowledge_gaps SET trace_id = "
        "(SELECT messages.trace_id FROM messages WHERE messages.id = knowledge_gaps.message_id)"
    )

    op.create_table(
        "gap_clusters",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("kb_id", sa.String(32), nullable=True),
        sa.Column("representative_query", sa.Text(), nullable=False),
        sa.Column("centroid", JSON, nullable=False),
        sa.Column("embedding_model", sa.String(255), nullable=False),
        sa.Column("embedding_dim", sa.Integer(), nullable=False),
        sa.Column("gap_count", sa.Integer(), nullable=False),
        sa.Column("occurrences", sa.Integer(), nullable=False),
        sa.Column("open_count", sa.Integer(), nullable=False),
        sa.Column("sources", JSON, nullable=False),
        _ts("last_seen_at"),
        _ts("created_at"),
        _ts("updated_at"),
        sa.PrimaryKeyConstraint("id", name="pk_gap_clusters"),
    )
    _tenant("gap_clusters")
    op.create_index("ix_gap_clusters_org_seen", "gap_clusters", ["org_id", "last_seen_at"])

    op.create_table(
        "knowledge_objects",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("kb_id", sa.String(32), nullable=False),
        sa.Column("ko_type", sa.String(32), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("variants", JSON, nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("sources", JSON, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("published_version", sa.Integer(), nullable=True),
        sa.Column("acl_inherit", sa.Boolean(), nullable=False),
        _ts("effective_from", nullable=True),
        _ts("effective_to", nullable=True),
        sa.Column("owner_id", sa.String(32), nullable=True),
        sa.Column("origin", sa.String(16), nullable=False),
        sa.Column("gap_ids", JSON, nullable=False),
        sa.Column("ai_draft", JSON, nullable=False),
        sa.Column("conflicts", JSON, nullable=False),
        _ts("conflicts_checked_at", nullable=True),
        _ts("published_at", nullable=True),
        sa.Column("published_by", sa.String(32), nullable=True),
        _ts("expiry_notified_at", nullable=True),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("updated_by", sa.String(32), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.ForeignKeyConstraint(
            ["kb_id"],
            ["knowledge_bases.id"],
            name="fk_knowledge_objects_kb_id_knowledge_bases",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_objects"),
    )
    _tenant("knowledge_objects")
    op.create_index(
        "ix_knowledge_objects_kb_status", "knowledge_objects", ["org_id", "kb_id", "status"]
    )

    op.create_table(
        "ko_versions",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("ko_id", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("ko_type", sa.String(32), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("variants", JSON, nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("sources", JSON, nullable=False),
        _ts("effective_from", nullable=True),
        _ts("effective_to", nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(32), nullable=True),
        _ts("created_at"),
        _ts("published_at", nullable=True),
        sa.Column("published_by", sa.String(32), nullable=True),
        sa.ForeignKeyConstraint(
            ["ko_id"],
            ["knowledge_objects.id"],
            name="fk_ko_versions_ko_id_knowledge_objects",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ko_versions"),
        sa.UniqueConstraint("ko_id", "version", name="uq_ko_versions_ko_id_version"),
    )
    _tenant("ko_versions")

    op.create_table(
        "ko_entries",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("ko_id", sa.String(32), nullable=False),
        sa.Column("ko_version", sa.Integer(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        _ts("created_at"),
        sa.ForeignKeyConstraint(
            ["ko_id"],
            ["knowledge_objects.id"],
            name="fk_ko_entries_ko_id_knowledge_objects",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ko_entries"),
        sa.UniqueConstraint(
            "ko_id", "ko_version", "seq", name="uq_ko_entries_ko_id_ko_version_seq"
        ),
    )
    _tenant("ko_entries")

    op.create_table(
        "ko_source_refs",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("ko_id", sa.String(32), nullable=False),
        sa.Column("document_id", sa.String(32), nullable=False),
        sa.Column("chunk_id", sa.String(32), nullable=True),
        sa.ForeignKeyConstraint(
            ["ko_id"],
            ["knowledge_objects.id"],
            name="fk_ko_source_refs_ko_id_knowledge_objects",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ko_source_refs"),
    )
    _tenant("ko_source_refs")
    op.create_index("ix_ko_source_refs_ko_id", "ko_source_refs", ["ko_id"])
    op.create_index("ix_ko_source_refs_document", "ko_source_refs", ["org_id", "document_id"])

    op.create_table(
        "review_tasks",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("ko_id", sa.String(32), nullable=False),
        sa.Column("ko_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("submitted_by", sa.String(32), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("reviewer_id", sa.String(32), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        _ts("decided_at", nullable=True),
        sa.Column("conflicts", JSON, nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
        sa.ForeignKeyConstraint(
            ["ko_id"],
            ["knowledge_objects.id"],
            name="fk_review_tasks_ko_id_knowledge_objects",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_review_tasks"),
    )
    _tenant("review_tasks")
    op.create_index("ix_review_tasks_ko_id", "review_tasks", ["ko_id"])
    op.create_index(
        "ix_review_tasks_org_status", "review_tasks", ["org_id", "status", "created_at"]
    )

    op.create_table(
        "notifications",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("user_id", sa.String(32), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("resource_type", sa.String(32), nullable=True),
        sa.Column("resource_id", sa.String(64), nullable=True),
        sa.Column("link", sa.String(512), nullable=True),
        sa.Column("dedupe_key", sa.String(255), nullable=True),
        _ts("read_at", nullable=True),
        _ts("created_at"),
        sa.PrimaryKeyConstraint("id", name="pk_notifications"),
        sa.UniqueConstraint(
            "user_id", "dedupe_key", name="uq_notifications_user_id_dedupe_key"
        ),
    )
    _tenant("notifications")
    op.create_index("ix_notifications_user", "notifications", ["org_id", "user_id", "created_at"])

    conn = op.get_bind()
    for code, name in NEW_PERMISSIONS.items():
        exists = conn.execute(
            sa.text("SELECT 1 FROM permissions WHERE code = :code"), {"code": code}
        ).first()
        if exists is None:
            conn.execute(
                sa.text("INSERT INTO permissions (id, code, name) VALUES (:id, :code, :name)"),
                {"id": uuid.uuid4().hex, "code": code, "name": name},
            )
    # Existing tenants: the system editor role gets the new default permissions.
    roles = conn.execute(
        sa.text("SELECT id, org_id FROM roles WHERE code = :code AND is_system"),
        {"code": EDITOR_ROLE},
    ).all()
    for code in NEW_PERMISSIONS:
        perm_id = conn.execute(
            sa.text("SELECT id FROM permissions WHERE code = :code"), {"code": code}
        ).scalar_one()
        for role_id, org_id in roles:
            linked = conn.execute(
                sa.text(
                    "SELECT 1 FROM role_permissions "
                    "WHERE role_id = :role_id AND permission_id = :perm_id"
                ),
                {"role_id": role_id, "perm_id": perm_id},
            ).first()
            if linked is None:
                conn.execute(
                    sa.text(
                        "INSERT INTO role_permissions (org_id, role_id, permission_id) "
                        "VALUES (:org_id, :role_id, :perm_id)"
                    ),
                    {"org_id": org_id, "role_id": role_id, "perm_id": perm_id},
                )


def downgrade() -> None:
    conn = op.get_bind()
    for code in NEW_PERMISSIONS:
        conn.execute(
            sa.text(
                "DELETE FROM role_permissions WHERE permission_id IN "
                "(SELECT id FROM permissions WHERE code = :code)"
            ),
            {"code": code},
        )
        conn.execute(sa.text("DELETE FROM permissions WHERE code = :code"), {"code": code})
    op.drop_table("notifications")
    op.drop_table("review_tasks")
    op.drop_table("ko_source_refs")
    op.drop_table("ko_entries")
    op.drop_table("ko_versions")
    op.drop_table("knowledge_objects")
    op.drop_table("gap_clusters")
    op.execute("UPDATE knowledge_gaps SET status = 'open' WHERE status IN ('in_review')")
    op.execute(
        "UPDATE knowledge_gaps SET status = 'ignored' WHERE status IN ('rejected', 'duplicate')"
    )
    with op.batch_alter_table("knowledge_gaps") as batch:
        batch.drop_index("ix_knowledge_gaps_cluster_hash")
        batch.drop_index("ix_knowledge_gaps_duplicate_of_id")
        batch.drop_index("ix_knowledge_gaps_assignee_id")
        batch.drop_index("ix_knowledge_gaps_kb_id")
        for column in (
            "resolved_at",
            "resolved_by",
            "resolution",
            "duplicate_of_id",
            "assignee_id",
            "last_seen_at",
            "occurrences",
            "query_hash",
            "cluster_id",
            "kb_id",
            "trace_id",
        ):
            batch.drop_column(column)
