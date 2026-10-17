# V2 批量评测开发记录

日期：2026-10-16。用户确认原 TASK-301 只作参考，以当前 V2 项目和问题—标准答案流程实施。

状态：代码实现完成，待迁移、授权测试与最终验收。本报告不是测试通过报告。

## 实际交付

- `assets/AI_Coach_批量评测模板.xlsx`：只必填问题、标准答案；可选动作、参数、标签、关键用例与上下文。
- `backend/app/schemas/evaluation.py`：用例、精确期望、任务、评审和人工复核输入。
- `backend/app/services/evaluation/`：Excel 导入导出、不可变数据集/任务、冻结模型、模型评审、规则匹配、统计、独立 Worker。
- `backend/app/api/admin/evaluation.py` 和 Admin Router：模板、评测集、任务、取消、结果筛选、复核、导出和任务对比。
- `backend/app/db/models.py`、`0006_evaluation_v2.py`：新增快照、自动结论、复核历史等字段；清除不符合 V2 语义的旧评测记录。
- `backend/app/core/settings.py`、`.env.example`：Worker 并发、领取间隔和租约配置。
- `backend/pyproject.toml`、`uv.lock`：加入 openpyxl。
- `backend/scripts/generate_evaluation_template.py`：无需数据库/模型生成模板。
- `frontend/src/EvaluationWorkbench.vue`、ExpectedEditor、ResultView、evaluationApi、evaluation.css、App.vue：完整后台入口与操作页面。
- `backend/tests/test_evaluation.py`、`test_evaluation_mysql.py`：定向验证代码，未执行。
- `docs/05`、`docs/06`、`docs/07`、`docs/12`、任务说明、README、PROJECT_STATUS：对齐当前语义和执行状态。

## 已完成的开发检查

- `uv lock`、`uv sync --locked --extra dev`：完成依赖锁定和安装。
- `uv run --locked python scripts/generate_evaluation_template.py`：已生成模板文件，没有数据库或模型调用。
- 新增及修改的后端文件 Ruff 静态检查与格式整理。
- 前端新增页面 Prettier 格式整理、`vue-tsc --noEmit` 类型检查。
- Git diff 空白检查。

没有执行 pytest、Vitest、Playwright、浏览器交互验收、数据库迁移或真实模型调用。

## 功能完成情况

| 项目 | 开发状态 | 执行验收 |
|---|---|---|
| 问题—标准答案模板、导入、页面编辑、新版本 | 已实现 | 待授权 |
| V2 单/复合动作、参数、依赖、风险、追问精确规则 | 已实现 | 待授权 |
| 可选模型评审、REVIEW、人工复核留痕 | 已实现 | 待授权 |
| 数据库队列、独立 Worker、心跳恢复、防旧写者提交 | 已实现 | 待隔离 MySQL 验证 |
| 通过率、关键用例阈值、重复稳定性、显式标注指标 | 已实现 | 待授权 |
| badcase 筛选、对照、筛选导出、复测与同集对比 | 已实现 | 待端到端验证 |

## 下一步

1. 获得用户测试授权后，先执行定向纯逻辑用例，再使用显式指定的隔离 MySQL 库验证迁移和 300 条 Mock run。
2. 完成前后端端到端验收并修正暴露的问题。
3. 实际库迁移前确认清除旧评测集/任务/结果的范围，再执行迁移并启动独立 Worker。
4. 真实识别/评审模型需要单独授权调用，以人工标注样本校准评审质量。

当前不能宣称 TASK-301 验收 PASS，也不能据此宣称具备生产部署条件。
