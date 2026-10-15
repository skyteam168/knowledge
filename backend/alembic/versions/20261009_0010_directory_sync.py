"""organization directory sync (WeCom / DingTalk / Weaver / Excel) and QR-code login identities

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-09 18:00:00

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

NEW_PERMISSIONS = {"admin:directory": "管理组织架构同步与扫码登录"}


def _ts(name: str, nullable: bool = False) -> sa.Column[sa.DateTime]:
    if nullable:
        return sa.Column(name, sa.DateTime(timezone=True), nullable=True)
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def _source(name: str = "source") -> sa.Column[sa.String]:
    return sa.Column(name, sa.String(16), server_default="local", nullable=False)


def upgrade() -> None:
    op.add_column("departments", _source())
    op.add_column("departments", sa.Column("external_id", sa.String(128), nullable=True))
    op.add_column(
        "departments", sa.Column("status", sa.String(16), server_default="active", nullable=False)
    )
    with op.batch_alter_table("departments") as batch:
        batch.create_unique_constraint(
            "uq_departments_org_id_source_external_id", ["org_id", "source", "external_id"]
        )

    op.add_column("users", sa.Column("employee_no", sa.String(64), nullable=True))
    op.add_column("users", sa.Column("mobile", sa.String(32), nullable=True))
    op.add_column("users", sa.Column("job_title", sa.String(128), nullable=True))
    op.add_column("users", _source())
    op.create_index("ix_users_employee_no", "users", ["employee_no"])

    op.create_table(
        "user_departments",
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("user_id", sa.String(32), nullable=False),
        sa.Column("department_id", sa.String(32), nullable=False),
        sa.Column("is_primary", sa.Boolean(), server_default=sa.false(), nullable=False),
        _source(),
        sa.PrimaryKeyConstraint("user_id", "department_id", name="pk_user_departments"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_user_departments_user_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["department_id"],
            ["departments.id"],
            name="fk_user_departments_department_id_departments",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_user_departments_org_id", "user_departments", ["org_id"])
    op.create_index("ix_user_departments_department_id", "user_departments", ["department_id"])
    op.execute(
        "INSERT INTO user_departments (org_id, user_id, department_id, is_primary, source) "
        "SELECT org_id, id, department_id, true, 'local' FROM users "
        "WHERE department_id IS NOT NULL"
    )

    op.create_table(
        "user_identities",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("user_id", sa.String(32), nullable=False),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("external_id", sa.String(128), nullable=False),
        sa.Column("union_id", sa.String(128), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.PrimaryKeyConstraint("id", name="pk_user_identities"),
        sa.UniqueConstraint(
            "org_id", "provider", "external_id", name="uq_user_identities_org_id_provider_external_id"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_user_identities_user_id_users", ondelete="CASCADE"
        ),
    )
    op.create_index("ix_user_identities_org_id", "user_identities", ["org_id"])
    op.create_index("ix_user_identities_user_id", "user_identities", ["user_id"])

    op.create_table(
        "directory_sources",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("is_primary", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("config_encrypted", sa.Text(), nullable=False),
        sa.Column("sync_interval_minutes", sa.Integer(), server_default="0", nullable=False),
        _ts("last_sync_at", nullable=True),
        sa.Column("last_status", sa.String(16), nullable=True),
        sa.Column("last_run_id", sa.String(32), nullable=True),
        sa.Column("created_by", sa.String(32), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.PrimaryKeyConstraint("id", name="pk_directory_sources"),
    )
    op.create_index("ix_directory_sources_org_id", "directory_sources", ["org_id"])

    op.create_table(
        "directory_sync_runs",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("source_id", sa.String(32), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("forced", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("stats", JSON, server_default=sa.text("'{}'"), nullable=False),
        sa.Column("changes", JSON, server_default=sa.text("'{}'"), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("triggered_by", sa.String(64), nullable=True),
        _ts("started_at"),
        _ts("finished_at", nullable=True),
        sa.Column("duration_ms", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_directory_sync_runs"),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["directory_sources.id"],
            name="fk_directory_sync_runs_source_id_directory_sources",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_directory_sync_runs_org_id", "directory_sync_runs", ["org_id"])
    op.create_index(
        "ix_directory_sync_runs_source_started", "directory_sync_runs", ["source_id", "started_at"]
    )

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
    op.drop_table("directory_sync_runs")
    op.drop_table("directory_sources")
    op.drop_table("user_identities")
    op.drop_table("user_departments")
    op.drop_index("ix_users_employee_no", table_name="users")
    for col in ("source", "job_title", "mobile", "employee_no"):
        op.drop_column("users", col)
    with op.batch_alter_table("departments") as batch:
        batch.drop_constraint("uq_departments_org_id_source_external_id", type_="unique")
        for col in ("status", "external_id", "source"):
            batch.drop_column(col)
