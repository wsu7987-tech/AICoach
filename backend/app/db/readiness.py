from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine


def expected_schema_revision() -> str:
    """Resolve Alembic's current head rather than duplicating a revision constant."""

    backend_root = Path(__file__).resolve().parents[2]
    config = Config(str(backend_root / "alembic.ini"))
    return ScriptDirectory.from_config(config).get_current_head()


class DatabaseSchemaReadiness:
    """Checks database reachability and that its schema is at Alembic head only."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._expected_revision = expected_schema_revision()

    async def __call__(self) -> bool:
        try:
            async with self._engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
                version = await connection.scalar(text("SELECT version_num FROM alembic_version"))
            return version == self._expected_revision
        except SQLAlchemyError:
            return False
