# 06 API 与数据结构设计

## 1. Runtime API

### POST /api/v1/intent/analyze

Request：

```json
{
  "request_id": "optional-upstream-id",
  "text": "我要做深蹲",
  "conversation_id": null,
  "context": {}
}
```

Response：

```json
{
  "request_id": "req_xxx",
  "text": "我要做深蹲",
  "route": "training_business",
  "intents": [{"name": "start_training", "zh": "想开始训练", "confidence": 0.98}],
  "slots": [{"name": "exercise", "zh": "动作", "value": "深蹲", "start": 3, "end": 5, "confidence": 0.99}],
  "risk": null,
  "need_clarification": false,
  "clarification": null
}
```

Runtime 不返回 `reason_summary/evidence/final_prompt/raw_*` 等调试字段。

## 2. request_id 与 trace_id

- `request_id`：业务关联 ID，可由上游传入；不存在时由服务生成。
- `trace_id`：每一次实际执行唯一，由服务内部生成；Replay/上游重试可共享 request_id 但 trace_id 不同。

数据库唯一 Attempt 键使用 `(trace_id, attempt_no)`，避免上游重复 request_id 导致冲突。

## 3. Runtime Errors

```json
{
  "request_id": "req_xxx",
  "status": "failed",
  "error_code": "MODEL_TIMEOUT",
  "message": "model request timeout"
}
```

HTTP 与 error_code 映射（Contract，不再“按网关约定”）：

| error_code | HTTP | 说明 |
|---|---|---|
| INVALID_INPUT | 422 | 字段缺失/类型错误、text 超 `MAX_TEXT_CHARS`、context 超 `MAX_CONTEXT_BYTES` |
| PAYLOAD_TOO_LARGE | 413 | 请求体超 `MAX_REQUEST_BODY_BYTES` / 评估文件超 `MAX_EVAL_FILE_BYTES` |
| CONFIG_NOT_READY | 503 | 无 Active Release / 默认 Model Config 不完整 |
| MODEL_TIMEOUT | 504 | Provider 超时（重试耗尽后） |
| MODEL_RATE_LIMIT | 503 + `Retry-After` | **上游 Provider** 限流（重试耗尽后） |
| SERVICE_BUSY | 503 + `Retry-After` | 本服务 Provider 并发队列等待超过 `PROVIDER_QUEUE_WAIT_TIMEOUT` |
| MODEL_PROVIDER_ERROR | 502 | Provider 5xx/网络错误 |
| MODEL_OUTPUT_PARSE_ERROR / MODEL_OUTPUT_SCHEMA_ERROR | 502 | 模型输出无法解析/不符合 Schema |
| INTERNAL_ERROR | 500 | 其他内部错误 |

一期不实现本服务自身的限流器，故一期不返回 429；若后期新增，429 仅用于本服务主动限流。

## 4. Admin API

### Config

- `GET /api/admin/config/draft`
- `PUT /api/admin/config/draft`
- `POST /api/admin/config/validate`
- `POST /api/admin/config/prompt-preview`
- `POST /api/admin/releases`（body 必填 `default_model_config_id` 与 `note`；该 Model Config 必须 enabled；服务端基于当前 Draft 生成 Snapshot）
- `GET /api/admin/releases`
- `GET /api/admin/releases/{id}`
- `POST /api/admin/releases/{id}/create-draft`
- Model Config CRUD/version create endpoints

### Debug/Trace

- `POST /api/admin/debug/analyze`
- `GET /api/admin/traces`
- `GET /api/admin/traces/{trace_id}`
- `POST /api/admin/traces/{trace_id}/replay`
- `POST /api/admin/traces/diff`

### Evaluation

- dataset import/list
- run create/list/detail/cancel
- case result list
- export

### Status

- `GET /api/admin/status/summary`

至少返回/展示：

- `service_ready`：与 `/ready` 同义，只检查服务面（进程、DB/基础依赖、Migration schema），不要求 Active Release；
- `runtime_config_ready`：Active Release + default Model Config 完整且可加载；
- `active_release_id/version/hash`、default model、最近 24h 摘要。

无 Runtime 配置时 Admin 仍必须可访问；仅 Runtime analyze 返回 `CONFIG_NOT_READY`。

## 5. Core Pydantic Types

- IntentAnalyzeRequest
- IntentCandidate
- SlotValue
- RiskInfo
- IntentResult
- LLMStructuredIntentOutput
- LLMRequest / LLMResponse / LLMAttempt
- RuntimeConfigSnapshot
- ModelConfigSnapshot
- TraceRecord
- EvaluationRun/Result

一级 Route 是 Runtime API Contract：使用固定 7 个 key 的 `Literal`/Enum 常量（见 docs/03 §3），不从配置读取；二级 Intent、Slot、Enum 不写死，使用当前 Config Snapshot 做业务校验，并校验“二级 Intent 所属 route 与返回的 route 一致”。

## 6. 输入/队列保护

必须支持环境变量或配置项：

- `MAX_TEXT_CHARS`
- `MAX_CONTEXT_BYTES`
- `MAX_REQUEST_BODY_BYTES`
- `MAX_EVAL_FILE_BYTES`
- `MAX_EVAL_CASES`（默认 500，与 Excel 模板 500 行一致）
- `PROVIDER_QUEUE_WAIT_TIMEOUT`

Provider semaphore 满时不得无限等待，超过 queue wait timeout 返回 `SERVICE_BUSY`（503 + Retry-After）。
