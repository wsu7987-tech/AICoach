"""TASK-103 Runtime/Trace contracts that do not require a configured MySQL server."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.errors import AppError, ErrorCode
from app.main import create_app
from app.providers.types import LLMAttempt
from app.schemas.intent import IntentResult, OutputValidationIssue, SlotValue
from app.services.intent_service import IntentService, TraceRecord
from app.services.trace_store import DatabaseTraceStore


class _RuntimeService:
    def __init__(self, outcome: IntentResult | AppError) -> None:
        self.outcome = outcome
        self.calls: list[dict[str, Any]] = []

    async def analyze(self, **kwargs: Any) -> IntentResult:
        self.calls.append(kwargs)
        if isinstance(self.outcome, AppError):
            raise self.outcome
        return self.outcome


def _result(request_id: str = "req") -> IntentResult:
    return IntentResult(
        request_id=request_id,
        text="你好",
        route="social_chat",
        intents=[],
        slots=[],
        risk=None,
        need_clarification=False,
        clarification=None,
    )


def test_runtime_analyze_public_contract_and_upstream_request_id() -> None:
    app = create_app()
    service = _RuntimeService(_result("upstream"))
    app.state.intent_service = service
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/intent/analyze",
            json={"request_id": "upstream", "text": "你好", "context": {"page": "home"}},
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
    assert service.calls == [
        {
            "text": "你好",
            "context": {"page": "home"},
            "request_id": "upstream",
            "execution_mode": "runtime",
        }
    ]


@pytest.mark.parametrize(
    ("code", "status", "retry_after"),
    [
        (ErrorCode.CONFIG_NOT_READY, 503, None),
        (ErrorCode.MODEL_TIMEOUT, 504, None),
        (ErrorCode.MODEL_RATE_LIMIT, 503, 7),
        (ErrorCode.SERVICE_BUSY, 503, 1),
        (ErrorCode.MODEL_PROVIDER_ERROR, 502, None),
        (ErrorCode.MODEL_OUTPUT_PARSE_ERROR, 502, None),
        (ErrorCode.MODEL_OUTPUT_SCHEMA_ERROR, 502, None),
        (ErrorCode.INTERNAL_ERROR, 500, None),
    ],
)
def test_runtime_error_mapping(code: ErrorCode, status: int, retry_after: int | None) -> None:
    app = create_app()
    app.state.intent_service = _RuntimeService(
        AppError(code, "safe message", status, retry_after=retry_after)
    )
    with TestClient(app) as client:
        response = client.post("/api/v1/intent/analyze", json={"text": "你好"})

    assert response.status_code == status
    assert response.json()["error_code"] == code
    if retry_after:
        assert response.headers["Retry-After"] == str(retry_after)


def test_runtime_input_and_body_limits() -> None:
    app = create_app()
    with TestClient(app) as client:
        no_config = client.post("/api/v1/intent/analyze", json={"text": "你好"})
        invalid = client.post("/api/v1/intent/analyze", json={"text": " "})
        oversized = client.post(
            "/api/v1/intent/analyze",
            content=b"x" * (app.state.settings.max_request_body_bytes + 1),
            headers={"content-type": "application/json"},
        )
    assert no_config.status_code == 503
    assert no_config.json()["error_code"] == "CONFIG_NOT_READY"
    assert invalid.status_code == 422
    assert invalid.json()["error_code"] == "INVALID_INPUT"
    assert oversized.status_code == 413
    assert oversized.json()["error_code"] == "PAYLOAD_TOO_LARGE"


def test_validation_issue_is_utf8_bounded_without_changing_original_slot() -> None:
    raw_value = "中文😀" * 80_000
    original = OutputValidationIssue(
        code="SLOT_SPAN_INVALID",
        slot=SlotValue(name="exercise", zh="动作", value=raw_value, start=0, end=1, confidence=0.1),
    )
    trace = TraceRecord(
        trace_id="trace-p2",
        request_id="request-p2",
        text="输入",
        validation_issues=[original],
    )
    encoded = json.dumps(
        [issue.model_dump(mode="json") for issue in trace.validation_issues], ensure_ascii=False
    ).encode("utf-8")
    issue = trace.validation_issues[0]
    assert len(encoded) <= 65_536
    assert issue.code == "SLOT_SPAN_INVALID"
    assert issue.truncated is True
    assert issue.slot is not None and issue.slot.value.endswith("[truncated=true]")
    assert original.slot is not None and original.slot.value == raw_value


def test_trace_rows_are_sanitized_bounded_and_keep_attempt_provenance() -> None:
    attempt = LLMAttempt(
        attempt_no=1,
        is_retry=False,
        provider="qwen",
        model="qwen-test",
        params={"temperature": 0.1},
        raw_request={"authorization": "Bearer top-secret", "text": "hello"},
        raw_response={"content": "x" * 200_000},
        latency_ms=12,
        status="success",
    )
    trace = TraceRecord(
        trace_id="trace-store",
        request_id="same-upstream-request",
        text="hello",
        prompt={"final_prompt": "p" * 200_000, "prompt_hash": "a" * 64},
        attempts=[attempt],
    )
    safe = TraceRecord.model_validate(trace.model_dump(mode="json"))
    request_row = DatabaseTraceStore._request_row(safe)
    attempt_row = DatabaseTraceStore._attempt_row(safe, safe.attempts[0])
    assert request_row.trace_id == "trace-store"
    assert attempt_row.attempt_no == 1
    assert attempt_row.raw_request_json == {"authorization": "[REDACTED]", "text": "hello"}
    assert attempt_row.raw_response_truncated is True
    assert attempt_row.final_prompt_truncated is True
    assert attempt_row.prompt_hash == "a" * 64


def test_trace_failure_policy_runtime_open_and_debug_closed() -> None:
    class FailingSink:
        async def write(self, trace: TraceRecord) -> None:
            raise RuntimeError("database unavailable")

    service = IntentService(None, None, None, FailingSink())  # type: ignore[arg-type]
    trace = TraceRecord(trace_id="trace-policy", request_id="request-policy", text="hello")
    asyncio.run(service._persist_success(trace, fail_open=True))
    with pytest.raises(AppError) as raised:
        asyncio.run(service._persist_success(trace, fail_open=False))
    assert raised.value.code == ErrorCode.INTERNAL_ERROR
