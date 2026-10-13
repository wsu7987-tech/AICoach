"""Release -> effective snapshot -> real HTTP -> Trace, without a production loader."""

import asyncio
import json

import httpx
import pytest

from app.core.settings import Settings
from app.db.database import Database
from app.db.models import RuntimeState
from app.main import create_app
from app.prompting.builder import PromptBuilder
from app.providers.factory import ModelProviderFactory
from app.schemas.config import ModelConfigCreate
from app.services import config_service as config
from app.services.intent_service import InMemoryTraceSink, IntentService, RuntimeConfiguration
from tests.test_config_contract import document, model_input
from tests.test_config_mysql import mysql_url as mysql_url
from tests.test_config_mysql import reviewed_request
from tests.test_provider_contract import _completion, _wait_for_requests
from tests.test_provider_contract import scenario_server as scenario_server


def test_active_switch_uses_effective_model_on_real_http_and_keeps_provenance(
    mysql_url, scenario_server
):
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
        {"delay": 0.3, "payload": _completion(output)},
        {"status": 500, "payload": {"error": {"message": "retry once"}}},
        {"payload": _completion(output)},
    ]

    async def scenario():
        db = Database(Settings(_env_file=None, database_url=mysql_url))
        factory = ModelProviderFactory(
            lambda reference: "local-test-credential", queue_wait_timeout=1
        )
        sink = InMemoryTraceSink()

        class TestDatabaseLoader:
            async def load(self):
                async with db.transaction() as s:
                    active = (await s.get(RuntimeState, 1)).active_release_id
                    return RuntimeConfiguration.from_release(
                        await config.release_configuration(s, active)
                    )

        service = IntentService(TestDatabaseLoader(), factory, PromptBuilder(), sink)
        pending = None
        try:
            async with db.transaction() as s:
                await config.save_draft(s, document(), None)
                model_a = await config.create_model(
                    s,
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
                release_a = await config.publish(s, await reviewed_request(s, model_a.id))
            pending = asyncio.create_task(service.analyze(text="你好", request_id="request-a"))
            await _wait_for_requests(scenario_server, 1)
            async with db.transaction() as s:
                model_b = await config.create_model(
                    s,
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
                release_b = await config.publish(s, await reviewed_request(s, model_b.id))
            await service.analyze(text="你好", request_id="request-b")
            await pending
            assert len(scenario_server.request_bodies) == 3
            a, b1, b2 = scenario_server.request_bodies
            assert a["model"] == "model-a" and a["temperature"] == 0.1 and a["top_p"] == 0.8
            for body in (b1, b2):
                assert (
                    body["model"] == "model-b"
                    and body["temperature"] == 0.9
                    and body["seed"] == 123
                )
                assert "top_p" not in body and "max_tokens" not in body
            traces = {trace.request_id: trace for trace in sink.records}
            for request_id, model, release, count in (
                ("request-a", model_a, release_a, 1),
                ("request-b", model_b, release_b, 2),
            ):
                trace = traces[request_id]
                assert trace.model_config_id == model.id
                assert trace.release_id == release["id"]
                assert trace.config_snapshot_hash == release["config_snapshot_hash"]
                assert trace.model_config_hash == release["model_config_hash"]
                assert trace.release_fingerprint == release["release_fingerprint"]
                assert trace.model_config_snapshot == model.model_dump(mode="json")
                assert len(trace.attempts) == count
                assert all(attempt.model == model.model for attempt in trace.attempts)
                assert [attempt.attempt_no for attempt in trace.attempts] == list(
                    range(1, count + 1)
                )
                provider = factory.resolve(model)
                assert provider.sdk_max_retries == 0
                assert provider._client.timeout == model.timeout_seconds
                assert provider._semaphore._value == model.max_concurrency
        finally:
            if pending is not None and not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
            await factory.close()
            await db.dispose()

    asyncio.run(scenario())


def test_publish_reloads_cached_draft_after_acquiring_database_lock(mysql_url):
    async def scenario():
        db = Database(Settings(_env_file=None, database_url=mysql_url))
        try:
            async with db.transaction() as s:
                draft = await config.save_draft(s, document(), None)
                model = await config.create_model(s, ModelConfigCreate(**model_input()))
            async with db.transaction() as stale_session:
                # Keep a strong reference to the cached ORM instance; locking reads
                # must refresh it rather than accidentally accepting stale fields.
                cached = await config.require_draft(stale_session)
                request = await reviewed_request(stale_session, model.id)
                changed = document()
                changed["prompt_template"]["system"] += " changed concurrently"
                async with db.transaction() as other_session:
                    saved = await config.save_draft(other_session, changed, draft["draft_hash"])
                with pytest.raises(config.ConfigError) as error:
                    await config.publish(stale_session, request)
                assert error.value.code == "DRAFT_CONFLICT"
                assert cached.draft_json == saved["draft_json"]
            async with db.transaction() as s:
                assert (await s.get(RuntimeState, 1)).active_release_id is None
        finally:
            await db.dispose()

    asyncio.run(scenario())


def test_publish_missing_and_stale_confirmations_are_atomic(mysql_url):
    async def scenario():
        app = create_app(Settings(_env_file=None, database_url=mysql_url, log_level="WARNING"))
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test/api/admin"
            ) as client:
                draft = (
                    await client.post("/config/bootstrap", json={"draft_json": document()})
                ).json()
                model = (await client.post("/model-configs", json=model_input())).json()

                async def summary():
                    response = await client.get(
                        "/config/publish-summary", params={"default_model_config_id": model["id"]}
                    )
                    assert response.status_code == 200
                    data = response.json()
                    return {
                        "default_model_config_id": model["id"],
                        "note": "reviewed",
                        "expected_draft_hash": data["draft_hash"],
                        "expected_active_release_id": data["active_release_id"],
                    }

                old = await summary()
                for key in ("expected_draft_hash", "expected_active_release_id"):
                    body = {k: v for k, v in old.items() if k != key}
                    assert (await client.post("/releases", json=body)).status_code == 422
                changed = document()
                changed["prompt_template"]["system"] += " changed after review"
                assert (
                    await client.put(
                        "/config/draft",
                        json={"draft_json": changed, "expected_draft_hash": draft["draft_hash"]},
                    )
                ).status_code == 200
                response = await client.post("/releases", json=old)
                assert (
                    response.status_code == 409
                    and response.json()["error_code"] == "DRAFT_CONFLICT"
                )
                assert (await client.get("/releases")).json() == {
                    "active_release_id": None,
                    "items": [],
                }
                fresh = await summary()
                responses = await asyncio.gather(
                    *(client.post("/releases", json=fresh) for _ in range(8))
                )
                assert sorted(r.status_code for r in responses) == [201] + [409] * 7
                assert all(
                    r.json()["error_code"] == "RELEASE_CONFLICT"
                    for r in responses
                    if r.status_code == 409
                )
                first = next(r.json() for r in responses if r.status_code == 201)
                history = (await client.get("/releases")).json()
                assert len(history["items"]) == 1 and history["active_release_id"] == first["id"]
                again = await client.post("/releases", json=await summary())
                assert again.status_code == 201
                assert again.json()["id"] != first["id"]
                assert again.json()["release_fingerprint"] == first["release_fingerprint"]

    asyncio.run(scenario())
