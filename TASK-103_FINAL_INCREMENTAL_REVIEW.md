# TASK-103 最终独立增量复核

审核日期：2026-10-13  
审核对象：实现提交 `3e05b497724ee0e8fe15964e21d6ac3cb3468458`、报告提交 `e9bc6d13021839a4fbf92eba5eba6b4ade81e99c`  
结论：**TASK-103 PASS；TASK-202 ALLOWED。**

本复核仅新增本审核报告，未修改生产代码、测试或既有审核材料。

## 1. Git 基线与范围

- 当前 `HEAD` 为报告提交 `e9bc6d13021839a4fbf92eba5eba6b4ade81e99c`；其父实现提交为指定的 `3e05b497...`。
- `git show --name-only 3e05b497...` 与报告列出的 16 个文件一致：Runtime API、Trace/Loader、readiness、诊断、测试与 `.gitignore`；未混入 TASK-202 或审核材料。
- `git diff --check 3e05b497^ 3e05b497` 无输出。
- 原有 staged 文件仍为 `TASK-102_FINAL_INDEPENDENT_REVIEW.md`、`TASK-201_FINAL_INCREMENTAL_REVIEW.md`、`TASK-201_INDEPENDENT_REVIEW.md`；本审核未改动、取消暂存或提交它们。
- `/.tmp-task103-*/` 已由 `.gitignore` 覆盖；新的 datadir 命中该规则，`git ls-files -- '.tmp-task103-*'` 无输出。

## 2. 新的隔离 MySQL 8 证据

本次新建本地 MySQL Community Server `8.0.32`，监听 `127.0.0.1:13359`，未使用 3306 或任何已有审计库。仅创建：

- `ai_coach_task201_test_task103_final`
- `ai_coach_task002_test_task103_final`

两库均实际执行 Alembic `0001_initial_schema -> 0002_release_fp_index -> 0003_model_timeout_double`，退出码均为 0。服务端字符集/排序规则为 `utf8mb4` / `utf8mb4_0900_ai_ci`。Provider 流量仅到本机 localhost 测试 HTTP 服务。

## 3. 首次 P1 问题关闭结论

| 问题 | 结论 | 独立复核证据 |
|---|---|---|
| P1-1 Credential / Runtime E2E | **PASS** | `credential_ref` 的 Schema 使用 `^[A-Z_][A-Z0-9_]*$`；实际 E2E 用 `QWEN_API_KEY`，Resolver 对它读取 Settings，其余只按环境变量名查找，没有小写 `qwen_api_key` fallback。ASGI `POST /api/v1/intent/analyze` 经真实 `DatabaseRuntimeConfigLoader`、`ModelProviderFactory`、localhost Provider 和 `DatabaseTraceStore` 返回 200，且 MySQL 中有成功 request Trace 与 1 条 Attempt。假凭据只通过测试进程环境注入，未调用真实 Qwen。 |
| P1-2 C10 Readiness | **PASS** | `required_schema()` 只从 `Base.metadata.sorted_tables` 推导；无手工表/列清单。一次带 expanding bind 的 `information_schema.COLUMNS` 查询检查所有 metadata 表/列。真实 MySQL 回归覆盖缺列、缺表及无 Active Release；另在本次隔离库把 `alembic_version` 临时设为 `0001_initial_schema`，`DatabaseSchemaReadiness` 实测返回 `False`，随后恢复到 `0003_model_timeout_double`。 |
| P1-3 真实数据库验收 | **PASS** | 下列所有要求均由 `tests/test_task103_mysql.py` 在本次新 MySQL 8 与 localhost HTTP 上通过；没有以 SQLite 或 Mock DB 替代数据库验收。 |

### P1-3 分项核验

- request INSERT、Attempt INSERT、DBAPI commit 前三种真实故障均抛错，事务回滚后 request/Attempt 都是 0 行。
- 正式 Runtime HTTP 在 Trace INSERT 故障下仍返回正确业务 200；无 request/Attempt 半写入或伪造持久化。
- `execution_mode="debug"` 的真实 `DatabaseTraceStore` 故障返回 `INTERNAL_ERROR` / 500，不伪装为成功；未要求 TASK-202 页面或 TASK-301 Worker。
- Active A→B 使用真实 DB Loader（TTL 60）、Provider Factory、TraceStore 和 localhost HTTP：在途 A 保留 `model-a`，B 的两次物理 HTTP 使用 `model-b`；每条 MySQL Trace 的 Release ID、Model ID、Business/Model Hash、Fingerprint、snapshot 与 Attempt model 均匹配。
- 取消验收真实覆盖一槽 pool wait、MySQL `BEFORE INSERT ... SLEEP(5)` 执行中、DBAPI commit 前和 commit 后。取消均传播 `CancelledError`，未提交路径无行、后续连接可写；commit 后取消以查询到的 MySQL 行为准。
- commit 测试明确区分 commit event（DBAPI commit 前）和 `after_commit`（DBAPI commit 后）；`write()` 在两种情况下均传播取消、从不返回“已持久化”状态。网络中断所致结果未知没有被声称为 rollback 或 persisted，符合保守语义。
- 超长中文/emoji Slot 的真实 MySQL `validation_json` 小于等于 65,536 UTF-8 bytes，保留 `SLOT_SPAN_INVALID` 和 `truncated=true`，敏感明文被脱敏，原业务 Slot 未改写。40 天 Evaluation 关联 Trace 在普通 30 天 / Evaluation 90 天保留期下保留，`evaluation_case_result` 也保留。

因此，**TASK-102 的 `validation_issues` 无界长度遗留问题正式关闭**。

## 4. C10 / C13 / C14

- **C10 PASS**：metadata 推导、一次 information_schema 查询、缺表/缺列/Alembic 不匹配 not ready，以及无 Active Release 仍 `/ready` 通过、`runtime_config_ready=false`，均有源码及真实 MySQL 证据。
- **C13 PASS**：Runtime Contract 覆盖 `docs/06 §3` 的错误码—HTTP 状态与 `Retry-After`，全量门禁通过。
- **C14 PASS**：Runtime 成功结果的 Trace 故障 fail-open；非 Runtime 的真实 DB Trace 故障 fail-closed。两者均有本次真实 MySQL 用例。

## 5. 本次门禁输出

在 `backend/` 且上述两个隔离 MySQL URL 已配置时，实际执行：

```text
uv run --locked --extra dev ruff check .
All checks passed!
RUFF_CHECK_EXIT=0

uv run --locked --extra dev ruff format --check .
63 files already formatted
RUFF_FORMAT_EXIT=0

uv run --locked --extra dev pytest -q -rs
PYTEST_EXIT=0
```

全量实际 collect 为 **187 tests**，无 skipped 条目；仅有既有 Starlette/httpx deprecation warning。

额外真实 MySQL 回归：

```text
pytest -q -rs tests/test_task103_mysql.py
13 passed, exit 0

pytest -q -rs tests/test_task103_mysql.py tests/test_mysql_integration.py \
  tests/test_config_mysql.py tests/test_task201_interface_mysql.py
26 passed, exit 0
```

## 6. 剩余 P2 与边界

- P2：`IntentService` 仍直接导入具体的 `app.providers.qwen.ProviderError`；在未来增加第二 Provider 前，应改为 Provider-agnostic 的错误类型。本项不影响本 Task 的 Runtime 合同或验收。
- `REAL_QWEN_SMOKE=UNVERIFIED`：本复核没有真实 Qwen 凭据或外部 Qwen 调用；所有模型 HTTP 流量均为 localhost 假服务。
- 当前隔离实例和 datadir 仅供本复核；其目录被忽略。结束时应先停止该实例；不因安全策略无法删除被忽略临时 datadir 而阻断本结论。

## 7. 最终放行

P1-1、P1-2、P1-3 均已关闭；C10、C13、C14 通过；完整门禁和真实 MySQL 验收均通过。

**TASK-103：PASS。**  
**TASK-202：ALLOWED。**

外部资料：本独立复核未访问外部资料；依据 `AGENTS.md`、`tasks/README.md`、TASK-103、`docs/03/06/07/10`、两份提交报告、当前源码与本次实际测试结果。
