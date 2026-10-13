# TASK-103 执行报告

日期：2026-10-13
基线：`053d8851d4a0993876ded4395edc435ea065d3c6`

## 结果

已实现 Runtime 的 Active Release DB Loader、事务化 TraceStore、Trace retention cleanup command 与 `POST /api/v1/intent/analyze`。TASK-102 遗留 P2-2 已在 Trace 持久化边界关闭：`validation_issues` 按 UTF-8 字节限制截断，保留 `SLOT_SPAN_INVALID`，以 `truncated=true` 标识，且不修改业务校验的原 Slot 或发送给 Provider 的请求。

P1 增量修复后，开发方已在隔离 MySQL 8.0.32 与 localhost Provider 完成 Runtime DB fail-open、非 Runtime fail-closed、Active Release A→B provenance、pool/SQL/commit cancellation 与连接释放的真实验收。状态为“待独立增量复核”，不自行宣布 TASK-103 PASS，也未开始 TASK-202。

实现提交为 `3e05b497724ee0e8fe15964e21d6ac3cb3468458`；精确文件列表见 `TASK-103_P1_FIX_REPORT.md`。既有独立审核材料未混入该实现提交。

## 修改文件

- `backend/app/services/runtime_config.py`：Active Release ID 校验、TTL cache、Release/Model hash 与 enabled fail-closed 验证。
- `backend/app/services/trace_store.py`：AsyncSession 单事务请求/Attempt 落库、持久化边界脱敏/截断、保留期清理。
- `backend/app/trace/cleanup.py`：`python -m app.trace.cleanup` 清理命令；Evaluation 关联 Trace 使用独立更长期限。
- `backend/app/api/runtime/router.py`、`backend/app/main.py`：正式 Runtime API、request/body/context 限制、Provider/Loader/Store 组装。
- `backend/app/services/intent_service.py`、`backend/app/core/diagnostics.py`、`backend/app/schemas/intent.py`、`backend/app/core/settings.py`、`backend/app/db/database.py`：Trace 语义、诊断限长、执行模式的 fail-open/fail-closed、取消 rollback、设置项。
- `backend/tests/test_task103_contract.py`：C13/C14、公开响应、限长/脱敏与 provenance 回归。
- `backend/tests/test_task103_mysql.py`：真实隔离 MySQL 8 + localhost HTTP 的 Trace/Attempt 集成验收，以及 Runtime HTTP API 全链路验收（环境未配置时明确 skip）。
- `PROJECT_STATUS.md`。

## 验证结果

在 `backend/` 实际执行：

```text
uv run --locked --extra dev ruff check .
All checks passed!

uv run --locked --extra dev ruff format --check .
63 files already formatted

uv run --locked --extra dev pytest -q -rs tests/test_task103_contract.py tests/test_task103_mysql.py
.............ss                                                          [100%]
SKIPPED [2] MYSQL_CONFIG_TEST_DATABASE_URL not configured; TASK-201 MySQL acceptance BLOCKED
```

增量复测取得真实隔离 MySQL 环境变量后，`tests/test_task103_mysql.py` 为 13 passed；连同既有 MySQL 回归的四文件组合为 26 passed。完整 `uv run --locked --extra dev pytest -q -rs` 通过仓库外受控日志进程取得 exit 0；当前 collect 为 185 项、0 skipped，只有既有 Starlette/httpx 弃用警告。

## DoD

| 项目 | 结论 |
|---|---|
| Active Release / effective Model Runtime 链路 | PASS（实现与契约测试） |
| Runtime API、稳定公开输出、C13 | PASS |
| Trace request/attempt 单事务、raw 脱敏/限长 | PASS（实现与单元契约） |
| Runtime Trace 失败 fail-open；Debug/Replay/Eval fail-closed | PASS（契约测试） |
| C10 | PASS（metadata 推导，完整/缺表/缺列/迁移不一致/无 Active Release 的真实 MySQL 回归） |
| P2-2 validation issue 无界长度 | PASS（真实 MySQL UTF-8 限长、脱敏、中文/emoji 超长 Slot） |
| 隔离 MySQL 8 + localhost HTTP 验收 | PASS（13 项 TASK-103 MySQL；26 项含历史 MySQL 回归） |
| 全量规定 pytest 命令取得最终退出码 | PASS（exit 0；185 collected；0 skipped） |
| 真实 Qwen smoke | UNVERIFIED（无授权 API Key） |

## 风险与后续

开发方 MySQL 专项与完整门禁已完成；独立增量复核仍需复跑连接池等待、SQL/commit 取消及 commit 结果未知不虚报持久化的场景。当前没有开始 TASK-202，在独立复核结论前不应进入下一 Task。

## 外部资料

按 `docs/09-参考项目与采用策略.md` 阅读并遵守已有 OpenAI Async/retry 与 Qwen structured-output 约束；本次未访问或复制外部源码/资料，原因是实现复用已验收的 Provider/Factory，只新增本项目 Runtime/Trace DB 适配层。
