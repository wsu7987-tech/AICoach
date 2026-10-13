# TASK-102 Independent Review — v1.2.5

**Review conclusion: FAIL.** This is a read-only independent review; no business code was changed and TASK-201 was not started.

TASK-102 has a sound async/provider core in the normal success, timeout, retry, and queue-full paths. It cannot be closed, however: an already-sent request cancelled by its caller has no `LLMAttempt` available to the caller or `TraceSink`, violating the mandatory one-physical-request/one-attempt invariant (C11). In addition, the claimed secret redaction demonstrably leaves common prose-form secrets in `raw_request`.

## 1. Git baseline and review scope

| Item | Observed result |
|---|---|
| Branch / HEAD | `main` / `ed30115e169fb4234789f37ba61d2d2bb68d220a` (`feat: implement Qwen provider and intent service`) |
| v1.2.5 document baseline | `090cb0b5db7921654f15d2a8440871db14c89aa5` (`fix：1.2.5文档提交`) |
| TASK-102 delta | 10 files, 1,268 insertions: provider/types, Qwen provider, IntentService, test, OpenAI dependency/lockfile, execution report, status marker |
| Working tree / index | clean at review start; this report is the sole uncommitted review artifact at completion, with no staged or business-code changes |
| Diff quality | `git diff --check 090cb0b..ed30115` passed |

Reviewed: `AGENTS.md`, `tasks/README.md`, TASK-102, docs 02/03/06/09/10, TASK-101 final review, TASK-102 execution report, the changed Python/test files, `backend/pyproject.toml`, and `backend/uv.lock`. The Task-101 contract suite and PromptBuilder were also inspected as consumed dependencies.

## 2. Architecture and implementation audit

### Provider

Passing observations:

- `QwenProvider` uses `AsyncOpenAI` and supplies explicit `timeout`, `max_retries=0`, and an async `httpx.AsyncClient` ([qwen.py:62](backend/app/providers/qwen.py#L62)). No synchronous OpenAI call is placed in an async path.
- The provider's own bounded loop is `range(1, max_retries + 2)` ([qwen.py:94](backend/app/providers/qwen.py#L94)); it retries only OpenAI timeout, 429, connection, and 5xx categories ([qwen.py:246](backend/app/providers/qwen.py#L246)). Backoff is cancellable `asyncio.sleep`.
- The semaphore is acquired through a bounded `wait_for` and released in `finally` ([qwen.py:75](backend/app/providers/qwen.py#L75)). A queue timeout returns `SERVICE_BUSY`, without an HTTP request or Attempt.
- Successful and ordinary failed calls retain sequential `attempt_no`, `is_retry`, latency, status, sanitised request/response, parsed payload, request id, model/fingerprint/finish reason and usage where supplied ([qwen.py:108](backend/app/providers/qwen.py#L108), [qwen.py:230](backend/app/providers/qwen.py#L230)). Missing SDK fields are read as `None`, not fabricated.
- Authentication headers are not put in `LLMAttempt`; no actual API key was found in code, Git delta, or current environment.

Failures are typed rather than converted to `unknown`; 400 is non-retryable, 429 is `MODEL_RATE_LIMIT`, and timeout is `MODEL_TIMEOUT`. The mapped HTTP statuses conform to docs/06 for the implemented codes.

### IntentService

The intended pipeline is present: `load -> PromptBuilder.build -> LLMProvider.invoke -> JSON parse -> Pydantic parse -> dynamic business validation -> result -> TraceSink` ([intent_service.py:117](backend/app/services/intent_service.py#L117)). It keeps Runtime output separate from trace diagnostics. Provider errors are re-raised, never made into `route=unknown`; malformed JSON and Pydantic/business violations are separated into `MODEL_OUTPUT_PARSE_ERROR` and `MODEL_OUTPUT_SCHEMA_ERROR`.

TASK-101 validation is actually reused, not duplicated: the service calls `validate_llm_output`. This preserves route-only `training_business`, non-training `INTENTS_EMPTY_NON_TRAINING`, training `CLARIFICATION_FORCED_OFF`, required nullable `risk`, and `SLOT_SPAN_INVALID` behavior. `InMemoryRuntimeConfigLoader` and `InMemoryTraceSink` are appropriate TASK-102-only adapters.

Two non-blocking integration boundaries remain for TASK-201/103: `IntentService` imports the concrete Qwen `ProviderError` ([intent_service.py:13](backend/app/services/intent_service.py#L13)), despite declaring an `LLMProvider` protocol; and the loader's model snapshot is not checked against the independently constructed provider snapshot. TASK-201 must use one immutable effective Model Config snapshot to construct/cache the matching provider and loader result. TASK-103 must move the provider error base type to the provider-neutral boundary before another provider is added, and persist full release/model trace fields.

## 3. C11/C12 acceptance

| Invariant | Result | Evidence |
|---|---|---|
| C11: SDK has `max_retries=0` | PASS | Constructor line 66; local 500→200 server test observed exactly two HTTP calls, not the SDK default retries. |
| C11: bounded provider retry, 1 + `max_retries` | PASS for normal/network/timeout failures | Local server scenarios below: 5xx×3 with `max_retries=2`; 400 and zero-retry both made exactly one request. |
| C11: every physical request has one Attempt | **FAIL on caller cancellation** | A local server received one request, then the client task was cancelled. `except asyncio.CancelledError: raise` at [qwen.py:134](backend/app/providers/qwen.py#L134) creates no Attempt; the raised cancellation exposes none. |
| C12: structured bodies omit `max_tokens` | PASS locally | Actual serialized local-server request had no `max_tokens`; model validation rejects a non-null `params.max_tokens`; defensive `pop` is also present. |
| C12: `json_schema` strict construction | PASS locally / external compatibility unverified | Actual body: `response_format.type=json_schema`, `strict=true`; no silent fall-back. |
| C12: unsupported `minItems` absent | PASS locally | Actual submitted schema contained no `minItems`. Full-schema acceptance by Qwen remains unverified. |
| C12: `json_object` explicit and prompt has JSON instruction | PASS | It emits only `{"type":"json_object"}` and the reused PromptBuilder system message includes `JSON`. |

## 4. Independent local HTTP request/Attempt verification

I used a separate ephemeral localhost `ThreadingHTTPServer` through the real locked `AsyncOpenAI` network stack. This was not an SDK `create` mock and was deleted after execution. Counts below are observed by that server; for connection failure it closes a request it has already received.

| Scenario | Config / terminal result | HTTP received | Attempt rows observable to caller | Result |
|---|---|---:|---:|---|
| Success | 200 | 1 | 1 | success |
| 429 then 200 | `max_retries=1` | 2 | 2 | success; failed then succeeded |
| 5xx to upper bound | 500×3, `max_retries=2` | 3 | 3 | `MODEL_PROVIDER_ERROR` |
| Timeout | delayed 200×2, timeout 0.05, retry 1 | 2 | 2 | `MODEL_TIMEOUT` |
| 400 | `max_retries=2` | 1 | 1 | `MODEL_PROVIDER_ERROR`, no retry |
| Retry zero | 500, `max_retries=0` | 1 | 1 | `MODEL_PROVIDER_ERROR` |
| Connection interrupted after receipt | drop connection×2 | 2 | 2 | `MODEL_PROVIDER_ERROR` |
| Cancel while request in flight | 200 delayed 0.4 | 1 | **not exposed** | `CancelledError`; no later retry |
| Same provider after cancellation | next 200 | 1 | 1 | success; semaphore permit was released |
| Cancel during backoff | 500 then cancellation | 1 | **not exposed** | `CancelledError`; second request was not sent |
| Concurrency queue limit | one in flight, second wait 0.05 | 1 | 0 for rejected call | `SERVICE_BUSY`; correct because it never sent HTTP |

The Attempt order in the successful retry case was 1 (failed, `is_retry=false`) then 2 (succeeded, `is_retry=true`). The actual request bodies also showed no `max_tokens`.

The server cannot observe a TCP connect failure that never reaches it; this review therefore used a post-receipt connection drop for a real HTTP-stack count, and records zero server requests only for queue rejection. It does not invent a server-side count for a pre-connect failure.

## 5. Structured Output and Qwen compatibility

Current Alibaba Model Studio documentation lists `qwen3.7-plus` / Qwen3.7-Plus series among JSON Schema models, and requires the implemented shape `response_format={"type":"json_schema","json_schema":{"...","strict":true}}`; JSON Object requires `JSON` in a message and does not guarantee the schema. It also documents workspace/region-specific OpenAI-compatible endpoints, including Beijing `https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1`, Singapore `https://{WorkspaceId}.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1`, Tokyo `https://{WorkspaceId}.ap-northeast-1.maas.aliyuncs.com/compatible-mode/v1`, and others. The endpoint is rightly Model Config data, not hard-coded. Sources: [Structured output](https://docs.modelstudio.console.alibabacloud.com/en/model-studio/qwen-structured-output), [OpenAI-compatible Chat](https://www.alibabacloud.com/help/en/model-studio/qwen-api-via-openai-chat-completions).

`DASHSCOPE_API_KEY` is absent. No secret was sought, printed, substituted, or sent. Therefore **REAL_QWEN_SMOKE=UNVERIFIED**. The Pydantic-generated submitted schema contains, besides supported primitive/object/array/enum types, `$defs`/`$ref`, `anyOf`, `minLength`, numeric bounds, defaults and titles. Documentation saying the *series* supports JSON Schema does not prove this exact schema works for this account, region, endpoint and thinking-mode policy. A real minimal smoke must submit the real PromptBuilder output, this full schema, then parse and dynamically validate it before this compatibility claim can become PASS.

## 6. Regression and test gate

Executed from `backend/` with the committed lock file:

```text
uv run --locked --extra dev ruff check .
All checks passed!

uv run --locked --extra dev ruff format --check .
43 files already formatted

uv run --locked --extra dev pytest -q -rs
65 passed, 2 skipped, 1 warning
SKIPPED [2] tests\test_mysql_integration.py:57:
MYSQL_TEST_DATABASE_URL is not configured; MySQL 8 integration tests are skipped
```

Collection was 67 tests: TASK-101 contract/prompt suites passed and 17 Provider/IntentService tests passed. The warning is FastAPI/Starlette's deprecation notice for its TestClient/httpx combination, not a test failure. `MYSQL_TEST_DATABASE_URL` is absent; no MySQL test was attempted against a shared or production database. Those two pre-existing MySQL skips are unrelated to Provider request-count verification.

Existing TASK-102 tests do use a local HTTP server for success/retry/timeout/body checks, so they are not merely SDK method-call assertions. They do **not** test a caller cancellation or a real local connection drop; the cancellation gap above was found by this independent run.

## 7. Findings

### P1-1 — Cancellation loses the physical-request Attempt and all service trace diagnostics (blocks TASK-102/TASK-201)

- Location: [qwen.py:101](backend/app/providers/qwen.py#L101)-[qwen.py:135](backend/app/providers/qwen.py#L135); propagation/trace gap at [intent_service.py:117](backend/app/services/intent_service.py#L117)-[intent_service.py:152](backend/app/services/intent_service.py#L152).
- Counterexample: local server records POST #1; cancel the awaiting task after receipt. Provider immediately re-raises `CancelledError`, with no failed/cancelled `LLMAttempt`; IntentService catches neither cancellation nor a diagnostic carrier, so no TraceRecord is written.
- Impact: C11's required one-real-HTTP/one-Attempt trace becomes false exactly when operators need to explain an aborted model charge/call. TASK-103 cannot faithfully persist attempts or diagnose cancellation, even though the semaphore itself releases correctly.
- Minimal fix: create and retain a per-attempt record before/at send; on `CancelledError`, complete it with `status="cancelled"`, elapsed time and sanitized available metadata, and propagate cancellation with the attempts attached through a provider-neutral diagnostic/cancellation type. Ensure IntentService preserves the diagnostics to TraceSink without converting cancellation into `unknown`; add local-server tests for in-flight and backoff cancellation, Attempt fields, no subsequent HTTP, trace behavior, and permit release.
- Blocker: **yes**. Do not close TASK-102 or start TASK-201 on this implementation.

### P1-2 — Sanitizer permits common prose-form secrets into `raw_request` (blocks TASK-102/TASK-201)

- Location: [qwen.py:184](backend/app/providers/qwen.py#L184)-[qwen.py:204](backend/app/providers/qwen.py#L204), persisted in the attempt construction at [qwen.py:115](backend/app/providers/qwen.py#L115) and [qwen.py:236](backend/app/providers/qwen.py#L236).
- Counterexample executed against the actual sanitizer: `{"user_input":"my password is Tr0ub4dor", "note":"token is abc123"}` remains unchanged. Only key names or `:`/`=` inline formats are redacted.
- Impact: a user message incorporated into the Final Prompt can carry an API key/token/password expressed naturally; it is retained in `raw_request` and ready for TASK-103 persistence, contrary to the project secret filtering constraint. This is not a finding that the configured DashScope API key is currently emitted—headers are excluded—but it is a proven raw-trace secret leak class.
- Minimal fix: centralize and test context-aware raw trace redaction before all sink persistence, covering JSON keys and text forms such as `password is …`, `token is …`, `Bearer …`, and known key prefixes; preserve only a `[REDACTED]` marker. Apply the same policy to error strings and nested list/message content.
- Blocker: **yes**. Trace security contract is a production gate.

### P2-1 — Provider-neutral interface is coupled to Qwen's concrete error class (does not independently block TASK-201)

- Location: [intent_service.py:13](backend/app/services/intent_service.py#L13), [intent_service.py:133](backend/app/services/intent_service.py#L133), while `LLMProvider` is declared as a protocol at [types.py:45](backend/app/providers/types.py#L45).
- Counterexample: a future compliant provider cannot return its own typed provider failure and obtain the same trace/persistence path unless it imports/raises `qwen.ProviderError`.
- Impact: weakens the stated replaceable Provider boundary.
- Minimal fix: move a provider-neutral typed error (including Attempts) to `app.providers.types` or the shared error layer; Qwen subclasses/uses it and IntentService catches that base type.
- Blocker: no for Qwen-only TASK-201; fix before adding another provider.

## 8. TASK-201/103 handoff and release decision

| Question | Decision |
|---|---|
| Can TASK-102 code be closed? | **No. FAIL** until P1-1 and P1-2 are fixed and independently retested. |
| Is real Qwen compatibility verified? | **No — REAL_QWEN_SMOKE=UNVERIFIED.** No API key was available. |
| May TASK-201 start? | **No.** Review-gate rule and P1 blockers require repair/re-review first. After code repair, a no-key review can at most be **CONDITIONAL PASS**, contingent on an authorised real smoke before the configured release is activated. |
| TASK-103 prerequisites after repair | Re-run all request-count/cancellation tests; real Qwen full-schema/prompt/parse/business-validation smoke; verify centralized truncation/redaction and that request + attempts persist atomically/with stated fail-open/closed policy; verify release id/hash/fingerprint and the identical frozen effective model snapshot appear in Trace. |

The post-TASK-201 Provider/IntentService ↔ Release/ModelConfig interface review remains mandatory. It must prove the loader reads only the active immutable release, uses its `default_model_config_id`, verifies the frozen `model_config_hash`, and cannot pair a loader snapshot for one model with a provider configured for another.

External material consulted for this review: the local project documents named above, the locked OpenAI SDK path exercised through real local HTTP, and the two Alibaba official documents linked in section 5. No third-party implementation was adopted; no external production service was called.
