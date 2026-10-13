# TASK-103 P1 定向修复报告

基线：`053d8851d4a0993876ded4395edc435ea065d3c6`。实现提交：`3e05b497724ee0e8fe15964e21d6ac3cb3468458`；既有 staged 审核材料保持原样。

## 已关闭

- P1-1：Runtime MySQL E2E 改用合法 `QWEN_API_KEY` credential reference。测试用 `monkeypatch` 仅向隔离进程注入本地假凭据，Provider 仅调用 localhost；Resolver 不再保留非法小写引用的特殊回退分支。
- P1-2：`DatabaseSchemaReadiness` 不再维护手写表/列清单，改由 `Base.metadata.sorted_tables` 推导，并以一次 `information_schema.COLUMNS` 查询检查全部业务表/列；保留 Alembic head 比较。

实际隔离 MySQL 8.0.32（127.0.0.1:13358，两个专用 `ai_coach_task*_test_task103_p1` 库）结果：

```text
pytest -q -rs tests/test_task103_mysql.py tests/test_mysql_integration.py
.... [100%]

pytest -q -rs tests/test_config_mysql.py tests/test_task201_interface_mysql.py
........... [100%]
```

首组包含正式 Runtime HTTP -> DatabaseRuntimeConfigLoader -> ModelProviderFactory -> localhost Provider -> DatabaseTraceStore -> MySQL Trace 查询；第二组包含 C10 完整 schema、缺列、缺表、无 Active Release 的真实 MySQL 回归。

## P1-3（本轮前已完成）

P1-3 已新增真实 MySQL request insert、attempt insert、commit 前故障注入；三种情形均观察到 `DatabaseTraceStore` 抛错后请求/Attempt 均为 0 行，证明单事务 rollback。实际命令：

```text
pytest -q -rs tests/test_task103_mysql.py::test_trace_store_mysql_failure_rolls_back_atomically
... [100%]
```

已新增真实 MySQL validation/retention 用例：超长中文/emoji/敏感 Slot 诊断写入后 `validation_json` 不超过 65,536 UTF-8 bytes，保留 `SLOT_SPAN_INVALID` 和 `truncated=true`，不含敏感明文；关联 `evaluation_case_result` 的 40 天 Trace 在普通 30 天、评测 90 天策略下不被删除，Evaluation result 保留。实际命令：

```text
pytest -q -rs tests/test_task103_mysql.py::test_validation_diagnostics_and_retention_use_real_mysql
. [100%]
```

当时尚未完成的项目已在下节以隔离 MySQL 8 的复测关闭；本报告不自行宣布 TASK-103 PASS，也不启动 TASK-202。

## Git 临时数据整理

整理前发现两个未跟踪的仓库内 MySQL 审计 datadir：`.tmp-task103-mysql-audit-20261013` 与 `.tmp-task103-mysql-audit2-20261013`，包含 datadir、binlog、证书及日志；`git ls-files -- '.tmp-task103-*'` 无输出，未发现 tracked 文件。已在 `.gitignore` 增加严格根目录规则 `/.tmp-task103-*/`，并以 `git check-ignore -v .tmp-task103-mysql-audit2-20261013/data/ibdata1` 验证命中。实例仍运行于 13358，故未删除目录。

## P1-3 收尾：真实 MySQL 8 验收

所有下述用例使用 `127.0.0.1:13358` 的隔离 MySQL 8.0.32、真实 SQLAlchemy AsyncSession 和本机 localhost HTTP Provider；未使用 SQLite、Mock DB 或真实 Qwen 凭据。

- Runtime fail-open：正式 `POST /api/v1/intent/analyze` 收到 Provider 成功结果时，对 `intent_request_trace` INSERT 注入真实数据库故障；HTTP 仍为 200 且业务 route 正确。请求与 Attempt 均为 0 行，没有半写入；测试输入的敏感值没有落入 Trace。
- 非 Runtime fail-closed：以真实 `DatabaseTraceStore` 调用 `execution_mode="debug"`，同样的数据库 INSERT 故障传播为 `INTERNAL_ERROR` / 500，不返回伪造业务成功，且 Trace/Attempt 均为 0 行。
- Active A→B：真实 `DatabaseRuntimeConfigLoader`（TTL 60 秒）、`ModelProviderFactory`、`DatabaseTraceStore` 及 localhost HTTP 验证。A 请求已实际发出后发布并激活 B；A 保持 `model-a` 参数，B 发出两次物理 HTTP（一次可重试失败、一次成功）且均为 `model-b` 参数。两条 MySQL Trace 分别核对 Release ID、Model ID、business/model hash、fingerprint、model snapshot 和 Attempt model，未发生缓存串用。
- 取消与资源释放：一槽真实连接池耗尽时取消，不到达 SQL、无 Trace 行，释放后可正常写入；通过真实 MySQL `BEFORE INSERT` 慢触发器使 INSERT 进入执行后取消，回滚且后续连接可写；commit 前注入 `CancelledError` 时无行，commit 后注入时 MySQL 行存在。两种路径均传播 `CancelledError`，后续写入成功。后者按已观测到的 DBAPI commit 完成处理，不声称回滚；网络中断导致的 commit 结果未知路径不报告为 persisted。
- validation/retention：超长中文、emoji 和敏感 Slot 经真实 MySQL 持久化后，`validation_json` UTF-8 长度不超过 65,536，保留 `SLOT_SPAN_INVALID` 与 `truncated=true`，不含敏感明文，也不改变业务结果 Slot。40 天 Evaluation 关联 Trace 在普通 30 天、Evaluation 90 天策略下未被删除，`evaluation_case_result` 仍在。当前 Schema 的可验收关联关系仅此项；未实现 TASK-301 Worker。

实际命令与结果：

```text
pytest -q -rs tests/test_task103_mysql.py
............. [100%]  # 13 passed

pytest -q -rs tests/test_task103_mysql.py tests/test_mysql_integration.py tests/test_config_mysql.py tests/test_task201_interface_mysql.py
.......................... [100%]  # 26 passed

uv run --locked --extra dev ruff check .
All checks passed!

uv run --locked --extra dev ruff format --check .
63 files already formatted

uv run --locked --extra dev pytest -q -rs
exit 0; 185 collected; 0 skipped; only existing Starlette/httpx deprecation warning
```

`REAL_QWEN_SMOKE` 仍为 **UNVERIFIED**：全部 Provider 流量仅到 localhost，未使用真实 Qwen key 或外部 Qwen 请求。

## 复核边界

P1-1、P1-2 与 P1-3 的开发方隔离 MySQL 验收已完成；TASK-103 状态为“待独立增量复核”，不是自行判定 PASS。独立复核应复跑上述 13 项 TASK-103 MySQL 用例及完整门禁，特别关注 commit 结果未知时不允许报告持久化成功。

## 测试环境收尾与提交隔离

13358 实例通过 `mysqladmin shutdown` 正常停止（exit 0），端口已释放。确认本轮实例只使用 `.tmp-task103-mysql-audit2-20261013`；另一个同前缀目录来源不明，未触碰。对已确认目录的删除被当前执行环境的删除安全策略拒绝，未绕过该限制；其仍由 `/.tmp-task103-*/` 排除，且不包含 Git tracked 文件。原始受控 pytest 日志在仓库外的用户 TEMP 目录。

提交前已重新核对 staged、unstaged 与 untracked 文件：既有 TASK-102/TASK-201 审核报告和 `TASK-103_INDEPENDENT_REVIEW.md` 明确排除；不会使用 `git add -A`、`git add .` 或无路径范围的提交。

实现提交 `3e05b497724ee0e8fe15964e21d6ac3cb3468458` 的准确文件清单为：`.gitignore`；`backend/app/api/runtime/router.py`；`backend/app/core/diagnostics.py`；`backend/app/core/settings.py`；`backend/app/db/database.py`；`backend/app/db/readiness.py`；`backend/app/main.py`；`backend/app/schemas/intent.py`；`backend/app/services/intent_service.py`；`backend/app/services/runtime_config.py`；`backend/app/services/trace_store.py`；`backend/app/trace/__init__.py`；`backend/app/trace/cleanup.py`；`backend/tests/test_migration_metadata.py`；`backend/tests/test_task103_contract.py`；`backend/tests/test_task103_mysql.py`。`git show --name-only` 已核对该列表；未混入审核材料、datadir、binlog、证书、密钥或测试日志。
