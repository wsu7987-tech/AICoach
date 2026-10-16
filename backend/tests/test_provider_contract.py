"""TASK-102 contract tests for the async Qwen provider and IntentService.

The HTTP fixture is deliberately a real local HTTP server.  Mocking an SDK
method cannot detect the OpenAI SDK's built-in retry behaviour.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from app.core.errors import ErrorCode
from app.prompting.builder import PromptBuilder
from app.providers.openai_compatible import OpenAICompatibleProvider
from app.providers.qwen import ProviderError, QwenProvider
from app.providers.types import ProviderCancelledError
from app.schemas.config import model_hash
from app.schemas.intent import ModelConfigSnapshot, RuntimeConfigSnapshot
from app.services.intent_service import (
    InMemoryRuntimeConfigLoader,
    InMemoryTraceSink,
    IntentService,
    IntentServiceError,
)

BOOTSTRAP_PATH = Path(__file__).resolve().parents[2] / "bootstrap" / "initial-config.v1.json"


class _ScenarioServer(ThreadingHTTPServer):
    responses: list[dict[str, Any]]
    request_bodies: list[dict[str, Any]]


class _ScenarioHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - stdlib handler hook
        length = int(self.headers["Content-Length"])
        self.server.request_bodies.append(json.loads(self.rfile.read(length)))  # type: ignore[attr-defined]
        response = self.server.responses.pop(0)  # type: ignore[attr-defined]
        delay = response.get("delay", 0)
        if delay:
            time.sleep(delay)
        payload = response["payload"]
        body = json.dumps(payload).encode()
        self.send_response(response.get("status", 200))
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.send_header("x-request-id", response.get("request_id", "mock-request"))
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            # A cancellation test intentionally closes the client side first.
            return

    def log_message(self, format: str, *args: object) -> None:
        return


@pytest.fixture
def scenario_server() -> Iterator[_ScenarioServer]:
    server = _ScenarioServer(("127.0.0.1", 0), _ScenarioHandler)
    server.responses = []
    server.request_bodies = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def _completion(content: str) -> dict[str, Any]:
    return {
        "id": "chatcmpl_mock",
        "object": "chat.completion",
        "created": 1,
        "model": "qwen3.7-plus",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


def _model_config(base_url: str, **overrides: Any) -> ModelConfigSnapshot:
    payload = {
        "id": 1,
        "name": "qwen-test",
        "version": "1",
        "provider": "qwen",
        "model": "qwen3.7-plus",
        "base_url": base_url,
        "params": {"temperature": 0},
        "timeout_seconds": 0.1,
        "max_retries": 1,
        "max_concurrency": 1,
        "structured_output_mode": "json_schema",
        "credential_ref": "DASHSCOPE_API_KEY",
        "model_config_hash": "a" * 64,
    }
    payload.update(overrides)
    config = ModelConfigSnapshot.model_validate(payload)
    config.model_config_hash = model_hash(config)
    return config


def _snapshot() -> RuntimeConfigSnapshot:
    return RuntimeConfigSnapshot.model_validate(
        json.loads(BOOTSTRAP_PATH.read_text(encoding="utf-8"))
    )


def _provider(server: _ScenarioServer, **overrides: Any) -> QwenProvider:
    config = _model_config(f"http://127.0.0.1:{server.server_port}/v1", **overrides)
    return QwenProvider(config, api_key="test-key", queue_wait_timeout=0.05, backoff_base_seconds=0)


def _prompt() -> Any:
    return PromptBuilder().build(_snapshot(), text="你好")


async def _wait_for_requests(server: _ScenarioServer, expected: int) -> None:
    for _ in range(100):
        if len(server.request_bodies) >= expected:
            return
        await asyncio.sleep(0.005)
    raise AssertionError(f"server did not receive {expected} request(s)")


def test_c11_sdk_retries_are_disabled_and_each_http_request_has_one_attempt(
    scenario_server: _ScenarioServer,
) -> None:
    scenario_server.responses = [
        {"status": 500, "payload": {"error": {"message": "temporary"}}},
        {
            "status": 200,
            "payload": _completion(
                '{"route":"social_chat","intents":[],"risk":null,"need_clarification":false,"clarification":null}'
            ),
        },
    ]
    provider = _provider(scenario_server)

    response = asyncio.run(provider.invoke(_prompt()))

    assert provider.sdk_max_retries == 0
    assert len(scenario_server.request_bodies) == 2
    assert len(response.attempts) == 2
    assert [attempt.attempt_no for attempt in response.attempts] == [1, 2]
    assert response.attempts[0].error_code == ErrorCode.MODEL_PROVIDER_ERROR
    assert response.attempts[1].status == "succeeded"


def test_generic_openai_compatible_provider_uses_endpoint_and_model_without_vendor_choice(
    scenario_server: _ScenarioServer,
) -> None:
    scenario_server.responses = [{"status": 200, "payload": _completion("{}")}]
    config = _model_config(
        f"http://127.0.0.1:{scenario_server.server_port}/v1",
        name="deepseek-compatible-test",
        provider="openai_compatible",
        model="deepseek-chat",
    )
    provider = OpenAICompatibleProvider(
        config,
        api_key="test-key",
        queue_wait_timeout=0.05,
        backoff_base_seconds=0,
    )

    response = asyncio.run(provider.invoke(_prompt()))

    assert scenario_server.request_bodies[0]["model"] == "deepseek-chat"
    assert response.attempts[0].provider == "openai_compatible"


def test_c12_structured_requests_omit_max_tokens_and_schema_has_no_minitems(
    scenario_server: _ScenarioServer,
) -> None:
    scenario_server.responses = [{"status": 200, "payload": _completion("{}")}]
    provider = _provider(scenario_server)

    asyncio.run(provider.invoke(_prompt()))

    request = scenario_server.request_bodies[0]
    assert "max_tokens" not in request
    assert request["response_format"]["type"] == "json_schema"
    assert request["response_format"]["json_schema"]["strict"] is True
    assert "minItems" not in json.dumps(request["response_format"]["json_schema"]["schema"])


@pytest.mark.parametrize(
    ("status", "expected"),
    [(429, ErrorCode.MODEL_RATE_LIMIT), (500, ErrorCode.MODEL_PROVIDER_ERROR)],
)
def test_retryable_provider_errors_are_bounded(
    scenario_server: _ScenarioServer, status: int, expected: ErrorCode
) -> None:
    scenario_server.responses = [
        {"status": status, "payload": {"error": {"message": "retryable"}}},
        {"status": status, "payload": {"error": {"message": "retryable"}}},
    ]
    provider = _provider(scenario_server)

    with pytest.raises(ProviderError) as raised:
        asyncio.run(provider.invoke(_prompt()))

    assert raised.value.code == expected
    assert len(scenario_server.request_bodies) == 2
    assert len(raised.value.attempts) == 2


def test_timeout_is_retried_without_blocking_the_event_loop(
    scenario_server: _ScenarioServer,
) -> None:
    scenario_server.responses = [
        {"status": 200, "delay": 0.2, "payload": _completion("{}")},
        {"status": 200, "delay": 0.2, "payload": _completion("{}")},
    ]
    provider = _provider(scenario_server)

    async def invoke_with_tick() -> tuple[bool, ProviderError]:
        ticked = False

        async def tick() -> None:
            nonlocal ticked
            await asyncio.sleep(0.01)
            ticked = True

        ticker = asyncio.create_task(tick())
        with pytest.raises(ProviderError) as raised:
            await provider.invoke(_prompt())
        await ticker
        return ticked, raised.value

    ticked, error = asyncio.run(invoke_with_tick())
    assert ticked
    assert error.code == ErrorCode.MODEL_TIMEOUT
    assert len(scenario_server.request_bodies) == 2


def test_queue_wait_timeout_returns_service_busy(scenario_server: _ScenarioServer) -> None:
    scenario_server.responses = [{"status": 200, "delay": 0.2, "payload": _completion("{}")}]
    provider = _provider(scenario_server, max_retries=0, timeout_seconds=1)

    async def invoke_twice() -> ProviderError:
        first = asyncio.create_task(provider.invoke(_prompt()))
        await asyncio.sleep(0.01)
        with pytest.raises(ProviderError) as raised:
            await provider.invoke(_prompt())
        await first
        return raised.value

    error = asyncio.run(invoke_twice())
    assert error.code == ErrorCode.SERVICE_BUSY
    assert len(scenario_server.request_bodies) == 1


def test_in_flight_cancellation_records_attempt_reaches_trace_and_releases_permit(
    scenario_server: _ScenarioServer,
) -> None:
    scenario_server.responses = [
        {"status": 200, "delay": 0.3, "payload": _completion("{}")},
        {"status": 200, "payload": _completion("{}")},
    ]
    provider = _provider(scenario_server, max_retries=0, timeout_seconds=1)
    sink = InMemoryTraceSink()
    service = IntentService(
        InMemoryRuntimeConfigLoader(_snapshot(), provider.model_config),
        provider,
        PromptBuilder(),
        sink,
    )

    async def cancel_service_call() -> ProviderCancelledError:
        task = asyncio.create_task(service.analyze(text="cancelling", request_id="cancel-1"))
        await _wait_for_requests(scenario_server, 1)
        task.cancel()
        with pytest.raises(ProviderCancelledError) as raised:
            await task
        return raised.value

    cancelled = asyncio.run(cancel_service_call())

    assert len(cancelled.attempts) == 1
    assert cancelled.attempts[0].status == "cancelled"
    assert cancelled.attempts[0].latency_ms >= 0
    assert sink.records[0].cancelled is True
    assert sink.records[0].error_code is None
    assert sink.records[0].attempts == cancelled.attempts

    # The cancelled invocation released its permit; the next request is sent.
    asyncio.run(provider.invoke(_prompt()))
    assert len(scenario_server.request_bodies) == 2


def test_backoff_cancellation_keeps_completed_attempt_and_sends_no_retry(
    scenario_server: _ScenarioServer,
) -> None:
    scenario_server.responses = [{"status": 500, "payload": {"error": {"message": "retry"}}}]
    provider = _provider(scenario_server, max_retries=1)
    provider.backoff_base_seconds = 1

    async def cancel_during_backoff() -> ProviderCancelledError:
        task = asyncio.create_task(provider.invoke(_prompt()))
        await _wait_for_requests(scenario_server, 1)
        await asyncio.sleep(0.02)
        task.cancel()
        with pytest.raises(ProviderCancelledError) as raised:
            await task
        return raised.value

    cancelled = asyncio.run(cancel_during_backoff())

    assert len(scenario_server.request_bodies) == 1
    assert len(cancelled.attempts) == 1
    assert cancelled.attempts[0].status == "failed"
    assert cancelled.attempts[0].error_code == ErrorCode.MODEL_PROVIDER_ERROR


def test_queue_wait_cancellation_has_no_synthetic_http_attempt(
    scenario_server: _ScenarioServer,
) -> None:
    scenario_server.responses = [{"status": 200, "delay": 0.1, "payload": _completion("{}")}]
    provider = _provider(scenario_server, max_retries=0, timeout_seconds=1)
    provider.queue_wait_timeout = 1

    async def cancel_while_waiting() -> ProviderCancelledError:
        first = asyncio.create_task(provider.invoke(_prompt()))
        await _wait_for_requests(scenario_server, 1)
        waiting = asyncio.create_task(provider.invoke(_prompt()))
        await asyncio.sleep(0.01)
        waiting.cancel()
        with pytest.raises(ProviderCancelledError) as raised:
            await waiting
        await first
        return raised.value

    cancelled = asyncio.run(cancel_while_waiting())

    assert cancelled.attempts == []
    assert len(scenario_server.request_bodies) == 1


def test_network_error_is_bounded_and_typed() -> None:
    def no_network(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline")

    provider = QwenProvider(
        _model_config("http://network.example/v1", max_retries=1, timeout_seconds=0.1),
        api_key="test-key",
        queue_wait_timeout=0.05,
        backoff_base_seconds=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(no_network)),
    )

    with pytest.raises(ProviderError) as raised:
        asyncio.run(provider.invoke(_prompt()))

    assert raised.value.code == ErrorCode.MODEL_PROVIDER_ERROR
    assert len(raised.value.attempts) == 2


def test_json_object_is_explicit_and_never_silently_falls_back(
    scenario_server: _ScenarioServer,
) -> None:
    scenario_server.responses = [{"status": 400, "payload": {"error": {"message": "unsupported"}}}]
    provider = _provider(scenario_server, structured_output_mode="json_object", max_retries=0)

    with pytest.raises(ProviderError):
        asyncio.run(provider.invoke(_prompt()))

    request = scenario_server.request_bodies[0]
    assert request["response_format"] == {"type": "json_object"}
    assert "JSON" in request["messages"][0]["content"]


def test_json_schema_failure_never_falls_back_to_json_object(
    scenario_server: _ScenarioServer,
) -> None:
    scenario_server.responses = [{"status": 400, "payload": {"error": {"message": "unsupported"}}}]
    provider = _provider(scenario_server, max_retries=0)

    with pytest.raises(ProviderError):
        asyncio.run(provider.invoke(_prompt()))

    assert len(scenario_server.request_bodies) == 1
    assert scenario_server.request_bodies[0]["response_format"]["type"] == "json_schema"


def test_structured_model_config_rejects_max_tokens() -> None:
    with pytest.raises(ValidationError, match="max_tokens"):
        _model_config("http://example.test/v1", params={"max_tokens": 10})


def test_intent_service_validates_output_and_preserves_trace_diagnostics(
    scenario_server: _ScenarioServer,
) -> None:
    output = {
        "route": "information_query",
        "intents": [],
        "slots": [],
        "risk": None,
        "need_clarification": False,
        "clarification": None,
    }
    scenario_server.responses = [{"status": 200, "payload": _completion(json.dumps(output))}]
    provider = _provider(scenario_server)
    sink = InMemoryTraceSink()
    service = IntentService(
        InMemoryRuntimeConfigLoader(_snapshot(), provider.model_config),
        provider,
        PromptBuilder(),
        sink,
    )

    result = asyncio.run(service.analyze(text="查进度", request_id="req-1"))

    assert result.route == "information_query"
    assert result.intents == []
    assert sink.records[0].validation_issues[0].code == "INTENTS_EMPTY"
    assert sink.records[0].attempts[0].provider_request_id == "mock-request"


@pytest.mark.parametrize(
    ("output", "expected_route", "expected_risk", "expected_clarification"),
    [
        (
            {
                "route": "training_business",
                "intents": [],
                "slots": [],
                "risk": None,
                "need_clarification": True,
                "clarification": "训练什么部位？",
            },
            "training_business",
            None,
            True,
        ),
        (
            {
                "route": "safety",
                "intents": [],
                "slots": [],
                "risk": {"type": "pain_injury", "zh": "疼痛", "level": "high"},
                "need_clarification": False,
                "clarification": None,
            },
            "safety",
            "high",
            False,
        ),
    ],
)
def test_intent_service_preserves_task_101_contracts(
    scenario_server: _ScenarioServer,
    output: dict[str, Any],
    expected_route: str,
    expected_risk: str | None,
    expected_clarification: bool,
) -> None:
    scenario_server.responses = [{"status": 200, "payload": _completion(json.dumps(output))}]
    provider = _provider(scenario_server, max_retries=0)
    sink = InMemoryTraceSink()
    service = IntentService(
        InMemoryRuntimeConfigLoader(_snapshot(), provider.model_config),
        provider,
        PromptBuilder(),
        sink,
    )

    result = asyncio.run(service.analyze(text="测试", request_id="req-3"))

    assert result.route == expected_route
    assert (result.risk.level if result.risk else None) == expected_risk
    assert result.need_clarification is expected_clarification
    if expected_route == "training_business":
        assert sink.records[0].validation_issues[0].code == "INTENTS_EMPTY"


def test_provider_failure_is_not_mapped_to_unknown(scenario_server: _ScenarioServer) -> None:
    scenario_server.responses = [{"status": 429, "payload": {"error": {"message": "limited"}}}]
    provider = _provider(scenario_server, max_retries=0)
    service = IntentService(
        InMemoryRuntimeConfigLoader(_snapshot(), provider.model_config),
        provider,
        PromptBuilder(),
        InMemoryTraceSink(),
    )

    with pytest.raises(ProviderError) as raised:
        asyncio.run(service.analyze(text="你好", request_id="req-4"))

    assert raised.value.code == ErrorCode.MODEL_RATE_LIMIT


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("not-json", ErrorCode.MODEL_OUTPUT_PARSE_ERROR),
        (
            '{"route":"social_chat","intents":[],"need_clarification":false,"clarification":null}',
            ErrorCode.MODEL_OUTPUT_SCHEMA_ERROR,
        ),
    ],
)
def test_intent_service_separates_parse_and_schema_errors(
    scenario_server: _ScenarioServer, content: str, expected: ErrorCode
) -> None:
    scenario_server.responses = [{"status": 200, "payload": _completion(content)}]
    provider = _provider(scenario_server, max_retries=0)
    service = IntentService(
        InMemoryRuntimeConfigLoader(_snapshot(), provider.model_config),
        provider,
        PromptBuilder(),
        InMemoryTraceSink(),
    )

    with pytest.raises(IntentServiceError) as raised:
        asyncio.run(service.analyze(text="你好", request_id="req-2"))

    assert raised.value.code == expected


def test_provider_sanitizes_sensitive_values() -> None:
    sanitized = QwenProvider.sanitize(
        {
            "Authorization": "Bearer secret",
            "nested": {"api_key": "abc", "safe": "ok"},
            "message": '{"token":"also-hidden","safe":"ok"}',
            "inline": "api_key=also-hidden",
            "prose": "my password is Tr0ub4dor and token is abc123",
            "bearer": "Authorization: Bearer abc.def-123",
            "nested_list": ["the API key is sk-live", {"note": "secret: hidden"}],
        }
    )

    assert sanitized == {
        "Authorization": "[REDACTED]",
        "nested": {"api_key": "[REDACTED]", "safe": "ok"},
        "message": '{"token":"[REDACTED]","safe":"ok"}',
        "inline": "api_key=[REDACTED]",
        "prose": "my password is [REDACTED] and token is [REDACTED]",
        "bearer": "Authorization: Bearer [REDACTED]",
        "nested_list": ["the API key is [REDACTED]", {"note": "secret: [REDACTED]"}],
    }


def test_raw_request_redacts_natural_language_secrets(scenario_server: _ScenarioServer) -> None:
    scenario_server.responses = [{"status": 500, "payload": {"error": {"message": "token is abc"}}}]
    provider = _provider(scenario_server, max_retries=0)
    prompt = PromptBuilder().build(
        _snapshot(),
        text="My password is Tr0ub4dor; bearer abc.def-123",
        context={"token": "abc"},
    )

    with pytest.raises(ProviderError) as raised:
        asyncio.run(provider.invoke(prompt))

    serialized_attempt = json.dumps(raised.value.attempts[0].model_dump(mode="json"))
    assert "Tr0ub4dor" not in serialized_attempt
    assert "abc.def-123" not in serialized_attempt
    assert 'abc"' not in serialized_attempt
    assert "[REDACTED]" in serialized_attempt
