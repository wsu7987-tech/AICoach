# TASK-002 MySQL、Migration 与 Bootstrap

## 依赖

TASK-001

## 阅读

- `docs/07-数据库与配置版本设计.md`
- `bootstrap/initial-config.v1.json`

## 目标

建立 v1.2 精简后的生产数据模型、Alembic migration 和首次 Draft bootstrap。

## 实现

至少创建：

- `config_draft`
- `model_config`
- `config_release`
- `runtime_state`
- `intent_request_trace`
- `llm_call_trace`
- `evaluation_dataset`
- `evaluation_run`
- `evaluation_case_result`

要求：

- **字段以 `docs/07` 为准**，必须包含 `config_snapshot_hash` / `release_fingerprint` / `model_config_hash` / `credential_ref` / 各 `*_truncated` 标记 / `dataset_hash` / `worker_concurrency` 等延续字段；禁止 Codex 自行改名。
- Trace 与 Evaluation 相关索引按 docs/07 §8 一并创建。

- SQLAlchemy 2.x async 优先。
- MySQL 8 JSON/TEXT 类型按字段实际用途选择。
- `trace_id` unique；`request_id` index 但不强制 unique。
- `llm_call_trace UNIQUE(trace_id, attempt_no)`。
- `evaluation_case_result UNIQUE(run_id, case_id, repeat_index)`。
- bootstrap import command/API：仅把 `bootstrap/initial-config.v1.json` 写入 Draft，不自动发布 Release；导入严格校验顶层字段只能是 `schema_version/routes/intents/slots/enums/examples/prompt_template`，禁止静默忽略未知字段。
- bootstrap 幂等：重复执行不会生成重复业务配置。
- DB session/transaction 生命周期明确。

## 测试

- clean DB upgrade
- downgrade/upgrade 基础验证
- bootstrap import + repeat import + 顶层 extra-field 反例
- constraint tests

## DoD

空库可通过 migration 建好全部一期表；bootstrap 后已有可编辑 Draft。`/ready` 只反映服务面/DB schema 就绪，不等待首个 Release；Runtime 配置未发布时 `runtime_config_ready=false`。
