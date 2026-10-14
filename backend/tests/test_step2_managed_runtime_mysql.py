"""Focused Step 2 acceptance against the isolated MySQL test database."""

import asyncio
import json

import httpx
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.core.settings import Settings
from app.db.models import IntentRequestTrace, LLMCallTrace, RuntimeModelState
from app.main import create_app
from app.schemas.config import ModelConfigCreate
from app.services import config_service as config
from tests.test_config_contract import document, model_input
from tests.test_config_mysql import mysql_url as mysql_url
from tests.test_config_mysql import reviewed_request
from tests.test_provider_contract import _completion
from tests.test_provider_contract import scenario_server as scenario_server


def _managed_model(base_url: str, display_name: str, model_name: str, api_key: str) -> dict:
    return {
        "display_name": display_name,
        "base_url": base_url,
        "api_key": api_key,
        "model_name": model_name,
        "temperature": 0.1,
        "top_p": 0.8,
        "timeout_seconds": 5,
        "max_retries": 0,
        "max_concurrency": 2,
    }


def test_runtime_uses_default_and_explicit_managed_models_without_secret_trace(
    mysql_url, scenario_server
) -> None:
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
        {"payload": _completion(output)},
        {"payload": _completion(output)},
    ]

    async def scenario() -> None:
        first_secret = "sk-default-never-traced"
        second_secret = "sk-explicit-never-traced"
        settings = Settings(
            _env_file=None,
            database_url=mysql_url,
            credential_encryption_key=Fernet.generate_key().decode(),
            log_level="WARNING",
        )
        app = create_app(settings)
        async with app.router.lifespan_context(app):
            database = app.state.database
            async with database.transaction() as session:
                await config.save_draft(session, document(), None)
                historical_model = await config.create_model(
                    session,
                    ModelConfigCreate(**model_input()),
                )
                release = await config.publish(
                    session,
                    await reviewed_request(session, historical_model.id),
                )

            base_url = f"http://127.0.0.1:{scenario_server.server_port}/v1"
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                first = (
                    await client.post(
                        "/api/admin/models",
                        json=_managed_model(
                            base_url,
                            "Default compatible model",
                            "default-model",
                            first_secret,
                        ),
                    )
                ).json()
                second = (
                    await client.post(
                        "/api/admin/models",
                        json=_managed_model(
                            base_url,
                            "Explicit compatible model",
                            "explicit-model",
                            second_secret,
                        ),
                    )
                ).json()

                default_response = await client.post(
                    "/api/v1/intent/analyze",
                    json={"request_id": "step2-default", "text": "你好"},
                )
                explicit_response = await client.post(
                    "/api/v1/intent/analyze",
                    json={
                        "request_id": "step2-explicit",
                        "text": "你好",
                        "model_uid": second["model_uid"],
                    },
                )

                async with database.transaction() as session:
                    model_state = await session.get(RuntimeModelState, 1, with_for_update=True)
                    model_state.default_model_id = None
                unconfigured_response = await client.post(
                    "/api/v1/intent/analyze",
                    json={"request_id": "step2-no-default", "text": "你好"},
                )

            assert default_response.status_code == explicit_response.status_code == 200
            assert unconfigured_response.status_code == 503
            assert unconfigured_response.json()["error_code"] == "CONFIG_NOT_READY"
            assert "model_uid" not in default_response.json()
            async with database.transaction() as session:
                traces = list(
                    await session.scalars(
                        select(IntentRequestTrace)
                        .where(
                            IntentRequestTrace.request_id.in_(
                                ["step2-default", "step2-explicit"]
                            )
                        )
                        .order_by(IntentRequestTrace.id)
                    )
                )
                assert len(traces) == 2
                assert all(item.release_id == release["id"] for item in traces)
                assert all(item.effective_model_config_id is None for item in traces)
                assert all(item.model_config_hash is None for item in traces)
                assert traces[0].model_config_snapshot_json["model_uid"] == first["model_uid"]
                assert traces[1].model_config_snapshot_json["model_uid"] == second["model_uid"]
                assert all(
                    item.model_config_snapshot_json["snapshot_type"] == "managed_model"
                    for item in traces
                )
                attempts = list(
                    await session.scalars(
                        select(LLMCallTrace)
                        .where(LLMCallTrace.trace_id.in_([item.trace_id for item in traces]))
                        .order_by(LLMCallTrace.id)
                    )
                )
                assert [item.model for item in attempts] == [
                    "default-model",
                    "explicit-model",
                ]
                persisted = json.dumps(
                    [
                        {
                            "snapshot": item.model_config_snapshot_json,
                            "result": item.final_result_json,
                            "timeline": item.timeline_json,
                            "error": item.error_message,
                        }
                        for item in traces
                    ],
                    ensure_ascii=False,
                ) + json.dumps(
                    [
                        {
                            "request": item.raw_request_json,
                            "response": item.raw_response_json,
                            "error": item.error_message,
                        }
                        for item in attempts
                    ],
                    ensure_ascii=False,
                )
                assert first_secret not in persisted
                assert second_secret not in persisted
                failed = await session.scalar(
                    select(IntentRequestTrace).where(
                        IntentRequestTrace.request_id == "step2-no-default"
                    )
                )
                assert failed is not None
                assert failed.status == "failed"
                assert failed.error_code == "CONFIG_NOT_READY"
                assert failed.timeline_json["failure_stage"] == "configuration"

    asyncio.run(scenario())
