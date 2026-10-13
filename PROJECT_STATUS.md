# PROJECT STATUS — v1.2.5

状态：`⬜ 未开始` / `🚧 进行中` / `✅ 完成` / `⛔ 阻塞`

| Task | 状态 | 备注 |
|---|---|---|
| TASK-102 execution gate | 待独立增量复核 — second fix | ed2e8ae 的 FAIL 历史见 TASK-102_INCREMENTAL_REVIEW_ed2e8ae.md；本轮修复及 32/32 探针证据见 TASK-102_SECOND_FIX_REPORT.md；TASK-201/TASK-103 未开始 |
| TASK-001 工程骨架与API边界 | ✅ | 已完成；包管理已迁移到 uv |
| TASK-002 MySQL、Migration与Bootstrap | ✅ | MySQL 8.0.32；独立 Review 通过；`release_fingerprint` 已去 UNIQUE；`/ready` 做全表全列检查（当前 head：9 表 / 126 列，仅参考值） |
| TASK-101 Intent Contract与PromptBuilder | ✅ | v1.2.5 对齐清单已通过；等待独立增量复核后才可进入 TASK-102。 |
| TASK-102 Qwen Provider与IntentService | 🚧 | 第二轮修复完成，待独立增量复核；P1 取消收尾/全出口脱敏及 P2 长度自测通过，仓库 94 passed / 2 skipped；未独立批准关闭 |
| TASK-201 在线配置与Release | ⬜ | |
| TASK-103 Trace与Runtime API | ⬜ | |
| TASK-202 研发后台：调试/观测/Replay/Diff/状态 | ⬜ | |
| TASK-301 批量评测闭环 | ⬜ | |
| TASK-401 生产部署与主系统接入 | ⬜ | |
| TASK-501 自动化测试与E2E验收 | ⬜ | |

## 待确认事项

| 事项 | 默认 | 确认时点 |
|---|---|---|
| `疲劳咨询` 归属（sports_knowledge vs safety） | sports_knowledge | TASK-301 开始前 |
| `docs/08 §12` 部署决策表 | 表内默认 | TASK-401 开始前 |
