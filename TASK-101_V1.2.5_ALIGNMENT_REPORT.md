# TASK-101 v1.2.5 最终契约对齐报告

基线：`65ed64f41857b107b8e6c121c5f602e63cb37e27`。本次仅对齐 TASK-101 的
Intent Contract、PromptBuilder 契约测试和项目状态；未改数据库、Provider、Runtime
API 或其他任务代码。

## 结论

TASK-101 的 v1.2.5 Addendum 十项已完成，待独立增量复核。TASK-102 的代码前置条件
已满足，但按任务要求不得在复核前启动 TASK-102。

## 已发现并处理的旧语义冲突

`65ed64f` 的独立审核把以下旧测试语义判为通过：

1. 非训练 Route 的空 `intents` 在模型输出 Schema 阶段被拒绝；
2. 训练 Route 的原始 `need_clarification=true` 在模型输出 Schema 阶段被拒绝。

这与 v1.2.5 的 `docs/03 §3`、`docs/10 §1` 和 Addendum 明确冲突。按新 Contract：
所有 Route 均可 Route-only；非训练 Route 保留一级 Route 并记录
`INTENTS_EMPTY_NON_TRAINING`，而训练澄清先归一化为 `false/null` 并记录
`CLARIFICATION_FORCED_OFF`。本次只替换这两项已废弃的断言，没有放宽固定 Route、
Snapshot、intent-route 归属、enabled、confidence、risk、extra 或 slot 校验。

## C1–C7 对齐及测试证据

| ID | 对齐结论 | 代码/测试证据 |
|---|---|---|
| C1 | 通过：固定七个 Route；缺失、增加、disable 均拒绝。 | `RuntimeConfigSnapshot.valid_business_config`；`test_snapshot_rejects_any_fixed_route_contract_change`。 |
| C2 | 通过：`IntentResult` 与 `LLMStructuredIntentOutput` 的 `intents` 为 `0..n`，没有 `min_length`/`minItems`；七个 Route 均可 Route-only。非训练空列表产生诊断而非 Schema 错误。 | `test_all_routes_support_route_only_output`、`test_training_business_supports_route_only_output_and_runtime_mapping`、`test_prompt_is_deterministic_and_contains_dynamic_config_and_schema`。 |
| C3 | 通过：非训练 clarification 双向规则仍严格；训练原始澄清先被接收并归一化为 `false/null`，记录 `CLARIFICATION_FORCED_OFF`。 | `LLMStructuredIntentOutput.valid_llm_invariants`、`validate_llm_output`；`test_training_business_supports_route_only_output_and_runtime_mapping`、`test_clarification_and_training_business_invariants`。 |
| C4 | 通过：`risk` 必须出现，`null` 合法。 | `IntentResult.risk`、`LLMStructuredIntentOutput.risk`；`test_risk_is_required_but_null_is_valid_and_runtime_fields_are_exact`。 |
| C5 | 通过：Runtime 模型 `extra=forbid`，字段集合恰为 `request_id/text/route/intents/slots/risk/need_clarification/clarification`。 | `ContractModel`；`test_runtime_contract_rejects_debug_fields_and_invalid_input`、`test_risk_is_required_but_null_is_valid_and_runtime_fields_are_exact`。 |
| C6 | 通过：UTF-16 `[start,end)` 的唯一重算、值不存在丢弃、重复歧义丢弃、emoji offset 均独立覆盖；丢弃为非致命 `SLOT_SPAN_INVALID`。 | `_validate_or_repair_span`；`test_utf16_span_is_repaired_when_unique`、`test_unlocatable_slot_is_dropped_without_failing_intent_result`、`test_utf16_span_is_dropped_when_value_is_ambiguous`、`test_utf16_span_is_repaired_when_unique_with_emoji`。 |
| C7 | 通过：Snapshot 在边界以 `model_dump(mode="json")` 重建验证；构造后缺 Route、disable、增加第八项和 intent 指向非法 Route 均无法绕过；PromptBuilder 同样重校验。 | `validate_runtime_config_snapshot`、`PromptBuilder.build`；`test_snapshot_validation_reconstructs_instances_before_returning_them`、`test_snapshot_validation_rejects_mutated_missing_route_and_invalid_dict`、`test_snapshot_validation_rejects_other_post_construction_mutations`、`test_prompt_builder_revalidates_snapshot_instances_before_use`。 |

## Addendum 十项核对

1. 完成：空 intents 无 schema 下限；非训练空列表保留 route 并附诊断。
2. 完成：训练澄清在 business validation 后归一化；非训练非法组合仍拒绝。
3. 完成：缺少 `risk` 拒绝，`risk=null` 接受。
4. 完成：Runtime response 为严格、无 debug 字段的精确字段集合。
5. 完成：四类 slot span 用例已独立覆盖。
6. 完成：所有指定的构造后 Snapshot 变异都经重解析拒绝。
7. 完成：PromptBuilder 重校验 Snapshot；已有测试证明 disabled 配置不注入、相同输入确定性、有效配置改变改变 hash。
8. 完成：LLM JSON Schema 由 `LLMStructuredIntentOutput` 生成；完整 Schema 文本断言不含 `minItems`。
9. 完成：下列三条锁定环境门禁均通过。
10. 完成：本报告记录参考资料与未参考项。

## 实际门禁输出

在 `backend/` 执行：

```text
$ uv run --locked --extra dev ruff check .
All checks passed!

$ uv run --locked --extra dev ruff format --check .
37 files already formatted

$ uv run --locked --extra dev pytest -q -rs
...........................................ss.....                       [100%]
============================== warnings summary ===============================
.venv\Lib\site-packages\fastapi\testclient.py:1
  D:\akae\AICoach\backend\.venv\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ===========================
SKIPPED [2] tests\test_mysql_integration.py:57: MYSQL_TEST_DATABASE_URL is not configured; MySQL 8 integration tests are skipped
```

三条命令均以 exit code 0 结束。两个 skip 是既有 MySQL 集成测试缺少隔离的
`MYSQL_TEST_DATABASE_URL`；本 Task 未改 DB，且该环境前置不影响纯 Contract/PromptBuilder
验收。

## 修改文件

- `backend/app/schemas/intent.py`
- `backend/tests/test_intent_contract.py`
- `backend/tests/test_prompt_builder.py`
- `PROJECT_STATUS.md`
- `TASK-101_V1.2.5_ALIGNMENT_REPORT.md`

## 参考资料

已阅读并作为规范：`AGENTS.md`、`docs/03`、`docs/06`、
`docs/10-契约不变量与验收样例.md`、`TASK-101-ADDENDUM-v1.2.5.md`、
`TASK-101_INDEPENDENT_REVIEW.md`、当前 Intent Contract、PromptBuilder、测试及
`docs/09-参考项目与采用策略.md`。未使用外部实现或外部资料：本次是本地纯 Contract
对齐，不涉及 TASK-102 的 OpenAI/Qwen Provider 行为；因此没有采用第三方源码。

## 未完成项与风险

- 未完成项：无代码范围内未完成项；等待独立增量复核是流程门禁，不是实现阻塞。
- 风险：`INTENTS_EMPTY_NON_TRAINING` 与 `CLARIFICATION_FORCED_OFF` 目前作为
  `ValidatedIntentOutput.validation_issues` 交付给后续 TASK-103 Trace 持久化；TASK-103
  必须将它们写入 `validation_json`，且 Runtime response 不得暴露这些诊断。
- TASK-102 前置：**满足（待独立增量复核批准）**。
