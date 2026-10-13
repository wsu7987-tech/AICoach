# TASK-101 v1.2.5 最终增量复核

## 结论

**PASS**。`b927380d2b308c7ef050c89855fa01582cb0666f` 对 TASK-101 的增量实现与当前
v1.2.5 契约一致；没有发现新增或未解决的 P0/P1/P2。本复核只覆盖 TASK-101
v1.2.5 对齐差异，未启动 TASK-102，也没有修改业务代码。

## Git 审核基线与工作区隔离

- 审核 HEAD：`b927380d2b308c7ef050c89855fa01582cb0666f`
  (`fix: align TASK-101 v1.2.5 contracts`)；父提交：
  `65ed64f41857b107b8e6c121c5f602e63cb37e27`。
- `HEAD` 正是指定的对齐提交；`git diff b927380^ b927380` 的实现差异仅为
  `backend/app/schemas/intent.py` 和相应的 TASK-101 测试，另有对齐报告。
- 当前 index 已有用户暂存的 v1.2.5 文档、`UV_MIGRATION_REVIEW.md` 等 21 个文件；
  本次未修改、未暂存、未将其混入审核结论。新增的本报告为未暂存审核产物。
- 以当前暂存的 `docs/03`、`docs/06`、`docs/10` 和 TASK-101 Addendum 为契约，逐项
  对照 `b927380` 的代码。其 Route-only、训练归一化、risk、Runtime 字段和 Schema
  语义与实现逐项一致，因此代码与 v1.2.5 契约属于同一逻辑基线。

## C1–C7

| 契约 | 结论 | 复核证据 |
|---|---|---|
| C1 固定七 Route | PASS | `RouteKey`/`FIXED_ROUTE_KEYS` 固定为七项；`RuntimeConfigSnapshot.valid_business_config` 拒绝缺失、额外和 disabled Route。 |
| C2 `intents` 为 0..n | PASS | 两个输出模型均未设置 `min_length`；七 Route 皆可 `intents=[]`。非 training 输出保留一级 route，产生 `INTENTS_EMPTY_NON_TRAINING`，不作为 Pydantic Schema 错误。 |
| C3 clarification | PASS | 原始 training `need_clarification=true` 可通过 `LLMStructuredIntentOutput`，随后由 `validate_llm_output` 归一化为 `false/null` 并记录 `CLARIFICATION_FORCED_OFF`；非 training 的双向非法组合仍在 Schema 阶段拒绝。 |
| C4 risk | PASS | `IntentResult.risk` 与 `LLMStructuredIntentOutput.risk` 无默认值，缺失被拒绝；显式 `null` 合法。 |
| C5 Runtime Contract | PASS | 所有契约模型使用 `extra=forbid`；`IntentResult` 只含 `request_id/text/route/intents/slots/risk/need_clarification/clarification`，不会携带 reason/evidence/prompt/raw 等调试字段，显式 null 不会在 `model_dump()` 中消失。 |
| C6 Slot span | PASS | 保留 UTF-16 `[start,end)` 验证；唯一命中重算、不存在和歧义丢弃、emoji 偏移均有独立测试，丢弃使用含原 Slot 的 `SLOT_SPAN_INVALID`，不令请求失败。 |
| C7 Snapshot 防绕过 | PASS | `validate_runtime_config_snapshot` 对已构造对象执行 `model_dump(mode="json")` 后重解析；`validate_llm_output` 与 `PromptBuilder.build` 均从该边界进入。删 Route、disable、加第八项、非法 intent route 的构造后变异均被测试拒绝。 |

## 核心专项复核

- Structured Output：`PromptBuilder` 直接以 `LLMStructuredIntentOutput.model_json_schema()`
  生成 Schema；完整 JSON Schema 文本不含 `minItems`，但 Python 端仍保留 confidence、
  risk、clarification、Route 和动态二级业务校验。
- 原有逻辑：本次未改变 Snapshot 重解析、纯 Python PromptBuilder、canonical JSON/hash、
  UTF-16 span、固定 Route 或动态 Intent/Slot/Enum 的实现；全量现有测试无回归。
- 非训练空 intents 的状态是显式的 `ValidatedIntentOutput.validation_issues` 诊断，
  而非伪造二级 Intent 或将它转为 `MODEL_OUTPUT_SCHEMA_ERROR`。Runtime 的公开结果仍仅是
  稳定 Contract；后续 Trace/Evaluation/消费方必须使用该诊断避免执行未识别的二级业务动作。

## TASK-102 接口交接

**兼容，前置满足。**

- Provider 可直接消费 `PromptBuildResult.messages` 的 `role/content` 消息列表，并使用
  `LLMStructuredIntentOutput.model_json_schema()` 作为 json_schema 响应格式。
- Provider 解析 JSON 后可调用 `LLMStructuredIntentOutput.model_validate()`；IntentService
  再调用 `validate_llm_output()`，完成动态 Intent/Slot/Enum、risk、clarification 及 span
  的业务校验和归一化。
- `ValidatedIntentOutput` 同时给出公开 `IntentResult` 和不泄露至 Runtime 的
  `validation_issues`，可供 TASK-102 的 TraceSink/后续 TASK-103 持久化
  `INTENTS_EMPTY_NON_TRAINING`、`CLARIFICATION_FORCED_OFF` 与 Slot 诊断。
- TASK-102 不得把非 training 空 intents 自动视为已经识别二级业务或执行下游动作；该状态
  必须保留为诊断并在 Evaluation 中判为二级 Intent 不匹配。

## 实际测试结果

在 `backend/` 执行：

```text
$ uv run --locked --extra dev ruff check .
All checks passed!

$ uv run --locked --extra dev ruff format --check .
37 files already formatted

$ uv run --locked --extra dev pytest -q -rs
...........................................ss.....                       [100%]
=========================== short test summary info ===========================
SKIPPED [2] tests\test_mysql_integration.py:57: MYSQL_TEST_DATABASE_URL is not configured; MySQL 8 integration tests are skipped
```

三条命令均以 exit code 0 完成。两个 skip 是既有 MySQL 集成测试没有隔离的
`MYSQL_TEST_DATABASE_URL`；本次没有数据库变更，故不构成阻断。

另执行独立反例脚本，结果为：

```text
independent counterexamples: passed
```

该脚本独立验证七个 Route 的空 intents 语义、training 澄清归一化、缺失 risk 被拒绝、
生成 Schema 无 `minItems`，以及 Runtime 完整字段集合。

## 问题、风险与资料

- P0：无。
- P1：无。
- P2：无。
- 遗留风险：诊断字段尚未有真实 Trace 持久化（TASK-103 范围）；TASK-102/103 必须保持其
  与 Runtime 响应的隔离并写入 `validation_json`。这不是 TASK-101 增量的契约缺陷。
- 复核依据：`AGENTS.md`、`docs/03`、`docs/06`、`docs/10`、TASK-101 Addendum、
  对齐报告、TASK-101 源码/测试、`PROJECT_STATUS.md` 以及 TASK-102 任务说明。
  未采用外部资料：本轮仅审阅本地 Contract/纯函数实现，不涉及 Provider SDK 或 Qwen
  能力选择。

## 最终判定

TASK-101 v1.2.5：**符合，PASS**。TASK-102 可在其自身任务与门禁范围内开始。
