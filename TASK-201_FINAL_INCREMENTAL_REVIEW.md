# TASK-201 最终增量复核与接口联查

日期：2026-10-13  
审核结论：**TASK-201：PASS**  
接口结论：**TASK-102/201 INTERFACE GATE：PASS**

本次为独立复核：只增加本报告，未修改业务代码、测试、既有审核产物或暂存内容，未启动 TASK-103。

## 1. 基线与工作区

| 项目 | 实际观测 |
|---|---|
| 审核时 HEAD | `053d885` (`docs(task201): record P1 fixes and independent rereview gate`) |
| 被复核修复提交 | `fceafde` |
| 原 TASK-201 实现提交 | `ead771e` |
| 实际差异 | `ead771e..fceafde`：47 files，1,665 insertions / 122 deletions；`git diff --check` exit 0 |
| 审核前既有工作区 | `TASK-102_FINAL_INDEPENDENT_REVIEW.md` 已暂存；`TASK-201_INDEPENDENT_REVIEW.md` 未跟踪；均未改动 |
| 本报告写入后预期额外变更 | 仅本文件未跟踪 |

已阅读 `AGENTS.md`、`tasks/README.md`、TASK-201 正式任务书、docs/03/06/07/10、`TASK-201_INDEPENDENT_REVIEW.md`、`TASK-201_P1_FIX_REPORT.md`、`TASK-102_FINAL_INDEPENDENT_REVIEW.md`，以及 Config Schema/Service、Provider/Factory、IntentService、0003 migration/audit、Admin API、Vue client 与相关测试。

环境为新建临时 datadir、仅监听 `127.0.0.1:13346` 的 MySQL Community Server **8.0.32**；测试库均使用 `ai_coach_task201_test_*` / `ai_coach_task002_test_*` 前缀。未连接既有 3306 数据库，未以 SQLite 或 SDK method mock 替代 MySQL/HTTP 验证。

## 2. 先复现原 P1 负例

在临时 worktree 的原提交 `ead771e` 上，使用真实隔离 MySQL/API 与 localhost HTTP server 独立复现：

| 原问题 | 实际复现 |
|---|---|
| P1-1 Publish Token 可绕过 | 获取 Summary 后修改 Draft，再以只含 `default_model_config_id`/`note` 的真实 `POST /api/admin/releases` 发布，旧 API 返回 **201**，Release snapshot 确实包含未经审阅的改动。 |
| P1-2 0003 存量升级 | 构造被 Active Release 引用的旧 FLOAT `30.123456789` 与原 hash；旧 0003 `upgrade head` 返回 **0**、版本被标为 0003，但模型 hash 已无法重建。 |
| P1-3 双重真相源 | Loader 返回 B、静态 Provider 绑定 A 时，旧 IntentService 向真实 localhost HTTP server 发出 **A** 的模型请求，同时 Trace 的 model ID 为 **B**。 |

原负例的临时 probe 均在隔离 worktree 外执行，不修改项目工作区或已有审核证据。

## 3. P1-1：Publish Summary Token — PASS

`PublishInput` 现在要求 `expected_draft_hash` 为严格小写 64 位 hex，且 `expected_active_release_id` 必须显式出现；其类型允许 `null`，因此首个 Release 仍须明确提交 `null`。`publish()` 在同一 state lock 内无条件校验两项 token，且 `/api/admin/releases` 是唯一 API publish 路径；搜索未发现绕过该 Service 校验的发布入口。前端 `configApi.publish(summary, note)` 使用当前 `PublishSummary` 的两个值。

真实 MySQL + ASGI API 回归：

```text
tests/test_task201_interface_mysql.py::test_publish_missing_and_stale_confirmations_are_atomic
1 passed in 0.86s
```

该用例实际验证：省略任一 token 返回 422；Summary 后 Draft 改变返回 `409 DRAFT_CONFLICT`、Release 列表仍为空且 Active 仍为 null；同一 Summary 的 8 个并发 publish 仅 1 个 201，其余 7 个因 Active 已变返回 `409 RELEASE_CONFLICT`，仅产生一个 Release/Active 切换；重新获取 Summary 后可正确发布。`tests/test_task201_p1.py` 的 Schema、固定 Provider/Loader、缓存与变异 Loader 负例亦随接口定向集通过。

## 4. P1-2：Alembic 0003 存量升级安全 — PASS（生产存量未审计）

`config_audit.audit_configuration()` 对每条存量 Model 重建 runtime hash，并对每条 Release 重建 Business hash、冻结 Model hash、fingerprint、引用与 Active enabled 状态。任一不一致 fail-closed，不重写历史 hash。`alembic/env.py` 在所有 online migration（包括已在 head 的 `upgrade head`）前审计；0003 自身也在 DDL 前审计，offline 0003 拒绝执行。

真实 MySQL 8 定向结果：

```text
legacy high-precision FLOAT / re-entry / offline cases: 5 passed in 12.59s
already-head corruption and missing-table cases:       7 passed in 17.73s
```

覆盖的正反例包括：

- `30.123456789`、`0.123456789`、`599.9999999` 的旧 FLOAT hash 损失（含 Active Release）均在 DDL 前拒绝；revision 保持 0002、FLOAT 列未变、无临时列。
- 正常 `30.1` 存量可升级，hash 保持；临时 upgrade column 中断、最终 atomic swap 后未标记 head、重复 `upgrade head` 均可恢复。
- 已处 0003 head 的 Model、Business hash、Release Model hash、fingerprint、引用、Active 和缺表损坏均被重复审计拒绝，数据库行不被修改。
- DOUBLE 精度无法安全窄化回 FLOAT 时 downgrade 被拒绝。

运维 Runbook 已给出停写、备份/隔离克隆、`python -m app.db.config_audit` 和不可恢复 FLOAT 历史的处理方式：不猜测或重算历史 hash；无可验证备份时原地升级应阻断。**未对任何生产存量库执行审计，因此“生产升级已验证”仍为 UNVERIFIED，不能作此宣称。**

## 5. P1-3：TASK-102/201 接口联查 — PASS

以下是实际 MySQL 发布、数据库 Loader、`ModelProviderFactory`、真实 localhost HTTP server 和 TraceSink 的完整链路，不是 mock `Provider.invoke`：

```text
tests/test_task201_interface_mysql.py::test_active_switch_uses_effective_model_on_real_http_and_keeps_provenance
1 passed in 3.40s
```

观测结果：

| 请求 | 实际 HTTP | Attempt 数 | Trace provenance |
|---|---|---:|---|
| A（切换前已在途） | `model-a`, `temperature=0.1`, `top_p=0.8` | 1 | Release A、Business hash、Model A ID/hash、Fingerprint、A snapshot 均匹配 |
| B（Active 切换后） | 两次均为 `model-b`, `temperature=0.9`, `seed=123`；无 A 的 `top_p`、无 `max_tokens` | 2（一次真实 500 后 Provider retry） | Release B、Business hash、Model B ID/hash、Fingerprint、B snapshot 均匹配 |

Provider SDK `max_retries=0`，B 的两个物理 HTTP 请求对应 Attempt 1/2；历史 A 请求的 Trace 没有被 Active B 切换改写。Factory 缓存键为 `(model_config_id, verified_model_config_hash)`，同 ID 但变更 hash 会创建新 client；旧 ID/hash 或被篡改 snapshot 不会复用错误 Provider，而是在 HTTP 前返回 `CONFIG_NOT_READY`。固定 Provider 与 Loader snapshot 不一致同样在 HTTP 前拒绝。

此结论仅覆盖 TASK-102/201 的 Release→有效 Model snapshot→Provider→内存 Trace 边界。TASK-103 的 Runtime API、TTL loader 和 DB TraceStore 尚未实现，按任务边界不作为本项缺陷。

## 6. 回归结果

后端（`backend/`，隔离 MySQL 环境变量已配置）：

```text
uv run --locked --extra dev ruff check .
All checks passed!

uv run --locked --extra dev ruff format --check .
57 files already formatted

uv run --locked --extra dev pytest -q -rs
160/160 completed, [100%], no failures
```

收集确认：`160 tests collected in 0.12s`。全量运行仅保留既有 Starlette/httpx deprecation warning。MySQL 专项完整集曾实际运行；可见定向结果为 Config/MySQL 8 passed、P1/interface 14 passed、migration audit 12 passed。

前端（`frontend/`）：

```text
npm run lint    -> exit 0
npm run test    -> 2 files / 7 tests passed
npm run build   -> exit 0 (仅既有 >500 kB chunk warning)
npm run format  -> all matched files use Prettier code style
npm run test    -> 2 files / 7 tests passed
CONFIG_E2E_DATABASE_URL=<isolated MySQL> npm run test:e2e
1 passed (11.6s)
```

E2E 真实经过 Vite → FastAPI → 隔离 MySQL；无 API route mock。首次 E2E 因目标空数据库尚未创建而迁移失败；创建显式隔离目标库后重跑通过，不是产品断言失败。

## 7. 剩余问题、Qwen 与后续门禁

| 级别 | 状态 | 项目 |
|---|---|---|
| P0 | 无 | 无 |
| P1 | 无 | 三项原 P1 均已独立关闭 |
| P2 | 开放 | TASK-102：`validation_issues[].slot.value` 诊断副本可无界；必须在 TASK-103 **DB Trace 持久化前**修复并用真实 DB Trace 回归。 |
| P2 | 开放 | `IntentService` 对 Qwen `ProviderError` 的具体类型耦合；新增第二 Provider 前修复。 |
| P2 | 开放 | `params_json` 数值等价 hash（如 `0`/`0.0`）尚未定义归一化策略。 |
| P2 | 开放 | `/ready` metadata 推导为既有非阻断问题。 |

未配置或读取真实 Qwen 凭据，未发起外部模型调用；**REAL_QWEN_SMOKE=UNVERIFIED**。localhost HTTP 验证不能替代账户、地域、模型和 strict schema 的真实 Qwen smoke。

外部资料：本轮未依赖新的外部资料；结论仅基于项目 Contract、实际代码、MySQL 8.0.32、锁定依赖与本地 HTTP/浏览器实测。未引用第三方 classifier/retry 实现，因其不构成本项目验收依据。

## 8. 最终决定

- **TASK-201：PASS。** 原 P1-1/P1-2/P1-3 已复现旧负例，并在修复提交上以真实 MySQL/API/HTTP 验证关闭；TASK-201 可以关闭。
- **TASK-102/201 INTERFACE GATE：PASS。** 这是独立于 TASK-201 结论的接口门禁；本次也单独通过，不能由 TASK-201 的 PASS 自动推导。
- **TASK-103：可在本门禁通过后开始，但其 DB Trace 持久化实现前必须先关闭 TASK-102 的 `validation_issues` 长度 P2，并用真实异步 DB TraceSink 验证取消、rollback/连接释放和持久化边界。** 第二 Provider 开始前还必须解除 ProviderError 具体类型耦合。不得把未实现的 TASK-103 TraceStore 追溯为 TASK-201 缺陷。
