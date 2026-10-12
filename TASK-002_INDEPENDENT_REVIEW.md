# TASK-002 独立代码复核报告

## 第三次核验（当前有效；修复尚未提交）

**当前结论：BLOCKED，暂不签发 TASK-101 放行。** 代码和真实 MySQL 验收在已暂存工作树上通过；原审核规则要求先确定最终审核 commit。当前 `HEAD=b671d403ab70aa4a2531b559d4447f203c5ccd61` 仍是旧版，影响 TASK-002 的修复位于 Git index，尚未形成新 commit。下方前两次 FAIL 记录保留作历史，不能代表此工作树的测试结果。

### 当前 Git 基线及审核文件

- 分支 `main`；`git status --short` 显示已暂存的 `.gitignore`、`PROJECT_STATUS.md`、`TASK-002_EXECUTION_REPORT.md`、本报告、Migration 0002 文件替换、`backend/tests/test_migration_metadata.py`、`backend/tests/test_mysql_integration.py`。`git diff --cached --check` 无错误；无未暂存源码改动。修复内容尚未提交，所以审查范围不是最终 commit。
- 本次重审 `backend/alembic/versions/0002_release_fp_index.py:1-108`、`backend/app/db/models.py:62-77`、`backend/app/db/readiness.py:9-62`、`backend/tests/test_migration_metadata.py:1-14`、`backend/tests/test_mysql_integration.py:1-440`，并对照 v1.2.4 契约、0001 Migration、Bootstrap 源码及前两次审查。
- 已暂存的新 revision `0002_release_fp_index` 长 21 字符，可写入 Alembic 的 `version_num varchar(32)`。在线升级会识别 0001 正常唯一索引以及先前失败后留下的普通索引半完成状态；测试覆盖两种路径。原 34 字符 revision 文件已暂存删除。

### 卡点定位：执行方临时 MySQL 的启动配置

执行报告说无法连接隔离 MySQL。本次读取其遗留日志 `.tmp/mysql-task002-repair/data/LAPTOP-P2VP6OQ2.err:30-32`：实例曾显示 `port: 0`，随后报 `TCP/IP, --shared-memory, or --named-pipe should be configured on NT OS` 并退出。因此当时的两项 SKIP 是**测试环境没有可连接的隔离库及 `MYSQL_TEST_DATABASE_URL`**，不是修复代码的真实失败。已有 3306 服务拒绝无密码 root 登录，也不能拿来执行破坏性迁移测试。

本次在系统临时目录新建独立 datadir，先用 `mysqld --no-defaults --initialize-insecure` 初始化，再以前台 `mysqld --no-defaults --console --datadir=... --port=33307 --bind-address=127.0.0.1 --mysqlx=OFF` 启动 MySQL 8.0.32；仅在新建的 `ai_coach_task002_test_staged` 库测试。该实例与数据目录在审核结束后关闭、清理；未触碰现有 3306 或业务库。

### 本次 DoD 与实际命令

| 项目 / 命令 | 结果与证据 |
|---|---|
| `python -m ruff check .`、`python -m ruff format --check .`（`backend`） | **PASS**；32 files already formatted。 |
| `python -m pytest -q -rs`，未提供隔离库 URL | **13 PASS、2 SKIP**；两个 SKIP 均为受保护的真实 MySQL 集成测试，不能单独用于放行。 |
| `MYSQL_TEST_DATABASE_URL=mysql+asyncmy://root@localhost:33307/ai_coach_task002_test_staged python -m pytest -q -rs` | **15 PASS、0 FAIL、0 SKIP**，涵盖空库升级、downgrade/upgrade、0001 既有 Release 保留、半完成 0002 恢复、重复指纹不同版本发布、唯一版本约束、Bootstrap、Trace/Evaluation 关系、缺表 readiness。测试内的破坏性操作由 `backend/tests/test_mysql_integration.py:55-65` 限定到指定前缀的隔离库。 |
| `DATABASE_URL=...staged python -m alembic -c alembic.ini current` | **PASS**：`0002_release_fp_index (head)`。 |
| `DATABASE_URL=...staged python -m alembic -c alembic.ini check` | **PASS**：`No new upgrade operations detected`；ORM 与当前 Migration 对齐。 |
| 实库 `information_schema` | **PASS**：MySQL 8.0.32；9 张业务表；`config_release.release_fingerprint` 是非唯一索引；测试结束时无 Release、Model Config 或 Active State 行。 |
| 实际 API / CLI | **PASS**：`/health=200`、完整 schema 且无 Active Release 时 `/ready=200`；Bootstrap CLI 首次 `created`、再次 `already current`，实库 Draft=1、Release=0、runtime_state=0。 |

**当前没有复现新的 P0 或核心测试失败。** Readiness 的九表关键列检查仍只覆盖指定列，完整 schema 漂移检测不是本次放行证据；当前实库迁移后的列/索引另由 `alembic check` 与集成测试核对。没有提前实施 TASK-101、Provider、Release 发布业务、Runtime Analyze 或 Evaluation Worker。

### 当前审批与下一步

当前阻塞点已经从“真实 MySQL 不可用”收敛为**修复尚未提交**。按本审核初始规则，影响 TASK-002 的未提交修改不能作为最终 commit 批准。将已暂存修复提交后，若内容不再变化，可用该新 SHA 作为最终审核基线复核 Git 状态与测试证据，再作 PASS/FAIL 判定；不需要迁移包管理器或实施 TASK-101。

**TASK-002 独立复核结论：BLOCKED。是否允许开始 TASK-101：否。**

---

## 第二次核验记录（基线 `b671d40`，由上方第三次核验覆盖）

本节审核修复提交 `b671d403ab70aa4a2531b559d4447f203c5ccd61`，覆盖下方初次审核结论；下方原始审查记录保留用于追溯。**当前结论仍为 FAIL，不能进入 TASK-101。**

### 审核基线与范围

- 分支 `main`；审核 commit `b671d403ab70aa4a2531b559d4447f203c5ccd61`；有效契约 v1.2.4。`git diff --check 7ca1b48..HEAD` 无错误。
- 工作区不干净：`.gitignore` 有未提交的 `.tmp` 忽略规则；`.tmp/mysql-task002-repair/data` 是被忽略的本地 MySQL 数据目录；本审核报告为未跟踪文件。`git diff` 与目录检查确认这些未提交内容没有修改 TASK-002 源码、Migration 或测试，修复代码审查范围完整。未将 `.tmp` 当作测试通过证据。
- 实际重读：`backend/alembic/versions/0002_release_fingerprint_nonunique.py`、`backend/app/db/models.py`、`backend/app/db/readiness.py`、`backend/tests/test_bootstrap_unit.py`、`backend/tests/test_mysql_integration.py`、`TASK-002_EXECUTION_REPORT.md`、`PROJECT_STATUS.md`；沿用下方初次审核已核对的 v1.2.4 契约、0001 Migration、Bootstrap 和其他源代码。
- 真实数据库：本次在工作区外新建临时 MySQL 8.0.32 实例，独立端口 33307；仅对新建的 `ai_coach_task002_test_reaudit` 与 `ai_coach_task002_test_reaudit_clean` 隔离库执行破坏性测试。未操作现有 MySQL80 或开发/生产库。

### 修复项与 DoD 复核

| 项目 | 结论 | 源码与实际证据 | 风险 |
|---|---|---|---|
| R-001：Release 指纹可重复 | **FAIL** | ORM 已改为普通索引（`backend/app/db/models.py:74`），0002 的 DDL 意图正确（`backend/alembic/versions/0002_release_fingerprint_nonunique.py:18-29`）。但同文件 `:12` 的 revision ID 长 **34** 字符，真实 MySQL 的 `alembic_version.version_num` 是 `varchar(32)`；空库 `upgrade head` 在版本号写入时失败，无法独立验收新的 Release 语义。 | 新的 P0，见 R-003；不能把离线 SQL 或 ORM 声明视作真实迁移成功。 |
| R-002：head 但缺业务表的 readiness | **PASS（局部行为）/ UNVERIFIED（完整部署链）** | `backend/app/db/readiness.py:9-21,39-60` 现查询九表的指定关键列。因 0002 无法到 head，在隔离库的 0001 schema 上仅为隔离该逻辑而把 checker 的预期 revision 临时设为 `0001_initial_schema`，实测 `TABLES_PRESENT True`、重命名 `evaluation_case_result` 后 `TABLE_MISSING False`，随后恢复表名。 | 原始缺表误报已修复；真实 `/ready` 在当前 head 的完整验证被 R-003 阻断。当前列表只覆盖部分字段，不等于完整列/约束漂移校验。 |
| 空库 migration、downgrade/upgrade | **FAIL** | `python -m alembic -c alembic.ini upgrade head` 在全新隔离库报 MySQL 1406：`Data too long for column 'version_num'`。两项 MySQL 集成测试均失败。 | TASK-002 核心 DoD 未满足。 |
| 其余九表结构、Bootstrap、Trace/Evaluation 关系、TASK-001 回归 | **PASS（未改部分的既有实库证据）/ UNVERIFIED（当前 head 端到端）** | 0001 未修改；下方初次审核已在真实 MySQL 核对。当前修复不能完成 0002，因此无法重新运行 head 下的 Bootstrap/关系验收。 | 不把旧版本正向证据误记为当前 head 通过。 |
| 范围控制与状态记录 | **PASS** | 修复只涉及 Migration、ORM、readiness、测试与状态文档；`PROJECT_STATUS.md:8` 已恢复 TASK-002 进行中。 | 未提前实现 TASK-101 或后续业务。 |

### 本次实际测试结果

| 命令/检查 | 本次结果 |
|---|---|
| `git status --short`、`git log -5 --oneline`、`git diff --check` | 已检查；未提交项如上，未发现未提交的 TASK-002 实现代码。 |
| `cd backend; python -m ruff check .` | PASS。 |
| `cd backend; python -m ruff format --check .` | PASS，31 files already formatted。 |
| `cd backend; python -m pytest -q -rs`（无 MySQL URL） | PASS：12 passed、2 skipped；两项真实 MySQL 测试未运行，此结果不是 DB Gate PASS。 |
| `MYSQL_TEST_DATABASE_URL=mysql+asyncmy://root@localhost:33307/ai_coach_task002_test_reaudit python -m pytest -q -rs` | **FAIL：12 passed、2 failed**；两项集成测试的 Migration 都失败。 |
| 新建隔离库 `python -m alembic -c alembic.ini upgrade head` | **FAIL**：MySQL 1406，version_num 长度不足。 |
| 对失败后的隔离库查询 `alembic_version` 和 `information_schema.STATISTICS` | 版本仍为 `0001_initial_schema`，但唯一指纹索引已被替换为普通索引 `ix_config_release_release_fingerprint`。再次 `upgrade head` 报 MySQL 1091（原唯一键已不存在）。证明 MySQL 非事务性 DDL 留下半完成状态。 |
| 条件化 checker 实库试验（仅将 checker 预期 revision 暂设 0001） | 表齐全返回 true，缺 `evaluation_case_result` 返回 false；这是 R-002 逻辑隔离验证，不是当前 head 的 `/ready` PASS。 |

### 新问题：R-003 — P0 — 0002 revision ID 超长导致真实 MySQL 迁移失败且不可直接重试

- **位置**：`backend/alembic/versions/0002_release_fingerprint_nonunique.py:12,18-29`。Alembic 自身 `alembic_version.version_num` 在新建 MySQL 库中实测为 `varchar(32)`。
- **具体问题**：`0002_release_fingerprint_nonunique` 为 34 字符。0002 已执行 `DROP INDEX` 和 `CREATE INDEX` 后，更新版本号时 MySQL 1406；Alembic 仍记录 0001。再次执行升级时，因原唯一键已被删除而报 MySQL 1091。真实 MySQL 空库 upgrade 和恢复性重试都失败，测试 `backend/tests/test_mysql_integration.py:94-97,296-298` 均因此失败。
- **后续影响**：首次部署与既有 0001 库升级均无法达到 head；`/ready` 无法按新版 head 就绪，TASK-201 Release 回退仍没有可用迁移。失败后的库需要可重复的恢复途径。
- **最小修复**：将 revision ID 改为不超过 32 字符的稳定值，并让升级逻辑识别“旧唯一键仍在”与“唯一键已删除、普通索引已建”的两种状态，使此前 MySQL 非事务性 DDL 的半完成库可以重试；补充真实 MySQL 空库升级、0001→head 升级、失败后重试，以及相同指纹多 Release 插入测试。修复后重新跑 `alembic check` 和完整测试。

### 当前审批与 TASK-101

虽然 R-001 的 ORM/DDL 方向与 R-002 的缺表检查方向合理，**0002 在真实 MySQL 8.0.32 无法执行**，属于明确 P0 和核心测试失败，按审核规则只能 **FAIL**。`RuntimeConfigSnapshot`、`ModelConfigSnapshot` 与 PromptBuilder 输入所需的既有字段仍在，但 TASK-002 的数据库迁移前置条件没有满足；TASK-101 暂不放行。`runtime_config_ready` 的 Admin 输出仍属于 TASK-103，不提前实现。

**TASK-002 独立复核结论：FAIL。是否允许开始 TASK-101：否。**

---

## 初次审核记录（基线 `7ca1b48`，由上方再次核验结论覆盖）

审核日期：2026-10-12（Asia/Tokyo）。本报告只审核 TASK-002，不实施 TASK-101，也不修改业务代码。

## 1. 审核基线

| 项目 | 结果 |
|---|---|
| 分支 | `main` |
| 审核 commit | `7ca1b483ce068de6415e5401a95534f0b6a0b565` |
| Git 检查 | 审核开始时 `git status --short` 无输出；`git diff --check` 无输出；最近提交依次为 `7ca1b48`、`17502f3`、`77a30f9`、`2fdc0e0`。TASK-002 无未提交改动。写入本报告后仅本报告为新增工作区文件。 |
| 有效契约 | `AGENTS.md`、`tasks/README.md` 的 **v1.2.4**；`/ready` 不依赖 Active Release。 |
| 证据等级 | 下文“独立验证”是本次实际读源码、查询 MySQL 8.0.32 或重跑命令得到；原执行报告仅作对照，不充当 PASS 证据。 |

## 2. 实际审核文件

- 契约与任务：`AGENTS.md`、`tasks/README.md`、`tasks/phase-01-foundation/TASK-002-MySQL-Migration与Bootstrap.md`、`docs/03-Intent路由与动态Prompt设计.md`、`docs/06-API与数据结构设计.md`、`docs/07-数据库与配置版本设计.md`、`docs/09-参考项目与采用策略.md`、`bootstrap/initial-config.v1.json`、`PROJECT_STATUS.md`、`TASK-002_EXECUTION_REPORT.md`；另核对 TASK-101、TASK-103 任务边界。
- 实现：`backend/app/db/{base,database,models,readiness}.py`、`backend/app/bootstrap/{service,cli}.py`、`backend/app/core/{readiness,settings}.py`、`backend/app/main.py`、`backend/app/api/{admin,runtime}/router.py`、`backend/alembic.ini`、`backend/alembic/env.py`、`backend/alembic/script.py.mako`、`backend/alembic/versions/0001_initial_schema.py`、`backend/pyproject.toml`、`backend/.env.example`、`Makefile`。
- 测试：`backend/tests/{conftest,test_app,test_bootstrap_unit,test_mysql_integration}.py`；对比 `2fdc0e0..HEAD` 的全部 TASK-002 文件清单。

## 3. DoD 与 Gate 逐项审查

| 项目 | 结论 | 代码证据 | 独立测试证据及风险 |
|---|---|---|---|
| SQLAlchemy 2.x 异步访问、事务与连接释放 | **PASS** | `backend/app/db/database.py:18-46` 使用 async engine/session、`session.begin()`、异常 rollback、engine dispose；`backend/alembic/env.py:44-53` 异步迁移。 | 真实 MySQL 集成测试通过；未发现 async HTTP 路径直接执行同步 DB I/O。未来业务写入应沿用该事务边界。 |
| 空库建表、downgrade/upgrade、ORM 与 Migration 一致 | **PASS** | `backend/alembic/versions/0001_initial_schema.py:32-304`、`backend/app/db/models.py:29-263`。 | 隔离 MySQL 8.0.32 执行集成测试成功，`alembic check` 返回 `No new upgrade operations detected`；实库有 9 张业务表和 `alembic_version`。 |
| 必备列、类型、索引、FK 与唯一键 | **FAIL** | `backend/alembic/versions/0001_initial_schema.py:76-85` 给 `release_fingerprint` 加唯一键，ORM 同样如此：`backend/app/db/models.py:74`。 | 实库 `information_schema` 确认该唯一键；同一 Snapshot 和模型再次发布遭 MySQL 1062，破坏契约中的回退发布。详见 **R-001/P0**。其余必备列、FK 和关键唯一键均验证通过。 |
| Bootstrap 首次导入、重复导入、编辑保护、事务回滚 | **PASS** | `backend/app/bootstrap/service.py:96-122`、`backend/app/bootstrap/cli.py:18-38`、`backend/app/db/database.py:33-43`。 | 真实 CLI 首次输出 `created`、第二次 `already current`；实库计数 Draft=1、Release=0、runtime_state=0。集成测试覆盖编辑冲突与强制回滚。 |
| Bootstrap 顶层严格校验、固定七 Route、原始内容保留 | **PASS** | `backend/app/bootstrap/service.py:34-87` 使用 `extra="forbid"`、schema_version 与 Route 校验；`bootstrap/initial-config.v1.json`。 | 单测验证未知顶层字段被拒绝、route disable 被拒绝、规范化 JSON 与原 JSON 语义相同；独立数得 7 routes、40 intents、3 slots、1 enum group、10 examples，中文、aliases 和 prompt_template 保留。嵌套业务字段的全面校验属于后续 Config Validate，不是本次顶层校验要求。 |
| Trace 与 Evaluation 关系及清理 | **PASS** | `backend/app/db/models.py:103-150,240-263`；Migration 的 FK/唯一键见 `backend/alembic/versions/0001_initial_schema.py:137-142,202-208,282-292`。 | 实库确认 request_id 非唯一、trace_id 唯一、attempt 复合唯一、case repeat 复合唯一；集成测试删除 Trace 后 Attempt 消失而 Case Result 留存。parent_trace_id、Case Result trace_id 均无阻塞清理的 FK。 |
| `/ready`：DB 不可达、未迁移时 503；无 Release/Model 时 200 | **PASS** | `backend/app/main.py:52-62,133-148`、`backend/app/db/readiness.py:25-32`。 | 本次空库 `/ready=503`，完整 head `/ready=200`；单测验证 DB 无 URL/连接失败为 503；集成测试在无 Active Release/Model Config 时为 200；`/health` 独立返回 200。 |
| `/ready`：必要数据库 Schema 不完整时 503 | **FAIL** | `backend/app/db/readiness.py:27-30` 只读 `alembic_version`，不核查业务表存在。 | 在隔离库迁移到 head 后删除 `evaluation_case_result`，`/ready` 仍为 **200**。详见 **R-002/P0**。 |
| `runtime_config_ready` 与 service readiness 分开 | **UNVERIFIED（按任务边界延期）** | `/ready` 不读取 Release/Model；`backend/app/api/admin/router.py:3-10` 仍只有骨架。 | `GET /api/admin/status/summary` 与 Runtime Analyze 由 TASK-103 明确实施（`tasks/phase-02-runtime-core/TASK-103-Trace与Runtime-API.md:47-57`），本任务不能验证该字段实际为 false。当前未把“尚未实现”当成 TASK-002 缺陷，也不把它写成已验证 PASS。 |
| TASK-001 回归、Ruff、范围控制 | **PASS** | `backend/tests/test_app.py:8-88`、`backend/pyproject.toml:10-26`，API 仅保留骨架。 | `ruff check`、`ruff format --check` 均通过；无数据库 URL 的 pytest 为 11 PASS/1 SKIP，注入隔离 MySQL URL 后为 12 PASS。未发现 Provider、IntentService、PromptBuilder、Release 发布业务、Runtime Analyze、Worker、前端新页面、Redis/MQ。 |
| `PROJECT_STATUS.md` 更新 | **PASS（记录存在；结论需修正）** | `PROJECT_STATUS.md:7` 标记 TASK-002 完成。 | 本报告发现两个 P0，现有完成标记不能代表独立批准；修复时应由 TASK-002 执行方同步状态和执行报告。 |

## 4. 数据库审查

本次在**新建临时 MySQL 8.0.32 实例**（端口 33307）的 `ai_coach_task002_test_audit` 隔离库执行迁移和查询 `information_schema.COLUMNS`、`STATISTICS`、`TABLE_CONSTRAINTS`、`KEY_COLUMN_USAGE`、`REFERENTIAL_CONSTRAINTS`。没有操作现有 MySQL80 服务或业务库。列的非空、默认值与 `backend/alembic/versions/0001_initial_schema.py` 对齐；以下给出全部业务字段，`?` 表示 nullable，`=0/1` 表示数据库默认。

| 表 | 实库字段（关键类型） | 实库约束、索引与结论 |
|---|---|---|
| `config_draft` | `id bigint`, `schema_version int`, `draft_json json`, `updated_by varchar(128)`, `updated_at datetime(6)`；全部非空。 | PK(id)，CHECK(id=1)，id 无 auto_increment；PASS。 |
| `model_config` | `id bigint`, `name varchar(128)`, `version varchar(64)`, `provider varchar(64)`, `model varchar(256)`, `base_url varchar(2048)`, `params_json json`, `timeout_seconds float`, `max_retries int`, `max_concurrency int`, `structured_output_mode varchar(32)`, `credential_ref varchar(255)`, `model_config_hash varchar(64)`, `enabled tinyint(1)=1`, `immutable_from_at datetime(6)?`, `created_at datetime(6)`；其余非空。 | PK，UNIQUE(name,version)，hash 普通索引；PASS。credential_ref 是逻辑引用列，不存实际 Key。 |
| `config_release` | `id bigint`, `version varchar(64)`, `snapshot_json json`, `config_snapshot_hash varchar(64)`, `default_model_config_id bigint`, `model_config_hash varchar(64)`, `release_fingerprint varchar(64)`, `note text`, `created_by varchar(128)`, `created_at datetime(6)`；全部非空。 | PK，UNIQUE(version)，model FK RESTRICT，snapshot/model 索引；**UNIQUE(release_fingerprint) 违反再次发布/回退语义，FAIL**。 |
| `runtime_state` | `id smallint=1`, `active_release_id bigint?`, `updated_at datetime(6)`。 | PK，CHECK(id=1)，release FK SET NULL，active_release_id 索引；PASS。 |
| `intent_request_trace` | `id bigint`, `trace_id varchar(64)`, `request_id varchar(128)`, `parent_trace_id varchar(64)?`, `source varchar(64)`, `input text`, `context_json json?`, `release_id bigint?`, `config_snapshot_hash varchar(64)?`, `release_fingerprint varchar(64)?`, `effective_model_config_id bigint?`, `model_config_hash varchar(64)?`, `model_config_snapshot_json json?`, `final_route varchar(64)?`, `final_result_json json?`, `reason_summary text?`, `evidence_json json?`, `validation_json json?`, `timeline_json json?`, `latency_ms int?`, `input_tokens int?`, `output_tokens int?`, `total_tokens int?`, `retry_count int=0`, `status varchar(32)`, `error_code varchar(64)?`, `error_message text?`, `created_at datetime(6)`；未标 `?` 的非空。 | UNIQUE(trace_id)；request_id 普通索引，可复用；parent 无 FK；release/model FK SET NULL；created/status/route/release/model 及组合索引齐全；PASS。 |
| `llm_call_trace` | `id bigint`, `trace_id varchar(64)`, `attempt_no int`, `provider varchar(64)`, `model varchar(256)`, `model_params_json json?`, `final_prompt text?`, `prompt_hash varchar(64)?`, `raw_request_json json?`, `raw_response_json json?`, `final_prompt_truncated tinyint(1)=0`, `raw_request_truncated tinyint(1)=0`, `raw_response_truncated tinyint(1)=0`, `provider_request_id varchar(255)?`, `provider_model_version varchar(255)?`, `system_fingerprint varchar(255)?`, `finish_reason varchar(128)?`, `parsed_result_json json?`, `input_tokens int?`, `output_tokens int?`, `total_tokens int?`, `latency_ms int?`, `status varchar(32)`, `error_code varchar(64)?`, `error_message text?`, `created_at datetime(6)`；未标 `?` 的非空。 | UNIQUE(trace_id,attempt_no)，trace FK CASCADE；status/created 索引；PASS。 |
| `evaluation_dataset` | `id bigint`, `name varchar(128)`, `version varchar(64)`, `source_filename varchar(512)`, `hash varchar(64)`, `normalized_cases_json json`, `created_at datetime(6)`；全部非空。 | UNIQUE(name,version)，hash 索引；PASS。 |
| `evaluation_run` | `id bigint`, `dataset_id bigint`, `dataset_hash varchar(64)`, `release_id bigint?`, `config_snapshot_hash varchar(64)`, `release_fingerprint varchar(64)`, `effective_model_config_id bigint?`, `model_config_hash varchar(64)`, `model_config_snapshot_json json`, `repeat_count int`, `worker_concurrency int`, `status varchar(32)`, `progress_json json?`, `claimed_by varchar(128)?`, `heartbeat_at datetime(6)?`, `error text?`, `created_at datetime(6)`, `started_at datetime(6)?`, `finished_at datetime(6)?`；未标 `?` 的非空。 | dataset FK RESTRICT，release/model FK SET NULL；status/created 与 status/claimed/heartbeat 组合索引；PASS。 |
| `evaluation_case_result` | `id bigint`, `run_id bigint`, `case_id varchar(128)`, `repeat_index int`, `expected_json json`, `actual_json json?`, `passed tinyint(1)?`, `error_type varchar(64)?`, `error_message text?`, `request_id varchar(128)?`, `trace_id varchar(64)?`, `latency_ms int?`；未标 `?` 的非空。 | UNIQUE(run_id,case_id,repeat_index)，run FK CASCADE，trace_id 仅普通索引、无 FK；PASS。`parent_trace_id` 不在此表，属于 Trace。 |

所有业务表的 MySQL 表选项为 `utf8mb4` / `utf8mb4_unicode_ci`；JSON 列真实类型为 `json`，时间列为 `datetime(6)`。实库成功执行空库 upgrade、downgrade/upgrade；`alembic check` 未发现 ORM/Migration 自动生成差异。事务错误可回滚且 session/engine 有关闭路径。MySQL DDL 本身非事务性，部署迁移中断仍需按 Alembic 常规方式恢复，非本次缺陷。

## 5. Bootstrap 审查

`backend/app/bootstrap/service.py:34-87` 只接受七个固定顶层字段，固定 Route 恰好七个且全部 enabled；`schema_version=1`。Bootstrap 文件内容计数为 7 routes、40 intents、3 slots、1 enum group、10 examples、2 个 prompt_template 字段。`backend/tests/test_bootstrap_unit.py:12-41` 的 canonical JSON 等价断言覆盖别名、槽位、枚举、示例及中文字段保留。`backend/app/bootstrap/service.py:105-122` 仅创建 `config_draft(id=1)`，已有相同 Draft 返回 no-op，差异 Draft 抛冲突。`backend/app/bootstrap/cli.py:30-38` 将写入放在一个事务中并释放连接；非法文件在开事务前拒绝。真实 CLI 独立复验两次输出 `created`/`already current`，Release 与 runtime_state 均为 0；集成测试在开发者修改 Draft 后验证冲突、强制异常后验证回滚。未发现覆盖用户修改的路径。

## 6. 实际执行的测试与环境

| 命令/检查 | 本次结果 |
|---|---|
| `git status --short`、`git log -5 --oneline`、`git diff --check` | 审核前工作区干净、diff check 无错误；HEAD 如上。 |
| `cd backend; python -m ruff check .` | PASS。 |
| `cd backend; python -m ruff format --check .` | PASS，30 files already formatted。 |
| `cd backend; python -m pytest -q`（未设 MySQL URL） | PASS：11 passed、1 skipped；SKIP 是 `MYSQL_TEST_DATABASE_URL` 未设置，不能据此宣称真实 MySQL 通过。 |
| 临时实例 MySQL `SELECT VERSION()` | PASS：8.0.32。安装目录本身不是验收证据，以下测试均连接 33307 临时实例。 |
| `MYSQL_TEST_DATABASE_URL=mysql+asyncmy://root@localhost:33307/ai_coach_task002_test_audit python -m pytest tests/test_mysql_integration.py -q -rs` | PASS：1 passed；测试执行隔离库 downgrade/base、空库 upgrade/head、Bootstrap/冲突/回滚、关键 unique/FK/cleanup、无 Release 的 readiness、再次 downgrade/upgrade。 |
| 同一 URL 执行 `python -m pytest -q -rs` | PASS：12 passed、0 skipped。包含 TASK-001 回归与 TASK-002 测试。 |
| `DATABASE_URL=...audit python -m alembic -c alembic.ini check` | PASS：`No new upgrade operations detected`。 |
| `information_schema` 实库查询 | PASS：9 张业务表、关键列类型/nullable/default/索引/FK/删除规则均实际可见；具体见第 4 节。 |
| `python -m app.bootstrap.cli --file ../bootstrap/initial-config.v1.json` 连续两次 | PASS：首次创建、再次 no-op；实库 Draft=1、Release=0、runtime_state=0。 |
| 实库同一 request_id 两个 Trace、缺失父 Trace 的 Attempt | PASS：两个 Trace 可插入；缺失父 Trace 的 Attempt 被 FK 1452 拒绝。 |
| 实库同一 Snapshot/Model 再发布不同版本 Release | **FAIL**：第二次插入因 `uq_config_release_release_fingerprint` 报 MySQL 1062；见 R-001。 |
| `ai_coach_task002_test_readiness` 隔离库 `/ready`：空库、head、head 但删去一张必需表 | **503 / 200 / 200**；最后一个应为 503，见 R-002。此测试只破坏新建隔离库。 |

原执行报告声称 MySQL 测试通过；本次已在独立临时实例重跑并直接查证实库，因此主要正向证据不依赖原报告。报告未覆盖的两条反例由本次新增独立复现发现。

## 7. 问题清单

### R-001 — P0 — Release 指纹错误设为唯一，阻断历史 Snapshot 再发布

- **位置**：`backend/app/db/models.py:74`；`backend/alembic/versions/0001_initial_schema.py:76-85`。契约见 `AGENTS.md:104-108`、`docs/07-数据库与配置版本设计.md:44,139-148`。
- **问题**：指纹只由业务配置 hash、默认模型 ID、模型配置 hash 计算。回退流程从历史 Snapshot 创建新 Draft/Release；若选用原模型，指纹与历史 Release 必然相同。数据库唯一键拒绝新版本，即使 `version` 不同。本次 MySQL 8.0.32 以两个版本、相同内容/模型直接复现 1062。
- **后续影响**：TASK-201 的回退和“重新发布相同配置”不能实现；如果 TASK-101/后续 Contract 假设每个发布版本均可持久化，后续会被数据库约束卡住。属于配置可回退的核心契约违背。
- **最小修复**：通过**新增 Alembic revision** 删除 `uq_config_release_release_fingerprint` 唯一约束，按查询需要改为普通索引；ORM 同步去掉 `unique=True`；保留 `version` 唯一键，并加 MySQL 回归测试验证相同指纹可属于不同 Release 版本。已发布的历史迁移不要原地静默改写。

### R-002 — P0 — `/ready` 对缺失的必需业务表误报可用

- **位置**：`backend/app/db/readiness.py:25-32` 仅执行 `SELECT 1` 并比较 `alembic_version`；入口 `backend/app/main.py:52-62,137-148`。
- **问题**：隔离库迁到 head 后删除 `evaluation_case_result`，Alembic 版本仍为 head，`/ready` 实际返回 200。v1.2.4 要求 DB/Migration schema **可用**，必需表缺失不满足该条件。该反例没有使用 mock。
- **后续影响**：Pod 会接收流量，但后续 TASK-103 Trace/TASK-301 Evaluation 所需表可能不存在；故障被 readiness 掩盖，影响故障定位与部署恢复。
- **最小修复**：沿用现有 `ReadinessChecker` 注册方式，在 `DatabaseSchemaReadiness` 同一次异步连接中验证九张必需业务表存在（至少再覆盖关键列/约束的 schema 健康条件）；保留 Alembic head 检查，新增真实 MySQL “head 但缺表”负例。不要把 Active Release 或 Model Config 加入 `/ready`。

## 8. 最终审批结论

**FAIL：存在两个独立复现的 P0，必须留在 TASK-002 修复。** 真实 MySQL 正向集成测试通过，不能抵消上述核心契约与 readiness 反例。修复后应以新的审核 commit 重跑隔离 MySQL 迁移/ORM 对照、Release 同指纹再发布和 schema 缺表 readiness 测试，再重新审批。

## 9. 对 TASK-101 的影响

`config_draft.draft_json`、`config_release.snapshot_json`、独立的 `default_model_config_id`、`model_config` 调用参数与 hash 字段，结构上足以表示 TASK-101 所需 `RuntimeConfigSnapshot`、`ModelConfigSnapshot` 和 `PromptBuilder` 输入；没有要求 TASK-101 实现数据库发布业务。**但当前 Gate 未通过**：R-001 必须先修复，避免后续 Release Contract 建立在无法回退的约束上；R-002 必须先修复，避免把不完整 Schema 判为服务就绪。`runtime_config_ready` 的实际 Admin 字段和 Runtime `CONFIG_NOT_READY` 属 TASK-103 的明确范围，不作为 TASK-101 前置实现要求。

**TASK-002 独立复核结论：FAIL。是否允许开始 TASK-101：否。**
