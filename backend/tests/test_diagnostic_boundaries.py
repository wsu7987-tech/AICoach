"""Second-fix regressions: real HTTP plus diagnostic-only security boundaries."""

import asyncio
import json
import logging
import time
import traceback
from typing import Any

import httpx
import openai
import pytest

from app.core.diagnostics import (
    ERROR_SUMMARY_MAX_BYTES,
    diagnostic_payload,
    error_summary,
    sanitize,
)
from app.core.logging import JsonFormatter
from app.core.settings import get_settings
from app.prompting.builder import PromptBuilder
from app.providers.qwen import ProviderError, QwenProvider
from app.providers.types import ProviderCancelledError
from app.services.intent_service import (
    InMemoryRuntimeConfigLoader,
    InMemoryTraceSink,
    IntentService,
    IntentServiceError,
)
from tests.test_provider_contract import (
    _completion,
    _provider,
    _snapshot,
    _wait_for_requests,
)
from tests.test_provider_contract import scenario_server as scenario_server

SECRET = "fictional-private-value"
TEXT = f"password is {SECRET}"
OUTPUT = {
    "route": "information_query",
    "intents": [],
    "slots": [],
    "risk": None,
    "need_clarification": False,
    "clarification": None,
}


def service(provider: QwenProvider, sink: Any) -> IntentService:
    return IntentService(
        InMemoryRuntimeConfigLoader(_snapshot(), provider.model_config),
        provider,
        PromptBuilder(),
        sink,
    )


@pytest.mark.parametrize(
    "value",
    [
        TEXT,
        f"token is {SECRET}",
        f"API key is {SECRET}",
        f"Authorization: Bearer {SECRET}",
        {"password": SECRET, "nested": [{"token": SECRET}, {"api_key": SECRET}]},
        json.dumps({"password": SECRET, "nested": [{"token": SECRET}]}),
        f"Error code: 400 - {{'error': {{'password': '{SECRET}', 'token': '{SECRET}'}}}}",
        f'Error code: 400 - {{"api_key": "{SECRET}"}}',
        f"password is '{SECRET} with spaces'",
    ],
)
def test_redaction_is_recursive_idempotent_and_does_not_mutate(value):
    before = json.dumps(value)
    clean = sanitize(value)
    assert SECRET not in json.dumps(clean)
    assert "[REDACTED]" in json.dumps(clean)
    assert sanitize(clean) == clean
    assert json.dumps(value) == before


def test_sdk_summary_prefers_structured_body_over_exception_string():
    response = httpx.Response(400, request=httpx.Request("POST", "http://localhost/v1"))
    error = openai.BadRequestError(
        SECRET, response=response, body={"message": TEXT, "password": SECRET, "code": "bad"}
    )
    summary = QwenProvider._safe_error_message(error)
    assert SECRET not in summary
    assert "BadRequestError" in summary and "400" in summary and "bad" in summary


@pytest.mark.parametrize(
    "mode,status",
    [
        ("success", "written"),
        ("raise", "failed"),
        ("block", "timed_out"),
        ("repeat_cancel", "interrupted"),
        ("self_cancel", "interrupted"),
    ],
)
def test_cancel_trace_deadline_identity_cleanup_and_safe_fallback(
    scenario_server, caplog, mode, status
):
    scenario_server.responses = [
        {"delay": 0.3, "payload": _completion("{}")},
        {"payload": _completion(json.dumps(OUTPUT))},
    ]

    async def run():
        provider = _provider(scenario_server, timeout_seconds=2, max_retries=2)
        originals = []
        invoke = provider.invoke

        async def observe(prompt):
            try:
                return await invoke(prompt)
            except ProviderCancelledError as exc:
                originals.append(exc)
                raise

        provider.invoke = observe

        class Sink:
            def __init__(self):
                self.entered = asyncio.Event()
                self.cleaned = False
                self.records = []

            async def write(self, trace):
                self.entered.set()
                try:
                    if mode == "raise":
                        raise RuntimeError(TEXT)
                    if mode == "self_cancel":
                        raise asyncio.CancelledError(TEXT)
                    if mode == "success":
                        await asyncio.sleep(0.005)
                        self.records.append(trace)
                    else:
                        await asyncio.Event().wait()
                finally:
                    self.cleaned = True

        sink = Sink()
        task = asyncio.create_task(service(provider, sink).analyze(text=TEXT))
        try:
            await _wait_for_requests(scenario_server, 1)
            started = time.monotonic()
            task.cancel("first")
            await asyncio.wait_for(sink.entered.wait(), 1)
            if mode == "repeat_cancel":
                task.cancel("second")
                task.cancel("third")
            done, _ = await asyncio.wait({task}, timeout=0.3)
            assert task in done
            with pytest.raises(ProviderCancelledError) as caught:
                await task
            cancellation = caught.value
            assert cancellation is originals[0]
            assert task.cancelled() and time.monotonic() - started < 0.3
            assert sink.cleaned
            assert cancellation.trace_write_status == status
            assert len(cancellation.attempts) == len(scenario_server.request_bodies) == 1
            assert cancellation.attempts[0].status == "cancelled"
            assert cancellation.trace_diagnostic["cancelled"] is True
            assert cancellation.trace_diagnostic["error_code"] is None
            assert SECRET not in json.dumps(cancellation.trace_diagnostic)
            assert SECRET not in caplog.text
            assert len(sink.records) == (1 if mode == "success" else 0)
            if mode != "success":
                assert "TRACE_PERSIST_FAILED" in caplog.text
                assert f"status={status}" in caplog.text
            assert provider._semaphore._value == 1
            assert not [
                t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()
            ]
            # Verify reuse through the real network, not only the private permit counter.
            next_sink = InMemoryTraceSink()
            await service(provider, next_sink).analyze(text="next")
            assert len(scenario_server.request_bodies) == 2
            assert len(next_sink.records) == len(next_sink.records[0].attempts) == 1
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await provider._client.close()

    asyncio.run(run())


@pytest.mark.parametrize("present", [True, False])
def test_business_validation_uses_original_slot_while_diagnostics_are_clean(
    scenario_server, present
):
    slot = {
        "name": "exercise",
        "zh": "动作",
        "value": TEXT,
        "start": 0,
        "end": len(TEXT),
        "confidence": 1,
    }
    output = OUTPUT | {
        "intents": [{"name": "query_progress", "zh": "进度", "confidence": 1}],
        "slots": [slot],
        "reason_summary": TEXT,
    }
    scenario_server.responses = [{"payload": _completion(json.dumps(output))}]

    async def run():
        provider = _provider(scenario_server)
        sink = InMemoryTraceSink()
        try:
            result = await service(provider, sink).analyze(text=TEXT if present else "ordinary")
            if present:
                assert result.text == TEXT and result.slots[0].value == TEXT
                assert sink.records[0].validation_issues == []
                assert SECRET in json.dumps(scenario_server.request_bodies[0])
            else:
                assert result.slots == []
                assert sink.records[0].validation_issues[0].code == "SLOT_SPAN_INVALID"
                assert sink.records[0].validation_issues[0].slot.value == "password is [REDACTED]"
            assert SECRET not in sink.records[0].model_dump_json()
            assert sink.records[0].attempts[0].parsed_payload["route"] == "information_query"
        finally:
            await provider._client.close()

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["provider", "business", "schema"])
def test_error_tracebacks_do_not_reexpose_raw_causes(scenario_server, kind):
    output = OUTPUT | {"intents": [{"name": TEXT, "zh": "x", "confidence": 1}]}
    if kind == "schema":
        output["risk"] = TEXT
    scenario_server.responses = [
        {"status": 400, "payload": {"error": {"password": SECRET}}}
        if kind == "provider"
        else {"payload": _completion(json.dumps(output))}
    ]

    async def run():
        provider = _provider(scenario_server, max_retries=0)
        sink = InMemoryTraceSink()
        try:
            with pytest.raises((ProviderError, IntentServiceError)) as caught:
                await service(provider, sink).analyze(text="ordinary")
            assert SECRET not in "".join(traceback.format_exception(caught.value))
            assert SECRET not in caught.value.message
            assert SECRET not in sink.records[0].model_dump_json()
        finally:
            await provider._client.close()

    asyncio.run(run())


def test_utf8_limits_include_markers_and_json_escaping(monkeypatch):
    monkeypatch.setenv("TRACE_RAW_MAX_BYTES", "1024")
    get_settings.cache_clear()
    try:
        huge = '😀汉字"\\\n' * 1000
        payload = diagnostic_payload({"body": huge, "password": SECRET})
        assert payload["truncated"] is True
        assert len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) <= 1024
        assert SECRET not in json.dumps(payload)
        assert "\ufffd" not in payload["preview"]
        assert diagnostic_payload(payload) == payload
        summary = error_summary(huge)
        assert len(summary.encode("utf-8")) <= ERROR_SUMMARY_MAX_BYTES
        assert summary.endswith("[truncated=true]") and "\ufffd" not in summary
    finally:
        get_settings.cache_clear()


def test_real_http_size_caps_leave_business_content_intact(scenario_server, monkeypatch):
    monkeypatch.setenv("TRACE_RAW_MAX_BYTES", "1024")
    get_settings.cache_clear()
    output = OUTPUT | {"reason_summary": "😀" * 2000}
    scenario_server.responses = [{"payload": _completion(json.dumps(output))}]

    async def run():
        provider = _provider(scenario_server, timeout_seconds=2)
        sink = InMemoryTraceSink()
        try:
            result = await service(provider, sink).analyze(text=TEXT)
            assert result.route == "information_query" and result.text == TEXT
            attempt = sink.records[0].attempts[0]
            for field in (attempt.raw_request, attempt.raw_response, attempt.parsed_payload):
                assert field["truncated"] is True
                assert len(json.dumps(field, ensure_ascii=False).encode("utf-8")) <= 1024
            assert SECRET in json.dumps(scenario_server.request_bodies[0])
            assert SECRET not in sink.records[0].model_dump_json()
        finally:
            await provider._client.close()

    try:
        asyncio.run(run())
    finally:
        get_settings.cache_clear()


def test_log_formatter_sanitizes_message_and_exception_copies():
    record = logging.LogRecord("test", logging.ERROR, "test", 1, "%s", (TEXT,), None)
    try:
        raise RuntimeError(f"SDK error {{'password': '{SECRET}'}}")
    except RuntimeError as exc:
        record.exc_info = (type(exc), exc, exc.__traceback__)
    encoded = JsonFormatter().format(record)
    assert SECRET not in encoded and "[REDACTED]" in encoded


@pytest.mark.parametrize("provider_failed", [False, True])
def test_cancellation_during_normal_sink_write_preserves_completed_attempt(
    scenario_server, provider_failed
):
    scenario_server.responses = [
        {"status": 400, "payload": {"error": {"message": TEXT}}}
        if provider_failed
        else {"payload": _completion(json.dumps(OUTPUT))}
    ]

    async def run():
        provider = _provider(scenario_server, max_retries=0)

        class Sink:
            def __init__(self):
                self.entered = asyncio.Event()
                self.cleaned = 0

            async def write(self, trace):
                self.entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    self.cleaned += 1

        sink = Sink()
        task = asyncio.create_task(service(provider, sink).analyze(text=TEXT))
        try:
            await asyncio.wait_for(sink.entered.wait(), 1)
            task.cancel()
            done, _ = await asyncio.wait({task}, timeout=0.3)
            assert task in done
            with pytest.raises(ProviderCancelledError) as caught:
                await task
            assert caught.value.trace_write_status == "timed_out"
            assert caught.value.trace_diagnostic["cancelled"] is True
            assert len(caught.value.attempts) == len(scenario_server.request_bodies) == 1
            assert caught.value.attempts[0].status == ("failed" if provider_failed else "succeeded")
            assert sink.cleaned == 2
            assert SECRET not in json.dumps(caught.value.trace_diagnostic)
            assert provider._semaphore._value == 1
            assert not [
                t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()
            ]
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await provider._client.close()

    asyncio.run(run())
