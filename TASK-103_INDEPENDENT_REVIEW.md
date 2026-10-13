# TASK-103 独立验收与代码复核

审核日期：2026-10-13  
审核结论：**FAIL**。不得启动 TASK-202。

本报告由独立会话形成；未采用开发自验的 PASS 结论，未修改业务代码、未提交或重置任何已有改动。

## 1. Git 基线与范围

- 分支：`main`
- HEAD：`053d8851d4a0993876ded4395edc435ea065d3c6`（`docs(task201): record P1 fixes and independent rereview gate`）。
- TASK-103 没有实现提交：所有实现均为 **staged、未提交** 改动，实际实现 SHA 不能写成 HEAD。
- 既有 staged 审核资料 `TASK-102_FINAL_INDEPENDENT_REVIEW.md`、`TASK-201_FINAL_INCREMENTAL_REVIEW.md`、`TASK-201_INDEPENDENT_REVIEW.md` 均保留，未改动。
- TASK-103 范围内 staged 改动为 Runtime router、`IntentService`、Loader、TraceStore、cleanup、settings/diagnostics、测试和执行报告；未发现 TASK-202 文件或功能提前开发。
- `git diff --cached --check` 发现三个既有/随交付报告的 Markdown whitespace 问题：`TASK-103_EXECUTION_REPORT.md:3`、`TASK-201_FINAL_INCREMENTAL_REVIEW.md:3-4`、`TASK-201_INDEPENDENT_REVIEW.md:3,304`。业务 Python 无该类问题。
- 没有未暂存的业务代码；本审核仅产生本报告及临时隔离实例证据。实现修改了 Runtime API / Trace 生产行为，属于正式任务范围；未发现对固定 Route 或 `IntentResult` 字段的变更。

## 2. 隔离 MySQL 8 真实环境

使用本机 MySQL Community Server **8.0.32** 新建 datadir，监听 `127.0.0.1:13358`，从未连接 3306 或任何生产库。新建的唯一测试库为：

- `ai_coach_task201_test_task103_audit`：`MYSQL_CONFIG_TEST_DATABASE_URL=mysql+asyncmy://root@127.0.0.1:13358/ai_coach_task201_test_task103_audit`
- `ai_coach_task002_test_task103_audit`：`MYSQL_TEST_DATABASE_URL=mysql+asyncmy://root@127.0.0.1:13358/ai_coach_task002_test_task103_audit`

先以 `DATABASE_URL=$MYSQL_CONFIG_TEST_DATABASE_URL` 执行：

```text
uv run --locked --extra dev python -m alembic upgrade head
MIGRATION_EXIT=0
0001_initial_schema -> 0002_release_fp_index -> 0003_model_timeout_double
```

因此本次不是 SQLite、Mock DB，也不是跳过 MySQL 的验收。

## 3. 实测 MySQL / Trace 结果

执行：

```text
uv run --locked --extra dev pytest -q -rs \
  tests/test_task103_mysql.py tests/test_config_mysql.py \
  tests/test_task201_interface_mysql.py tests/test_mysql_integration.py
```

结果为 **14 passed, 1 failed, 0 skipped**。失败用例为：

```text
tests/test_task103_mysql.py::test_runtime_api_mysql_end_to_end
pydantic ValidationError: credential_ref="qwen_api_key"
does not match ^[A-Z_][A-Z0-9_]*$
```

其中第一个 TASK-103 MySQL 用例实际通过，证明了局部链路：本地 HTTP Provider 的一次 500 后重试对应两条 `LLMCallTrace`，第二次成功调用合计三条 Attempt；相同 upstream `request_id` 写入两条不同 `trace_id`；请求 Trace 含 Release/Model hash、snapshot、retry count。这是有价值的局部证据，但不构成 TASK-103 整体验收通过。

失败原因具备可复现性且是代码/测试契约不一致：`backend/app/schemas/config.py:124` 只允许大写环境变量名，而 `backend/tests/test_task103_mysql.py:136` 写入小写 `qwen_api_key`；`backend/app/main.py` 又只对该不可创建的小写引用使用 `Settings.qwen_api_key` 分支。因此正式 ASGI Runtime → Loader → Provider → DB Trace E2E 尚未跑到 HTTP/Trace 断言。

## 4. 必须项逐项结论

| 项目 | 结论 | 独立证据 / 原因 |
|---|---|---|
| 请求级与 Attempt 级写库 | 部分 PASS | 真实 MySQL 首个 TASK-103 用例通过，且验证物理 HTTP 3 calls / DB Attempt 3 rows。|
| 正常 Runtime API 与 Trace 一致 | FAIL | 唯一 Runtime API MySQL E2E 在创建 Model Config 前失败。|
| retry = 真实物理 HTTP Attempt | PASS（局部） | 同上，真实 localhost HTTP、非 SDK method mock。|
| Trace 写入故障 rollback | 未验收 | 没有对 MySQL insert/attempt/commit 的 fault injection；仅有失败 Sink mock。|
| Runtime Trace 失败 fail-open | 未验收 | `test_task103_contract.py` 只直接调用私有 `_persist_success` 且使用 mock Sink，不是数据库 Runtime 链路。|
| Debug/Replay/Evaluation fail-closed | 未验收 | 同为私有方法 mock；且对应 Admin execution 端点尚不存在。|
| 重复 request_id | PASS | 真实 MySQL 用例验证两个不同 trace_id、无冲突。|
| Active Release A→B Provider/Trace provenance | 未验收 | 已有 TASK-201 用例使用 `InMemoryTraceSink` 和自定义无 TTL Loader；没有 DatabaseTraceStore + DatabaseRuntimeConfigLoader 的切换实测。|
| pool wait / SQL / commit 取消与释放 | 未验收 | 无真实 MySQL 取消阶段测试；不能用现有 Provider cancellation 测试替代。|
| 不吞 CancelledError、不虚报持久化 | 未验收 | 无实际数据库 cancellation/commit 证据。|
| validation_issues UTF-8 限长、脱敏、真实 DB | 未验收 | 单元测试证明 `TraceRecord` 拷贝限长，但失败的 Runtime E2E 没有走到 DB，也没有 DB 查询 `validation_json` 字节数/敏感信息。TASK-102 遗留 P2-2 不能据此关闭。|
| retention 不误删 Evaluation 关联数据 | 未验收 | `cleanup_expired_traces` 有实现但没有 TASK-103 MySQL Evaluation-link 测试。|

## 5. Runtime API、Loader、C10/C13/C14 审核

- `POST /api/v1/intent/analyze` 有请求体、text、context 限制；公开成功模型字段集合不包含 prompt/raw/reason/evidence。无 DB 的 Contract 用例覆盖 Route-only/空 intents 的核心 `IntentService` 既有契约，错误映射 C13 的模拟 API 用例通过。
- 无 Active Release 时 Loader 返回 `CONFIG_NOT_READY`，且 `/ready` 不要求 Active Release 的已有 MySQL 回归通过；`status/summary.runtime_config_ready` 的局部回归通过。
- **C10 不通过代码复核。** `backend/app/db/readiness.py` 仍以手写 `REQUIRED_BUSINESS_COLUMNS` 和 SQL 中手写表名列表检查 schema；`docs/10 §5` 与项目约束要求由 SQLAlchemy metadata 推导，且一次查询。即使现有缺表/缺列测试在 MySQL 上通过，该实现仍违反 C10 的“不得手写表/列清单”约束。
- **C14 未被真实 DB 验收。** 实现具有 runtime `fail_open` / 非 runtime fail-closed 分支，但唯一测试用失败 Sink mock，不能证明事务 rollback、错误传播、或数据库写入失败时实际响应。
- Loader 每次读取 active id、再以 TTL 缓存重载 Release 的结构符合目标；但 A→B 使用真实 Loader/Provider/Trace 的端到端测试缺失，故不可标为 PASS。

## 6. 全量门禁

在 `backend/`、上述两个隔离 URL 已配置时实测：

```text
uv run --locked --extra dev ruff check .
All checks passed!
exit 0

uv run --locked --extra dev ruff format --check .
63 files already formatted
exit 0

uv run --locked --extra dev pytest -q -rs
exit 1
```

为避免 30 秒窗口丢失退出码，最后一条由受控本地 `cmd /v:on` 进程运行并在结束后写回动态 `!errorlevel!`；真实退出码是 **1**。`--collect-only` 统计 175 项；完整运行有 1 个上列失败、174 个通过、0 skip，另有 1 个既有 Starlette/httpx deprecation warning。故全量门禁 FAIL。

## 7. 问题分级与最小复现

### P1-1：TASK-103 真实 Runtime E2E 不可运行

最小复现：配置上述 `MYSQL_CONFIG_TEST_DATABASE_URL` 后执行：

```text
uv run --locked --extra dev pytest -q -rs tests/test_task103_mysql.py::test_runtime_api_mysql_end_to_end
```

预期进入 Runtime HTTP 与 Trace 查询；实际在 `ModelConfigCreate` 因小写 `credential_ref` 报 ValidationError。修复须统一 `credential_ref` 的 schema、`credential_resolver` 和测试：选择合法大写环境引用并安全注入局部 credential，或正式改变 schema/契约；不能绕过校验。

### P1-2：C10 metadata 推导硬约束被违反

最小复现：审阅 `backend/app/db/readiness.py` 的 `REQUIRED_BUSINESS_COLUMNS` 与手写 `IN (...)` 表名单。修复须从 SQLAlchemy `Base.metadata` 导出 required tables/columns，再进行一次 information_schema 查询；补真实 MySQL 缺表、缺列回归。

### P1-3：数据库核心验收覆盖缺口

最小复现：检索 `backend/tests/test_task103_mysql.py`。其中仅两个用例，不含 Trace transaction rollback、Runtime DB fail-open、Debug/Replay/Evaluation DB fail-closed、pool/SQL/commit cancellation、validation_json bytes/redaction、retention Evaluation link 或真实 A→B provenance。修复后必须在隔离 MySQL 8 对每项加入真实 DB 测试，不能用 mock Sink、SQLite 或 skip 代替。

### P2（继续记录）

- 第二 Provider 前仍须解除 `IntentService` 对 `app.providers.qwen.ProviderError` 的具体耦合。
- `REAL_QWEN_SMOKE=UNVERIFIED`：本会话确认 `DASHSCOPE_API_KEY`、`QWEN_API_KEY`、`qwen_api_key` 均未配置；未执行真实模型调用。localhost HTTP 不是 Qwen smoke。
- staged Markdown 的 whitespace 问题不阻断 Runtime 行为，但应在后续报告整理时清除。

## 8. DoD 与放行结论

TASK-103 DoD 要求生产主链可通过 HTTP 调用、正常持久化 execution 可查询 Trace，并完成规定的 fail-open 语义。当前真实 Runtime HTTP MySQL 用例失败、全量 pytest exit 1，且多项明确要求的数据库事务/取消/retention 验收没有测试证据。

**最终：FAIL。** 不允许启动 TASK-202。定向修复并在全新的隔离 MySQL 8 库复跑上述 MySQL 矩阵和完整三条门禁后，才可重新独立审核。

外部资料：本审核未参考外部资料；仅依据 `AGENTS.md`、`tasks/README.md`、TASK-103、`docs/03/06/07/10`、提交的执行/既有审核报告与当前实现/测试。
