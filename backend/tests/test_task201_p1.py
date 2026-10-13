"""Targeted regressions for TASK-201 independent review P1 findings."""

import asyncio
import json

import pytest
from pydantic import ValidationError

from app.core.errors import ErrorCode
from app.prompting.builder import PromptBuilder
from app.providers.factory import ModelProviderFactory
from app.providers.qwen import ProviderError
from app.schemas.config import PublishInput, model_hash
from app.services.intent_service import (
    InMemoryRuntimeConfigLoader,
    InMemoryTraceSink,
    IntentService,
)
from tests.test_provider_contract import _completion, _provider, _snapshot
from tests.test_provider_contract import scenario_server as scenario_server


@pytest.mark.parametrize(
    "tokens",
    [
        {},
        {"expected_draft_hash": "a" * 64},
        {"expected_active_release_id": None},
        {"expected_draft_hash": None, "expected_active_release_id": None},
    ],
)
def test_publish_requires_both_review_tokens(tokens):
    with pytest.raises(ValidationError):
        PublishInput(default_model_config_id=1, note="reviewed", **tokens)


def test_static_provider_cannot_silently_call_a_and_trace_b(scenario_server):
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
    provider = _provider(scenario_server, timeout_seconds=2)
    other = provider.model_config.model_copy(deep=True, update={"id": 2, "model": "model-b"})
    other.model_config_hash = model_hash(other)
    sink = InMemoryTraceSink()
    service = IntentService(
        InMemoryRuntimeConfigLoader(_snapshot(), other), provider, PromptBuilder(), sink
    )

    async def scenario():
        try:
            with pytest.raises(ProviderError) as raised:
                await service.analyze(text="你好")
            assert raised.value.code == ErrorCode.CONFIG_NOT_READY
            assert not scenario_server.request_bodies
            assert not sink.records[-1].attempts
        finally:
            await provider._client.close()

    asyncio.run(scenario())


def test_factory_identity_copies_corruption_capacity_and_close(scenario_server):
    async def scenario():
        initial = _provider(scenario_server)
        config = initial.model_config
        await initial.close()
        factory = ModelProviderFactory(lambda ref: "test-key", queue_wait_timeout=1, max_entries=3)
        try:
            a = factory.resolve(config)
            assert (
                factory.resolve(config.model_copy(update={"name": "renamed", "enabled": False}))
                is a
            )
            # An ID alone (or a display name) cannot select a stale client.
            changed = config.model_copy(deep=True)
            changed.params_json["temperature"] = 1
            changed.model_config_hash = model_hash(changed)
            b = factory.resolve(changed)
            assert a is not b
            other_id = config.model_copy(deep=True, update={"id": 2})
            assert factory.resolve(other_id) is not a
            changed.params_json["temperature"] = 0.5
            with pytest.raises(ProviderError) as error:
                factory.resolve(changed)
            assert error.value.code == ErrorCode.CONFIG_NOT_READY
            # Both the constructor input and accessor are isolated copies.
            config.params_json["temperature"] = 0.8
            view = a.model_config
            view.params_json["temperature"] = 0.9
            assert a.model_config.params_json["temperature"] == 0
            with pytest.raises(ProviderError) as error:
                factory.resolve(other_id.model_copy(update={"id": 3}))
            assert error.value.code == ErrorCode.SERVICE_BUSY
        finally:
            await factory.close()
        assert a._client.is_closed() and b._client.is_closed()
        with pytest.raises(ProviderError):
            factory.resolve(other_id)
        assert not scenario_server.request_bodies

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "field",
    [
        "snapshot",
        "model_config_snapshot",
        "config_snapshot_hash",
        "model_config_hash",
        "release_fingerprint",
    ],
)
def test_mutated_loaded_configuration_fails_before_http(scenario_server, field):
    provider = _provider(scenario_server)
    loader = InMemoryRuntimeConfigLoader(_snapshot(), provider.model_config)
    value = loader._configuration
    if field == "snapshot":
        value.snapshot.routes.pop()
    elif field == "model_config_snapshot":
        value.model_config_snapshot.params_json["temperature"] = 1
    else:
        setattr(value, field, "0" * 64)
    sink = InMemoryTraceSink()
    service = IntentService(loader, provider, PromptBuilder(), sink)

    async def scenario():
        try:
            with pytest.raises(ProviderError) as error:
                await service.analyze(text="你好")
            assert error.value.code == ErrorCode.CONFIG_NOT_READY
            assert sink.records[-1].error_code == ErrorCode.CONFIG_NOT_READY
            assert not sink.records[-1].attempts
            assert not scenario_server.request_bodies
        finally:
            await provider.close()

    asyncio.run(scenario())
