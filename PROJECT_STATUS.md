# PROJECT STATUS — v1.2.5

状态：`⬜ 未开始` / `🚧 进行中` / `✅ 完成` / `⛔ 阻塞`

| Task | 状态 | 备注 |
|---|---|---|
| TASK-102 execution gate | CONDITIONAL PASS | 最终独立结论见 TASK-102_FINAL_INDEPENDENT_REVIEW.md；允许 TASK-201；P2-2 在 TASK-103 DB Trace 接入前必须关闭 |
| TASK-001 工程骨架与API边界 | ✅ | 已完成；包管理已迁移到 uv |
| TASK-002 MySQL、Migration与Bootstrap | ✅ | MySQL 8.0.32；独立 Review 通过；`release_fingerprint` 已去 UNIQUE；`/ready` 做全表全列检查（当前 head：9 表 / 126 列，仅参考值） |
| TASK-101 Intent Contract与PromptBuilder | ✅ | PASS；TASK-201 继续复用 Snapshot 校验及纯 PromptBuilder |
| TASK-102 Qwen Provider与IntentService | CONDITIONAL PASS | P1 已关闭；P2-2 validation_issues.slot.value 无界，P2-1 Provider Error 耦合仍保留；REAL_QWEN_SMOKE=UNVERIFIED |
| TASK-201 在线配置与Release | P1 修复完成，待独立复审 | 原实现 ead771e / 报告 18256ec 的独立审核 FAIL；三个 P1 定向修复 fceafde；160 项后端、25 项 MySQL、7 项前端、1 项真实 E2E 通过；见 TASK-201_P1_FIX_REPORT.md。原 FAIL 待独立复审改签 |
| TASK-103 Trace与Runtime API | ⬜ 禁止开始 | TASK-201 须经 5.6 Sol 独立复核 PASS，再完成 TASK-102/201 接口联查；DB Trace 前关闭 P2-2 |
| TASK-202 研发后台：调试/观测/Replay/Diff/状态 | ⬜ | |
| TASK-301 批量评测闭环 | ⬜ | |
| TASK-401 生产部署与主系统接入 | ⬜ | |
| TASK-501 自动化测试与E2E验收 | ⬜ | |

## 待确认事项

TASK-201 P1 修复已停止在交付边界，未实现 TASK-103 TTL DB Loader/Runtime API/DB TraceStore。TASK-102/201 的真实 MySQL 发布 A→B、HTTP 参数与 Trace provenance 定向自验通过，但仍需独立复审与接口联查验收。部署前必须停写并审计全量 Model/Release Hash，包括已处于 `0003_model_timeout_double` 的库；损坏历史 fail-closed，不自动改写 Hash。见 `docs/TASK-201-0003-审计与恢复Runbook.md`。测试环境发布不代表真实 Qwen 或生产启用验收。

| 事项 | 默认 | 确认时点 |
|---|---|---|
| `疲劳咨询` 归属（sports_knowledge vs safety） | sports_knowledge | TASK-301 开始前 |
| `docs/08 §12` 部署决策表 | 表内默认 | TASK-401 开始前 |
