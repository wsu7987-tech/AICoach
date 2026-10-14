"""Add encrypted credentials and product-facing managed models.

Revision ID: 0004_managed_models
Revises: 0003_model_timeout_double
"""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "0004_managed_models"
down_revision = "0003_model_timeout_double"
branch_labels = None
depends_on = None

UTC_DATETIME = mysql.DATETIME(fsp=6)
JSON = mysql.JSON()
TABLE_OPTIONS = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"}


def upgrade() -> None:
    op.create_table(
        "provider_credential",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("credential_uid", sa.String(length=69), nullable=False),
        sa.Column("encrypted_secret", sa.Text(), nullable=False),
        sa.Column("secret_hint", sa.String(length=16), nullable=False),
        sa.Column("key_version", sa.String(length=32), nullable=False, server_default="v1"),
        sa.Column("last_verified_at", UTC_DATETIME, nullable=True),
        sa.Column("created_at", UTC_DATETIME, nullable=False),
        sa.Column("updated_at", UTC_DATETIME, nullable=False),
        sa.UniqueConstraint("credential_uid", name="uq_provider_credential_uid"),
        **TABLE_OPTIONS,
    )
    op.create_table(
        "managed_model",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("model_uid", sa.String(length=69), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        # Internal protocol adapter id, not a user-facing vendor selection.
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=256), nullable=False),
        sa.Column("base_url", sa.String(length=2048), nullable=False),
        sa.Column("credential_id", sa.BigInteger(), nullable=True),
        sa.Column("credential_ref", sa.String(length=255), nullable=True),
        sa.Column("params_json", JSON, nullable=False),
        sa.Column("timeout_seconds", sa.Double(), nullable=False),
        sa.Column("max_retries", sa.Integer(), nullable=False),
        sa.Column("max_concurrency", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", UTC_DATETIME, nullable=False),
        sa.Column("updated_at", UTC_DATETIME, nullable=False),
        sa.ForeignKeyConstraint(["credential_id"], ["provider_credential.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("model_uid", name="uq_managed_model_uid"),
        sa.UniqueConstraint("credential_id", name="uq_managed_model_credential_id"),
        **TABLE_OPTIONS,
    )
    op.create_table(
        "runtime_model_state",
        sa.Column("id", sa.SmallInteger(), primary_key=True, autoincrement=False),
        sa.Column("default_model_id", sa.BigInteger(), nullable=True),
        sa.Column("updated_at", UTC_DATETIME, nullable=False),
        sa.CheckConstraint("id = 1", name="ck_runtime_model_state_singleton"),
        sa.ForeignKeyConstraint(["default_model_id"], ["managed_model.id"], ondelete="RESTRICT"),
        **TABLE_OPTIONS,
    )
    op.create_index(
        "ix_runtime_model_state_default_model_id",
        "runtime_model_state",
        ["default_model_id"],
    )
    op.execute(
        sa.text(
            "INSERT INTO runtime_model_state (id, default_model_id, updated_at) "
            "VALUES (1, NULL, CURRENT_TIMESTAMP(6))"
        )
    )


def downgrade() -> None:
    op.drop_index("ix_runtime_model_state_default_model_id", table_name="runtime_model_state")
    op.drop_table("runtime_model_state")
    op.drop_table("managed_model")
    op.drop_table("provider_credential")
