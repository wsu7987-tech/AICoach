# TASK-101 Intent Contract 与 PromptBuilder

## 依赖

TASK-002

## 阅读

- `docs/03-Intent路由与动态Prompt设计.md`
- `docs/06-API与数据结构设计.md`
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
- clarification 为 `str | None`；false -> null，true -> 非空字符串；training route 强制 false/null

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
- span 错误：LLM 给错下标但 value 唯一 → 重算；value 不存在或多处歧义 → 丢弃并记录 `SLOT_SPAN_INVALID`

## DoD

后续 Provider、Config、Runtime 都能只依赖这些 Contract；Prompt 可独立预览。
