"""identity, rbac, resource acl and audit logs

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-08 12:00:00

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

# Snapshot of the permission catalog at this revision (app bootstrap keeps it up to date).
PERMISSIONS = {
    "kb:create": "创建知识库",
    "kb:read": "查看知识库",
    "kb:update": "编辑知识库",
    "kb:delete": "删除知识库",
    "doc:upload": "上传文档",
    "doc:delete": "删除文档",
    "review:approve": "审核通过",
    "chat:use": "使用 AI 助手",
    "search:use": "使用搜索",
    "analytics:view": "查看分析",
    "admin:org": "管理组织信息",
    "admin:dept": "管理部门",
    "admin:user": "管理用户",
    "admin:group": "管理用户组",
    "admin:role": "管理角色与授权",
    "admin:audit": "查看审计日志",
    "admin:*": "全部管理权限",
    "*": "超级权限",
}


def _timestamps() -> list[sa.Column[object]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_organizations"),
        sa.UniqueConstraint("code", name="uq_organizations_code"),
    )

    op.create_table(
        "departments",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("parent_id", sa.String(32), nullable=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("path", sa.String(1024), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_departments"),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["departments.id"],
            name="fk_departments_parent_id_departments",
            ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_departments_org_id", "departments", ["org_id"])
    op.create_index("ix_departments_parent_id", "departments", ["parent_id"])
    op.create_index("ix_departments_path", "departments", ["path"])

    op.create_table(
        "users",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("keycloak_sub", sa.String(64), nullable=True),
        sa.Column("username", sa.String(128), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("display_name", sa.String(128), nullable=True),
        sa.Column("department_id", sa.String(32), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("claims_hash", sa.String(64), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.ForeignKeyConstraint(
            ["department_id"],
            ["departments.id"],
            name="fk_users_department_id_departments",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("keycloak_sub", name="uq_users_keycloak_sub"),
        sa.UniqueConstraint("org_id", "username", name="uq_users_org_id_username"),
    )
    op.create_index("ix_users_org_id", "users", ["org_id"])
    op.create_index("ix_users_department_id", "users", ["department_id"])

    op.create_table(
        "groups",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source", sa.String(16), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_groups"),
        sa.UniqueConstraint("org_id", "name", name="uq_groups_org_id_name"),
    )
    op.create_index("ix_groups_org_id", "groups", ["org_id"])

    op.create_table(
        "user_groups",
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("user_id", sa.String(32), nullable=False),
        sa.Column("group_id", sa.String(32), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "group_id", name="pk_user_groups"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_user_groups_user_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["group_id"], ["groups.id"], name="fk_user_groups_group_id_groups", ondelete="CASCADE"
        ),
    )
    op.create_index("ix_user_groups_org_id", "user_groups", ["org_id"])
    op.create_index("ix_user_groups_group_id", "user_groups", ["group_id"])

    op.create_table(
        "roles",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_system", sa.Boolean(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_roles"),
        sa.UniqueConstraint("org_id", "code", name="uq_roles_org_id_code"),
    )
    op.create_index("ix_roles_org_id", "roles", ["org_id"])

    permissions = op.create_table(
        "permissions",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_permissions"),
        sa.UniqueConstraint("code", name="uq_permissions_code"),
    )

    op.create_table(
        "role_permissions",
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("role_id", sa.String(32), nullable=False),
        sa.Column("permission_id", sa.String(32), nullable=False),
        sa.PrimaryKeyConstraint("role_id", "permission_id", name="pk_role_permissions"),
        sa.ForeignKeyConstraint(
            ["role_id"], ["roles.id"], name="fk_role_permissions_role_id_roles", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["permission_id"],
            ["permissions.id"],
            name="fk_role_permissions_permission_id_permissions",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_role_permissions_org_id", "role_permissions", ["org_id"])

    op.create_table(
        "user_roles",
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("user_id", sa.String(32), nullable=False),
        sa.Column("role_id", sa.String(32), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "role_id", name="pk_user_roles"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_user_roles_user_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["role_id"], ["roles.id"], name="fk_user_roles_role_id_roles", ondelete="CASCADE"
        ),
    )
    op.create_index("ix_user_roles_org_id", "user_roles", ["org_id"])
    op.create_index("ix_user_roles_role_id", "user_roles", ["role_id"])

    op.create_table(
        "resource_acl",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("resource_type", sa.String(32), nullable=False),
        sa.Column("resource_id", sa.String(64), nullable=False),
        sa.Column("principal_type", sa.String(16), nullable=False),
        sa.Column("principal_id", sa.String(64), nullable=False),
        sa.Column("permission", sa.String(16), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_resource_acl"),
        sa.UniqueConstraint(
            "resource_type",
            "resource_id",
            "principal_type",
            "principal_id",
            "permission",
            name="uq_resource_acl_entry",
        ),
    )
    op.create_index("ix_resource_acl_org_id", "resource_acl", ["org_id"])
    op.create_index(
        "ix_resource_acl_resource", "resource_acl", ["org_id", "resource_type", "resource_id"]
    )
    op.create_index(
        "ix_resource_acl_principal", "resource_acl", ["org_id", "principal_type", "principal_id"]
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("actor_id", sa.String(32), nullable=True),
        sa.Column("actor_name", sa.String(128), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("resource_type", sa.String(32), nullable=True),
        sa.Column("resource_id", sa.String(64), nullable=True),
        sa.Column("before", JSON, nullable=True),
        sa.Column("after", JSON, nullable=True),
        sa.Column("diff", JSON, nullable=True),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column("trace_id", sa.String(128), nullable=True),
        sa.Column("method", sa.String(8), nullable=True),
        sa.Column("path", sa.String(512), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_logs"),
    )
    op.create_index("ix_audit_logs_org_id", "audit_logs", ["org_id"])
    op.create_index("ix_audit_logs_actor_id", "audit_logs", ["actor_id"])
    op.create_index("ix_audit_logs_trace_id", "audit_logs", ["trace_id"])
    op.create_index("ix_audit_logs_org_created", "audit_logs", ["org_id", "created_at"])
    op.create_index(
        "ix_audit_logs_resource", "audit_logs", ["org_id", "resource_type", "resource_id"]
    )

    op.bulk_insert(
        permissions,
        [{"id": uuid.uuid4().hex, "code": code, "name": name} for code, name in PERMISSIONS.items()],
    )


def downgrade() -> None:
    for table in (
        "audit_logs",
        "resource_acl",
        "user_roles",
        "role_permissions",
        "permissions",
        "roles",
        "user_groups",
        "groups",
        "users",
        "departments",
        "organizations",
    ):
        op.drop_table(table)
