# TASK-002 执行复核报告

执行日期：2026-10-12（Asia/Tokyo）  
执行基线：v1.2.4；分支：`main`；开始时 HEAD：`2fdc0e05a41ff655315993d22c7ae8304f459f95`。  
实现 checkpoint commit SHA：`77a30f993b7ef7a14952ee0bc067be63a55edc65`。后续真实 MySQL 验收发现 `config_draft` 单例 ID 的 AUTO_INCREMENT/CHECK 定义不兼容 MySQL 8.0.32，已同步修复 Alembic Migration、ORM 与回归测试。

> **2026-10-12 独立复核 P0 修复增补：** 独立复核（`TASK-002_INDEPENDENT_REVIEW.md`）否决了此前的完成结论，发现 R-001（`release_fingerprint` 错误唯一）和 R-002（head 但缺失业务表时 `/ready` 误报 200）。当前已新增 `0002_release_fingerprint_nonunique`、取消 ORM 唯一约束并加入 fingerprint 普通索引；readiness 也已要求 9 张业务表全部存在。此前本报告中关于 TASK-002 “已完成”的结论不再有效；待当前 P0 修复在隔离 MySQL 8 中完成复验和独立复核前，`PROJECT_STATUS.md` 保持 🚧，不得进入 TASK-101。

> **本轮实际验证：** Ruff 通过；`pytest` 为 12 PASS、2 SKIP（两项均为受 `MYSQL_TEST_DATABASE_URL` 保护的真实 MySQL 测试）；新版 Migration 的 MySQL offline upgrade/downgrade SQL 均成功生成，确认会删除 `uq_config_release_release_fingerprint` 并创建普通索引。独立复核曾使用的 `127.0.0.1:33307` 临时实例当前不可连接。本轮尝试在工作区外启动新的临时 MySQL 8.0.32 实例也因该 Windows 安装的本地 TCP/权限表启动异常而失败；仅停止了该临时进程，未以 mock/SQLite 替代验收。因此 R-001/R-002 的真实 MySQL 复验仍为 BLOCKED，不能标记 TASK-002 完成。

## 结论

原始实现和真实 MySQL 8 集成测试曾通过；但独立复核已发现两个 P0，TASK-002 当前验收状态为 **修复中 / 未完成**。`PROJECT_STATUS.md` 已恢复为 TASK-002 进行中，TASK-101 前置条件未满足。

验收数据库：Windows 本地 MySQL Community Server 8.0.32，隔离测试库 `ai_coach_task002_test_local`。未使用生产数据库、SQLite 或 mock 替代真实 MySQL 验收。

## 文件清单

- 新增：`backend/alembic.ini`、`backend/alembic/*`、`backend/app/db/*`、`backend/app/bootstrap/*`、`backend/tests/test_bootstrap_unit.py`、`backend/tests/test_mysql_integration.py`。
- 修改：`backend/pyproject.toml`、`backend/.env.example`、`backend/app/main.py`、`backend/app/core/settings.py`、`backend/app/core/readiness.py`、`backend/tests/test_app.py`、`Makefile`、`PROJECT_STATUS.md`。

TASK-001 接口衔接修正：`Settings.database_url` 不再包含可运行的示例用户名/密码/主机默认值；未设置 `DATABASE_URL` 时 `/ready` 为 503（database failed），而不是把配置状态视为 readiness。该改动未改变 Runtime/API Contract。

## Schema / 迁移核对

Migration revision：`0001_initial_schema`。所有业务表显式采用 MySQL `utf8mb4` / `utf8mb4_unicode_ci`，JSON 使用 MySQL JSON，时间字段为 `DATETIME(6)`。

| 表 | 字段核对 | 约束 / 索引核对 |
|---|---|---|
| `config_draft` | `id,schema_version,draft_json,updated_by,updated_at` | singleton `CHECK(id=1)` |
| `model_config` | `name,version,provider,model,base_url,params_json,timeout_seconds,max_retries,max_concurrency,structured_output_mode,credential_ref,model_config_hash,enabled,immutable_from_at,created_at` | `UNIQUE(name,version)`；`model_config_hash` 普通索引，避免将展示/生命周期字段错误纳入或把相同不可变调用配置误设为唯一 |
| `config_release` | `version,snapshot_json,config_snapshot_hash,default_model_config_id,model_config_hash,release_fingerprint,note,created_by,created_at` | model FK `RESTRICT`；version / fingerprint 唯一；snapshot/model 索引 |
| `runtime_state` | `id,active_release_id,updated_at` | singleton `CHECK(id=1)`；release FK `SET NULL`；不在 bootstrap 时写入 |
| `intent_request_trace` | `trace_id,request_id,parent_trace_id,source,input,context_json,release/config/model snapshot 与 hash、final result、reason/evidence、validation/timeline、latency/token/retry/status/error,created_at` | `UNIQUE(trace_id)`；request、parent、created、status、route、release、effective model 及组合查询索引；`parent_trace_id` 无 FK，不阻止清理 |
| `llm_call_trace` | `trace_id,attempt_no,provider,model,model_params_json,final_prompt,prompt_hash,raw_request_json,raw_response_json,final_prompt_truncated,raw_request_truncated,raw_response_truncated,provider metadata,parsed result,token/latency/status/error,created_at` | `UNIQUE(trace_id,attempt_no)`；trace FK `ON DELETE CASCADE` |
| `evaluation_dataset` | `name,version,source_filename,hash,normalized_cases_json,created_at` | `UNIQUE(name,version)`；hash 索引 |
| `evaluation_run` | `dataset_id,dataset_hash,release/config/model snapshots and hashes,repeat_count,worker_concurrency,status,progress_json,claimed_by,heartbeat_at,error,created/started/finished_at` | dataset `RESTRICT`；release/model `SET NULL`；status/created 与 status/claimed/heartbeat worker-claim 索引 |
| `evaluation_case_result` | `run_id,case_id,repeat_index,expected_json,actual_json,passed,error_type,error_message,request_id,trace_id,latency_ms` | `UNIQUE(run_id,case_id,repeat_index)`；run FK `CASCADE`；`trace_id` 仅普通索引、无 FK，Trace 过期不会丢失评测结果 |

静态 migration 编译已运行：`DATABASE_URL=<offline placeholder> python -m alembic -c alembic.ini upgrade head --sql`，输出 10 个 `CREATE TABLE`（其中 1 个是 Alembic 自身 `alembic_version`，其余为上述 9 张业务表）。这不是 MySQL 实库验收。

## Bootstrap 核对

入口：`make backend-bootstrap`，等价于：

```powershell
cd backend
python -m app.bootstrap.cli --file ../bootstrap/initial-config.v1.json
```

导入仅在单一显式事务中写入 `config_draft(id=1)`；不会创建 `config_release` 或 `runtime_state`。顶层 Pydantic schema 使用 `extra="forbid"`，只接受 `schema_version/routes/intents/slots/enums/examples/prompt_template`，并验证固定 7 个 route 恰好出现且全为 enabled。重复且完全相同的文档返回 no-op；现有 Draft 不同则以冲突退出，不覆盖开发者编辑。

- 单元验证：初始 JSON 与 canonical payload 语义相同，中文、aliases、slots、enums、examples、prompt template 均保留；未知顶层字段和禁用 Route 均拒绝。
- 真实 MySQL 首次/重复/冲突/回滚验证：**PASS**。相应测试仅对名称以 `ai_coach_task002_test_` 开头的隔离库执行 downgrade/upgrade，不会操作开发库。

## Readiness 核对

`/ready` 现在只注册数据库 + Alembic head 检查：连接后执行 `SELECT 1` 与 `alembic_version` head 对比；没有 Active Release 或 Model Config 的检查。数据库不可达、`DATABASE_URL` 缺失、或 schema 未升级均返回 503；DB/schema 正常时应返回 200，即使不存在 `runtime_state` 行、Active Release 或 Model Config。

- `/ready` 在未设 URL 和真实连接拒绝两种情形均返回 503 / `{"database":"failed"}`。
- 人工注入已就绪 DB/schema 检查但未创建任何 Release/Model：PASS，`/ready` 返回 200。
- 真实 MySQL schema 正常且无 Active Release：**PASS**（由隔离 MySQL 集成测试覆盖）。

## 实际命令与结果

| 命令 | 结果 |
|---|---|
| `python -m pip install -e ".[dev]"`（`backend`） | SQLAlchemy/Alembic/asyncmy 依赖已安装 |
| `python -m ruff check .`（`backend`） | PASS |
| `python -m pytest`（`backend`） | 11 PASS，0 FAIL，1 SKIP（当前工具进程未注入 MySQL 环境变量） |
| `python -m pytest tests/test_mysql_integration.py -q`（隔离 MySQL 8） | 1 PASS，0 FAIL |
| `python -m alembic -c alembic.ini upgrade head --sql`（临时离线 URL） | PASS；生成 MySQL DDL，9 个业务表 + Alembic 表 |
| `python -m app.bootstrap.cli --file ../bootstrap/initial-config.v1.json`（未设 DB URL） | 预期失败，清晰返回数据库配置错误；未写库 |
| `mysql -uroot -e "SELECT VERSION()"` | FAIL：10061，MySQL 服务未监听 |
| `Start-Service -Name MySQL80` | FAIL：无权限/无法打开本机服务 |

## DoD 逐项

| DoD | 状态 | 证据 |
|---|---|---|
| Async SQLAlchemy、9 表、Alembic schema 实现 | PASS | ORM、revision、真实 MySQL DDL |
| 空 MySQL upgrade / downgrade / upgrade | PASS | 隔离 MySQL 8 集成测试 |
| 字段、索引、唯一键、Trace cleanup | PASS | migration 与 MySQL integration test |
| Bootstrap 首次、重复、未知字段、事务回滚、编辑冲突 | PASS | unit tests 与 integration test |
| `/ready` 不依赖 Release/Model | PASS | `test_app.py` 与真实 MySQL integration test |
| TASK-001 测试回归 / Ruff | PASS | pytest 11 PASS / Ruff PASS |
| `PROJECT_STATUS.md` 完成标记 | PASS | 已标记 TASK-002 完成 |

## 未完成项、风险、下一任务前置

未完成项：无。真实集成测试仅对受名称保护的隔离库执行 `alembic downgrade base` / `upgrade head`，并验证 Bootstrap、唯一键、级联删除、评测结果保留及真实 `/ready`。

已知边界：未实施 TASK-101+ 的 Release、Provider、Runtime、Trace 写入或 Evaluation Worker 业务，符合本 Task 范围。TASK-101 前置条件：**已满足**。
