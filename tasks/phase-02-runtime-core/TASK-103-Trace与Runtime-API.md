# TASK-103 Trace 与 Runtime API

## 依赖

TASK-102, TASK-201

## 阅读

- `docs/06-API与数据结构设计.md`
- `docs/07-数据库与配置版本设计.md`

## 目标

把 IntentService 与真实 Active Release、Model Config、DB Trace、Runtime API 接通，形成第一条生产可调用链路。

## 实现

### RuntimeConfigLoader

- 从 `runtime_state.active_release_id` 读取 Release。
- 短 TTL cache + active id 校验。
- 找不到 Active Release / default model config 时返回 CONFIG_NOT_READY。
- Runtime 只使用 Release default model config；若 Active Release/default model config 不完整或不可用 -> fail-closed `CONFIG_NOT_READY`。

### TraceStore

- request-level `intent_request_trace`
- attempt-level `llm_call_trace`
- 所有成功/失败/timeout/retry 都落 Trace
- sanitizer 再次作为持久化边界防线
- `TRACE_RETENTION_DAYS` / `TRACE_RAW_MAX_BYTES`，raw 超限截断并标记
- stdout 不记录完整 input/final_prompt/raw_response
- Runtime：模型结果已成功但 Trace 最终持久化失败 -> fail-open，业务仍返回成功，同时记录 metric/log `TRACE_PERSIST_FAILED`
- Debug/Replay/Evaluation：Trace 失败 -> fail-closed，由对应 execution/case 标记失败

### Runtime API

`POST /api/v1/intent/analyze`

- request_id 透传/生成
- 每次 execution 生成 unique trace_id
- 返回稳定 IntentResult
- Debug 字段绝不进入 Runtime response
- 标准 error mapping：HTTP 状态码严格按 `docs/06 §3` 表（含 413、503+Retry-After、SERVICE_BUSY），逐项测试
- context 一期只参与本次 Prompt，不持久化会话

### readiness / runtime config status

- `/ready`：供 K8s readinessProbe，只检查进程 + DB/基础依赖 + Migration schema；**不要求 Active Release/default Model Config**。
- `/api/admin/status/summary.runtime_config_ready`：Active Release + default Model Config 可完整加载时为 true；否则 false。
- Runtime 未配置时 `POST /api/v1/intent/analyze` 继续返回 `CONFIG_NOT_READY`，但 Admin API 必须仍可用于修复配置。

## 测试

- Runtime success
- training/safety/social/unknown fixture cases with Mock Provider
- no active release -> Runtime 503 `CONFIG_NOT_READY`，同时 `/ready` 仍为 ready、`runtime_config_ready=false`
- retry attempts persisted；SDK retries=0 且每个真实 HTTP 调用对应一个 attempt
- provider error persisted
- duplicate upstream request_id -> different trace_id, no DB conflict
- Runtime response contract excludes debug fields
- config cache refresh after active release switch

## DoD

主系统可以通过 HTTP 调用生产链路；正常持久化情况下 execution 有可查询 Trace。Runtime Trace 持久化失败按既定 fail-open 契约返回业务成功并记录 `TRACE_PERSIST_FAILED`，不得因 DoD 反向改成 fail-closed。
