"""Replace unused evaluation records with the V2 gold-answer evaluation contract.

Revision ID: 0006_evaluation_v2
Revises: 0005_remove_legacy_model_config
"""

import sqlalchemy as sa
from sqlalchemy.dialects.mysql import DATETIME

from alembic import op

revision = "0006_evaluation_v2"
down_revision = "0005_remove_legacy_model_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Old unlabelled/V1 evaluation records have no valid V2 gold-answer meaning.
    # This only clears evaluation data; business releases, models and traces remain.
    for table in ("evaluation_case_result", "evaluation_run", "evaluation_dataset"):
        op.execute(sa.text(f"DELETE FROM {table}"))
    with op.batch_alter_table("evaluation_run") as batch:
        batch.add_column(sa.Column("name", sa.String(128), nullable=False))
        batch.add_column(sa.Column("config_snapshot_json", sa.JSON(), nullable=False))
        batch.add_column(sa.Column("evaluation_config_json", sa.JSON(), nullable=False))
        batch.add_column(sa.Column("cases_json", sa.JSON(), nullable=False))
        batch.add_column(sa.Column("parent_run_id", sa.BigInteger(), nullable=True))
        batch.add_column(
            sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default="0")
        )
    with op.batch_alter_table("evaluation_case_result") as batch:
        batch.add_column(sa.Column("auto_status", sa.String(32), nullable=False))
        batch.add_column(sa.Column("verdict_json", sa.JSON(), nullable=False))
        batch.add_column(sa.Column("review_json", sa.JSON(), nullable=False))
        batch.add_column(
            sa.Column("review_revision", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(sa.Column("created_at", DATETIME(fsp=6), nullable=False))


def downgrade() -> None:
    raise RuntimeError("V2 evaluation replaces old evaluation data; restore a backup to roll back")
