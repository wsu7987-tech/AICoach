"""Opt-in isolated MySQL acceptance; no real model calls, never uses DATABASE_URL.

Set EVALUATION_TEST_DATABASE_URL to a disposable local ai_coach_evaluation_test_* database
only after the project owner authorizes tests. The fixture migrates and clears that database.
"""

import asyncio
import json
import os
from datetime import timedelta
from pathlib import Path

import pytest
from alembic.config import Config
from cryptography.fernet import Fernet
from sqlalchemy import delete, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from app.core.settings import Settings, get_settings
from app.db.base import Base
from app.db.database import Database
from app.db.models import (
    EvaluationCaseResult,
    EvaluationDataset,
    EvaluationRun,
    IntentRequestTrace,
    ManagedModel,
    RuntimeState,
)
from app.providers.factory import ModelProviderFactory
from app.providers.types import LLMAttempt, LLMResponse
from app.schemas.config import PublishInput
from app.schemas.evaluation import DatasetCreate, ReviewInput, RunCreate
from app.schemas.managed_model import ManagedModelCreate
from app.security.credentials import CredentialCipher
from app.services import config_service, managed_model_service
from app.services.evaluation import service
from app.services.evaluation import worker as worker_module
from app.services.evaluation.worker import ClaimLost, EvaluationWorker
from app.services.runtime_model import DatabaseManagedModelLoader


@pytest.fixture
def evaluation_mysql(monkeypatch):
    raw = os.environ.get("EVALUATION_TEST_DATABASE_URL")
    if not raw:
        pytest.skip("Explicit EVALUATION_TEST_DATABASE_URL and owner test approval required")
    url = make_url(raw)
    if (
        url.drivername != "mysql+asyncmy"
        or url.host not in {"localhost", "127.0.0.1", "::1"}
        or not (url.database or "").startswith("ai_coach_evaluation_test_")
    ):
        pytest.fail("Refusing a non-local or non-isolated evaluation test database")

    async def reset():
        engine = create_async_engine(raw)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.drop_all)
                await connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
        finally:
            await engine.dispose()

    asyncio.run(reset())
    monkeypatch.setenv("DATABASE_URL", raw)
    get_settings.cache_clear()
    configuration = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(configuration, "head")
    try:
        yield raw
    finally:
        asyncio.run(reset())
        get_settings.cache_clear()


def test_claim_recovery_rejects_stale_writer_and_duplicate_results(evaluation_mysql):
    async def scenario():
        settings = Settings(_env_file=None, database_url=evaluation_mysql)
        database = Database(settings)
        first, second = EvaluationWorker(database, settings), EvaluationWorker(database, settings)
        try:
            async with database.transaction() as session:
                dataset = EvaluationDataset(
                    name="lease",
                    version="1",
                    source_filename="test",
                    hash="a" * 64,
                    normalized_cases_json=[],
                )
                session.add(dataset)
                await session.flush()
                session.add(
                    EvaluationRun(
                        name="lease",
                        dataset_id=dataset.id,
                        dataset_hash="a" * 64,
                        config_snapshot_hash="a" * 64,
                        config_snapshot_json={},
                        evaluation_config_json={},
                        cases_json=[],
                        managed_model_uid="mdl_" + "a" * 64,
                        managed_model_snapshot_json={},
                        repeat_count=1,
                        worker_concurrency=2,
                        status="queued",
                    )
                )
            old_claim = await first.claim()
            assert await second.claim() is None
            async with database.transaction() as session:
                row = await session.get(EvaluationRun, old_claim.id)
                row.heartbeat_at = service.now() - timedelta(seconds=120)
            recovered = await second.claim()
            assert recovered.id == old_claim.id and recovered.claimed_by != old_claim.claimed_by
            kwargs = {
                "actual": {},
                "status": "judging",
                "verdict": {},
                "request_id": "request",
                "trace_id": None,
                "latency": 1,
            }
            with pytest.raises(ClaimLost):
                await first.checkpoint(old_claim, {"case_id": "a"}, 0, **kwargs)
            one = await second.checkpoint(recovered, {"case_id": "a"}, 0, **kwargs)
            two = await second.checkpoint(recovered, {"case_id": "a"}, 0, **kwargs)
            assert one.id == two.id
            async with database.session_factory() as session:
                assert (
                    await session.scalar(select(func.count()).select_from(EvaluationCaseResult))
                    == 1
                )
        finally:
            await database.dispose()

    asyncio.run(scenario())


def test_300_cases_frozen_model_trace_and_review(evaluation_mysql, monkeypatch):
    output = {
        "schema_version": 2,
        "is_compound": False,
        "composition": "single",
        "actions": [
            {
                "action_id": "action_1",
                "source_text": "你好",
                "route": "social_chat",
                "intent": None,
                "slots": [],
                "order": 1,
                "depends_on": [],
            }
        ],
        "risk": None,
        "need_clarification": False,
        "clarification": None,
        "reason_summary": None,
        "evidence": [],
    }

    class FakeProvider:
        def __init__(self, snapshot):
            self.runtime_snapshot = snapshot

        async def invoke(self, prompt):
            attempt = LLMAttempt(
                attempt_no=1,
                is_retry=False,
                provider="openai_compatible",
                model="local-model",
                params={},
                raw_request={},
                raw_response={},
                parsed_payload=output,
                latency_ms=1,
                status="succeeded",
                usage={"total_tokens": 10},
            )
            return LLMResponse(
                content=json.dumps(output), attempts=[attempt], response_mode="json_object"
            )

    class FakeFactory(ModelProviderFactory):
        def resolve_managed(self, snapshot, **kwargs):
            return FakeProvider(snapshot)

    monkeypatch.setattr(worker_module, "ModelProviderFactory", FakeFactory)

    async def scenario():
        settings = Settings(
            _env_file=None,
            database_url=evaluation_mysql,
            credential_encryption_key=Fernet.generate_key().decode(),
        )
        database = Database(settings)
        cipher = CredentialCipher(settings.credential_encryption_key)
        loader = DatabaseManagedModelLoader(database.session_factory, cipher)
        try:
            document = json.loads(
                (
                    Path(__file__).resolve().parents[2] / "bootstrap" / "initial-config.v1.json"
                ).read_text(encoding="utf-8")
            )
            async with database.transaction() as session:
                draft = await config_service.save_draft(session, document, None)
                await config_service.publish(
                    session,
                    PublishInput(
                        note="evaluation test",
                        expected_draft_hash=draft["draft_hash"],
                        expected_active_release_id=None,
                    ),
                )
                model = await managed_model_service.create_model(
                    session,
                    ManagedModelCreate(
                        display_name="本地 Mock",
                        base_url="http://127.0.0.1:1/v1",
                        api_key="local-only",
                        model_name="local-model",
                        temperature=0.1,
                        max_concurrency=4,
                    ),
                    cipher,
                )
                dataset = await service.create_dataset(
                    session,
                    DatasetCreate(
                        name="300 条",
                        cases=[
                            {
                                "case_id": str(index),
                                "question": "你好",
                                "standard_answer": "识别为社交问候，无需追问",
                            }
                            for index in range(300)
                        ],
                    ),
                )
                task = await service.create_run(
                    session,
                    RunCreate(name="300 条", dataset_id=dataset["id"], model_uid=model.model_uid),
                    loader,
                )
            # Mutating live defaults must not alter the previously frozen run.
            async with database.transaction() as session:
                live = await session.scalar(
                    select(ManagedModel).where(ManagedModel.model_uid == model.model_uid)
                )
                live.params_json = {**live.params_json, "temperature": 0.9}
                live.enabled = False
                runtime = await session.get(RuntimeState, 1)
                runtime.active_release_id = None
            worker = EvaluationWorker(database, settings)
            claimed = await worker.claim()
            await worker.execute_run(claimed)
            async with database.transaction() as session:
                run = await service.require_run(session, task["id"])
                records = await service.all_results(session, run)
                assert run.status == "completed" and len(records) == 300
                assert all(
                    row["status"] == "review" and row["trace_state"] == "available"
                    for row in records
                )
                trace = await session.scalar(select(IntentRequestTrace).limit(1))
                assert trace.managed_model_snapshot_json["params_json"]["temperature"] == 0.1
                await service.review_result(
                    session,
                    run.id,
                    records[0]["id"],
                    ReviewInput(
                        decision="pass", reason="识别符合标准", reviewer="验收", expected_revision=0
                    ),
                )
            async with database.transaction() as session:
                await session.execute(delete(IntentRequestTrace))
            async with database.session_factory() as session:
                run = await service.require_run(session, task["id"])
                records = await service.all_results(session, run)
                stats = service.summary(run, records)
                assert stats["pass_rate"] == 0.33 and not stats["final"]
                assert all(row["trace_state"] == "expired" for row in records)
                assert len({row["request_id"] for row in records}) == 300
        finally:
            await database.dispose()

    asyncio.run(scenario())
