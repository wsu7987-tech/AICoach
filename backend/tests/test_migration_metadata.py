from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.db.base import Base
from app.db.readiness import required_schema


def test_migration_revision_ids_fit_alembic_version_column() -> None:
    backend_root = Path(__file__).resolve().parents[1]
    script = ScriptDirectory.from_config(Config(str(backend_root / "alembic.ini")))
    revision_ids = [revision.revision for revision in script.walk_revisions()]

    assert revision_ids
    assert all(revision_id is not None and len(revision_id) <= 32 for revision_id in revision_ids)
    assert script.get_current_head() == "0003_model_timeout_double"


def test_readiness_schema_is_derived_from_sqlalchemy_metadata() -> None:
    assert required_schema() == {
        table.name: frozenset(column.name for column in table.columns)
        for table in Base.metadata.sorted_tables
    }
    assert "REQUIRED_BUSINESS_COLUMNS" not in Path("app/db/readiness.py").read_text(
        encoding="utf-8"
    )
