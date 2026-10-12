# TASK-101 最终修复报告

执行日期：2026-10-12
状态：P0-1、P1-2、P1-3、P1-4 均已修复；等待独立增量复核。未开始 TASK-102。

## 修复内容

- P0-1：`IntentResult` 与 `LLMStructuredIntentOutput` 的 `intents` 改为必填但允许空列表；跨字段规则仅允许 `training_business` 使用 `[]`。训练业务仍强制 `need_clarification=false`、`clarification=null`；非训练 Route 空列表仍拒绝。
- P1-2：`validate_runtime_config_snapshot()` 对模型实例使用 `model_dump(mode="json")` 后重建校验；`PromptBuilder` 和 `validate_llm_output()` 使用其返回的新实例，避免“验证副本却使用旧实例”。
- P1-3：补充 Slot value 不存在于原文时的非致命丢弃测试，断言 `SLOT_SPAN_INVALID` 与成功的 Intent Result。
- P1-4：执行 Ruff formatter，且 formatter check 通过。

## 验证

在 `backend` 工作目录执行：

```powershell
uv run --locked --extra dev ruff check .
uv run --locked --extra dev ruff format --check .
uv run --locked --extra dev pytest -q -rs
```

结果：lint 通过；`37 files already formatted`；pytest `38 passed, 2 skipped`。两个跳过项为 MySQL 集成测试，原因是未配置 `MYSQL_TEST_DATABASE_URL`；环境中没有可安全使用的独立 MySQL 8 测试库，因此未执行完整 MySQL 集成回归。

## 修改文件

- `backend/app/schemas/intent.py`
- `backend/app/prompting/builder.py`
- `backend/tests/test_intent_contract.py`
- `backend/tests/test_prompt_builder.py`
- `TASK-101_EXECUTION_REPORT.md`
- `PROJECT_STATUS.md`
- 本报告

## 剩余风险与边界

- 未修改数据库 Schema/Migration、uv.lock 或依赖版本；未实现 Provider、IntentService、Release、Runtime API。
- TASK-103 必须持久化已有 validation issue；TASK-102 仍须等待本任务的独立增量复核 PASS。
