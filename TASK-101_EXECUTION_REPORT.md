# TASK-101 执行报告：Intent Contract 与动态 PromptBuilder

执行日期：2026-10-12
任务状态：实现完成，等待独立 AI 复核；**未开始 TASK-102**。

## 实现内容

- 新增纯 Pydantic Intent Contract：请求、Runtime Result、Intent、Slot、Risk、澄清、Evidence、LLM Structured Output、Runtime/Model Snapshot 与 Prompt Build Result。
- 一级 Route 使用固定七个 `Literal` key；`RuntimeConfigSnapshot` 拒绝缺失、新增、重复或 disabled Route，并校验动态 Intent、Slot、Enum 与 Example 的关联。
- 新增纯 Python `PromptBuilder`，仅接收 Snapshot、text、context；稳定地构造 system/user messages、最终 Prompt、SHA-256 hash 与 preview 结果。业务配置、Schema、Rules 和用户输入均以 canonical JSON 序列化。
- Prompt 只注入启用的二级 Intent/Slot/Enum/Example；修改启用配置会改变 Prompt/hash，不在 Router 分支中写死二级业务配置。
- 新增 Structured Output 业务校验：Intent 必须启用且属于输出 Route；enum slot 必须匹配当前配置；Slot 使用 UTF-16 `[start,end)`。错误 span 在 value/alias 唯一出现时重算，否则丢弃并产出 `SLOT_SPAN_INVALID` Trace-ready validation issue。
- Runtime `IntentResult` 严格排除 reason/evidence/raw/prompt/model 参数等调试字段；训练业务及全局 clarification 约束由 Contract 强制。

## 验证

在 `backend` 目录执行：

```powershell
uv run --locked --extra dev ruff check .
uv run --locked --extra dev pytest
```

结果：Ruff 通过；pytest `31 passed, 2 skipped`。唯一 warning 来自现有 Starlette TestClient 对已安装 httpx 的弃用提示，不影响测试结果。

覆盖的新测试包括：Contract 正反例、confidence/clarification、固定 Route 反例、Runtime 无调试字段、二级 Intent 动态归属、中文/emoji UTF-16 span 修复与丢弃、Prompt 确定性、disabled 配置排除与配置变更 hash 回归。

## DoD

| 项目 | 结论 |
|---|---|
| Pydantic Contract | 完成 |
| 固定七 Route 与动态二级配置 | 完成 |
| 无 DB/LLM 的 Prompt preview | 完成 |
| canonical prompt/hash | 完成 |
| UTF-16 Slot span 处理 | 完成 |
| Ruff/pytest locked 验证 | 完成 |
| 独立 AI 复核 | 待执行 |

## 未完成项、风险与后续依赖

- 未实现 Provider、Runtime Analyze/Trace、Release 或数据库变更；均明确留给后续任务。
- `SLOT_SPAN_INVALID` 以结构化 validation issue 返回，TASK-102/103 必须将其写入 Trace `validation_json`，但不得将其转换为 Runtime 请求失败。
- `PromptBuilder` 已提供后续 Admin preview、Provider request 与 Trace prompt hash 所需接口；TASK-102 的前置 Contract 已具备，仍须以独立复核通过作为开工门槛。
