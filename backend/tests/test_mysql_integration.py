"""Destructive tests restricted to an explicitly named isolated MySQL test database."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, inspect, select
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
    RuntimeState,
)
from app.db.readiness import DatabaseSchemaReadiness
from app.main import create_app

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

    _alembic("downgrade", "base")
    _alembic("upgrade", "head")
