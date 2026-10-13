# TASK-102 Execution Report

## Result

**Implementation complete; pending independent review.** No TASK-201 or TASK-103 work was started.

## Baseline and workspace isolation

- Code baseline: `b927380d2b308c7ef050c89855fa01582cb0666f` (`fix: align TASK-101 v1.2.5 contracts`).
- At task start, the index already contained the user-owned v1.2.5 documents, including
  `UV_MIGRATION_REVIEW.md`, `TASK-101_V1.2.5_FINAL_REVIEW.md`, and contract-document changes.
  They were inspected as the contract source and not modified, staged, or included in the
  TASK-102 change set.
- Real Qwen smoke test: **UNVERIFIED**. `DASHSCOPE_API_KEY` was absent; no key was printed,
  sent, or substituted.

## Files changed for TASK-102

- `backend/pyproject.toml`, `backend/uv.lock`: add locked `openai==1.109.1`.
- `backend/app/providers/types.py`: provider protocol, normalized response, and one-record-per-
  physical-request `LLMAttempt` contract.
- `backend/app/providers/qwen.py`: async OpenAI-compatible Qwen adapter, explicit timeout,
  SDK retry disablement, bounded cancellable retry, semaphore queue deadline, typed failures,
  structured-output request construction, and secret sanitization.
- `backend/app/providers/__init__.py`: provider exports.
- `backend/app/services/intent_service.py`: dependency-injected `load -> build -> invoke ->
  parse -> validate -> result -> trace sink` pipeline plus in-memory loader/sink.
- `backend/app/services/__init__.py`: service exports.
- `backend/tests/test_provider_contract.py`: TASK-102 contract coverage using a local counting
  HTTP server.
- `PROJECT_STATUS.md`: TASK-102 status update.

## Contract and implementation evidence

### C11: SDK retries and attempts

`QwenProvider` creates `AsyncOpenAI(..., max_retries=0, timeout=<ModelConfigSnapshot>)`.
Provider-owned retry retries only timeout, 429, 5xx, and connection failures, with at most
`1 + max_retries` physical requests; 4xx is not retried. Backoff uses `asyncio.sleep`, so it is
cancellable and does not block the event loop. Semaphore acquisition is bounded by
`queue_wait_timeout` and returns `SERVICE_BUSY` without an HTTP attempt on expiry.

`test_c11_sdk_retries_are_disabled_and_each_http_request_has_one_attempt` drives a real local
HTTP server through one 500 then one 200. The server counted **2** requests and the returned
response had exactly **2** `LLMAttempt` rows, with attempt numbers `[1, 2]`. This verifies the
SDK did not add its documented hidden retries.

Additional executable cases cover timeout, 429, 5xx, a transport connection error,
non-retryable 400, cancellation-friendly event-loop progress, and queue timeout.

### C12: structured output

Both `json_schema` and `json_object` are explicit Model Config modes. There is no failure-path
downgrade between them. For structured output, `ModelConfigSnapshot` rejects non-null
`params.max_tokens`; request construction also removes it defensively. The JSON Schema request
uses `LLMStructuredIntentOutput.model_json_schema()` with `strict: true` and asserts the schema
does not contain `minItems`.

The counting-server test proves the actual serialized body has no `max_tokens`, contains
`response_format.type=json_schema`, `strict=true`, and no `minItems`. The json-object test
proves the existing PromptBuilder message contains `JSON`, as required by Qwen, and a json-schema
400 remains a json-schema error rather than switching modes.

### IntentService and TASK-101 non-regression

- `IntentService` parses JSON separately from Pydantic/schema/business validation:
  malformed JSON is `MODEL_OUTPUT_PARSE_ERROR`; structural or business contradictions are
  `MODEL_OUTPUT_SCHEMA_ERROR`.
- Provider errors propagate as typed ProviderError values; they never become `route=unknown`.
- The service calls the existing `validate_llm_output`, preserving `INTENTS_EMPTY_NON_TRAINING`,
  `CLARIFICATION_FORCED_OFF`, and `SLOT_SPAN_INVALID` as trace-only diagnostics.
- Tests exercise non-training empty intents, training clarification normalization, `risk=null`,
  safety with risk, malformed JSON, schema-invalid missing `risk`, and Provider error propagation.
- Trace data is outside `IntentResult`; every attempt records sanitized request/response, parsed
  JSON when available, request id, model/finish metadata, usage, latency, status, and typed error.
  Authorization/API-key/secret/token/password keys and JSON embedded in raw message strings are
  redacted. Headers are never persisted.

## Qwen choice and compatibility

The selected initial model identifier for a `json_schema` Model Config is **`qwen3.7-plus`**.
Alibaba Model Studio currently lists the Qwen3.7-Plus series as supporting JSON Schema and requires
`response_format={"type":"json_schema","json_schema":{...,"strict":true}}`; its JSON Object
mode requires the word `JSON` in a message and does not guarantee schema shape. It also explicitly
advises not to set `max_tokens` with structured output. The real smoke request is UNVERIFIED due
to the missing deployment secret; the documented support result must not be read as an executed
account/model entitlement test.

## References actually consulted

- Repository: `AGENTS.md`; `tasks/README.md`; TASK-102; docs 02, 03, 06, 09, 10;
  `TASK-101_V1.2.5_FINAL_REVIEW.md`; current intent contract, PromptBuilder, tests;
  `backend/pyproject.toml`, and `backend/uv.lock`.
- [openai/openai-python README](https://github.com/openai/openai-python/blob/main/README.md):
  AsyncOpenAI, default retry behavior, `max_retries=0`, explicit timeout, `_request_id`, and
  raw-response behavior. The resulting locked SDK is `openai==1.109.1`.
- [Alibaba Model Studio structured-output documentation](https://www.alibabacloud.com/help/en/model-studio/qwen-structured-output):
  OpenAI-compatible modes, strict schema request shape, Qwen model support, JSON-object prompt
  requirement, and the `max_tokens` restriction.
- [sohaggain classifier.py](https://raw.githubusercontent.com/sohaggain/ai-text-classification-api/main/src/services/classifier.py):
  reviewed only for a single provider boundary, typed error split, and test organization.

Not adopted: its synchronous `OpenAI` client, Tenacity decorator retry, fixed static schema with
`minItems`, singleton wiring, and its generic parsing/error semantics. This task uses AsyncOpenAI,
SDK retries disabled, one explicit retry loop, dynamic TASK-101 schema, independent attempts, and
the project error contract.

## Required gate output

Run from `backend/` after the final changes:

```text
$ uv run --locked --extra dev ruff check .
All checks passed!

$ uv run --locked --extra dev ruff format --check .
43 files already formatted

$ uv run --locked --extra dev pytest -q -rs
...........................................ss......................      [100%]
=========================== short test summary info ===========================
SKIPPED [2] tests\test_mysql_integration.py:57: MYSQL_TEST_DATABASE_URL is not configured; MySQL 8 integration tests are skipped
```

All commands exited 0. The two skips are the existing MySQL 8 integration tests; no isolated
`MYSQL_TEST_DATABASE_URL` was supplied. Provider/unit contract tests are not skipped.

## DoD and risk

| Item | Result |
|---|---|
| Unit-testable IntentService without FastAPI/MySQL | PASS |
| Explicit typed provider and output failures | PASS |
| C11 / C12 executable evidence | PASS |
| TASK-101 regression | PASS |
| Real Qwen smoke request | UNVERIFIED — no API key |
| Durable DB Trace, raw-size retention, Admin/runtime wiring | Not implemented; TASK-103 scope |
| Active Release / Model Config persistence and runtime construction | Not implemented; TASK-201 scope |

Known boundary: `QwenProvider` is constructed from the immutable effective `ModelConfigSnapshot`.
TASK-201 must construct/replace that adapter only from the active release's frozen default model
config, never a mutable draft. Its persisted trace adapter must consume `TraceRecord.attempts`
without altering one-HTTP-request/one-attempt semantics.

## TASK-201 handoff

TASK-201 can use `RuntimeConfiguration(snapshot, model_config_snapshot)` from the loader,
`QwenProvider(ModelConfigSnapshot, api_key, ...)`, and the `LLMProvider`, `RuntimeConfigLoader`,
and `TraceSink` protocols directly. It must preserve this task's immutable Model Config snapshot,
the selected structured-output mode, and the provider instance/config pairing. Before TASK-103,
the required Provider/IntentService ↔ Release/ModelConfig interface review remains mandatory.
