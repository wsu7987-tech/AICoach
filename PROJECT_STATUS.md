# PROJECT STATUS — v1.2.5

状态：`⬜ 未开始` / `🚧 进行中` / `✅ 完成` / `⛔ 阻塞`

| Task | 状态 | 备注 |
|---|---|---|
| TASK-102 execution gate | CONDITIONAL PASS | 最终独立结论见 TASK-102_FINAL_INDEPENDENT_REVIEW.md；允许 TASK-201；P2-2 在 TASK-103 DB Trace 接入前必须关闭 |
| TASK-001 工程骨架与API边界 | ✅ | 已完成；包管理已迁移到 uv |
| TASK-002 MySQL、Migration与Bootstrap | ✅ | MySQL 8.0.32；`/ready` 根据 ORM 与 Alembic 当前 head 动态检查全表全列；旧 Release fingerprint 设计已由 0005 迁移取代。 |
| TASK-101 Intent Contract与PromptBuilder | ✅ | PASS；TASK-201 继续复用 Snapshot 校验及纯 PromptBuilder |
| TASK-102 Qwen Provider与IntentService | CONDITIONAL PASS | P1 已关闭；P2-2 validation_issues.slot.value 限长/脱敏已由 TASK-103 真实 MySQL Trace 复测关闭，P2-1 Provider Error 耦合仍保留；REAL_QWEN_SMOKE=UNVERIFIED |
| TASK-201 在线配置与Release | ✅ | 最终独立复核 PASS，且 TASK-102/201 interface gate PASS；见 TASK-201_FINAL_INCREMENTAL_REVIEW.md。 |
| TASK-103 Trace与Runtime API | ✅ | 最终独立增量复核 PASS；TASK-202 已获准。 |
| TASK-202 研发后台：调试/观测/Replay/Diff/状态 | 实现完成，待最终验收确认 | 专属 localhost Provider + 隔离 MySQL + FastAPI/Vite/Playwright 主流程已通过；不自行宣称正式 PASS。 |
| TASK-301 批量评测闭环 | ⬜ | |
| TASK-401 生产部署与主系统接入 | ⬜ | |
| TASK-501 自动化测试与E2E验收 | ⬜ | |
| vNext Step 1 模型管理重构 | 🚧 实现完成，待迁移与定向测试 | 已改为 Base URL + API Key + Model Name 的通用 OpenAI-compatible 接入；业务 Release 已与模型解耦，旧 ModelConfig 及兼容支路由破坏性迁移删除；迁移和测试尚未执行。 |
| 配置发布页面优化 | ✅ | 页面改为业务发布流程，隐藏 Hash、数据库 ID 和原始 JSON，版本详情只展示业务摘要。 |
| Route/Intent 配置中心优化 | ✅ | Route 支持新增/编辑；Intent 改为按 Route 分组的主从编辑器，支持典型说法与 Prompt 配置片段预览；详见 `docs/Route与Intent配置中心实施说明.md`。 |

## 待确认事项

TASK-103 开发方已使用隔离 MySQL 8 + localhost HTTP Provider 取得完整门禁退出码 0，下一步仅为独立增量复核；真实 Qwen Smoke 仍为 UNVERIFIED。部署前必须停写并审计全量 Model/Release Hash，包括已处于 `0003_model_timeout_double` 的库；损坏历史 fail-closed，不自动改写 Hash。见 `docs/TASK-201-0003-审计与恢复Runbook.md`。测试环境发布不代表真实 Qwen 或生产启用验收。

| 事项 | 默认 | 确认时点 |
|---|---|---|
| `疲劳咨询` 归属（sports_knowledge vs safety） | sports_knowledge | TASK-301 开始前 |
| `docs/08 §12` 部署决策表 | 表内默认 | TASK-401 开始前 |
