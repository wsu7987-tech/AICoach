from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

REQUIRED_BUSINESS_COLUMNS = {
    "config_draft": frozenset({"id", "schema_version", "draft_json"}),
    "model_config": frozenset({"id", "credential_ref", "model_config_hash"}),
    "config_release": frozenset(
        {"id", "version", "default_model_config_id", "release_fingerprint"}
    ),
    "runtime_state": frozenset({"id", "active_release_id"}),
    "intent_request_trace": frozenset({"trace_id", "status", "created_at"}),
    "llm_call_trace": frozenset({"trace_id", "attempt_no", "status"}),
    "evaluation_dataset": frozenset({"id", "hash", "normalized_cases_json"}),
    "evaluation_run": frozenset({"id", "dataset_id", "worker_concurrency", "heartbeat_at"}),
    "evaluation_case_result": frozenset({"run_id", "case_id", "repeat_index", "trace_id"}),
}


def expected_schema_revision() -> str:
    """Resolve Alembic's current head rather than duplicating a revision constant."""

    backend_root = Path(__file__).resolve().parents[2]
    config = Config(str(backend_root / "alembic.ini"))
    return ScriptDirectory.from_config(config).get_current_head()


class DatabaseSchemaReadiness:
    """Checks DB reachability, Alembic head, and required table/column health."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._expected_revision = expected_schema_revision()

    async def __call__(self) -> bool:
        try:
            async with self._engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
                version = await connection.scalar(text("SELECT version_num FROM alembic_version"))
                rows = (
                    await connection.execute(
                        text(
                            "SELECT TABLE_NAME AS table_name, COLUMN_NAME AS column_name "
                            "FROM information_schema.COLUMNS "
                            "WHERE TABLE_SCHEMA = DATABASE()"
                        )
                    )
                ).mappings()
                columns_by_table: dict[str, set[str]] = {}
                for row in rows:
                    columns_by_table.setdefault(row["table_name"], set()).add(row["column_name"])
            schema_is_healthy = all(
                required_columns <= columns_by_table.get(table_name, set())
                for table_name, required_columns in REQUIRED_BUSINESS_COLUMNS.items()
            )
            return version == self._expected_revision and schema_is_healthy
        except SQLAlchemyError:
            return False
