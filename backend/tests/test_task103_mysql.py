"""TASK-103 real MySQL + localhost HTTP acceptance (explicitly isolated DB only)."""

import asyncio
import json
import threading
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import event, func, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.errors import AppError, ErrorCode
from app.core.settings import Settings
from app.db.database import Database
from app.db.models import (
    EvaluationCaseResult,
    EvaluationDataset,
    EvaluationRun,
    IntentRequestTrace,
    LLMCallTrace,
)
from app.main import create_app
from app.prompting.builder import PromptBuilder
from app.providers.factory import ModelProviderFactory
from app.providers.types import LLMAttempt
from app.schemas.config import ModelConfigCreate
from app.schemas.intent import OutputValidationIssue, SlotValue
from app.services import config_service as config
from app.services.intent_service import IntentService, TraceRecord
from app.services.runtime_config import DatabaseRuntimeConfigLoader
from app.services.trace_store import DatabaseTraceStore, cleanup_expired_traces
from tests.test_config_contract import document, model_input
from tests.test_config_mysql import mysql_url as mysql_url
from tests.test_config_mysql import reviewed_request
from tests.test_provider_contract import _completion, _wait_for_requests
from tests.test_provider_contract import scenario_server as scenario_server


def _trace(request_id: str) -> TraceRecord:
    return TraceRecord(
        trace_id=uuid4().hex,
        request_id=request_id,
        text="测试",
        attempts=[
            LLMAttempt(
                attempt_no=1,
                is_retry=False,
                provider="qwen",
                model="local",
                params={},
                raw_request={},
                latency_ms=1,
                status="success",
            )
        ],
    )


@pytest.mark.parametrize("stage", ["request", "attempt", "commit"])
def test_trace_store_mysql_failure_rolls_back_atomically(mysql_url, stage):
    async def scenario() -> None:
        db = Database(Settings(_env_file=None, database_url=mysql_url))
        store = DatabaseTraceStore(db.session_factory)
        trace = _trace(f"rollback-{stage}")

        def fail(connection, cursor, statement, parameters, context, executemany):
            normalized = statement.lower()
            if stage == "request" and "insert into intent_request_trace" in normalized:
                raise RuntimeError("request insert failure")
            if stage == "attempt" and "insert into llm_call_trace" in normalized:
                raise RuntimeError("attempt insert failure")

        def fail_commit(connection):
            if stage == "commit":
                raise RuntimeError("commit failure before DBAPI commit")

        event.listen(db.engine.sync_engine, "before_cursor_execute", fail)
        event.listen(db.engine.sync_engine, "commit", fail_commit)
        try:
            with pytest.raises(RuntimeError):
                await store.write(trace)
        finally:
            event.remove(db.engine.sync_engine, "before_cursor_execute", fail)
            event.remove(db.engine.sync_engine, "commit", fail_commit)
        async with db.transaction() as session:
            assert (
                await session.scalar(
                    select(func.count(IntentRequestTrace.id)).where(
                        IntentRequestTrace.trace_id == trace.trace_id
                    )
                )
                == 0
            )
            assert (
                await session.scalar(
                    select(func.count(LLMCallTrace.id)).where(
                        LLMCallTrace.trace_id == trace.trace_id
                    )
                )
                == 0
            )
        await db.dispose()

    asyncio.run(scenario())


def test_validation_diagnostics_and_retention_use_real_mysql(mysql_url):
    async def scenario() -> None:
        db = Database(Settings(_env_file=None, database_url=mysql_url))
        store = DatabaseTraceStore(db.session_factory)
        raw_value = "中文😀 password is secret " * 20_000
        trace = _trace("validation-retention")
        trace.validation_issues = [
            OutputValidationIssue(
                code="SLOT_SPAN_INVALID",
                slot=SlotValue(
                    name="exercise", zh="动作", value=raw_value, start=0, end=1, confidence=0
                ),
            )
        ]
        await store.write(trace)
        async with db.transaction() as session:
            stored = await session.scalar(
                select(IntentRequestTrace).where(IntentRequestTrace.trace_id == trace.trace_id)
            )
            assert stored is not None and stored.validation_json is not None
            encoded = json.dumps(stored.validation_json, ensure_ascii=False).encode("utf-8")
            issue = stored.validation_json["issues"][0]
            assert len(encoded) <= 65_536
            assert issue["code"] == "SLOT_SPAN_INVALID" and issue["truncated"] is True
            assert "secret" not in json.dumps(stored.validation_json, ensure_ascii=False)

            dataset = EvaluationDataset(
                name="retention",
                version="v1",
                source_filename="test",
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
                    case_id="case",
                    repeat_index=0,
                    expected_json={},
                    trace_id=trace.trace_id,
                )
            )
            await session.execute(
                update(IntentRequestTrace)
                .where(IntentRequestTrace.trace_id == trace.trace_id)
                .values(created_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=40))
            )
        assert (
            await cleanup_expired_traces(
                db.session_factory, trace_retention_days=30, eval_trace_retention_days=90
            )
            == 0
        )
        async with db.transaction() as session:
            assert await session.get(IntentRequestTrace, stored.id) is not None
            assert await session.scalar(select(func.count(EvaluationCaseResult.id))) == 1
        await db.dispose()

    asyncio.run(scenario())


def test_runtime_loader_trace_store_mysql_and_physical_attempts(mysql_url, scenario_server):
    """No SDK-method or DB-commit mock: two HTTP calls become two persisted rows."""

    output = json.dumps(
        {
            "route": "social_chat",
            "intents": [],
            "slots": [],
            "risk": None,
            "need_clarification": False,
            "clarification": None,
        }
    )
    scenario_server.responses = [
        {"status": 500, "payload": {"error": {"message": "retry once"}}},
        {"payload": _completion(output)},
        {"payload": _completion(output)},
    ]

    async def scenario() -> None:
        db = Database(Settings(_env_file=None, database_url=mysql_url))
        factory = ModelProviderFactory(
            lambda reference: "local-test-credential", queue_wait_timeout=1
        )
        try:
            async with db.transaction() as session:
                await config.save_draft(session, document(), None)
                model = await config.create_model(
                    session,
                    ModelConfigCreate(
                        **model_input(
                            base_url=f"http://127.0.0.1:{scenario_server.server_port}/v1",
                            max_retries=1,
                        )
                    ),
                )
                release = await config.publish(session, await reviewed_request(session, model.id))
            service = IntentService(
                DatabaseRuntimeConfigLoader(db.session_factory, ttl_seconds=60),
                factory,
                PromptBuilder(),
                DatabaseTraceStore(db.session_factory),
            )
            first = await service.analyze(text="你好", request_id="duplicate-upstream")
            second = await service.analyze(text="你好", request_id="duplicate-upstream")
            assert first.route == second.route == "social_chat"
            async with db.transaction() as session:
                traces = list(
                    await session.scalars(
                        select(IntentRequestTrace)
                        .where(IntentRequestTrace.request_id == "duplicate-upstream")
                        .order_by(IntentRequestTrace.id)
                    )
                )
                assert len(traces) == 2
                assert traces[0].trace_id != traces[1].trace_id
                assert traces[0].release_id == release["id"]
                assert traces[0].effective_model_config_id == model.id
                assert traces[0].model_config_hash == model.model_config_hash
                assert traces[0].model_config_snapshot_json == model.model_dump(mode="json")
                assert traces[0].retry_count == 1
                attempts = await session.scalar(select(func.count(LLMCallTrace.id)))
                assert attempts == 3
                first_attempts = list(
                    await session.scalars(
                        select(LLMCallTrace)
                        .where(LLMCallTrace.trace_id == traces[0].trace_id)
                        .order_by(LLMCallTrace.attempt_no)
                    )
                )
                assert [item.attempt_no for item in first_attempts] == [1, 2]
                assert all(item.model == model.model for item in first_attempts)
        finally:
            await factory.close()
            await db.dispose()

    asyncio.run(scenario())


def test_runtime_api_mysql_end_to_end(mysql_url, scenario_server, monkeypatch):
    """ASGI Runtime API -> real DB Loader/TraceStore -> local HTTP Provider."""

    scenario_server.responses = [
        {
            "payload": _completion(
                json.dumps(
                    {
                        "route": "social_chat",
                        "intents": [],
                        "slots": [],
                        "risk": None,
                        "need_clarification": False,
                        "clarification": None,
                    }
                )
            )
        }
    ]

    async def scenario() -> None:
        db = Database(Settings(_env_file=None, database_url=mysql_url))
        try:
            async with db.transaction() as session:
                await config.save_draft(session, document(), None)
                model = await config.create_model(
                    session,
                    ModelConfigCreate(
                        **model_input(
                            base_url=f"http://127.0.0.1:{scenario_server.server_port}/v1",
                            credential_ref="QWEN_API_KEY",
                        )
                    ),
                )
                await config.publish(session, await reviewed_request(session, model.id))
        finally:
            await db.dispose()

        monkeypatch.setenv("QWEN_API_KEY", "local-test-credential")
        app = create_app(Settings(_env_file=None, database_url=mysql_url, log_level="WARNING"))
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/v1/intent/analyze",
                    json={"request_id": "runtime-e2e", "text": "你好"},
                )
        assert response.status_code == 200
        assert set(response.json()) == {
            "request_id",
            "text",
            "route",
            "intents",
            "slots",
            "risk",
            "need_clarification",
            "clarification",
        }
        check = Database(Settings(_env_file=None, database_url=mysql_url))
        try:
            async with check.transaction() as session:
                trace = await session.scalar(
                    select(IntentRequestTrace).where(IntentRequestTrace.request_id == "runtime-e2e")
                )
                assert trace is not None and trace.status == "success"
                assert (
                    await session.scalar(
                        select(func.count(LLMCallTrace.id)).where(
                            LLMCallTrace.trace_id == trace.trace_id
                        )
                    )
                    == 1
                )
        finally:
            await check.dispose()

    asyncio.run(scenario())


def test_runtime_http_trace_failure_is_fail_open_on_real_mysql(
    mysql_url, scenario_server, monkeypatch
):
    """The public Runtime API returns the model result when its Trace transaction fails."""

    scenario_server.responses = [
        {
            "payload": _completion(
                json.dumps(
                    {
                        "route": "social_chat",
                        "intents": [],
                        "slots": [],
                        "risk": None,
                        "need_clarification": False,
                        "clarification": None,
                    }
                )
            )
        }
    ]

    async def scenario() -> None:
        db = Database(Settings(_env_file=None, database_url=mysql_url))
        try:
            async with db.transaction() as session:
                await config.save_draft(session, document(), None)
                model = await config.create_model(
                    session,
                    ModelConfigCreate(
                        **model_input(
                            base_url=f"http://127.0.0.1:{scenario_server.server_port}/v1",
                            credential_ref="QWEN_API_KEY",
                        )
                    ),
                )
                await config.publish(session, await reviewed_request(session, model.id))
        finally:
            await db.dispose()

        monkeypatch.setenv("QWEN_API_KEY", "local-test-credential")
        app = create_app(Settings(_env_file=None, database_url=mysql_url, log_level="WARNING"))

        def fail_trace_insert(connection, cursor, statement, parameters, context, executemany):
            if "insert into intent_request_trace" in statement.lower():
                raise RuntimeError("controlled trace insert failure")

        async with app.router.lifespan_context(app):
            event.listen(
                app.state.database.engine.sync_engine, "before_cursor_execute", fail_trace_insert
            )
            try:
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://test"
                ) as client:
                    response = await client.post(
                        "/api/v1/intent/analyze",
                        json={
                            "request_id": "runtime-trace-fail-open",
                            "text": "password is runtime-secret",
                        },
                    )
            finally:
                event.remove(
                    app.state.database.engine.sync_engine,
                    "before_cursor_execute",
                    fail_trace_insert,
                )
        assert response.status_code == 200
        assert response.json()["route"] == "social_chat"
        assert len(scenario_server.request_bodies) == 1

        check = Database(Settings(_env_file=None, database_url=mysql_url))
        try:
            async with check.transaction() as session:
                assert (
                    await session.scalar(
                        select(func.count(IntentRequestTrace.id)).where(
                            IntentRequestTrace.request_id == "runtime-trace-fail-open"
                        )
                    )
                    == 0
                )
                assert await session.scalar(select(func.count(LLMCallTrace.id))) == 0
        finally:
            await check.dispose()

    asyncio.run(scenario())


def test_non_runtime_trace_failure_is_fail_closed_on_real_mysql(mysql_url, scenario_server):
    """Debug/Replay/Evaluation contract propagates real Trace DB failures."""

    scenario_server.responses = [
        {
            "payload": _completion(
                json.dumps(
                    {
                        "route": "social_chat",
                        "intents": [],
                        "slots": [],
                        "risk": None,
                        "need_clarification": False,
                        "clarification": None,
                    }
                )
            )
        }
    ]

    async def scenario() -> None:
        db = Database(Settings(_env_file=None, database_url=mysql_url))
        factory = ModelProviderFactory(
            lambda reference: "local-test-credential", queue_wait_timeout=1
        )

        def fail_trace_insert(connection, cursor, statement, parameters, context, executemany):
            if "insert into intent_request_trace" in statement.lower():
                raise RuntimeError("controlled trace insert failure")

        try:
            async with db.transaction() as session:
                await config.save_draft(session, document(), None)
                model = await config.create_model(
                    session,
                    ModelConfigCreate(
                        **model_input(base_url=f"http://127.0.0.1:{scenario_server.server_port}/v1")
                    ),
                )
                await config.publish(session, await reviewed_request(session, model.id))
            service = IntentService(
                DatabaseRuntimeConfigLoader(db.session_factory, ttl_seconds=60),
                factory,
                PromptBuilder(),
                DatabaseTraceStore(db.session_factory),
            )
            event.listen(db.engine.sync_engine, "before_cursor_execute", fail_trace_insert)
            try:
                with pytest.raises(AppError) as raised:
                    await service.analyze(
                        text="trace failure must not look successful",
                        request_id="debug-trace-fail-closed",
                        execution_mode="debug",
                    )
                assert raised.value.code == ErrorCode.INTERNAL_ERROR
                assert raised.value.status_code == 500
            finally:
                event.remove(db.engine.sync_engine, "before_cursor_execute", fail_trace_insert)
            async with db.transaction() as session:
                assert (
                    await session.scalar(
                        select(func.count(IntentRequestTrace.id)).where(
                            IntentRequestTrace.request_id == "debug-trace-fail-closed"
                        )
                    )
                    == 0
                )
                assert await session.scalar(select(func.count(LLMCallTrace.id))) == 0
            assert len(scenario_server.request_bodies) == 1
        finally:
            await factory.close()
            await db.dispose()

    asyncio.run(scenario())


def test_active_release_switch_uses_real_loader_factory_trace_store_and_http(
    mysql_url, scenario_server
):
    """An in-flight A request keeps A while a later B request sees B immediately."""

    output = json.dumps(
        {
            "route": "social_chat",
            "intents": [],
            "slots": [],
            "risk": None,
            "need_clarification": False,
            "clarification": None,
        }
    )
    scenario_server.responses = [
        {"delay": 0.2, "payload": _completion(output)},
        {"status": 500, "payload": {"error": {"message": "retry once"}}},
        {"payload": _completion(output)},
    ]

    async def scenario() -> None:
        db = Database(Settings(_env_file=None, database_url=mysql_url))
        factory = ModelProviderFactory(
            lambda reference: "local-test-credential", queue_wait_timeout=1
        )
        pending: asyncio.Task | None = None
        try:
            async with db.transaction() as session:
                await config.save_draft(session, document(), None)
                model_a = await config.create_model(
                    session,
                    ModelConfigCreate(
                        **model_input(
                            model="model-a",
                            version="a",
                            base_url=f"http://127.0.0.1:{scenario_server.server_port}/v1",
                            params_json={"temperature": 0.1, "top_p": 0.8},
                            timeout_seconds=2,
                            max_retries=0,
                        )
                    ),
                )
                release_a = await config.publish(
                    session, await reviewed_request(session, model_a.id)
                )
            service = IntentService(
                DatabaseRuntimeConfigLoader(db.session_factory, ttl_seconds=60),
                factory,
                PromptBuilder(),
                DatabaseTraceStore(db.session_factory),
            )
            pending = asyncio.create_task(service.analyze(text="A", request_id="switch-a"))
            await _wait_for_requests(scenario_server, 1)
            async with db.transaction() as session:
                model_b = await config.create_model(
                    session,
                    ModelConfigCreate(
                        **model_input(
                            model="model-b",
                            version="b",
                            base_url=f"http://127.0.0.1:{scenario_server.server_port}/v1",
                            params_json={"temperature": 0.9, "seed": 123},
                            timeout_seconds=3,
                            max_retries=1,
                        )
                    ),
                )
                release_b = await config.publish(
                    session, await reviewed_request(session, model_b.id)
                )
            assert (await service.analyze(text="B", request_id="switch-b")).route == "social_chat"
            assert (await pending).route == "social_chat"
            assert len(scenario_server.request_bodies) == 3
            request_a, request_b_first, request_b_second = scenario_server.request_bodies
            assert request_a["model"] == "model-a"
            assert request_a["temperature"] == 0.1 and request_a["top_p"] == 0.8
            for request_b in (request_b_first, request_b_second):
                assert request_b["model"] == "model-b"
                assert request_b["temperature"] == 0.9 and request_b["seed"] == 123
                assert "top_p" not in request_b and "max_tokens" not in request_b
            async with db.transaction() as session:
                traces = {
                    trace.request_id: trace
                    for trace in await session.scalars(
                        select(IntentRequestTrace).where(
                            IntentRequestTrace.request_id.in_(["switch-a", "switch-b"])
                        )
                    )
                }
                for request_id, model, release, attempts in (
                    ("switch-a", model_a, release_a, 1),
                    ("switch-b", model_b, release_b, 2),
                ):
                    trace = traces[request_id]
                    assert trace.release_id == release["id"]
                    assert trace.effective_model_config_id == model.id
                    assert trace.config_snapshot_hash == release["config_snapshot_hash"]
                    assert trace.model_config_hash == model.model_config_hash
                    assert trace.release_fingerprint == release["release_fingerprint"]
                    assert trace.model_config_snapshot_json == model.model_dump(mode="json")
                    stored_attempts = list(
                        await session.scalars(
                            select(LLMCallTrace)
                            .where(LLMCallTrace.trace_id == trace.trace_id)
                            .order_by(LLMCallTrace.attempt_no)
                        )
                    )
                    assert len(stored_attempts) == attempts
                    assert [item.model for item in stored_attempts] == [model.model] * attempts
        finally:
            if pending is not None and not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
            await factory.close()
            await db.dispose()

    asyncio.run(scenario())


def test_trace_store_pool_wait_cancellation_releases_real_mysql_connection(mysql_url):
    """A task cancelled while the one-slot real pool is exhausted writes nothing."""

    async def scenario() -> None:
        engine = create_async_engine(mysql_url, pool_size=1, max_overflow=0, pool_timeout=30)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        store = DatabaseTraceStore(sessions)
        reached_sql = threading.Event()

        def observe_sql(connection, cursor, statement, parameters, context, executemany):
            if "insert into intent_request_trace" in statement.lower():
                reached_sql.set()

        event.listen(engine.sync_engine, "before_cursor_execute", observe_sql)
        try:
            async with sessions() as held:
                await held.execute(text("SELECT 1"))
                assert engine.sync_engine.pool.checkedout() == 1
                waiting = asyncio.create_task(store.write(_trace("cancel-pool-wait")))
                await asyncio.sleep(0)
                assert not waiting.done()
                assert not reached_sql.is_set()
                waiting.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await waiting
            assert engine.sync_engine.pool.checkedout() == 0
            await store.write(_trace("cancel-pool-follow-up"))
            async with sessions() as session:
                assert (
                    await session.scalar(
                        select(func.count(IntentRequestTrace.id)).where(
                            IntentRequestTrace.request_id == "cancel-pool-wait"
                        )
                    )
                    == 0
                )
                assert (
                    await session.scalar(
                        select(func.count(IntentRequestTrace.id)).where(
                            IntentRequestTrace.request_id == "cancel-pool-follow-up"
                        )
                    )
                    == 1
                )
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", observe_sql)
            await engine.dispose()

    asyncio.run(scenario())


def test_trace_store_sql_cancellation_rolls_back_and_releases_real_mysql_connection(mysql_url):
    """Cancellation during an actual MySQL INSERT leaves no half-written Trace."""

    async def scenario() -> None:
        db = Database(Settings(_env_file=None, database_url=mysql_url))
        store = DatabaseTraceStore(db.session_factory)
        entered_insert = threading.Event()
        trigger_name = "task103_trace_cancel_insert"

        def observe_insert(connection, cursor, statement, parameters, context, executemany):
            if "insert into intent_request_trace" in statement.lower():
                entered_insert.set()

        try:
            async with db.engine.begin() as connection:
                await connection.execute(text(f"DROP TRIGGER IF EXISTS {trigger_name}"))
                await connection.execute(
                    text(
                        "CREATE TRIGGER task103_trace_cancel_insert "
                        "BEFORE INSERT ON intent_request_trace FOR EACH ROW "
                        "SET @task103_trace_cancel_insert = SLEEP(5)"
                    )
                )
            event.listen(db.engine.sync_engine, "before_cursor_execute", observe_insert)
            cancelled = asyncio.create_task(store.write(_trace("cancel-sql")))
            assert await asyncio.to_thread(entered_insert.wait, 1)
            cancelled.cancel()
            with pytest.raises(asyncio.CancelledError):
                await cancelled
        finally:
            event.remove(db.engine.sync_engine, "before_cursor_execute", observe_insert)
            async with db.engine.begin() as connection:
                await connection.execute(text(f"DROP TRIGGER IF EXISTS {trigger_name}"))

        try:
            await store.write(_trace("cancel-sql-follow-up"))
            async with db.transaction() as session:
                assert (
                    await session.scalar(
                        select(func.count(IntentRequestTrace.id)).where(
                            IntentRequestTrace.request_id == "cancel-sql"
                        )
                    )
                    == 0
                )
                assert (
                    await session.scalar(
                        select(func.count(IntentRequestTrace.id)).where(
                            IntentRequestTrace.request_id == "cancel-sql-follow-up"
                        )
                    )
                    == 1
                )
        finally:
            await db.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("stage", "request_id", "persisted"),
    [
        ("before_dbapi_commit", "cancel-commit-uncommitted", False),
        ("after_dbapi_commit", "cancel-commit-completed", True),
    ],
)
def test_trace_store_commit_cancellation_reports_only_observable_mysql_state(
    mysql_url, stage, request_id, persisted
):
    """Commit cancellation never returns a false persistence success.

    The engine commit event runs immediately before DBAPI commit; the session
    after_commit event is after it.  The test therefore records only the state
    MySQL can prove, rather than claiming a rollback for a completed commit.
    """

    async def scenario() -> None:
        db = Database(Settings(_env_file=None, database_url=mysql_url))
        store = DatabaseTraceStore(db.session_factory)

        def cancel_before_dbapi(connection):
            if stage == "before_dbapi_commit":
                raise asyncio.CancelledError("controlled cancellation before DBAPI commit")

        def cancel_after_dbapi(session):
            if stage == "after_dbapi_commit":
                raise asyncio.CancelledError("controlled cancellation after DBAPI commit")

        event.listen(db.engine.sync_engine, "commit", cancel_before_dbapi)
        event.listen(
            db.session_factory.class_.sync_session_class, "after_commit", cancel_after_dbapi
        )
        try:
            with pytest.raises(asyncio.CancelledError):
                await store.write(_trace(request_id))
        finally:
            event.remove(db.engine.sync_engine, "commit", cancel_before_dbapi)
            event.remove(
                db.session_factory.class_.sync_session_class, "after_commit", cancel_after_dbapi
            )
        try:
            async with db.transaction() as session:
                assert await session.scalar(
                    select(func.count(IntentRequestTrace.id)).where(
                        IntentRequestTrace.request_id == request_id
                    )
                ) == int(persisted)
            await store.write(_trace(f"{request_id}-follow-up"))
            async with db.transaction() as session:
                assert (
                    await session.scalar(
                        select(func.count(IntentRequestTrace.id)).where(
                            IntentRequestTrace.request_id == f"{request_id}-follow-up"
                        )
                    )
                    == 1
                )
        finally:
            await db.dispose()

    asyncio.run(scenario())
