"""Readiness checks derived from the ORM schema, never a duplicate table list."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import bindparam, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

# Register every production table before deriving Base.metadata.
from app.db import models as _models  # noqa: F401
from app.db.base import Base


def expected_schema_revision() -> str:
    """Resolve Alembic's current head rather than duplicate a revision constant."""

    backend_root = Path(__file__).resolve().parents[2]
    config = Config(str(backend_root / "alembic.ini"))
    return ScriptDirectory.from_config(config).get_current_head()


def required_schema() -> dict[str, frozenset[str]]:
    """The ORM metadata is the sole source of required tables and columns."""

    return {
        table.name: frozenset(column.name for column in table.columns)
        for table in Base.metadata.sorted_tables
    }


class DatabaseSchemaReadiness:
    """Check DB reachability, Alembic head, and metadata-derived schema health."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._expected_revision = expected_schema_revision()
        self._required_schema = required_schema()

    async def __call__(self) -> bool:
        try:
            async with self._engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
                version = await connection.scalar(text("SELECT version_num FROM alembic_version"))
                statement = text(
                    "SELECT TABLE_NAME AS table_name, COLUMN_NAME AS column_name "
                    "FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME IN :table_names"
                ).bindparams(bindparam("table_names", expanding=True))
                rows = (
                    await connection.execute(
                        statement, {"table_names": list(self._required_schema)}
                    )
                ).mappings()
                columns_by_table: dict[str, set[str]] = {}
                for row in rows:
                    columns_by_table.setdefault(row["table_name"], set()).add(row["column_name"])
            schema_is_healthy = all(
                columns <= columns_by_table.get(table, set())
                for table, columns in self._required_schema.items()
            )
            return version == self._expected_revision and schema_is_healthy
        except SQLAlchemyError:
            return False
