"""Allow releases with the same immutable fingerprint.

Revision ID: 0002_release_fingerprint_nonunique
Revises: 0001_initial_schema
Create Date: 2026-10-12
"""

import sqlalchemy as sa

from alembic import context, op

revision = "0002_release_fingerprint_nonunique"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_config_release_release_fingerprint",
        "config_release",
        type_="unique",
    )
    op.create_index(
        "ix_config_release_release_fingerprint",
        "config_release",
        ["release_fingerprint"],
        unique=False,
    )


def downgrade() -> None:
    if not context.is_offline_mode():
        bind = op.get_bind()
        duplicate = bind.execute(
            sa.text(
                "SELECT release_fingerprint "
                "FROM config_release "
                "GROUP BY release_fingerprint "
                "HAVING COUNT(*) > 1 "
                "LIMIT 1"
            )
        ).first()
        if duplicate is not None:
            raise RuntimeError(
                "cannot restore unique release_fingerprint while duplicate immutable releases exist"
            )
    op.drop_index("ix_config_release_release_fingerprint", table_name="config_release")
    op.create_unique_constraint(
        "uq_config_release_release_fingerprint",
        "config_release",
        ["release_fingerprint"],
    )
