# TASK-002 独立第二意见审核报告

审核日期：2026-10-12（Asia/Tokyo）  
审核范围：当前仓库 HEAD `a2fd1a1aee1905fee599ed1b675e44d23997753c` 及其工作树  
审核结论：**CONDITIONAL PASS**

本报告只审核 TASK-002，不修改业务代码、不切换 uv、不开始 TASK-101。`CONDITIONAL PASS` 表示当前没有已证实的 P0，可以进入 TASK-101；但 readiness 对部分业务列漂移的检测仍有一个明确的 P1 遗留项，不能把本结论等同于整个项目已达到生产上线标准。

## 1. Git 审核基线

审查开始时依次执行了任务要求的命令：

```text
git status --short
git branch --show-current
git rev-parse HEAD
git log -10 --oneline
git diff --check
```

结果：

| 项目 | 结果 |
|---|---|
| 分支 | `main` |
| 当前审核 HEAD | `a2fd1a1aee1905fee599ed1b675e44d23997753c` |
| 审核开始时未提交变更 | 无；`git status --short` 无输出 |
| `git diff --check` | 通过；无输出 |
| 当前 HEAD 提交 | `a2fd1a1 fix:task 002` |
| 前一提交 | `b671d40 fix: address task 002 review findings` |
| 初始 TASK-002 实现提交 | `77a30f9 feat: add task 002 database foundation` |

必须区分的版本变化：

1. `77a30f9` 是原始 TASK-002 实现。该版本的 `config_release.release_fingerprint` 仍为唯一键，readiness 只检查 DB 和 `alembic_version`。
2. `b671d40` 增加了取消 fingerprint 唯一性的迁移方向和九张业务表的 readiness 检查，但新增迁移 revision `0002_release_fingerprint_nonunique` 长度为 34，在 MySQL `alembic_version.version_num VARCHAR(32)` 上不能可靠落库。
3. 当前 `a2fd1a1` 将迁移替换为 `0002_release_fp_index`，revision 长度符合 Alembic/MySQL 限制，并增加了对正常 0001 状态及旧迁移 DDL 半完成状态的兼容处理；同时保留 readiness 的表/列检查。
4. `TASK-002_INDEPENDENT_REVIEW.md` 是历史复核记录，包含 `7ca1b48`、`b671d40` 及暂存工作树阶段的结论，不能代替当前 HEAD 的证据。本次以当前源码、当前迁移和本次重新运行的测试为准。

本报告写入后会成为预期的新工作树文件；上述“工作区干净”特指审查开始时的基线，不把本报告自身当作业务代码变更。

## 2. 实际读取的文件

已读取并用于本次判断的主要文件包括：

- `AGENTS.md`、`tasks/README.md`、`tasks/phase-01-foundation/TASK-002-MySQL-Migration与Bootstrap.md`；
- `docs/03-Intent路由与动态Prompt设计.md`、`docs/06-API与数据结构设计.md`、`docs/07-数据库与配置版本设计.md`、`docs/08-部署与主系统接入设计.md`、`docs/09-参考项目与采用策略.md`；
- `bootstrap/initial-config.v1.json`、`PROJECT_STATUS.md`、`TASK-002_EXECUTION_REPORT.md`、`TASK-002_INDEPENDENT_REVIEW.md`；
- `backend/app/db/base.py`、`database.py`、`models.py`、`readiness.py`；
- `backend/app/bootstrap/service.py`、`cli.py`、`backend/app/main.py`、`backend/app/core/readiness.py`；
- `backend/alembic/env.py`、`0001_initial_schema.py`、`0002_release_fp_index.py`、`backend/alembic.ini`；
- `backend/tests/conftest.py`、`test_app.py`、`test_bootstrap_unit.py`、`test_migration_metadata.py`、`test_mysql_integration.py`；
- `tasks/phase-02-runtime-core/TASK-101-Intent-Contract与PromptBuilder.md` 和 `TASK-103-Trace与Runtime-API.md`，用于确认后续任务边界。

## 3. 独立核实的 Task Contract

TASK-002 的实际完成条件是：

- 通过 Alembic 在空 MySQL 8 数据库建立九张一期业务表：`config_draft`、`model_config`、`config_release`、`runtime_state`、`intent_request_trace`、`llm_call_trace`、`evaluation_dataset`、`evaluation_run`、`evaluation_case_result`；
- 字段、hash、`credential_ref`、raw 截断标记、Evaluation 冻结字段和 Trace/Evaluation 索引符合 `docs/07`；
- SQLAlchemy 2.x async engine/session 的事务和生命周期明确；
- Bootstrap 只导入 Draft，不自动创建 Release 或 Active State；顶层字段严格拒绝未知字段；重复导入不覆盖已编辑 Draft；
- `trace_id` 唯一、`(trace_id, attempt_no)` 唯一、`(run_id, case_id, repeat_index)` 唯一；Trace attempts 可级联清理，但不能因 `evaluation_case_result.trace_id` 反向阻止清理或级联删除评测结果；
- `/ready` 只表达进程、DB/基础依赖和 Migration schema 可用，不依赖 Active Release 或 Model Config；Runtime 配置未就绪应由后续 Admin status/Runtime 逻辑表达；
- 不提前实现 TASK-101 的 Intent/Pydantic/PromptBuilder，也不提前实现 TASK-103 的 RuntimeConfigLoader、TraceStore 或 Runtime Analyze。

其中，`docs/03` 和 `docs/07` 明确规定：

```text
release_fingerprint = SHA256(config_snapshot_hash + default_model_config_id + immutable model_config_hash)
历史 Snapshot -> 新 Draft -> 新 Release
```

因此 fingerprint 是不可变内容的身份/诊断索引，不是 Release 行的版本唯一键；Release 版本需要由 `config_release.version` 单独保证唯一。

## 4. 原审核逐项重新判断

### R-001 原结论

原审核在旧代码上发现的事实成立：`0001_initial_schema.py` 和旧 ORM 均把 `release_fingerprint` 声明为 UNIQUE；同一不可变 Snapshot、同一 Model Config、不同 Release version 会生成相同 fingerprint。该约束会使历史 Snapshot 回退后重新创建新 Release 失败。

原审核把它列为 P0 是可以成立的，理由是它直接违反“新 Release 版本可审计、历史 Snapshot 可回退”的核心配置版本契约，并阻断后续 TASK-201 的正常发布/回退路径。不过，“因此必然阻断 TASK-101”说得过重：TASK-101 是不依赖数据库和模型的纯 Contract/PromptBuilder 任务，R-001 的直接阻断对象是 Release/Config 管理，而不是 PromptBuilder。按项目规定的严格顺序，它确实阻止 TASK-002 完整关单；但不是 TASK-101 的技术依赖。

### R-002 原结论

原审核的反例也成立：旧实现仅比较 `alembic_version`，在物理删除 `evaluation_case_result` 后仍能返回 200。一个“版本号为 head 但实际业务 schema 不完整”的数据库不能完整满足“Migration schema 可用”。这不是无依据的生产建议，而是 readiness 语义的真实边界问题。

但原审核直接定为 P0、并把它描述为必然阻塞 TASK-101，评级偏重：

- 触发条件是数据库发生了额外的表级漂移/破坏，不是正常空库 migration 路径；
- 缺失 Evaluation 表会影响 Evaluation/Admin 能力，但不必然影响 TASK-101 的纯内存 Contract/PromptBuilder；
- 它是可靠性和故障暴露问题，当前证据不足以证明数据已丢失或会阻断所有后续开发。

因此，旧代码上的 R-002 根因应评为 P1 更准确；修复方向正确，但无需把所有后续开发一概冻结。当前代码已经修复了“缺失必要表仍 200”的核心反例。

## 5. R-001 证据及结论

### 5.1 当前计算语义与唯一性

TASK-002 当前没有实现 Release 发布服务，因此没有可审计的 Python fingerprint 计算函数；计算公式由 `docs/03 §7`、`docs/07 §2/§3` 规定。当前 schema 的语义正确：

- `config_release.version` 仍由 ORM `UniqueConstraint("version", name="uq_config_release_version")` 和 0001 migration 保证唯一；
- `release_fingerprint` 在当前 ORM `backend/app/db/models.py:62-77` 中是普通索引，不是唯一列；
- 0002 在线 migration 删除历史 `uq_config_release_release_fingerprint`，创建普通索引 `ix_config_release_release_fingerprint`；
- `config_release` 历史行仍可通过 `id/version/snapshot/model hash/fingerprint` 追踪，未修改旧 Snapshot 的语义。

### 5.2 当前 HEAD 的真实 MySQL 验证

在独立 MySQL 8.0.32 实例和隔离库 `ai_coach_task002_test_second_opinion` 中验证：

- 空库 `upgrade head` 成功，版本为 `0002_release_fp_index`；
- 0001 中先插入一条 Release，再模拟旧迁移已删除唯一索引、已建立普通索引但尚未更新 Alembic 版本的半完成状态；重跑 `upgrade head` 成功，版本更新为 `0002_release_fp_index`，原 Release 仍存在；
- 两条 Release 使用相同 fingerprint、不同 version 可以同时插入；
- 相同 version、不同 fingerprint 仍因 `uq_config_release_version` 被拒绝；
- `information_schema.STATISTICS` 实际显示 `ix_config_release_release_fingerprint` 的 `NON_UNIQUE=1`，`config_release` 唯一约束仅剩 `uq_config_release_version` 和主键；
- `downgrade base -> upgrade head` 成功，历史迁移数据在 0001 -> 0002 路径中未被删除或改写。

### 5.3 Downgrade 安全性

在隔离库中实际插入两个相同 fingerprint 的 Release 后执行 `downgrade 0001_initial_schema`，命令以 exit code 1 失败并给出：

```text
cannot restore unique release_fingerprint while duplicate immutable releases exist
```

随后查询确认 Alembic 版本仍为 `0002_release_fp_index`，普通 fingerprint 索引仍存在。删除隔离测试行后，`downgrade base -> upgrade head` 再次成功。该行为避免 downgrade 在无法恢复唯一键时先删除可用索引。

### 5.4 结论

R-001 在旧 commit 上是真问题，原始 P0 评级基本合理；但其“必然阻断 TASK-101”的表述夸大了直接依赖范围。当前 HEAD 已通过新的 Alembic revision、ORM 一致性、旧数据保留和重复 fingerprint 回归测试修复。R-001 当前不再是阻断问题。

## 6. R-002 证据及结论

### 6.1 当前实现

`backend/app/db/readiness.py:9-62` 当前在同一异步 DB connection 中执行：

1. `SELECT 1`；
2. 读取 `alembic_version` 并与动态解析出的 Alembic head 比较；
3. 查询当前 database 的 `information_schema.COLUMNS`；
4. 对九张一期业务表检查各自的必需列集合。

`/ready` 入口仍只注册 `DatabaseSchemaReadiness`，没有查询 Active Release 或 Model Config，因此没有破坏 v1.2.4 的首次部署/配置修复语义。

### 6.2 正反条件实测

| 条件 | 实测结果 | 结论 |
|---|---:|---|
| DB 不可用/未配置 | `503`，database failed | 正确 |
| 新建空库、尚未 migration | `503` | 正确 |
| 完整 migration 到 `0002_release_fp_index` | `200` | 正确 |
| 完整 schema、无 Active Release、无 Model Config | `200` | 正确，符合不依赖运行时配置的契约 |
| head 仍在但重命名 `evaluation_case_result` | `503` | 原 R-002 反例已修复 |
| `health` | 独立 `200` | liveness/readiness 语义未混淆 |

真实 MySQL 集成测试 `test_mysql_migration_bootstrap_constraints_and_readiness` 也覆盖了完整 schema 200、缺失业务表 503，并在 finally 中恢复了隔离库表名。

### 6.3 是否需要九张表和每次查询 information_schema

检查九张表是合理的：TASK-002 明确把九张表作为一期完整数据模型，readiness 只代表 Runtime 的“进程/DB/迁移 schema 服务面”时，不能仅凭某一张 Runtime 表推断整个已部署 schema 正常。当前实现只发出一次 `information_schema.COLUMNS` 查询，不是九次查询；在独立 MySQL 数据库和九张小表的正常 Kubernetes probe 频率下，未观察到不合理压力。

但这不是唯一方案，也不是必须永远逐行扫描全部列：

- 可把查询收窄到九张表和声明的必需列，而不是当前读取当前 database 的全部列；
- 可在应用进程内做短 TTL 缓存，但应保留周期性复核，避免漂移长期被掩盖；
- 不应把 Active Release、Model Config 或完整业务数据状态加入 `/ready`；这些属于 `runtime_config_ready`。

### 6.4 结论

当前 R-002 的“缺表误报 200”已经修复且没有破坏无 Release/Model Config 时的 ready 语义。旧审核将该问题直接升为 P0 并据此冻结 TASK-101，属于严重性夸大；更准确的旧代码评级是 P1。当前仍有一个相关但更窄的残余问题，见下一节 N-001。

## 7. 新发现的问题

### N-001 — P1 — readiness 只覆盖部分列，未覆盖完整 Migration schema

**实际证据：** 当前 `REQUIRED_BUSINESS_COLUMNS` 只列举每张表的部分列。例如 `config_release` 只检查 `id/version/default_model_config_id/release_fingerprint`，不检查 `snapshot_json`、`config_snapshot_hash`、`model_config_hash`、`note` 等 Task Contract 必需列。在隔离 MySQL 中实际执行：

```text
ALTER TABLE config_release DROP COLUMN snapshot_json;
GET /ready -> 200, database=ok
```

随后恢复该列，`alembic check` 返回 `No new upgrade operations detected`。这证明该反例是 readiness 检查覆盖不足，而非测试残留或 Alembic 未恢复。

**契约依据：** TASK-002 DoD、`docs/07` 核心表字段清单、`docs/08 §4` 都要求 Migration schema 可用；缺失 `snapshot_json` 时发布/读取 Release 会失败，不能认为完整 schema 可用。

**业务影响：** 部署中若发生列级漂移，Pod 仍可能被加入 Service，直到 TASK-201/后续 Release 路径真正访问缺失列才暴露。没有证据表明这会丢数据或阻断 TASK-101。

**等级与处置：** P1；建议在 TASK-201 前或 TASK-002 的小修复中处理，但不阻断 TASK-101。最小修复是为九张表声明完整的 required column 集，并把 `information_schema` 查询限制到这些表/列；不需要引入 Redis、启动时重构或大规模 schema diff 系统。补一个“缺失任一完整必需列返回 503”的 MySQL 回归测试即可。

### N-002 — P2 — TASK-002 执行报告仍有已被当前 HEAD 推翻的表述

`TASK-002_EXECUTION_REPORT.md` 的历史表格仍写着 `release_fingerprint` 唯一，readiness 章节也保留“只执行 SELECT 1 与 alembic_version”的旧实现描述；当前 ORM、0002 migration 和实际测试已经相反。它不影响运行时，但会误导下一轮审计、发布审批和故障排查。

等级为 P2，建议下次 TASK-002 状态同步时更新；本报告不修改该历史文件，以保留审查记录链。

### 未升级为问题的扫描结果

| 检查项 | 结果 |
|---|---|
| ORM 与 Alembic 差异 | `alembic check` 通过；未发现当前 metadata 与 migration 的新增差异 |
| Bootstrap 顶层严格校验 | `extra="forbid"`；未知顶层字段、Route disable/增删均有测试；嵌套业务字段的完整 Validate 属后续配置任务 |
| 重复 Bootstrap 覆盖编辑 Draft | 当前 Draft 不同则抛 `BootstrapConflictError`；真实首次/重复 CLI 为 created/already current；Release/runtime_state 未被创建 |
| DB 事务回滚 | `Database.transaction()` 有 begin/rollback/dispose；集成测试验证强制异常后 Draft 仍存在 |
| Trace 删除关系 | `llm_call_trace` 对 request 为 CASCADE；`evaluation_case_result.trace_id` 无 FK；评测结果不会随 Trace 删除 |
| 外键/索引 | attempt、case repeat 唯一约束及查询索引实库存在；Trace cleanup 不被 Evaluation 反向 FK 阻塞 |
| Model Config hash/immutable 字段 | `credential_ref`、`model_config_hash`、`immutable_from_at` 存在；hash 为普通索引是正确的。真正的“已引用后不可原地修改”由后续 Model Config/Release service 强制，当前没有提前实现该业务路径 |
| AsyncEngine/AsyncSession 生命周期 | async engine、async sessionmaker、显式 transaction、lifespan dispose 均存在 |
| MySQL 8 兼容性 | 实测 MySQL 8.0.32；JSON、DATETIME(6)、CHECK、FK、索引及 Alembic 版本写入均通过 |
| SQL 注入/敏感值 | 生产 SQL 为静态语句或 SQLAlchemy 参数；Bootstrap 不拼接 SQL；仅存 `credential_ref`，未发现硬编码 API key/密码或完整 raw 日志输出路径 |
| readiness 异常状态 | SQLAlchemy 异常会返回 failed/503；无 Active Release/Model Config 不会错误变为 not ready |
| TASK-001 回归 | 现有 app/health、request_id、API 边界和错误 envelope 测试通过 |
| 后续 Task 越界 | 未发现 Intent Contract、PromptBuilder、Provider、Release publish、Runtime Analyze、Evaluation Worker 的提前实现 |

并发 Bootstrap 的 select-then-insert 竞态尚未形成实际生产入口，当前任务只要求重复导入幂等；不把该假设性边界升级为本次缺陷。TASK-201 建立 Admin import/publish API 时应补并发/唯一键错误语义测试。

## 8. 实际运行的测试及结果

### 静态检查与无数据库单元测试

```text
cd backend
python -m ruff check .
python -m ruff format --check .
python -m pytest -q -rs
```

结果：

- Ruff check：PASS；
- Ruff format：PASS，32 files already formatted；
- pytest：13 passed，2 skipped。两个 skip 是未设置 `MYSQL_TEST_DATABASE_URL` 时受保护的 MySQL 集成测试，未被伪造为通过。

### 隔离 MySQL 8 集成验证

在新建 MySQL 8.0.32 实例、独立端口 33329、隔离数据库 `ai_coach_task002_test_second_opinion` 上执行：

```text
MYSQL_TEST_DATABASE_URL=mysql+asyncmy://root@127.0.0.1:33329/ai_coach_task002_test_second_opinion \
  python -m pytest -q -rA
```

结果：15 passed，0 failed，0 skipped。通过项包括：

- 空库/迁移、`0001 -> 0002`、`downgrade base -> upgrade head`；
- 0001 已有 Release 保留、半完成旧 DDL 恢复；
- 相同 fingerprint 不同 version、相同 version 不同 fingerprint；
- 九张表 readiness、缺表 readiness、无 Active Release/Model Config readiness；
- Bootstrap 首次、重复、编辑冲突、事务回滚、顶层 extra-field；
- Trace/Attempt 级联删除、Evaluation Case Result 保留、唯一约束和外键。

另行执行并通过：

```text
python -m alembic -c alembic.ini current
python -m alembic -c alembic.ini check
python -m alembic -c alembic.ini downgrade base
python -m alembic -c alembic.ini upgrade head
```

最终版本为 `0002_release_fp_index (head)`，`alembic check` 为 `No new upgrade operations detected`。Bootstrap CLI 实测两次输出 `created`、`already current`，计数为 `draft=1/release=0/runtime_state=0`。

`/ready` 专项实测结果为：未迁移空库 503、完整 schema 无运行时配置 200、缺表 503、DB 不可达 503。审查用临时 MySQL 进程已停止；未操作共享 3306 实例或生产数据库。

### UNVERIFIED 项

未运行真实 Kubernetes Ingress/Probe、生产 Admin 网络隔离、真实 Qwen Provider、后续 Release API、Runtime Config Loader、Evaluation Worker 或前端 E2E。这些属于 TASK-101 之后的任务，不能被本报告写成 TASK-002 已验证能力。

## 9. 原 AI 审核是否存在误判或夸大

结论分开看：

- R-001 的事实判断正确；旧唯一约束确实阻断相同不可变内容的新 Release。其 P0 评级在 TASK-002 核心配置版本契约下合理，但“必然阻断 TASK-101”是范围夸大。
- R-002 的事实判断正确；head 但缺表返回 200 确实可复现。其修复方向正确，但直接 P0 和冻结 TASK-101 的结论偏重；更准确是 P1 可靠性/故障暴露问题。
- 旧报告没有在最终 commit `a2fd1a1` 上重新建立证据；它曾在 `b671d40`/暂存修复阶段被 R-003 阻塞。当前 `a2fd1a1` 已通过 revision 长度、半完成重试和真实 MySQL 迁移验证，不能继续沿用旧 BLOCKED/FAIL 结论。
- 旧报告未识别当前 readiness 的部分列覆盖缺口 N-001，也未明确区分“TASK-002 关单”和“TASK-101 技术依赖”。

## 10. 当前是否仍有真正阻断性问题

没有已证实的 P0。

- R-001：已修复并验证；不再阻断。
- R-002：缺表误报已修复并验证；不再阻断。
- R-003：旧 revision 超长导致真实 migration 失败的问题已由 `0002_release_fp_index` 修复并验证；不再阻断。
- N-001：P1，建议在 TASK-201 前修复，但不阻断 TASK-101。
- N-002：P2 文档同步项，不阻断任何运行时任务。

这只说明 TASK-002 的当前开发门禁没有 P0，不代表 Model Provider、Runtime API、Release/Admin、Trace、Evaluation、Kubernetes 或生产安全已经完成。

## 11. 最小修复建议

### 当前建议

1. 在 readiness 中补齐九张表的完整 required column 集，至少覆盖 `docs/07` 和 0001 migration 声明的字段；查询使用 `TABLE_NAME`/`COLUMN_NAME` 过滤，保留当前不依赖 Active Release 的语义。
2. 为一个缺失完整必需列的真实 MySQL 反例补集成测试；继续保留缺失表、无配置和 DB 不可达测试。
3. 更新 `TASK-002_EXECUTION_REPORT.md` 中与当前 HEAD 相矛盾的唯一键和 readiness 旧描述；不要覆盖原始历史结论，可在顶部追加当前 commit 记录。

### 明确不建议的修复

- 不把 `/ready` 改成检查 Active Release 或 Model Config；这会破坏首次部署和配置修复路径。
- 不在 0001 上原地改写已发布 migration；当前 0002 的兼容迁移方式应保留。
- 不为解决 N-001 引入 Redis、MQ、全量 schema 管理平台或大规模重构。
- 不为 TASK-002 提前实现 TASK-101 的 PromptBuilder、Provider 或 Runtime API。

## 12. TASK-101 是否可以开始

**可以开始，但审批状态应记录为 CONDITIONAL PASS。**

理由：当前 HEAD 的 TASK-002 migration、Bootstrap、Trace/Evaluation 基础表、R-001 修复、R-002 缺表修复和 TASK-001 回归均有真实 MySQL/自动化证据；没有 P0。N-001 是 readiness 完整列检测的 P1 遗留项，不影响 TASK-101 的纯 Pydantic Contract/PromptBuilder 实现，但必须在进入 TASK-201/生产部署前处理。

本次没有执行 uv 迁移，也没有修改业务代码。允许的下一步是：在记录 N-001/N-002 遗留项后进行 uv 迁移并开始 TASK-101；不能据此宣布整个项目已达到生产上线标准。

最终审批：**CONDITIONAL PASS：TASK-002 可条件性关闭并允许开始 TASK-101；R-001/R-002/R-003 当前无阻断，N-001 必须跟踪至 TASK-201/生产前修复。**

一句话总结：**原审核对 R-001/R-002 的事实判断基本正确但对 R-002 的 P0/阻断范围有所夸大；当前 TASK-002 可以在记录 P1 遗留项的条件下关闭，允许进行 uv 迁移并开始 TASK-101，但整个项目仍未达到生产上线标准。**
