# Codex 执行任务说明 — v1.2.4

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

v1.2.4 沿用 v1.2 的 10 个 Task（由 v1.1 的 22 个收敛而来）。每个 Task 都应形成一个可测试的完整垂直切片，避免为了“任务小”而反复创建临时接口再返工。

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

## 开工前置确认（不阻塞 TASK-001~301）

| 时点 | 需要确认 | 默认 |
|---|---|---|
| TASK-301 开始前 | 产品确认 `docs/03 §11` 二级 Intent 归属表（尤其 `疲劳咨询`） | 先按 Bootstrap 草案执行 |
| TASK-401 开始前 | `docs/08 §12` 部署决策表（Admin 入口、网关放行、副本数等） | 按表内默认方案 |

## v1.2.4 额外执行约束

- 参考项目优先级以 `docs/09` 为准；官方 SDK/Qwen 文档高于第三方示例。
- 不得复制 `sohaggain` 的双层 retry / 同步 client。
- `/ready` 不等待 Active Release；Runtime 配置状态单独看 `runtime_config_ready`。
- TASK-301 必须产出 Run 对比、一级 Route 混淆矩阵、Per-route P/R/F1。
