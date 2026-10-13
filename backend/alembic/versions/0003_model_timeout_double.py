"""Preserve model timeout/hash through database round trips.

Revision ID: 0003_model_timeout_double
Revises: 0002_release_fp_index
"""

import sqlalchemy as sa

from alembic import context, op

revision = "0003_model_timeout_double"
down_revision = "0002_release_fp_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # FLOAT's text-protocol representation is what existing Python consumers
    # hashed. Direct FLOAT -> DOUBLE widens the binary approximation (30.1 can
    # become 30.100000381469727), so copy the old text representation first.
    # MySQL 8's final column swap is atomic DDL. Re-entry after an interrupted
    # migration is safe before or after that swap.
    if not context.is_offline_mode():
        columns = {c["name"]: c for c in sa.inspect(op.get_bind()).get_columns("model_config")}
        if isinstance(columns["timeout_seconds"]["type"], sa.Double):
            return
        if "timeout_seconds_upgrade" not in columns:
            op.add_column("model_config", sa.Column("timeout_seconds_upgrade", sa.Double()))
    else:
        op.add_column("model_config", sa.Column("timeout_seconds_upgrade", sa.Double()))
    op.execute("UPDATE model_config SET timeout_seconds_upgrade = CAST(timeout_seconds AS CHAR)")
    op.execute(
        "ALTER TABLE model_config DROP COLUMN timeout_seconds, "
        "CHANGE COLUMN timeout_seconds_upgrade timeout_seconds DOUBLE NOT NULL"
    )


def downgrade() -> None:
    if not context.is_offline_mode():
        lossy = op.get_bind().scalar(
            sa.text(
                "SELECT COUNT(*) FROM model_config WHERE "
                "CAST(CAST(timeout_seconds AS FLOAT) AS CHAR) <> CAST(timeout_seconds AS CHAR)"
            )
        )
        if lossy:
            raise RuntimeError("cannot narrow model timeout without changing immutable values")
    op.alter_column(
        "model_config",
        "timeout_seconds",
        existing_type=sa.Double(),
        type_=sa.Float(),
        existing_nullable=False,
    )
