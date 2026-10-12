"""Allow releases with the same immutable fingerprint.

Revision ID: 0002_release_fp_index
Revises: 0001_initial_schema
Create Date: 2026-10-12
"""

import sqlalchemy as sa

from alembic import context, op

revision = "0002_release_fp_index"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def _index_exists(index_name: str) -> bool:
    """Return whether MySQL has the named physical index on config_release."""

    count = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT COUNT(*) "
                "FROM information_schema.STATISTICS "
                "WHERE TABLE_SCHEMA = DATABASE() "
                "AND TABLE_NAME = 'config_release' "
                "AND INDEX_NAME = :index_name"
            ),
            {"index_name": index_name},
        )
        .scalar_one()
    )
    return count > 0


def upgrade() -> None:
    """Replace the historical unique index, including a prior interrupted attempt.

    MySQL DDL auto-commits.  The former revision ID exceeded Alembic's
    ``version_num`` width, so an attempted upgrade could have completed these
    DDL statements while remaining recorded at 0001.  Check physical indexes
    before issuing each operation so rerunning this corrected migration records
    the new revision without requiring manual schema repair.
    """

    if context.is_offline_mode():
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
        return

    if _index_exists("uq_config_release_release_fingerprint"):
        op.drop_constraint(
            "uq_config_release_release_fingerprint",
            "config_release",
            type_="unique",
        )
    if not _index_exists("ix_config_release_release_fingerprint"):
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
        if _index_exists("ix_config_release_release_fingerprint"):
            op.drop_index("ix_config_release_release_fingerprint", table_name="config_release")
        if not _index_exists("uq_config_release_release_fingerprint"):
            op.create_unique_constraint(
                "uq_config_release_release_fingerprint",
                "config_release",
                ["release_fingerprint"],
            )
        return

    op.drop_index("ix_config_release_release_fingerprint", table_name="config_release")
    op.create_unique_constraint(
        "uq_config_release_release_fingerprint",
        "config_release",
        ["release_fingerprint"],
    )
