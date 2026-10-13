# TASK-101 Intent Contract 与 PromptBuilder

## 依赖

TASK-002

## 阅读

- `docs/03-Intent路由与动态Prompt设计.md`
- `docs/06-API与数据结构设计.md`
- `docs/10-契约不变量与验收样例.md`
- `sohaggain/ai-text-classification-api/src/models/schemas.py`

## 目标

先固定 Runtime/LLM/Config Contract，并实现不依赖数据库和模型的纯 PromptBuilder。

## 实现

Pydantic 类型至少：

- `IntentAnalyzeRequest`
- `IntentCandidate`
- `SlotValue`
- `RiskInfo`
- `IntentResult`
- `EvidenceItem`
- `LLMStructuredIntentOutput`
- `RuntimeConfigSnapshot`
- `ModelConfigSnapshot`
- `PromptBuildResult`

规则：

- confidence 0..1
- slot `start >= 0`, `end >= start`；span 服务端校验/重算/丢弃规则按 `docs/03 §1`（校验失败丢弃 slot + Trace 记录 `SLOT_SPAN_INVALID`，不使请求失败）
- 固定 7 个一级 Route key 作为 Runtime Contract 常量（Literal/Enum，不从配置读取）；Snapshot 的 routes 必须恰好是这 7 个且全部 enabled（Snapshot 校验函数 + 反例测试：缺失/新增/disable 均拒绝）
- 二级 Intent/Slot/Enum 等对 Snapshot 校验；二级 Intent 所属 route 必须等于返回的 route
- Runtime `risk` 字段必须存在，可 null
- Runtime Contract 不得包含 reason/evidence/raw/prompt/model params
- clarification 为 `str | None`；false -> null，true -> 非空字符串；training route 强制 false/null（规则细节见 `docs/10 §1`）
- `intents` 为 `0..n`，**不设 `min_length`**（Route-only 合法，见 `docs/03 §3`）；输出 Schema 不使用 `minItems`
- Snapshot 校验必须基于 dict 重新解析或 `revalidate_instances='always'`，不能被已构造实例绕过（`docs/10 §3`）

PromptBuilder：

- 输入 Snapshot + text + context
- 输出 messages/final_prompt + prompt_hash + metadata
- 动态注入 routes/intents/slots/enums/examples
- 注入由 `LLMStructuredIntentOutput` 生成的输出 Schema
- 同一输入/Snapshot 生成稳定 canonical prompt/hash
- 提供 preview 能力，不调用模型

## 测试

- Contract 正/反例
- Runtime schema 无 debug 字段
- Prompt deterministic
- disabled config 不注入
- Snapshot 改变会改变 hash
- 中文/emoji/特殊字符 slot span 使用 UTF-16 code-unit `[start,end)` contract
- span 错误（各自独立测试）：LLM 给错下标但 value 唯一 → 重算；value 不存在 → 丢弃并记录 `SLOT_SPAN_INVALID`；多处歧义 → 丢弃并记录 `SLOT_SPAN_INVALID`
- Route-only：training `intents=[]` 通过；非训练 `intents=[]` 通过且记录 `INTENTS_EMPTY_NON_TRAINING`
- Snapshot 构造后被改动（删/新增/disable route 等）仍被校验拒绝
- 门禁：`ruff check`、`ruff format --check`、`pytest -q -rs` 全绿并贴输出

## DoD

后续 Provider、Config、Runtime 都能只依赖这些 Contract；Prompt 可独立预览。

> v1.2.5：本 Task 已完成；进入 TASK-102 前先过 `TASK-101-ADDENDUM-v1.2.5.md`。
