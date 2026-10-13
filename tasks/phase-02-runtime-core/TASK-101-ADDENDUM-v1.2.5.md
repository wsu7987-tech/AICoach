# TASK-101 对齐清单（v1.2.5）

> 性质：TASK-101 已被标记完成。本清单是进入 TASK-102 **之前**的一次性对齐：把已有代码/测试逐条对照 `docs/10`，全部满足则只需在 `TASK-101_EXECUTION_REPORT` 补一段证据；不满足的项在 TASK-101 范围内修复，修完再进 TASK-102。**不新增功能，不碰 Provider/DB。**

## 依赖与阅读

- `docs/10-契约不变量与验收样例.md`（全文）
- `docs/03 §1 §3`（slot、`intents` 基数规则）

## 逐项核对（每项给出“代码位置 + 对应测试名 + 通过输出”）

1. [ ] `IntentResult` 与 `LLMStructuredIntentOutput` 的 `intents` **无** `min_length`；测试 C2：training Route-only（`intents=[]`）通过；非训练 `intents=[]` 通过并产生 `INTENTS_EMPTY_NON_TRAINING`。
2. [ ] clarification 规则按 `docs/10 §1`（training 归一化 + 非训练双向拒绝），测试 C3。
3. [ ] `risk` 字段缺失被拒、null 通过，测试 C4。
4. [ ] Runtime 响应模型 `extra=forbid`；测试 C5 断言字段集合恰好等于 `request_id/text/route/intents/slots/risk/need_clarification/clarification`。
5. [ ] Slot span 四条独立测试（重算 / value 不存在丢弃 / 歧义丢弃 / emoji），测试 C6，且“value 不存在”用例确实存在。
6. [ ] Snapshot 校验按 `docs/10 §3`：构造后改动（删 route / disable route / 第 8 个 route / intent 指向不存在 route）被拒绝，测试 C7。
7. [ ] PromptBuilder 入口同样走重校验，不接受未校验的 Snapshot；Snapshot 改变 → hash 改变；disabled 项不注入；同输入同输出。
8. [ ] 输出 Schema 由 `LLMStructuredIntentOutput` 生成，**不含 `minItems`** 等 Qwen strict 可能不支持的关键字（检查生成的 JSON Schema 文本）。
9. [ ] `docs/10 §7` 三条门禁命令全部通过，贴实际输出。
10. [ ] 报告含“参考了哪些 / 没参考哪些及原因”。

## 若发现不一致

- 优先以 `docs/10` 为准修复。
- 修复会破坏既有测试语义或需要改 Contract 的，**停下来记入报告，等待决策**，不要自行选边。

## DoD

上述 10 项全部勾选并附证据；`PROJECT_STATUS.md` 的 TASK-101 备注写明“v1.2.5 对齐清单已通过”。
