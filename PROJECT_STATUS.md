# PROJECT STATUS — v1.2.5

状态：`⬜ 未开始` / `🚧 进行中` / `✅ 完成` / `⛔ 阻塞`

| Task | 状态 | 备注 |
|---|---|---|
| TASK-102 execution gate | CONDITIONAL PASS | 最终独立结论见 TASK-102_FINAL_INDEPENDENT_REVIEW.md；允许 TASK-201；P2-2 在 TASK-103 DB Trace 接入前必须关闭 |
| TASK-001 工程骨架与API边界 | ✅ | 已完成；包管理已迁移到 uv |
| TASK-002 MySQL、Migration与Bootstrap | ✅ | MySQL 8.0.32；独立 Review 通过；`release_fingerprint` 已去 UNIQUE；`/ready` 做全表全列检查（当前 head：9 表 / 126 列，仅参考值） |
| TASK-101 Intent Contract与PromptBuilder | ✅ | PASS；TASK-201 继续复用 Snapshot 校验及纯 PromptBuilder |
| TASK-102 Qwen Provider与IntentService | CONDITIONAL PASS | P1 已关闭；P2-2 validation_issues.slot.value 无界，P2-1 Provider Error 耦合仍保留；REAL_QWEN_SMOKE=UNVERIFIED |
| TASK-201 在线配置与Release | 待独立复核 | 实现 ead771e；真实 Admin API + Vue 配置中心；134 项后端、10 项 MySQL、6 项前端、1 项真实浏览器流程通过；详见 TASK-201_EXECUTION_REPORT.md |
| TASK-103 Trace与Runtime API | ⬜ 禁止开始 | TASK-201 须经 5.6 Sol 独立复核 PASS，再完成 TASK-102/201 接口联查；DB Trace 前关闭 P2-2 |
| TASK-202 研发后台：调试/观测/Replay/Diff/状态 | ⬜ | |
| TASK-301 批量评测闭环 | ⬜ | |
| TASK-401 生产部署与主系统接入 | ⬜ | |
| TASK-501 自动化测试与E2E验收 | ⬜ | |

## 待确认事项

TASK-201 已停止在交付边界，未实现 TASK-103 Runtime loader/API/TraceStore。部署配置模块前需执行 Alembic 到 `0003_model_timeout_double`（避免 FLOAT 舍入破坏模型参数 Hash）。测试环境发布不代表真实 Qwen 或生产启用验收。

| 事项 | 默认 | 确认时点 |
|---|---|---|
| `疲劳咨询` 归属（sports_knowledge vs safety） | sports_knowledge | TASK-301 开始前 |
| `docs/08 §12` 部署决策表 | 表内默认 | TASK-401 开始前 |
