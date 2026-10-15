"""model providers, models and chat routing (model admin page)

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-15 18:00:00

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_PERMISSIONS = {"admin:model": "管理模型（提供方、模型检测、对话模型切换）"}


def upgrade() -> None:
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

    op.create_table(
        "llm_providers",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("base_url", sa.String(512), nullable=False),
        sa.Column("api_key_encrypted", sa.Text()),
        sa.Column("api_key_hint", sa.String(32)),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.String(32)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("name", name="uq_llm_providers_name"),
    )

    op.create_table(
        "llm_models",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "provider_id",
            sa.String(32),
            sa.ForeignKey(
                "llm_providers.id",
                ondelete="CASCADE",
                name="fk_llm_models_provider_id_llm_providers",
            ),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("origin", sa.String(16), nullable=False),
        sa.Column("base_url", sa.String(512)),
        sa.Column("path", sa.String(128)),
        sa.Column("last_check_status", sa.String(16)),
        sa.Column("last_check_at", sa.DateTime(timezone=True)),
        sa.Column("last_check_latency_ms", sa.Integer()),
        sa.Column("last_check_message", sa.Text()),
        sa.Column("detected_dim", sa.Integer()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("provider_id", "name", name="uq_llm_models_provider_id_name"),
    )
    op.create_index("ix_llm_models_provider_id", "llm_models", ["provider_id"])

    op.create_table(
        "llm_routes",
        sa.Column("scene", sa.String(32), primary_key=True),
        sa.Column(
            "model_id",
            sa.String(32),
            sa.ForeignKey(
                "llm_models.id", ondelete="RESTRICT", name="fk_llm_routes_model_id_llm_models"
            ),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(32)),
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
    op.drop_table("llm_routes")
    op.drop_table("llm_models")
    op.drop_table("llm_providers")
