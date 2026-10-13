"""Independent ed2e8ae review probes; deliberately retain failing acceptance tests.

Run from backend: uv run --locked --extra dev pytest -o addopts='' -q -rs
    ../review_artifacts/task102_incremental/test_review.py
Only fabricated secrets and localhost HTTP are used. No SDK method is mocked.
"""

import asyncio
import json
import logging
import socket
import sys
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.prompting.builder import PromptBuilder
from app.providers.qwen import ProviderError, QwenProvider
from app.providers.types import ProviderCancelledError
from app.schemas.intent import ModelConfigSnapshot, RuntimeConfigSnapshot
from app.services.intent_service import (
    InMemoryRuntimeConfigLoader,
    InMemoryTraceSink,
    IntentService,
    IntentServiceError,
)

SECRETS = ["Tr0ub4dor", "abc123", "secret123", "test-secret"]
TEXT = "my password is Tr0ub4dor; token is abc123; API key is secret123; Authorization: Bearer test-secret"
NESTED = {"password": SECRETS[0], "nested": [{"token": SECRETS[1]}, {"api_key": SECRETS[2]}]}
OUTPUT = dict(route="information_query", intents=[], slots=[], risk=None,
              need_clarification=False, clarification=None)


def completion(output=None):
    return dict(id="review-completion", object="chat.completion", created=1,
                model="review-model-version", system_fingerprint="review-fingerprint",
                choices=[dict(index=0, message=dict(role="assistant", content=json.dumps(
                    OUTPUT if output is None else output)), finish_reason="stop")],
                usage=dict(prompt_tokens=11, completion_tokens=7, total_tokens=18))


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        with self.server.lock:
            index = len(self.server.requests)
            self.server.requests.append(body)
            self.server.sdk_retry_counts.append(self.headers.get("x-stainless-retry-count"))
            action = self.server.actions[index] if index < len(self.server.actions) else {}
        if action.get("drop"):
            self.connection.shutdown(socket.SHUT_RDWR)
            self.connection.close()
            return
        if action.get("hold"):
            self.server.release.wait(4)
        time.sleep(action.get("delay", 0))
        body = json.dumps(action.get("payload", completion())).encode()
        try:
            self.send_response(action.get("status", 200))
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("x-request-id", "review-request-id")
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def log_message(self, *args):
        pass


@contextmanager
def server(actions):
    instance = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    instance.actions = actions
    instance.requests = []
    instance.sdk_retry_counts = []
    instance.lock = threading.Lock()
    instance.release = threading.Event()
    thread = threading.Thread(target=instance.serve_forever, kwargs={"poll_interval": 0.01})
    thread.start()
    try:
        yield instance
    finally:
        instance.release.set()
        instance.shutdown()
        instance.server_close()
        thread.join()


def snapshot():
    return RuntimeConfigSnapshot.model_validate(json.loads(
        (ROOT / "bootstrap/initial-config.v1.json").read_text(encoding="utf-8")))


def provider(srv, **kwargs):
    config = dict(id=1, name="independent-review", version="1", provider="qwen",
                  model="qwen3.7-plus", base_url=f"http://127.0.0.1:{srv.server_port}/v1",
                  params={"temperature": 0}, timeout_seconds=1, max_retries=0,
                  max_concurrency=1, structured_output_mode="json_schema",
                  credential_ref="env/DASHSCOPE_API_KEY", model_config_hash="a" * 64)
    config.update(kwargs)
    return QwenProvider(ModelConfigSnapshot.model_validate(config), api_key="review-fake-key",
                        queue_wait_timeout=0.1, backoff_base_seconds=0)


def service(p, sink):
    return IntentService(InMemoryRuntimeConfigLoader(snapshot(), p.model_config), p,
                         PromptBuilder(), sink)


async def received(srv, count):
    async with asyncio.timeout(3):
        while len(srv.requests) < count:
            await asyncio.sleep(0.002)


def serialized(value):
    return json.dumps(value.model_dump(mode="json") if hasattr(value, "model_dump") else value)


def assert_clean(value):
    encoded = serialized(value)
    assert all(secret not in encoded for secret in SECRETS), "fabricated secret survived in diagnostic"


@pytest.mark.parametrize("actions,retries,timeout,code,count", [
    ([{}], 0, 1, None, 1),
    ([{"status": 429}, {}], 1, 1, None, 2),
    ([{"status": 500}] * 3, 2, 1, "MODEL_PROVIDER_ERROR", 3),
    ([{"delay": 0.2}] * 2, 1, 0.05, "MODEL_TIMEOUT", 2),
    ([{"status": 400}], 2, 1, "MODEL_PROVIDER_ERROR", 1),
    ([{"status": 500}], 0, 1, "MODEL_PROVIDER_ERROR", 1),
    ([{"drop": True}] * 2, 1, 1, "MODEL_PROVIDER_ERROR", 2),
], ids=["200", "429-success", "5xx-bound", "timeout", "400", "retry-zero", "connection-drop"])
def test_real_http_matrix(actions, retries, timeout, code, count):
    with server(actions) as srv:
        async def run():
            p = provider(srv, max_retries=retries, timeout_seconds=timeout)
            sink = InMemoryTraceSink()
            try:
                if code:
                    with pytest.raises(ProviderError) as caught:
                        await service(p, sink).analyze(text="ordinary input")
                    assert caught.value.code.value == code
                else:
                    result = await service(p, sink).analyze(text="ordinary input")
                    assert result.route == "information_query"
                attempts = sink.records[0].attempts
                assert len(attempts) == len(srv.requests) == count
                assert [a.attempt_no for a in attempts] == list(range(1, count + 1))
                assert [a.is_retry for a in attempts] == [False] + [True] * (count - 1)
                assert p.sdk_max_retries == 0
                assert srv.sdk_retry_counts == ["0"] * count
                assert all("max_tokens" not in body for body in srv.requests)
                if not code:
                    assert attempts[-1].provider_request_id == "review-request-id"
                    assert attempts[-1].model_version == "review-model-version"
                    assert attempts[-1].system_fingerprint == "review-fingerprint"
                    assert attempts[-1].finish_reason == "stop"
                    assert attempts[-1].usage["total_tokens"] == 18
            finally:
                await p._client.close()
        asyncio.run(run())


@pytest.mark.parametrize("mode", ["json_schema", "json_object"])
def test_structured_modes(mode):
    with server([{}]) as srv:
        async def run():
            p = provider(srv, structured_output_mode=mode)
            try:
                await service(p, InMemoryTraceSink()).analyze(text="ordinary input")
                body = srv.requests[0]
                assert "max_tokens" not in body
                assert body["response_format"]["type"] == mode
                if mode == "json_schema":
                    assert body["response_format"]["json_schema"]["strict"] is True
                    assert "minItems" not in serialized(body["response_format"])
                    unsupported = ["multipleOf", "uniqueItems", "contains", "minContains",
                                   "maxContains", "additionalItems", "patternProperties", "propertyNames"]
                    assert all(f'"{key}":' not in serialized(body["response_format"])
                               for key in unsupported)
                else:
                    assert body["response_format"] == {"type": "json_object"}
                    assert "JSON" in body["messages"][0]["content"]
            finally:
                await p._client.close()
        asyncio.run(run())


def test_cancel_inflight_and_reuse():
    with server([{"hold": True}, {}]) as srv:
        async def run():
            p = provider(srv, max_retries=2)
            sink = InMemoryTraceSink()
            try:
                task = asyncio.create_task(service(p, sink).analyze(text=TEXT, context=NESTED))
                await received(srv, 1)
                task.cancel()
                with pytest.raises(ProviderCancelledError) as caught:
                    await task
                assert isinstance(caught.value, asyncio.CancelledError) and task.cancelled()
                assert len(srv.requests) == 1
                a = caught.value.attempts[0]
                assert a.status == "cancelled" and a.attempt_no == 1 and not a.is_retry
                assert a.latency_ms > 0 and a.provider == "qwen" and a.model == "qwen3.7-plus"
                assert a.provider_request_id is None and a.raw_response is None
                assert_clean(a)
                assert "[REDACTED]" in serialized(a.raw_request)
                assert sink.records[0].cancelled and sink.records[0].attempts == [a]
                assert all(secret in serialized(srv.requests[0]) for secret in SECRETS)
                await service(p, sink).analyze(text="next request")
                assert len(srv.requests) == 2
            finally:
                await p._client.close()
        asyncio.run(run())


def test_cancel_backoff_reaches_sink():
    with server([{"status": 500, "payload": {"error": {"message": TEXT}}}]) as srv:
        async def run():
            p = provider(srv, max_retries=1)
            p.backoff_base_seconds = 30
            sink = InMemoryTraceSink()
            task = asyncio.create_task(service(p, sink).analyze(text="ordinary input"))
            try:
                await received(srv, 1)
                # Observe actual coroutine suspension in backoff; no fixed sleep race.
                async with asyncio.timeout(3):
                    while True:
                        coro = task.get_coro()
                        backoff = False
                        while coro is not None:
                            frame = getattr(coro, "cr_frame", None)
                            if frame and frame.f_code.co_name == "_invoke_after_acquire":
                                backoff = len(frame.f_locals.get("attempts", [])) == 1
                            coro = getattr(coro, "cr_await", None)
                        if backoff:
                            break
                        await asyncio.sleep(0.002)
                task.cancel()
                with pytest.raises(ProviderCancelledError) as caught:
                    await task
                assert len(srv.requests) == len(caught.value.attempts) == 1
                assert caught.value.attempts[0].status == "failed"
                assert caught.value.attempts[0].provider_request_id == "review-request-id"
                assert sink.records[0].attempts == caught.value.attempts
                assert_clean(sink.records[0])
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                await p._client.close()
        asyncio.run(run())


@pytest.mark.parametrize("cancel", [True, False], ids=["queue-cancel", "queue-timeout"])
def test_queue_no_phantom_and_permit_reuse(cancel):
    with server([{"hold": True}, {}]) as srv:
        async def run():
            p = provider(srv)
            sink = InMemoryTraceSink()
            first = asyncio.create_task(service(p, sink).analyze(text="first"))
            try:
                await received(srv, 1)
                second = asyncio.create_task(service(p, sink).analyze(text="queued"))
                await asyncio.sleep(0.01)
                if cancel:
                    second.cancel()
                with pytest.raises(ProviderCancelledError if cancel else ProviderError) as caught:
                    await second
                assert caught.value.attempts == [] and len(srv.requests) == 1
                if not cancel:
                    assert caught.value.code.value == "SERVICE_BUSY"
                assert len(sink.records) == 1 and sink.records[0].attempts == []
                srv.release.set()
                await first
                await service(p, sink).analyze(text="third")
                assert len(srv.requests) == 2 and p._semaphore._value == 1
            finally:
                srv.release.set()
                await asyncio.gather(first, return_exceptions=True)
                await p._client.close()
        asyncio.run(run())


@pytest.mark.parametrize("behavior", ["raise", "block", "repeat_cancel"])
def test_cancel_sink_failure_boundary(behavior):
    with server([{"hold": True}]) as srv:
        async def run():
            p = provider(srv)
            class Sink:
                def __init__(self):
                    self.entered = asyncio.Event()
                    self.records = []
                async def write(self, trace):
                    self.entered.set()
                    if behavior == "raise":
                        raise RuntimeError("review sink failure")
                    await asyncio.Event().wait()
                    self.records.append(trace)
            sink = Sink()
            task = asyncio.create_task(service(p, sink).analyze(text="ordinary input"))
            try:
                await received(srv, 1)
                task.cancel()
                await asyncio.wait_for(sink.entered.wait(), 1)
                if behavior == "repeat_cancel":
                    task.cancel()
                    with pytest.raises(ProviderCancelledError):
                        await task
                else:
                    done, _ = await asyncio.wait({task}, timeout=0.3)
                    assert task in done, "cancellation stuck in TraceSink: no internal write deadline"
                    with pytest.raises(ProviderCancelledError):
                        await task
                assert len(srv.requests) == 1 and p._semaphore._value == 1
            finally:
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                await p._client.close()
                assert not [t for t in asyncio.all_tasks() if t is not asyncio.current_task()
                            and not t.done()], "unmanaged task survived cleanup"
        asyncio.run(run())


@pytest.mark.parametrize("value", [TEXT, NESTED, json.dumps(NESTED),
    {"messages": [{"role": "user", "content": TEXT}, {"content": json.dumps(NESTED)}]}])
def test_sanitizer_known_negative_inputs(value):
    clean = QwenProvider.sanitize(value)
    assert_clean(clean)
    assert "[REDACTED]" in serialized(clean)


def test_sanitizer_preserves_identifiers():
    value = dict(route="information_query", intent="query_progress", status="cancelled",
                 code="INTENTS_EMPTY_NON_TRAINING", provider_request_id="review-request-id")
    assert QwenProvider.sanitize(value) == value


@pytest.mark.parametrize("path", ["trace_text", "parsed_payload", "provider_error", "business_error",
                                  "cancel_trace", "cancel_params"])
def test_full_diagnostic_redaction(path, caplog):
    caplog.set_level(logging.INFO)
    output = OUTPUT | {"reason_summary": TEXT}
    actions = [{"payload": completion(output)}]
    if path == "provider_error":
        actions = [{"status": 400, "payload": {"error": NESTED}}]
    if path == "business_error":
        actions = [{"payload": completion(OUTPUT | {"intents": [
            {"name": "password is Tr0ub4dor", "zh": "review", "confidence": 0.9}]})}]
    if path.startswith("cancel"):
        actions = [{"hold": True}]
    with server(actions) as srv:
        async def run():
            p = provider(srv, **({"params": {"user": TEXT}} if path == "cancel_params" else {}))
            sink = InMemoryTraceSink()
            try:
                if path.startswith("cancel"):
                    task = asyncio.create_task(service(p, sink).analyze(text=TEXT))
                    await received(srv, 1)
                    task.cancel()
                    with pytest.raises(ProviderCancelledError) as caught:
                        await task
                    diagnostic = (caught.value.attempts[0].params if path == "cancel_params"
                                  else sink.records[0])
                elif path in {"provider_error", "business_error"}:
                    with pytest.raises(ProviderError if path == "provider_error" else IntentServiceError) as caught:
                        await service(p, sink).analyze(text="ordinary input")
                    diagnostic = dict(message=caught.value.message, trace=sink.records[0].model_dump(mode="json"))
                else:
                    result = await service(p, sink).analyze(text=TEXT, context=NESTED)
                    assert result.route == "information_query"
                    assert all(secret in serialized(srv.requests[0]) for secret in SECRETS)
                    assert_clean(sink.records[0].attempts[0].raw_request)
                    assert_clean(sink.records[0].attempts[0].raw_response)
                    diagnostic = (sink.records[0].text if path == "trace_text"
                                  else sink.records[0].attempts[0].parsed_payload)
                assert not any(secret in caplog.text for secret in SECRETS)
                assert_clean(diagnostic)
            finally:
                await p._client.close()
        asyncio.run(run())


def test_diagnostics_have_size_limit():
    # 2 MiB is a probe, not an invented contract limit. Current code retains all bytes.
    huge = "x" * (2 * 1024 * 1024)
    with server([{"status": 400, "payload": {"error": {"message": huge}}}]) as srv:
        async def run():
            p = provider(srv)
            sink = InMemoryTraceSink()
            try:
                with pytest.raises(ProviderError) as caught:
                    await service(p, sink).analyze(text="ordinary input")
                assert len(caught.value.message) < len(huge), "entire 2 MiB exception retained"
            finally:
                await p._client.close()
        asyncio.run(run())


def test_connect_refusal_is_network_attempt_not_server_receipt():
    # Reserve a localhost port without listen(): no HTTP server can receive a request.
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        class Endpoint:
            server_port = reserved.getsockname()[1]
        async def run():
            p = provider(Endpoint(), max_retries=1, timeout_seconds=3)
            started = []
            async def on_request(request):
                started.append(request.method)
            p._client._client.event_hooks["request"].append(on_request)
            try:
                with pytest.raises(ProviderError) as caught:
                    await service(p, InMemoryTraceSink()).analyze(text="ordinary input")
                assert caught.value.code.value == "MODEL_PROVIDER_ERROR"
                assert len(caught.value.attempts) == len(started) == 2
                assert all(a.provider_request_id is None and a.raw_response is None
                           for a in caught.value.attempts)
            finally:
                await p._client.close()
        asyncio.run(run())


@pytest.mark.parametrize("kind", ["success", "error", "cancel"])
def test_default_info_logs_do_not_emit_payload(kind, caplog, capsys):
    caplog.set_level(logging.INFO)
    actions = ([{"hold": True}] if kind == "cancel" else
               [{"status": 400, "payload": {"error": NESTED}}] if kind == "error" else
               [{"payload": completion(OUTPUT | {"reason_summary": TEXT})}])
    with server(actions) as srv:
        async def run():
            p = provider(srv)
            try:
                task = asyncio.create_task(service(p, InMemoryTraceSink()).analyze(text=TEXT))
                if kind == "cancel":
                    await received(srv, 1)
                    task.cancel()
                if kind == "success":
                    await task
                else:
                    with pytest.raises(ProviderError if kind == "error" else ProviderCancelledError):
                        await task
            finally:
                await p._client.close()
        asyncio.run(run())
    captured = capsys.readouterr()
    assert not any(secret in caplog.text + captured.out + captured.err for secret in SECRETS)
