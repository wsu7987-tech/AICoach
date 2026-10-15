"""Decouple business releases from the removed legacy ModelConfig.

Revision ID: 0005_remove_legacy_model_config
Revises: 0004_managed_models

This migration is intentionally destructive: every row whose historical
meaning depended on legacy ModelConfig is deleted instead of translated.
Product runtime model selection is owned exclusively by
managed_model + runtime_model_state after this revision.
"""

import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import mysql

from alembic import op

revision = "0005_remove_legacy_model_config"
down_revision = "0004_managed_models"
branch_labels = None
depends_on = None

JSON = mysql.JSON()


def _drop_foreign_keys(table_name: str, columns: set[str]) -> None:
    inspector = inspect(op.get_bind())
    for foreign_key in inspector.get_foreign_keys(table_name):
        if columns.intersection(foreign_key.get("constrained_columns") or []):
            op.drop_constraint(foreign_key["name"], table_name, type_="foreignkey")


def _drop_indexes(table_name: str, columns: set[str]) -> None:
    inspector = inspect(op.get_bind())
    for index in inspector.get_indexes(table_name):
        if columns.intersection(index.get("column_names") or []):
            op.drop_index(index["name"], table_name=table_name)


def upgrade() -> None:
    release_columns = {
        "default_model_config_id",
        "model_config_hash",
        "release_fingerprint",
    }
    trace_columns = {
        "release_fingerprint",
        "effective_model_config_id",
        "model_config_hash",
        "model_config_snapshot_json",
    }
    evaluation_columns = {
        "release_fingerprint",
        "effective_model_config_id",
        "model_config_hash",
        "model_config_snapshot_json",
    }

    # No legacy history compatibility is retained. These records all encoded a
    # mandatory or effective ModelConfig identity, so their meaning cannot be
    # preserved after removing that subsystem. Child rows are removed first.
    op.execute(sa.text("DELETE FROM evaluation_case_result"))
    op.execute(sa.text("DELETE FROM evaluation_run"))
    op.execute(sa.text("DELETE FROM llm_call_trace"))
    op.execute(sa.text("DELETE FROM intent_request_trace"))
    op.execute(sa.text("UPDATE runtime_state SET active_release_id = NULL"))
    op.execute(sa.text("DELETE FROM config_release"))
    op.execute(
        sa.text(
            "UPDATE runtime_model_state SET default_model_id = NULL "
            "WHERE default_model_id IN ("
            "SELECT id FROM managed_model "
            "WHERE credential_id IS NULL OR credential_ref IS NOT NULL)"
        )
    )
    op.execute(
        sa.text(
            "DELETE FROM managed_model "
            "WHERE credential_id IS NULL OR credential_ref IS NOT NULL"
        )
    )
    op.execute(
        sa.text(
            "DELETE FROM provider_credential WHERE id NOT IN ("
            "SELECT credential_id FROM managed_model)"
        )
    )

    _drop_foreign_keys("config_release", release_columns)
    _drop_foreign_keys("intent_request_trace", trace_columns)
    _drop_foreign_keys("evaluation_run", evaluation_columns)
    _drop_indexes("config_release", release_columns)
    _drop_indexes("intent_request_trace", trace_columns)
    _drop_indexes("evaluation_run", evaluation_columns)

    with op.batch_alter_table("config_release") as batch:
        for column in release_columns:
            batch.drop_column(column)

    with op.batch_alter_table("intent_request_trace") as batch:
        for column in trace_columns:
            batch.drop_column(column)
        batch.add_column(sa.Column("managed_model_uid", sa.String(length=69), nullable=True))
        batch.add_column(sa.Column("managed_model_snapshot_json", JSON, nullable=True))

    op.create_index(
        "ix_intent_request_trace_managed_model_uid",
        "intent_request_trace",
        ["managed_model_uid"],
    )
    op.create_index(
        "ix_intent_request_trace_managed_model_created_at",
        "intent_request_trace",
        ["managed_model_uid", "created_at"],
    )

    with op.batch_alter_table("evaluation_run") as batch:
        for column in evaluation_columns:
            batch.drop_column(column)
        batch.add_column(sa.Column("managed_model_uid", sa.String(length=69), nullable=False))
        batch.add_column(sa.Column("managed_model_snapshot_json", JSON, nullable=False))

    op.create_index(
        "ix_evaluation_run_managed_model_uid",
        "evaluation_run",
        ["managed_model_uid"],
    )

    with op.batch_alter_table("managed_model") as batch:
        batch.drop_column("credential_ref")
        batch.alter_column(
            "credential_id",
            existing_type=sa.BigInteger(),
            nullable=False,
        )

    op.drop_table("model_config")


def downgrade() -> None:
    raise RuntimeError(
        "0005 removed legacy ModelConfig data and bindings permanently; restore from backup"
    )
