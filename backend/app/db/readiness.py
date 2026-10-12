from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

REQUIRED_BUSINESS_COLUMNS = {
    "config_draft": frozenset({"id", "schema_version", "draft_json", "updated_by", "updated_at"}),
    "model_config": frozenset(
        {
            "id",
            "name",
            "version",
            "provider",
            "model",
            "base_url",
            "params_json",
            "timeout_seconds",
            "max_retries",
            "max_concurrency",
            "structured_output_mode",
            "credential_ref",
            "model_config_hash",
            "enabled",
            "immutable_from_at",
            "created_at",
        }
    ),
    "config_release": frozenset(
        {
            "id",
            "version",
            "snapshot_json",
            "config_snapshot_hash",
            "default_model_config_id",
            "model_config_hash",
            "release_fingerprint",
            "note",
            "created_by",
            "created_at",
        }
    ),
    "runtime_state": frozenset({"id", "active_release_id", "updated_at"}),
    "intent_request_trace": frozenset(
        {
            "id",
            "trace_id",
            "request_id",
            "parent_trace_id",
            "source",
            "input",
            "context_json",
            "release_id",
            "config_snapshot_hash",
            "release_fingerprint",
            "effective_model_config_id",
            "model_config_hash",
            "model_config_snapshot_json",
            "final_route",
            "final_result_json",
            "reason_summary",
            "evidence_json",
            "validation_json",
            "timeline_json",
            "latency_ms",
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "retry_count",
            "status",
            "error_code",
            "error_message",
            "created_at",
        }
    ),
    "llm_call_trace": frozenset(
        {
            "id",
            "trace_id",
            "attempt_no",
            "provider",
            "model",
            "model_params_json",
            "final_prompt",
            "prompt_hash",
            "raw_request_json",
            "raw_response_json",
            "final_prompt_truncated",
            "raw_request_truncated",
            "raw_response_truncated",
            "provider_request_id",
            "provider_model_version",
            "system_fingerprint",
            "finish_reason",
            "parsed_result_json",
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "latency_ms",
            "status",
            "error_code",
            "error_message",
            "created_at",
        }
    ),
    "evaluation_dataset": frozenset(
        {
            "id",
            "name",
            "version",
            "source_filename",
            "hash",
            "normalized_cases_json",
            "created_at",
        }
    ),
    "evaluation_run": frozenset(
        {
            "id",
            "dataset_id",
            "dataset_hash",
            "release_id",
            "config_snapshot_hash",
            "release_fingerprint",
            "effective_model_config_id",
            "model_config_hash",
            "model_config_snapshot_json",
            "repeat_count",
            "worker_concurrency",
            "status",
            "progress_json",
            "claimed_by",
            "heartbeat_at",
            "error",
            "created_at",
            "started_at",
            "finished_at",
        }
    ),
    "evaluation_case_result": frozenset(
        {
            "id",
            "run_id",
            "case_id",
            "repeat_index",
            "expected_json",
            "actual_json",
            "passed",
            "error_type",
            "error_message",
            "request_id",
            "trace_id",
            "latency_ms",
        }
    ),
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
                            "WHERE TABLE_SCHEMA = DATABASE() "
                            "AND TABLE_NAME IN ("
                            "'config_draft', 'model_config', 'config_release', 'runtime_state', "
                            "'intent_request_trace', 'llm_call_trace', 'evaluation_dataset', "
                            "'evaluation_run', 'evaluation_case_result'"
                            ")"
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
