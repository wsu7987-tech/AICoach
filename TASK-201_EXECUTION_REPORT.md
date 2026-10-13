# TASK-201 正式执行报告

日期：2026-10-13。状态：**待独立复核**。完成正式任务书的后端与 Vue 配置中心范围，以下 PASS 均为执行方自验，不能代替 5.6 Sol 独立复核及后续 TASK-102/201 接口联查。未开始 TASK-103。

## 1. Git 基线与提交

| 项目 | 值 |
|---|---|
| TASK-102 代码基线 | `b34627f1395d5eaa419a5cc5130a7ec61208111f` |
| 开工 HEAD / 分支 | `65ccd56b4d7f0410649d1fb0ab21105c476420d0` / main |
| 本次实现 Commit | `ead771eb0f24af276d9bd9ad4b4aa23674424a87` |
| 提交范围 | 29 个实现/测试/接口说明文件；报告、门禁原始输出及 PROJECT_STATUS 单独跟随提交 |
| 既有工作区内容 | `TASK-102_FINAL_INDEPENDENT_REVIEW.md` 已暂存；未修改、未纳入 TASK-201 commit，保留原暂存状态 |

开工已核对审核结论为 CONDITIONAL PASS、明确允许 TASK-201。阅读 AGENTS、tasks/README、正式 TASK-201、docs/03/04/06/07/09/10、最终独立审核、既有 SQLAlchemy/Alembic/Bootstrap、Snapshot/PromptBuilder、Provider/IntentService 和 Vue 工程。未修改既有审核材料、TASK-102 Provider 或 TraceSink。

## 2. 实际修改文件

实现提交的完整文件清单：

```text
.gitignore
backend/alembic/versions/0003_model_timeout_double.py
backend/app/api/admin/config.py
backend/app/api/admin/router.py
backend/app/db/models.py
backend/app/main.py
backend/app/schemas/config.py
backend/app/schemas/intent.py
backend/app/services/config_service.py
backend/scripts/config_e2e_server.py
backend/tests/test_config_contract.py
backend/tests/test_config_mysql.py
backend/tests/test_migration_metadata.py
backend/tests/test_mysql_integration.py
docs/10-契约不变量与验收样例.md
docs/TASK-201-配置接口与验收运行.md
frontend/e2e/config.spec.ts
frontend/package-lock.json
frontend/package.json
frontend/playwright.config.ts
frontend/src/App.vue
frontend/src/ConfigCenter.test.ts
frontend/src/ConfigCenter.vue
frontend/src/config-center.css
frontend/src/configApi.test.ts
frontend/src/configApi.ts
frontend/src/main.ts
frontend/vite.config.ts
frontend/vitest.config.ts
```

交付文件：本报告、`PROJECT_STATUS.md`，以及 `task_artifacts/task201/` 下的 `ruff-check.txt`、`ruff-format.txt`、`pytest.txt`、`pytest-collection.txt`、`mysql.txt`、`frontend-types.txt`、`frontend-tests.txt`、`frontend-build.txt`、`frontend-format.txt`、`frontend-e2e.txt`。

旧迁移测试只更新预期 head 为新增 `0003_model_timeout_double`，保留既有断言和测试逻辑；没有为通过门禁增加 skip/xfail/noqa 或放宽断言。

## 3. API 清单与数据契约

以下均在 `/api/admin` 内。完整字段、错误及运行方式见 [配置接口与验收运行](docs/TASK-201-配置接口与验收运行.md)，请求/响应有明确 Pydantic Schema。

| 方法 | 路径 | 功能 |
|---|---|---|
| GET / PUT | `/config/draft` | 读取/校验后保存，Draft Hash 乐观并发保护 |
| POST | `/config/bootstrap` | 显式导入 Draft，已有 Draft 拒绝覆盖，不发布 |
| POST | `/config/validate` | Schema + 业务校验 |
| POST | `/config/prompt-preview` | 纯 PromptBuilder 预览，不访问 Provider |
| GET / POST | `/model-configs` | 分页列表/创建独立新版本 |
| GET | `/model-configs/{id}` | 读取有效 Model Snapshot |
| POST | `/model-configs/{id}/disable` | 禁用，拒绝 Active 引用 |
| GET | `/config/publish-summary` | 指定模型，返回分区 before/after、模型变更、Hash/Fingerprint |
| GET / POST | `/releases` | 分页历史/事务发布并激活 |
| GET | `/releases/{id}` | 历史 Snapshot + Model Snapshot + 完整 provenance |
| POST | `/releases/{id}/create-draft` | 历史复制为 Draft，不切 Active |
| GET | `/status/summary` | 本 Task 的配置就绪状态及 Active ID |

Runtime API/IntentResult/错误码与 HTTP 对应关系不变。Admin 专用 422 校验错误携带字段 issues；404 区分不存在；409 区分 Draft/版本/Active/禁用/Hash 冲突。发布确认提交审阅时的 Draft Hash 与 Active ID，防止他人修改后发布未审阅内容。

## 4. Draft / Model / Release 实现

Draft 复用 TASK-101 的 `validate_runtime_config_snapshot`，对已有实例也 dump/reparse。新增全局 name/zh/alias 歧义检查，包括 disabled Intent；引用检查与七个 enabled Route 保持原 Contract。保存生成独立 canonical JSON 副本，编辑不修改 Release。前端 Route key/启用状态不开放编辑；二级 Intent、Few-shot、Slot、Enum/Alias、Prompt 按 Draft section 编辑。错误保留本地编辑并展示字段路径。

Model Config 从创建开始采用追加版本策略；没有参数原地更新/删除 API，ORM 也拒绝参数更改与删除。Model Snapshot 独立于 Business Snapshot。credential_ref 只允许逻辑环境变量引用，不保存 Key；参数采用非 Secret 调用参数白名单，拒绝 headers、credentials、messages/schema 覆盖、URL 中的认证与查询参数。max_tokens 仅接受 null/omit，并归一化为省略。启用状态与展示元数据不进入 Hash。历史 disabled Snapshot 可读，新发布不能选择，Active 引用禁止禁用。

发布在同一 AsyncSession transaction 内完成：锁 singleton runtime_state（MySQL upsert + FOR UPDATE，覆盖首次创建竞争）→ 锁 Draft → 重新校验/canonicalize → 锁并校验 enabled Model 及 Hash → 创建 Release → Model 首次冻结标记 → Active 指针切换 → 提交。所有配置写入口采用统一锁顺序。FastAPI function-scope dependency 在发送成功响应前提交；异常则 rollback。

Release ID 自增、version 为唯一 UUID 标识；允许相同 Snapshot/Model 连续发布，内容 Hash/Fingerprint 不唯一。历史恢复只复制业务 Snapshot 为新 Draft，再发布新 ID，不直接切回旧 ID。没有覆盖历史 Snapshot 的入口。

## 5. Hash 与数据库精度修复

- Business Hash：重新验证后的 JSON，UTF-8、sort_keys、紧凑分隔符；仅七个 Business 顶层字段。
- Model Hash：provider/model/base_url/params_json/timeout_seconds/max_retries/max_concurrency/structured_output_mode/credential_ref；排除 id/name/version/enabled/时间戳。
- Fingerprint：`SHA256(config_snapshot_hash + str(default_model_config_id) + model_config_hash)`，没有额外分隔符。
- 在 MySQL 读回模型与历史 Release 时重新核对 Hash/Fingerprint；损坏数据拒绝新发布，不错误激活。

真实数据库反例发现原 FLOAT 会舍入 `30.123456789` 秒，导致读回 Hash 不匹配。新增 Alembic `0003_model_timeout_double` 改为 DOUBLE：通过旧 FLOAT 的文本读回值复制，保留已有逻辑值和 Hash；原子列交换，临时列存在时可重跑。验证包括小数精度、旧 `30.1` Hash 不变、临时列阶段中断恢复、重复 upgrade、有损 downgrade 拒绝。对外字段仍为数值，未改变 Runtime Contract。

## 6. 失败用例与 C7/C9 证据

开发先加入核心正反例并运行：新模块尚不存在时 `ModuleNotFoundError: No module named 'app.schemas.config'`。后续 MySQL 不可变测试在加 ORM guard 前实际报 `DID NOT RAISE ValueError`；小数超时反例实际报 `CONFIG_CORRUPT / Model Config Hash 不一致`。真实浏览器还发现默认超时被 HTML step 判无效，修复 step 后重跑通过。

| 不变量 | 自动化证据 |
|---|---|
| C7：已构造 Snapshot 被变异不能绕过 | `test_c7_reparse_mutated_instance`；既有 TASK-101 missing/extra/disabled/invalid route 变异回归；MySQL Draft 存储后移除 Route，再 Publish 被拒绝，Active 不变 |
| C9：重复发布/回退 | MySQL `test_mysql_publish_atomicity_c7_c9_and_rollback`：两次发布 ID/version 不同，三个 Hash 相同；历史→Draft→新发布成功，旧 Snapshot 不变 |
| C15：原子与并发 | 指针 UPDATE 已到 MySQL 后注入异常，Release/指针整体回滚；8 个并发首次 Publish 的 ID/version 均不同，Active 指向最后一个序列化发布 |
| C16：Model 不可变/disable | ORM 参数更新拒绝；Active 禁用拒绝；替换模型后旧版本可禁用且历史可读；禁用与发布竞争后 Active 始终引用 enabled Model |
| C17：Hash | 独立 hashlib 公式核对；键顺序确定性；每个受支持运行参数变更影响 Hash；展示/生命周期元数据不影响 Hash；小数超时往返不变 |
| C18：Draft 隔离/并发 | 两个基于同一旧 Hash 的编辑只有一个成功，另一个 DRAFT_CONFLICT；重复 Model name/version 并发创建只有一个成功 |

矩阵已同步到 docs/10。Prompt Preview 确定性及无 Provider 调用保持纯函数边界；Bootstrap 导入后 Release 列表为空。不存在 SQLite 替代事务测试。

## 7. 实际后端门禁与 MySQL 输出

工作目录 `D:\akae\AICoach\backend`。所有最终命令退出码 **0**。原始输出见 [task_artifacts/task201](task_artifacts/task201)。

```text
uv run --locked --extra dev ruff check .
All checks passed!

uv run --locked --extra dev ruff format --check .
52 files already formatted

uv run --locked --extra dev pytest -q -rs
........................................................................ [ 53%]
..............................................................           [100%]
============================== warnings summary ===============================
.venv\Lib\site-packages\fastapi\testclient.py:1
  ... StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
```

项目 addopts 已有 `-q`，该必需命令双 quiet 不打印计数摘要；实际 collect 输出（原件 `pytest-collection.txt`）：

```text
tests/test_app.py: 7
tests/test_bootstrap_unit.py: 5
tests/test_config_contract.py: 30
tests/test_config_mysql.py: 8
tests/test_diagnostic_boundaries.py: 25
tests/test_intent_contract.py: 30
tests/test_migration_metadata.py: 1
tests/test_mysql_integration.py: 2
tests/test_prompt_builder.py: 5
tests/test_provider_contract.py: 21
```

合计 **134 passed，0 skipped，1 个既有 Starlette/httpx 弃用警告**。

MySQL 使用本机已安装的 **8.0.32 Community Server**，新建独立临时 datadir，仅监听 127.0.0.1:13316，未使用或清理已有项目/生产数据库。三个独立测试库：`ai_coach_task201_test_local`、`ai_coach_task002_test_201regression`、`ai_coach_task201_test_browser`。分别配置 MYSQL_CONFIG_TEST_DATABASE_URL / MYSQL_TEST_DATABASE_URL / CONFIG_E2E_DATABASE_URL。

```text
uv run --locked --extra dev pytest -o addopts='' -q -rs tests/test_config_mysql.py tests/test_mysql_integration.py
..........                                                               [100%]
10 passed, 1 warning in 16.08s
```

包含 8 项 TASK-201 真实 MySQL 场景与 2 项既有 migration/constraints/readiness 回归。新库 migration 后无 Active Release，/ready 仍成功且 runtime_config_ready=false。测试库前缀保护未放宽；缺少环境变量仍显式 skip/BLOCKED，**本次实际没有 skip**。

交付收尾已核对专用 datadir 与进程参数后关闭本次临时 MySQL 实例；Playwright 自行回收测试 API/Vite 进程。临时数据与日志留在系统 TEMP，未删除或停止其他 MySQL 实例。

## 8. 前端验证与真实操作

工作目录 `frontend`，Node 22.16.0。实际 `npm ci` 成功（211 packages；audit 212 packages；0 vulnerabilities）。新增 Vitest、Vue Test Utils、Playwright，固定版本；初次依赖审计发现问题后将测试工具及 Vite 更新到兼容的修复版本：Vite 6.4.3、plugin-vue 5.2.4、Vitest 4.1.11。未执行强制自动升级。

```text
npm run lint
> vue-tsc --noEmit
[exit 0]

npm run test
RUN v4.1.11 D:/akae/AICoach/frontend
Test Files 2 passed (2)
Tests 6 passed (6)
Duration 2.51s

npm run build
> vue-tsc --noEmit && vite build
vite v6.4.3 building for production...
✓ 1604 modules transformed.
dist/index.html                     0.41 kB │ gzip: 0.28 kB
dist/assets/index-DEAen3i9.css      363.24 kB │ gzip: 48.85 kB
dist/assets/index-Bkx1H3lf.js     1,050.27 kB │ gzip: 343.75 kB
✓ built in 4.11s

npm run format
All matched files use Prettier code style!

npm run test:e2e
Running 1 test using 1 worker
ok 1 ... real MySQL configuration: bootstrap, dynamic intent, publish, history and rollback (5.7s)
1 passed (10.6s)
```

浏览器为 Chromium，实际连接 Vite→FastAPI→MySQL，**无 API route mocking**。操作链：空 Draft 引导→显式导入→创建 Model→首发→新增二级 Intent、alias、Few-shot、Slot 枚举→保存→校验→完整 Prompt Preview→看摘要并发布→读取旧 Release 确认不变→从历史创建 Draft→重新发布，最终新 ID 与旧 Fingerprint 相同。组件测试额外覆盖错误展示和未保存编辑保护。

非阻塞警告：Element Plus 全量导入造成 Vite >500 kB chunk 提示；Playwright 输出 NO_COLOR/FORCE_COLOR 提示；PowerShell 记录 stderr 时附 NativeCommandError 包装（命令退出 0，不是测试失败）。原始记录保留，没有隐藏警告。

## 9. DoD 逐项结论

| 项目 | 自验结论 | 说明 |
|---|---|---|
| Draft 读取/保存/Schema 与业务验证 | PASS | 非法引用、重复名称/中文名/alias、七 Route missing/extra/disabled 拒绝 |
| Prompt Preview / Bootstrap | PASS | 复用纯 PromptBuilder；显式 Draft 导入，无自动 Publish |
| Model 新版本/独立 Snapshot/Secret 边界 | PASS | Hash 字段明确，禁止原地参数修改，Active 禁用保护 |
| 事务发布/Hash/Fingerprint | PASS | 同事务 Active 切换，读回一致性，小数精度迁移 |
| 并发/失败回滚 | PASS | 首次并发发布、publish/disable 竞争、指针 SQL 后故障回滚 |
| 历史不可变/重复发布/回退 | PASS | 新 ID，同内容 Hash 可重复，历史只复制到 Draft |
| 全部 Admin API | PASS | 真实 MySQL API 工作流、字段错误/冲突、响应 Schema |
| Vue 七个 Tabs 与全部操作 | PASS | 真实 API、错误显示、摘要确认、历史详情/恢复 |
| 不改 Python 快速新增业务配置 | PASS | 浏览器与数据库测试均覆盖 Intent/alias/Few-shot/枚举→Preview→Publish |
| C7/C9 及回归门禁 | PASS | 134 项、零 skip，矩阵补齐 C15–C18 |
| 隔离 MySQL 8 | PASS | 10 项数据库集成，独立 datadir/库 |
| 前端 types/build/component/API/E2E | PASS | 类型/构建/格式通过；6 + 1 项测试 |
| TASK-201 独立复核 | 待执行 | 交给 5.6 Sol，执行方不自签独立 PASS |
| TASK-102/201 接口联查 | 待执行 | 必须在独立复核 PASS 后完成 |
| TASK-103 开始前置 | BLOCKED | 当前不得开始，待独立复核及接口联查 |

## 10. 未完成项与风险

TASK-201 正式实现范围无已知未完成模块；以下边界继续保留，不以测试环境成功替代验收：

- **P2-2**：`validation_issues[].slot.value` 仍可能无界，必须在 TASK-103 DB Trace 接入前修复。本 Task 未实现 DB TraceStore。
- **P2-1**：Provider-neutral Error 类型仍耦合具体 Qwen Provider，新增其他 Provider 前修复。
- **REAL_QWEN_SMOKE=UNVERIFIED**：未调用真实 Qwen、未读取真实 Key、未批准生产启用。
- TASK-103 TTL Runtime loader / Runtime API / DB Trace、TASK-202 完整服务状态统计、TASK-301 Evaluation 不在本 Task 中提前实现。
- 应用层不可变防护不能代替数据库账户权限；部署仍须限制 Admin 公网入口。migration 必须先执行到新 head；有损 downgrade 会显式拒绝。
- 构建 chunk 较大为非功能性优化项；没有为消除提示而扩大页面范围或改变构建门禁。

## 11. TASK-102/201 接口联查准备

`effective_model_snapshot(row)` 返回既有 `ModelConfigSnapshot`；`release_configuration(session,id)` 提供 Business Snapshot、Model Snapshot、release_id/version、config_snapshot_hash、model_config_hash、release_fingerprint。真实 MySQL 测试已将其输入构造为 TASK-102 `RuntimeConfiguration`，包括历史 disabled Model 可读。类型准备和自测不等于独立联查通过。

建议独立复核核对：实际 Provider 参数 Hash 是否精确覆盖有效调用参数；Publish/disable 锁顺序和提交边界；Model Snapshot 与 `RuntimeConfiguration` 适配；Snapshot reparse；相同 Snapshot 发布/回退；Float→Double 迁移前后一致性。之后的 TTL Loader 只读已发布 Release，不能直接消费 Draft。

## 12. TASK-103 交接要求与参考资料

完成 5.6 Sol TASK-201 独立复核 PASS，再完成 TASK-102/201 接口联查，才满足下一任务门禁。DB Trace 前先关闭 P2-2；真实异步 DB Sink 要覆盖连接池等待/SQL/commit/rollback 的取消、回滚及资源释放；保留 TASK-102 协作式取消约束，不能吞取消或未确认 commit 就报告 written。真实 Qwen smoke 仍需要后续授权环境与完整 Prompt/schema/business validation 验证。

外部参考：仅查阅 [SQLAlchemy 2.0 asyncio 官方文档](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html) 的独立 session/transaction 用法，以及 [MySQL 8.0 Locking Reads 官方文档](https://dev.mysql.com/doc/refman/8.0/en/innodb-locking-reads.html) 的行锁语义；实现优先遵从本仓库 Contract。未采用 docs/09 的第三方分类器、Agent、Tenacity 或同步 Client；原因是 TASK-201 无需改 Provider/分类逻辑，数据库事务和现有 PromptBuilder 足够。未重新做 OpenAI/Qwen Structured Output 调研或真实调用，因为本次没有更改 Provider Contract，真实兼容性保持 UNVERIFIED。

交付后停止，状态为 **TASK-201 待独立复核**。
