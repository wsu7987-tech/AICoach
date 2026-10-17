# Codex 执行任务说明 — v1.2.5

## 固定执行顺序

```text
TASK-001 工程骨架与API边界
  -> TASK-002 MySQL、Migration与Bootstrap
  -> TASK-101 Intent Contract与PromptBuilder
  -> TASK-102 Qwen Provider与IntentService
  -> TASK-201 在线配置与Release
  -> TASK-103 Trace与Runtime API
  -> TASK-202 研发后台：调试/观测/Replay/Diff/状态
  -> TASK-301 批量评测闭环
  -> TASK-401 生产部署与主系统接入
  -> TASK-501 自动化测试与E2E验收
```

这个顺序是强约束，不允许把 Runtime API 提前到 Active Release/RuntimeConfigLoader 之前完成。

## 任务合并原则

v1.2.5 沿用 v1.2 的 10 个 Task（由 v1.1 的 22 个收敛而来）。每个 Task 都应形成一个可测试的完整垂直切片，避免为了“任务小”而反复创建临时接口再返工。

## 每个 Task 完成时必须输出

1. 实际修改/新增文件。
2. 运行的测试命令与结果。
3. DoD 逐项结论。
4. 未完成项/已知风险。
5. 下一 Task 的前置条件是否满足。
6. 更新 `PROJECT_STATUS.md`。

## 禁止跳步

- 未完成 TASK-201，不得把 Runtime API 宣称为生产可用。
- 未完成 TASK-103，不得开始后台 Trace 页面。
- 未完成 TASK-301，不得用临时脚本代替最终 Evaluation 闭环。
- 未完成 TASK-401，不得把本地运行视为“可上线”。

## Review 关口（v1.2.5）

| 时点 | 要求 |
|---|---|
| TASK-001 / TASK-202 | 独立 Review 可选 |
| TASK-002、101、102、201、103、301、401、501 完成后 | **必须**独立 Review（由未参与实现的 AI/人执行，核对证据而非转述） |
| TASK-102 + TASK-201 完成后、TASK-103 开始前 | 额外一次**接口联查**：Provider/IntentService 与 ConfigRelease/ModelConfig 的接口、hash、Snapshot 校验是否对得上 |
| Review 不通过 | **留在当前 Task** 修复并复审，不得开始下一 Task |
| 转述的 Review 结论 | 先核实再采纳；许可证/活跃度不作为结论依据 |

## 当前进度（v1.2.5）

以 `PROJECT_STATUS.md` 为当前进度来源。TASK-301 已按用户确认的 V2 方案实现，待迁移与授权测试；原任务内容只作参考。

## 开工前置确认（不阻塞 TASK-001~301）

| 时点 | 需要确认 | 默认 |
|---|---|---|
| TASK-102 开始前 | 确认 `intents` 基数规则（`docs/03 §3`，默认宽松 `0..n`）；选定 Qwen 模型并核对 `json_schema` strict 可用性 | 按 docs/03 §3 默认执行 |
| TASK-301 开始前 | 产品确认 `docs/03 §11` 二级 Intent 归属表（尤其 `疲劳咨询`） | 先按 Bootstrap 草案执行 |
| TASK-401 开始前 | `docs/08 §12` 部署决策表（Admin 入口、网关放行、副本数等） | 按表内默认方案 |

## v1.2.4/v1.2.5 额外执行约束

- 参考项目优先级以 `docs/09` 为准；官方 SDK/Qwen 文档高于第三方示例。
- 不得复制 `sohaggain` 的双层 retry / 同步 client。
- `/ready` 不等待 Active Release；Runtime 配置状态单独看 `runtime_config_ready`。
- 当前批量评测提供 Run 对比及显式标注动作的 Route 混淆统计、Per-route P/R/F1；最终通过率按问题—标准答案验收，详见 `docs/12`。
- Contract 以 `docs/10` 为验收依据；门禁命令与报告格式见 `AGENTS.md §14`。
