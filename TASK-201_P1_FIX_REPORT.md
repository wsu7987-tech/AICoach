# TASK-201 P1 定向修复执行报告

日期：2026-10-13。状态：**三个 P1 已完成执行方修复与自验，TASK-201 待独立复审**。原独立审核结论仍为 FAIL，执行方不自行改签 PASS。不开始 TASK-103。

## 1. 基线、范围与提交

- 开始 HEAD：`18256ec3148eafc628588ea743f1692fb4a37127`；原实现：`ead771eb0f24af276d9bd9ad4b4aa23674424a87`；TASK-102 代码基线：`b34627f1395d5eaa419a5cc5130a7ec61208111f`。
- 本轮实现/测试/运行证据提交：`fceafdedea2ef3fb6e9127f1ef17e71ccf7bfb7d`。
- 本报告与 PROJECT_STATUS 在后续独立文档提交中交付；其 SHA 可用 `git log -1 -- TASK-201_P1_FIX_REPORT.md` 查询。
- 开始时既有 `TASK-102_FINAL_INDEPENDENT_REVIEW.md` 已暂存，`TASK-201_INDEPENDENT_REVIEW.md` 未跟踪。两者原样保留，未加入本轮提交；原 TASK-201 执行报告与既有审核探针未修改。
- 已读 AGENTS、tasks/README、正式 TASK-201、docs/03/04/06/07/09/10、两份独立审核与执行报告，以及 Provider/IntentService、ConfigService、ORM/Alembic、Admin/Vue/API client/相关测试。
- 本轮收到的任务正文在 P1-2 第 11 条截断，已请求补充；未收到余文。本报告以已明确要求及独立审核中的 P1-1/P1-2/P1-3 为修复范围，不推定未收到的额外验收要求已满足。

## 2. 先复现，再修复

开始时执行 `uv run --locked --extra dev pytest -q -rs`：既有 134 项中 124 通过、10 个 MySQL 项因环境变量未设置跳过。随后启动全新隔离 MySQL 8，最终验收没有跳过项。

实现修复前实际运行的新反例：

```text
uv run --locked --extra dev pytest -o addopts='' -q tests/test_task201_p1.py
FFFFF
5 failed, 1 warning in 1.84s
```

四个缺失/null token 用例均 `DID NOT RAISE ValidationError`；固定 Provider A + Loader B 用例真实 localhost POST 200，未抛预期配置错误，复现了错误调用能够静默继续。

```text
uv run --locked --extra dev pytest -o addopts='' -q --tb=short tests/test_task201_migration_audit.py
FFF
AssertionError: corrupt legacy hash incorrectly upgraded to head
3 failed, 1 warning in 6.34s
```

三个实际 MySQL FLOAT 输入为 `30.123456789 / 0.123456789 / 599.9999999`，均建立真实 Model、引用它的历史 Release 和 Active 指针。原迁移均返回 0。初次构造该测试时补齐了 SQL 必填时间戳，以上输出来自有效旧库样本，不是 fixture 创建错误。

## 3. P1-3：有效 Model、Provider 与 Trace

唯一调用依据是每次 Loader 返回并重新校验的 `RuntimeConfiguration.model_config_snapshot`。`verified_model_snapshot()` 重新解析已构造实例，按正式 ModelConfigCreate 校验并重建 canonical runtime hash；Service 独立复制 Business/Model Snapshot，核对 Business Hash、Model Hash 和 Release Fingerprint，避免请求之间共享可变对象。

`ModelProviderFactory` 只支持当前 Qwen，按 `(Model Config ID, verified Hash)` 缓存，不依赖显示名或 ID 单字段；传入 Secret 逻辑引用解析函数。缓存最多 128 项，满时 SERVICE_BUSY 503，绝不回退旧 Provider；需按版本规模配置容量。每个进程/事件循环共享一个工厂，应用排空请求后 `await close()` 关闭客户端。凭据轮换需要重建客户端/滚动重启。这是最小装配边界，不是服务注册框架。

QwenProvider 保存构造参数的独立副本，公开 model_config 返回副本，防止调用参数被外部修改而 SDK timeout/base_url/semaphore 仍停留旧值。固定 Provider 兼容注入必须匹配有效 ID/Hash；否则在 HTTP 前 CONFIG_NOT_READY 503，零 Attempt。未修改 retry 循环、SDK `max_retries=0`、队列等待、取消传播、Attempt 或 sanitizer 处理逻辑。

`RuntimeConfiguration.from_release()` 承载 `release_id/config_snapshot_hash/model_config_hash/release_fingerprint`；Trace 同时记录上述字段、`model_config_id`（effective ID）及完整非 Secret `model_config_snapshot`。每次请求固定自身 provenance，不因 Active 切换重写在途/历史请求。

真实 MySQL + HTTP 联查 `test_active_switch_uses_effective_model_on_real_http_and_keeps_provenance`：

1. 发布 A，HTTP 收到 `model-a, temperature=0.1, top_p=0.8`，保持请求在途。
2. 发布 B 并切换 Active，随后的 HTTP 收到 `model-b, temperature=0.9, seed=123`，没有 A 的 top_p，没有 max_tokens。
3. B 服务端先 500 再成功：总 HTTP=3，A Attempt=1、B Attempt=2；SDK retry=0，两条 B Attempt 编号为 1/2。
4. A、B Trace 分别核对真实发布记录的全部 Hash/ID/Fingerprint/Model Snapshot；SDK timeout 与有效配置相同，并发 permit 释放后恢复配置数量。

另有缓存身份、显示元数据不影响身份、配置/返回视图隔离、损坏 Hash、容量和关闭、Loader 实例变异、固定 Provider 不匹配等反例。没有用模拟 SDK create() 证明调用参数。DB Loader 仅存在于测试内部；未实现 TASK-103 TTL Loader、正式 Runtime API 或 DB TraceStore。

## 4. P1-2：迁移前与已 head 的存量审计

`app.db.config_audit` 为只读、可重复命令。遍历每条 Model（包括未引用/disabled 版本）重建正式 runtime payload Hash；每条 Release 验证 Business Snapshot/Hash、Model 引用、冻结 Model Hash、Fingerprint；同时检查 Active 引用。错误只报告行 ID/类别，任一错误 fail-closed，不重签/覆盖历史值。

Alembic 在线入口在任何迁移操作前审计，之后结束只读 autobegin，再由 Alembic 管理事务。0003 在自身 DDL 前也审计；已有 DOUBLE 的中断恢复分支不能跳过。已处于 0003 head 再执行 `upgrade head` 同样审计，不依赖新增 revision 才触发。配置表缺失也拒绝。离线 0003 upgrade 拒绝执行。Schema 没有新变化，head 仍为 `0003_model_timeout_double`。

MySQL 回归证明：三个有损 FLOAT + Active 样本连续两次升级均拒绝，revision 保留 0002、原列仍 FLOAT、未新增临时列；已 head 的 Model/Business/冻结 Model Hash/Fingerprint/引用/Active 六类损坏连续审计均拒绝，逐表前后数据完全一致。覆盖 nullable 临时列中断、原子列交换后但尚未更新 head 的中断、重复 upgrade、30.1 历史 Hash 不变、高精度 DOUBLE 有损 downgrade 拒绝、缺表、离线绕过拒绝。

[Runbook](docs/TASK-201-0003-审计与恢复Runbook.md) 明确要求维护窗口停写、备份与隔离克隆演练：MySQL DDL 隐式提交，整个迁移不能依赖事务 rollback；本实现不是在线并发迁移屏障。丢失的 FLOAT 精度不能猜回，也不能通过新增替代 Release 消除历史损坏。没有可验证备份时原地升级保持 BLOCKED；只能另行审批保留旧库只读档案、在新库导入确认配置并新发布，禁止自动改写旧历史。本轮未执行生产审计/恢复。

## 5. P1-1：强制发布审阅与原子拒绝

`POST /api/admin/releases` 的 `expected_draft_hash` 改为必填小写 64 位 Hash，`expected_active_release_id` 为必须显式出现、允许 null 的字段。Service 重新解析请求，在统一 state 锁内无条件比较两个 token；锁定读显式刷新 Session 已缓存的 Draft/Model，避免 stale ORM 对象绕过。

真实 API/MySQL：缺任一 token 为 422；Summary 后编辑 Draft 为 409 DRAFT_CONFLICT，Release 数为 0、Active 仍 null；8 个同一审阅确认并发请求只有 1 个 201、其余 7 个 409 RELEASE_CONFLICT，只有一条 Release；重新获取摘要后同内容再发布成功，新 ID、同 Fingerprint。额外覆盖同一 Session 缓存旧 Draft 后的并发编辑拒绝。

Vue 已发送两个 token，无需重写页面；API client 测试补充首次 `active=null` 也显式发送字段。Runtime API Contract 不变，仅收紧 Admin 发布输入并同步 docs/06。C19–C21 已加入 docs/10。

原 MySQL 成功路径仍保留 8 次并发事务在每次获取锁后读取新摘要的压力验证；新增独立 API 竞争用例专门验证共用过期摘要只能一个成功。原负例仍实际进入 publish 检查 disabled/corrupt Model，未挪成只测 Summary。TASK-002 旧迁移 fixture 改为正式可审计数据，迁移前 Fingerprint 保存后逐值比较；未放宽历史不变断言。

## 6. 实际环境与命令输出

原始最终输出在 [task_artifacts/task201_p1](task_artifacts/task201_p1)。文本从 PowerShell UTF-16 转成 UTF-8，保留 warnings，去除行末空格。所有下述最终命令退出 0。

隔离 MySQL Community 8.0.32，独立 datadir：`C:\Users\su\AppData\Local\Temp\aicoach-task201-fix-704caa1439a94af8b7ecfed019707132`，仅监听 `127.0.0.1:13336`；未连接既有 3306/生产资源。无 SQLite 替代。测试结束按 PID/datadir/port 核验后 mysqladmin normal shutdown，13336 无监听，停止后的 datadir 保留。

在 backend 执行：

```powershell
$env:MYSQL_CONFIG_TEST_DATABASE_URL='mysql+asyncmy://root@127.0.0.1:13336/ai_coach_task201_test_p1'
$env:MYSQL_TEST_DATABASE_URL='mysql+asyncmy://root@127.0.0.1:13336/ai_coach_task002_test_p1'
uv run --locked --extra dev ruff check .
uv run --locked --extra dev ruff format --check .
uv run --locked --extra dev pytest -q -rs
```

```text
All checks passed!
57 files already formatted
........................................................................ [ 45%]
........................................................................ [ 90%]
................                                                         [100%]
```

全量 160 项通过、0 skip、1 条既有 Starlette/httpx deprecation warning。项目默认 addopts=-q 使以上命令不显示总数，`pytest --collect-only -q` 实测为 `7+5+30+8+25+30+1+2+5+21+3+12+11=160`，收集输出已保存。

```text
uv run --locked --extra dev pytest -o addopts='' -q -rs tests/test_config_mysql.py tests/test_mysql_integration.py tests/test_task201_interface_mysql.py tests/test_task201_migration_audit.py
.........................                                                [100%]
25 passed, 1 warning in 52.20s
```

独立命令在真实浏览器使用过的干净 head 库执行：

```text
DATABASE_URL=mysql+asyncmy://root@127.0.0.1:13336/ai_coach_task201_test_browser_p1
uv run --locked --extra dev python -m app.db.config_audit
{"status": "PASS", "models": 1, "releases": 3}
```

C7/C9 保留在 `test_config_contract.py`、`test_config_mysql.py`：构造后变异重验、同内容重复发布、回退新 ID/同 Fingerprint、历史不变、事务回滚均通过。

额外 TASK-102 历史兼容探针：

```text
uv run --locked --extra dev python ../task_artifacts/task201_p1/run_legacy_probes.py
TASK-102 assertions unchanged; valid credential/hash fixtures; cancel_params at Provider boundary.
................................                                         [100%]
32 passed in 27.26s
```

这是**适配后执行回归，不是原文探针/独立复核 PASS**。原文件不改；临时副本将旧假 Hash、`env/` 逻辑引用改成正式合法 fixture。原 cancel_params 使用 TASK-201 禁止的 `params.user`：首次适配运行 31 passed/1 failed，失败发生在配置 allowlist。最终该项在 Provider 边界直接真实 HTTP invoke，保留原取消及诊断脱敏断言；其他项仍走 Service。所有测试断言保持，适配代码可审核。正式后端 21 项 Provider + 25 项诊断测试另已全部通过。

前端（frontend）：

```text
npm run lint
> vue-tsc --noEmit

npm run test
Test Files 2 passed (2)
Tests 7 passed (7)

npm run build
✓ 1604 modules transformed.
dist/assets/index-Bkx1H3lf.js 1,050.27 kB
✓ built in 4.79s

npm run format
All matched files use Prettier code style!

CONFIG_E2E_DATABASE_URL=mysql+asyncmy://root@127.0.0.1:13336/ai_coach_task201_test_browser_p1
npm run test:e2e
ok 1 ... real MySQL configuration: bootstrap, dynamic intent, publish, history and rollback
1 passed (12.9s)
```

Playwright 实际 Vite→FastAPI→MySQL，无 API route mock。保留 >500 kB chunk、NO_COLOR/FORCE_COLOR 与 PowerShell stderr 包装提示。首次 frontend format 检出新增参数化测试格式，Prettier 修正后最终通过。未把后端 ASGI 冲突验证冒充浏览器错误交互 E2E。

## 7. 修改文件

实现/测试/文档（相对于本轮基线）：

```text
backend/alembic/env.py
backend/alembic/versions/0003_model_timeout_double.py
backend/app/db/config_audit.py
backend/app/providers/factory.py
backend/app/providers/qwen.py
backend/app/providers/types.py
backend/app/schemas/config.py
backend/app/services/config_service.py
backend/app/services/intent_service.py
backend/tests/test_config_mysql.py
backend/tests/test_mysql_integration.py
backend/tests/test_provider_contract.py
backend/tests/test_task201_interface_mysql.py
backend/tests/test_task201_migration_audit.py
backend/tests/test_task201_p1.py
frontend/src/configApi.test.ts
docs/06-API与数据结构设计.md
docs/10-契约不变量与验收样例.md
docs/TASK-201-配置接口与验收运行.md
docs/TASK-201-0003-审计与恢复Runbook.md
PROJECT_STATUS.md
TASK-201_P1_FIX_REPORT.md
```

证据目录的全部文件：`audit-clean-head.txt`、`frontend-build.txt`、`frontend-e2e.txt`、`frontend-format.txt`、`frontend-tests.txt`、`frontend-types.txt`、`mysql-explicit.txt`、`mysql-shutdown.txt`、`mysql-version.txt`、`pytest-collection.txt`、`pytest-full.txt`、`ruff-check.txt`、`ruff-format.txt`、`run_legacy_probes.py`、`task102-compat-probes.txt`。

## 8. DoD 与交接

| 项目 | 执行方结论 | 证据/限制 |
|---|---|---|
| P1-3 有效配置选择 Provider、完整 provenance | PASS | 真实发布 A→B + localhost HTTP；历史请求归属不变 |
| P1-3 retry/timeout/Attempt/cancellation/sanitizer 回归 | PASS | 正式 46 项、适配历史探针 32 项、实际 B retry=1 |
| P1-2 旧库/已 head 全量审计、失败不改历史 | PASS | 12 项新增 MySQL 审计用例 + 原迁移恢复/降级用例 |
| P1-2 生产存量分布与恢复演练 | UNVERIFIED | 未访问生产；Runbook 已交付，无可信恢复来源时原地升级 BLOCKED |
| P1-1 必填 token、过期拒绝、并发原子性 | PASS | Schema/真实 API/Session 缓存反例；同内容重发仍可成功 |
| C7/C9、原 TASK-201 Draft/Preview/版本/历史/回退 | PASS | 全量 160、显式 MySQL 25、真实 E2E |
| 前端类型/构建/组件/API/主流程 | PASS | 7 个测试 + 1 个真实浏览器流程 |
| 独立复审 | 待执行 | 交由 5.6 Sol；执行方不自签 |
| TASK-102/201 定向接口自验 | PASS | 本报告 §3；独立接口联查门禁仍待验收 |
| TASK-103 开始前置 | BLOCKED | 当前禁止开始 |

继续保留：TASK-102 P2-2 `validation_issues[].slot.value` 无界（DB Trace 接入前修复）；P2-1 Provider-neutral Error 耦合（新增 Provider 前修复）；`REAL_QWEN_SMOKE=UNVERIFIED`。本地真实 HTTP 不是 Qwen 账户/地域/完整 Schema 的真实服务验收。

本轮不扩展修复独立审核其他 P2：params 数值等价 canonicalization；浏览器真实 Draft/Active disable 冲突和字段定位缺口；既有 readiness metadata 推导债。Admin 公网隔离仍由部署门禁负责。生产迁移必须停写，客户端工厂须按文档关闭与规划容量；未实现任何 TASK-103 模块。

外部依据仅参考 MySQL 官方 [Implicit Commit](https://dev.mysql.com/doc/refman/8.0/en/implicit-commit.html)、[Atomic DDL](https://dev.mysql.com/doc/refman/8.0/en/atomic-ddl.html)，以本仓库 Contract 与实际 MySQL 8.0.32 行为优先。未采用第三方 classifier/Agent/Tenacity 方案；未改 Structured Output 协议/SDK 重试策略，未读取真实 Key 或调用外部 Qwen。

交付后停止在 TASK-201，等待独立复审及接口联查结论。
