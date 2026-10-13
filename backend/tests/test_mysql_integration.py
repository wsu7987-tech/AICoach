"""Destructive tests restricted to an explicitly named isolated MySQL test database."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from app.bootstrap.service import (
    BootstrapConflictError,
    BootstrapValidationError,
    import_bootstrap_draft,
    parse_bootstrap_json,
)
from app.core.settings import Settings
from app.db.database import Database
from app.db.models import (
    ConfigDraft,
    ConfigRelease,
    EvaluationCaseResult,
    EvaluationDataset,
    EvaluationRun,
    IntentRequestTrace,
    LLMCallTrace,
    ModelConfig,
    RuntimeState,
)
from app.db.readiness import DatabaseSchemaReadiness
from app.main import create_app
from app.schemas.config import ModelConfigCreate, business_snapshot, model_hash, release_fingerprint
from tests.test_config_contract import document, model_input

TEST_DATABASE_URL = os.getenv("MYSQL_TEST_DATABASE_URL")
BACKEND_ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP_PATH = BACKEND_ROOT.parent / "bootstrap" / "initial-config.v1.json"
EXPECTED_TABLES = {
    "config_draft",
    "model_config",
    "config_release",
    "runtime_state",
    "intent_request_trace",
    "llm_call_trace",
    "evaluation_dataset",
    "evaluation_run",
    "evaluation_case_result",
}


def _require_isolated_mysql() -> str:
    if not TEST_DATABASE_URL:
        pytest.skip(
            "MYSQL_TEST_DATABASE_URL is not configured; MySQL 8 integration tests are skipped"
        )
    url = make_url(TEST_DATABASE_URL)
    if not url.drivername.startswith("mysql+") or not url.database:
        pytest.fail("MYSQL_TEST_DATABASE_URL must be a MySQL URL with an isolated database name")
    if not url.database.startswith("ai_coach_task002_test_"):
        pytest.fail("refusing destructive tests outside ai_coach_task002_test_* database")
    return TEST_DATABASE_URL


def _alembic(*arguments: str) -> subprocess.CompletedProcess[str]:
    url = _require_isolated_mysql()
    environment = {**os.environ, "DATABASE_URL": url}
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", *arguments],
        cwd=BACKEND_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


def _database() -> Database:
    return Database(Settings(_env_file=None, database_url=_require_isolated_mysql()))


async def _rename_table(source_name: str, target_name: str) -> None:
    database = _database()
    try:
        async with database.engine.begin() as connection:
            await connection.execute(text(f"RENAME TABLE {source_name} TO {target_name}"))
    finally:
        await database.dispose()


async def _drop_and_restore_release_snapshot_column(*, restore: bool = False) -> None:
    database = _database()
    try:
        async with database.engine.begin() as connection:
            if restore:
                await connection.execute(
                    text(
                        "ALTER TABLE config_release "
                        "ADD COLUMN snapshot_json JSON NOT NULL AFTER version"
                    )
                )
            else:
                await connection.execute(
                    text("ALTER TABLE config_release DROP COLUMN snapshot_json")
                )
    finally:
        await database.dispose()


async def _simulate_interrupted_release_fingerprint_upgrade() -> str | None:
    """Leave the exact MySQL DDL state from the former overlong revision."""

    database = _database()
    try:
        async with database.engine.begin() as connection:
            await connection.execute(
                text("ALTER TABLE config_release DROP INDEX uq_config_release_release_fingerprint")
            )
            await connection.execute(
                text(
                    "CREATE INDEX ix_config_release_release_fingerprint "
                    "ON config_release (release_fingerprint)"
                )
            )
        async with database.engine.connect() as connection:
            return await connection.scalar(text("SELECT version_num FROM alembic_version"))
    finally:
        await database.dispose()


async def _alembic_version() -> str | None:
    database = _database()
    try:
        async with database.engine.connect() as connection:
            return await connection.scalar(text("SELECT version_num FROM alembic_version"))
    finally:
        await database.dispose()


def test_mysql_migration_bootstrap_constraints_and_readiness() -> None:
    _alembic("downgrade", "base")
    upgrade = _alembic("upgrade", "head")
    assert "Running upgrade" in upgrade.stderr

    async def scenario() -> None:
        database = _database()
        try:
            async with database.engine.connect() as connection:
                table_names = await connection.run_sync(
                    lambda sync: set(inspect(sync).get_table_names())
                )
                assert EXPECTED_TABLES <= table_names
                trace_columns = await connection.run_sync(
                    lambda sync: {
                        column["name"]
                        for column in inspect(sync).get_columns("intent_request_trace")
                    }
                )
                assert {
                    "model_config_snapshot_json",
                    "config_snapshot_hash",
                    "release_fingerprint",
                } <= trace_columns
                attempt_columns = await connection.run_sync(
                    lambda sync: {
                        column["name"] for column in inspect(sync).get_columns("llm_call_trace")
                    }
                )
                assert {
                    "final_prompt_truncated",
                    "raw_request_truncated",
                    "raw_response_truncated",
                } <= attempt_columns
                run_columns = await connection.run_sync(
                    lambda sync: {
                        column["name"] for column in inspect(sync).get_columns("evaluation_run")
                    }
                )
                assert {"dataset_hash", "worker_concurrency", "heartbeat_at"} <= run_columns

            payload = parse_bootstrap_json(BOOTSTRAP_PATH.read_text(encoding="utf-8"))
            async with database.transaction() as session:
                first = await import_bootstrap_draft(session, payload)
            assert first.created is True

            async with database.transaction() as session:
                repeated = await import_bootstrap_draft(session, payload)
            assert repeated.created is False

            async with database.transaction() as session:
                draft = await session.get(ConfigDraft, 1)
                assert draft is not None
                assert draft.draft_json == payload.model_dump(mode="json")
                assert await session.scalar(select(func.count(ConfigRelease.id))) == 0
                assert await session.scalar(select(func.count(RuntimeState.id))) == 0
                assert await session.scalar(select(func.count(EvaluationRun.id))) == 0

            edited = payload.model_dump(mode="json")
            edited["prompt_template"] = {"system": "edited by developer"}
            async with database.transaction() as session:
                draft = await session.get(ConfigDraft, 1)
                assert draft is not None
                draft.draft_json = edited

            async with database.transaction() as session:
                with pytest.raises(BootstrapConflictError):
                    await import_bootstrap_draft(session, payload)

            with pytest.raises(BootstrapValidationError):
                parse_bootstrap_json('{"schema_version": 1, "unexpected": true}')

            with pytest.raises(RuntimeError):
                async with database.transaction() as session:
                    await session.execute(delete(ConfigDraft))
                    await import_bootstrap_draft(session, payload)
                    raise RuntimeError("force rollback")
            async with database.transaction() as session:
                assert await session.get(ConfigDraft, 1) is not None

            async with database.transaction() as session:
                trace = IntentRequestTrace(
                    trace_id="trace-cleanup",
                    request_id="same-request-id",
                    source="test",
                    input="测试",
                    status="success",
                )
                session.add(trace)
                await session.flush()
                session.add(
                    LLMCallTrace(
                        trace_id=trace.trace_id,
                        attempt_no=1,
                        provider="test",
                        model="test",
                        status="success",
                    )
                )
                dataset = EvaluationDataset(
                    name="test",
                    version="v1",
                    source_filename="test.json",
                    hash="a" * 64,
                    normalized_cases_json=[],
                )
                session.add(dataset)
                await session.flush()
                run = EvaluationRun(
                    dataset_id=dataset.id,
                    dataset_hash=dataset.hash,
                    config_snapshot_hash="b" * 64,
                    release_fingerprint="c" * 64,
                    model_config_hash="d" * 64,
                    model_config_snapshot_json={},
                    repeat_count=1,
                    worker_concurrency=1,
                    status="finished",
                )
                session.add(run)
                await session.flush()
                session.add(
                    EvaluationCaseResult(
                        run_id=run.id,
                        case_id="case-1",
                        repeat_index=0,
                        expected_json={},
                        trace_id=trace.trace_id,
                    )
                )

            with pytest.raises(IntegrityError):
                async with database.transaction() as session:
                    session.add(
                        LLMCallTrace(
                            trace_id="trace-cleanup",
                            attempt_no=1,
                            provider="test",
                            model="test",
                            status="success",
                        )
                    )
                    await session.flush()

            with pytest.raises(IntegrityError):
                async with database.transaction() as session:
                    session.add(
                        IntentRequestTrace(
                            trace_id="trace-cleanup",
                            request_id="same-request-id",
                            source="test",
                            input="重复 trace",
                            status="success",
                        )
                    )
                    await session.flush()

            with pytest.raises(IntegrityError):
                async with database.transaction() as session:
                    session.add(
                        EvaluationCaseResult(
                            run_id=run.id,
                            case_id="case-1",
                            repeat_index=0,
                            expected_json={},
                        )
                    )
                    await session.flush()

            async with database.transaction() as session:
                await session.execute(
                    delete(IntentRequestTrace).where(IntentRequestTrace.trace_id == "trace-cleanup")
                )
            async with database.transaction() as session:
                assert await session.scalar(select(func.count(LLMCallTrace.id))) == 0
                assert await session.scalar(select(func.count(EvaluationCaseResult.id))) == 1

            readiness = DatabaseSchemaReadiness(database.engine)
            assert await readiness() is True
        finally:
            await database.dispose()

    asyncio.run(scenario())

    settings = Settings(_env_file=None, database_url=_require_isolated_mysql(), log_level="WARNING")
    with TestClient(create_app(settings=settings)) as client:
        ready = client.get("/ready")
        assert ready.status_code == 200
        assert ready.json()["checks"] == {"database": "ok"}

        # Bootstrap does not create a Release, so this also proves `/ready` does
        # not depend on an Active Release or a Model Config row.
        asyncio.run(_drop_and_restore_release_snapshot_column())
        try:
            incomplete_columns = client.get("/ready")
            assert incomplete_columns.status_code == 503
            assert incomplete_columns.json()["checks"] == {"database": "failed"}
        finally:
            asyncio.run(_drop_and_restore_release_snapshot_column(restore=True))

        restored_schema = client.get("/ready")
        assert restored_schema.status_code == 200
        assert restored_schema.json()["checks"] == {"database": "ok"}

        asyncio.run(_rename_table("evaluation_case_result", "evaluation_case_result_missing"))
        try:
            incomplete_schema = client.get("/ready")
            assert incomplete_schema.status_code == 503
            assert incomplete_schema.json()["checks"] == {"database": "failed"}
        finally:
            asyncio.run(_rename_table("evaluation_case_result_missing", "evaluation_case_result"))

    _alembic("downgrade", "base")
    _alembic("upgrade", "head")


def test_mysql_release_fingerprint_revision_preserves_existing_releases() -> None:
    _alembic("downgrade", "base")
    _alembic("upgrade", "0001_initial_schema")

    async def seed_0001_release() -> tuple[int, str]:
        database = _database()
        try:
            async with database.transaction() as session:
                config = ModelConfigCreate(**model_input(timeout_seconds=1.0))
                model_config = ModelConfig(
                    **config.model_dump(mode="json"), model_config_hash=model_hash(config)
                )
                session.add(model_config)
                await session.flush()
                release = ConfigRelease(
                    version="release-v1",
                    snapshot_json=business_snapshot(document())[0],
                    config_snapshot_hash=business_snapshot(document())[1],
                    default_model_config_id=model_config.id,
                    model_config_hash=model_config.model_config_hash,
                    release_fingerprint=release_fingerprint(
                        business_snapshot(document())[1],
                        model_config.id,
                        model_config.model_config_hash,
                    ),
                    note="pre-0002 release",
                    created_by="test",
                )
                session.add(release)
                await session.flush()
                return release.id, release.release_fingerprint
        finally:
            await database.dispose()

    existing_release_id, original_fingerprint = asyncio.run(seed_0001_release())
    assert asyncio.run(_simulate_interrupted_release_fingerprint_upgrade()) == "0001_initial_schema"
    _alembic("upgrade", "head")
    assert asyncio.run(_alembic_version()) == "0003_model_timeout_double"

    async def verify_0002_release_behavior() -> None:
        database = _database()
        try:
            async with database.transaction() as session:
                existing = await session.get(ConfigRelease, existing_release_id)
                assert existing is not None
                assert existing.version == "release-v1"
                assert existing.release_fingerprint == original_fingerprint

                session.add(
                    ConfigRelease(
                        version="release-v2",
                        snapshot_json=existing.snapshot_json,
                        config_snapshot_hash=existing.config_snapshot_hash,
                        default_model_config_id=existing.default_model_config_id,
                        model_config_hash=existing.model_config_hash,
                        release_fingerprint=existing.release_fingerprint,
                        note="same immutable configuration, new release version",
                        created_by="test",
                    )
                )

            with pytest.raises(IntegrityError):
                async with database.transaction() as session:
                    session.add(
                        ConfigRelease(
                            version="release-v2",
                            snapshot_json={"schema_version": 1},
                            config_snapshot_hash="b" * 64,
                            default_model_config_id=1,
                            model_config_hash="a" * 64,
                            release_fingerprint="different-fingerprint",
                            note="duplicate version must fail",
                            created_by="test",
                        )
                    )
                    await session.flush()

            async with database.engine.connect() as connection:
                indexes = await connection.run_sync(
                    lambda sync: inspect(sync).get_indexes("config_release")
                )
                unique_constraints = await connection.run_sync(
                    lambda sync: inspect(sync).get_unique_constraints("config_release")
                )
            fingerprint_index = next(
                index
                for index in indexes
                if index["name"] == "ix_config_release_release_fingerprint"
            )
            assert fingerprint_index["unique"] is False
            assert {constraint["name"] for constraint in unique_constraints} == {
                "uq_config_release_version"
            }
        finally:
            await database.dispose()

    asyncio.run(verify_0002_release_behavior())

    async def remove_duplicate_release_for_reversible_test_cleanup() -> None:
        database = _database()
        try:
            async with database.transaction() as session:
                await session.execute(
                    delete(ConfigRelease).where(ConfigRelease.version == "release-v2")
                )
        finally:
            await database.dispose()

    asyncio.run(remove_duplicate_release_for_reversible_test_cleanup())
    _alembic("downgrade", "base")
    _alembic("upgrade", "head")
