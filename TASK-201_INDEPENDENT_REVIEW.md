# TASK-201 独立代码复核

日期：2026-10-13  
审核结论：**FAIL**

> 本轮对 `ead771e` 的实现和 `18256ec` 的执行报告做了独立代码阅读、真实 MySQL 8.0.32 事务/迁移验证和真实 Chromium E2E。不是对执行报告的转述。发现 3 个 P1：Publish 审阅 token 在后端可被省略；0003 可在存量 Model Hash 不可重建时仍升级成功；TASK-102/201 之间的 Provider 与 effective Model Snapshot 仍有双重真相源。按审核规则，存在 P1 阻断缺陷必须 FAIL。

## 1. Git 基线、范围与审查材料

| 项目 | 独立观测 |
|---|---|
| 分支 / HEAD | `main` / `18256ec3148eafc628588ea743f1692fb4a37127` |
| 实现提交 | `ead771eb0f24af276d9bd9ad4b4aa23674424a87` |
| 报告与证据提交 | `18256ec3148eafc628588ea743f1692fb4a37127` |
| 相对远程 | `main...origin/main [ahead 14]` |
| 审核前工作区 | 仅 `TASK-102_FINAL_INDEPENDENT_REVIEW.md` 为既有已暂存新文件；本轮未修改、未取消暂存 |
| 差异卫生 | `git diff --check ead771e^..18256ec` 退出 0 |

实现和报告两个提交合计涉及 41 个文件。重点实际阅读：

- `AGENTS.md`、`tasks/README.md`、正式 TASK-201/002/101/102/103 任务书。
- `docs/03`、`04`、`06`、`07`、`09`、`10`、`docs/TASK-201-配置接口与验收运行.md`。
- `TASK-201_EXECUTION_REPORT.md`、`TASK-102_FINAL_INDEPENDENT_REVIEW.md`、TASK-002 执行/审核材料。
- TASK-201 全部新增后端 Schema/Service/API/Alembic/测试、Vue/API client/组件/浏览器 E2E，以及既有 PromptBuilder、Provider、IntentService、ORM、Readiness 代码。

`docs/10` 的改动仅新增 C15–C18 及 TASK-201 测试映射，没有改弱原 C1–C14。既有测试仅将 Alembic head 期望从 0002 更新为 0003；未发现删除断言、新增 `skip/xfail/noqa` 或放宽既有断言。`app/schemas/intent.py` 的变更是新增全局 Intent name/zh/alias 歧义校验，不是 Runtime Contract 放宽。

## 2. 正式 DoD 逐项结论

| DoD / 不变量 | 结论 | 证据与限制 |
|---|---|---|
| Draft read/update，CAS 防止丢失更新 | PASS | `save_draft()` 在统一写锁后比对 Draft Hash；真 MySQL 并发编辑仅一个成功。 |
| 七个固定 Route 且全 enabled | PASS | 复用 `validate_runtime_config_snapshot()`；缺失/新增/disable 均拒绝。 |
| Intent/zh/alias 全局歧义与引用校验 | PASS | enabled/disabled Intent 都参与歧义检查；Slot enum group 和 Few-shot Intent/Route 引用受校验。 |
| Prompt Preview 只走 PromptBuilder | PASS | `config_service.py:144-151`；无 Provider 依赖/调用。 |
| Bootstrap 显式导入且不发布 | PASS | API 和真浏览器 E2E 均证明导入后 Release 为 0。 |
| Model Config append-only / Active disable 保护 | PASS | 无 update/delete API；ORM event 拒绝运行参数 update/delete；disable/publish 竞争后 Active 始终指向 enabled Model。 |
| Publish 同事务写 Release/Model freeze/Active | PASS | 真 MySQL 指针 UPDATE 后注入失败，Release 和 Active 均回滚。 |
| Publish Summary 到 Publish 强制乐观并发 | **FAIL (P1-1)** | token 是可选的；省略后可发布 Summary 之后的未审阅 Draft。 |
| 历史 Release 不可变/回退新建 Release | PASS（应用边界） | API 无更新/删除；ORM event 拒绝；回退复制 Business Snapshot，新 ID。DB 维护账号的直接 SQL 防篡改仍属部署权限。 |
| C9 重复发布同内容 | PASS | 真 MySQL 下 ID/version 不同，三个 Hash 相同，普通索引非 UNIQUE。 |
| 不改 Python 完成 Intent/Alias/Few-shot/Enum/Prompt/发布 | PASS | 真 Chromium E2E 完成该主链路，历史 Snapshot 不变。 |
| 历史运行配置可准确恢复 | PARTIAL | Business Snapshot 可恢复；Model 运行字段依赖 ORM append-only，但 0003 对存量无法重建 Hash 的行不阻断升级，见 P1-2。 |

因 P1-1/P1-2/P1-3，TASK-201 不满足生产级 DoD，不可正式关闭。

## 3. Release 事务与并发

| # | 审查项 | 结论 |
|---:|---|---|
| 1 | Publish 是否在同一真 MySQL 事务 | PASS。`Database.transaction()` 的 `session.begin()` 包围整个 function-scope dependency；Release insert、freeze marker、Active update 统一 commit。 |
| 2 | Release 创建失败回滚 Active | PASS。创建在 Active update 之前；任何异常整个 transaction rollback。 |
| 3 | Active update 后、commit 前失败 | PASS。真 MySQL `after_cursor_execute` 注入失败后 Release 计数和 Active ID 不变。 |
| 4 | 首次无 runtime_state 并发 Publish | PASS。MySQL upsert singleton 后 `FOR UPDATE`；8 并发全成功且 Active 指向最后序列化的 Release。 |
| 5 | 多用户 Publish 版本冲突 | PASS。state 锁串行化；UUID version 和自增 ID 不冲突。 |
| 6 | Draft edit / Publish 并发不发布未审阅内容 | **CONDITIONAL / FAIL**。携带 Summary token 时返回 `409 DRAFT_CONFLICT`；但 token 可省略，实测发布了未审阅变更。 |
| 7 | Disable / Publish 竞争 | PASS。两者都先锁 state，竞争结果要么 disable 先成功且 publish 拒绝，要么 publish 先切换且 disable 拒绝。 |
| 8 | 统一数据库锁顺序 | PASS。写路径均 state → draft/model；restore 前的 release/model 是非锁定一致读，不形成反向写锁。 |
| 9 | 丢失更新 | PASS（Draft/Model）。Draft CAS 和统一 state 锁有真 MySQL 证据；Publish 审阅语义的缺口见 P1-1。 |
| 10 | Release 真正不可变 | PASS（API/ORM）。无 mutation endpoint，ORM before_update/before_delete 拒绝。 |
| 11 | 同配置重复发布 | PASS。不同 ID，同 Hash/Fingerprint。 |
| 12 | 历史 Release 创建 Draft | PASS。只复制 Snapshot，旧 Release/Active 不变。 |
| 13 | Summary / Publish 乐观校验 | **FAIL**。实现了但后端未强制，不能作为生产不变量。 |

### P1-1：Publish 审阅 token 可省略

- 位置：`backend/app/schemas/config.py:37-42`，两个 token 都 `default=None`；`backend/app/services/config_service.py:297-303` 只在 token 存在/字段被设置时校验；`docs/TASK-201-配置接口与验收运行.md:20` 也将其记为可选。
- 真 MySQL + 真 ASGI API 复现：先 GET Summary，再 PUT 修改 Draft，随后只传 `default_model_config_id/note` POST Release。实际输出：

```text
SAVE_AFTER_SUMMARY 200 True
PUBLISH_WITHOUT_TOKENS 201 35
PUBLISHED_UNREVIEWED_CHANGE True
```

- 对照：传入旧 Summary 的两个 token 时，实际返回 `409 DRAFT_CONFLICT`，说明 CAS 机制本身有效，问题是 API 可绕过。
- 最小修复：将 `expected_draft_hash` 改为必填 64 位 hash；将 `expected_active_release_id` 改为“必须显式出现但可为 null”；Service 无条件比对。新增真 MySQL 并发测试：Summary 后 Draft/Active 任一变化必须 409，且 Release/Active 不变。

## 4. Model Config 与三个 Hash

| 审查项 | 结论 |
|---|---|
| 运行参数不原地修改 | PASS。API 只有 create/list/get/disable；ORM 对除 enabled/immutable_from_at 外的更新拒绝。 |
| 历史 Release 的 Model 运行 payload | PASS（应用边界）。Release 保存 ID + hash，Model 运行列 append-only；enabled 是生命周期状态，历史读回可为 false 且不进入 hash。 |
| Active Model disable 保护 | PASS。同一 state 锁下比对 Active Release。 |
| Secret / credential_ref | PASS。DB 只存符合环境变量命名的逻辑引用；base URL 拒绝 credentials/query/fragment；params 白名单拒绝 key/header/messages/schema 覆盖。 |
| Model Hash 运行字段完整 | PASS。`provider/model/base_url/params_json/timeout/max_retries/max_concurrency/mode/credential_ref` 全部参与。 |
| 展示/生命周期元数据排除 | PASS。id/name/version/enabled/时间不进 hash。 |
| 数值 canonicalization | **PARTIAL / P2-1**。Pydantic 会将 `timeout_seconds=30` 归一为 float，但嵌套 `params_json` 保留 int/float 和负零词法差异。 |
| DB 读回 Hash 一致 | PASS（新 DOUBLE 正常行）；存量异常行见 P1-2。 |
| Release Fingerprint | PASS。独立核对为 `SHA256(config_hash + str(model_id) + model_hash)`，与正式文档一致，无额外分隔符。 |
| 读回 Hash 损坏不静默忽略 | PASS。Model/Release detail/publish 会返回 `CONFIG_CORRUPT`。 |

数值反例的独立输出：

```text
0 0.0 False {'temperature': 0} {'temperature': 0.0}
-0.0 0.0 False {'temperature': -0.0} {'temperature': 0.0}
1 1.0 False {'temperature': 1} {'temperature': 1.0}
```

这些值对 Provider 参数语义等价，但得到不同 Model Hash。当前文档没有锁定 JCS/Decimal 等具体数值规则，因此记为 P2 而非 P1。最小修复是先固定数值等价规则，在存储和 hash 前使用同一归一化函数，并增加 `0/0.0`、`-0.0/0.0`、小数往返用例。

## 5. Alembic 0003 迁移专项

### 已验证部分

- FLOAT → DOUBLE 的方向成立：新建 Model Config 允许高精度 timeout，FLOAT 会使新行在 DB 往返后无法通过自身 hash。
- 真 MySQL 8.0.32 升级后 `timeout_seconds double NOT NULL`，Alembic head 为 `0003_model_timeout_double`；`config_snapshot_hash`/`release_fingerprint` 均是非唯一 BTREE 索引。
- 迁移明确考虑 MySQL DDL auto-commit：临时列已创建时重跑会重新 copy；最终 `ALTER TABLE ... DROP/CHANGE` 是单条 MySQL 8 atomic DDL；已经是 DOUBLE 时直接返回。
- 真 MySQL 现有测试已实际覆盖：临时列中断后恢复、重复 upgrade、`30.1` 旧值/hash 保持、高精度 DOUBLE 有损 downgrade 拒绝。
- 本轮仅操作临时 datadir 和新建 `*_review` 库，未连接生产或既有 3306 数据库。

### P1-2：迁移会在存量不可重建 Hash 行存在时绿灯完成

- 位置：`backend/alembic/versions/0003_model_timeout_double.py:17-35`。它复制旧 FLOAT 的当前文本表示，但没有核对 `model_config_hash`、引用该 Model 的 Release hash/fingerprint，也不会在无法重建时中止。
- 现有迁移回归 `backend/tests/test_config_mysql.py:351-394` 只使用可恢复的 `30.1`。
- 独立旧库样本（0002 FLOAT）实测：

```text
id  old requested     FLOAT text
1   30.1              30.1
2   30.123456789      30.1235
3   0.123456789       0.123457
4   599.9999999       600
```

0003 升级后：

```text
READ_OK   1 30.1
READ_FAIL 2 30.1235   CONFIG_CORRUPT Model Config Hash 不一致
READ_FAIL 3 0.123457  CONFIG_CORRUPT Model Config Hash 不一致
READ_FAIL 4 600.0     CONFIG_CORRUPT Model Config Hash 不一致
```

其中高精度行在 0002 读回时已经损坏（0003 没有进一步改坏它们）；问题是 0003 与 readiness 可以成功，但未对存量数据做安全前置审计。如果现网库曾由脚本/直接 SQL/同事务路径创建并引用这类行，升级到 head 不等于运行配置可用。

最小修复/生产前置：

1. 增加升级前存量数据审计，对每个 Model 重建 runtime payload hash，对每个 Release 重建 model hash/fingerprint；任一不一致必须 fail-closed，不得只把 Alembic 标记到 head。
2. 对无法从 FLOAT 恢复的行给出显式运维策略（根据原始配置创建新 Model/Release；不得盲目重算并覆盖历史 Hash）。
3. 新增“旧 FLOAT 高精度 + 被 Active Release 引用”受控样本，验证升级拒绝/运维恢复流程，不只测 `30.1`。

因此，**0003 的 DDL 机制本身可重跑，但当前不满足生产升级前提**。实际生产存量行分布和原始 timeout 值仍 **UNVERIFIED**。非 MySQL 数据库不在项目支持范围，本轮也未将 MySQL-specific DDL 冒充为跨库 PASS。

## 6. Draft / Admin API / 配置契约

- PASS：7 Route 恰好存在且 enabled；Route key/enable 在 UI 无编辑入口。
- PASS：Intent name/zh/alias 跨全局歧义拒绝；Slot/Enum/Few-shot/Prompt 动态配置和引用校验完整。
- PASS：Draft 与 Release JSON 使用 canonical serialize/reparse 分离；编辑 Draft 不修改 Active Snapshot。
- PASS：已构造 `RuntimeConfigSnapshot` 被篡改后，Publish/business hash 入口 dump/reparse，不能绕过校验。模型对象本身未 frozen，但用户要求的“不能绕过”已满足。
- PASS：Bootstrap 只显式导入 Draft，已有 Draft 返回 409，不自动创建 Model/Release。
- PASS：Prompt Preview 返回真实 PromptBuilder 输出，不调 Provider。
- PASS：Draft Save/历史 Restore 使用 Draft Hash CAS；422/404/409 在真 API 主流程中分类正确。
- PASS：无历史 Release mutation endpoint；PUT/PATCH 返回 405。
- PASS：前端主要请求/响应类型与后端字段一致；`provider`/`structured_output_mode` 前端类型比后端宽，但固定 UI 值及后端 422 会阻止非法值，记为类型改进而非阻断。
- FAIL：Publish token 可选，见 P1-1。

Admin 应用内账号/RBAC 不是 TASK-201 范围。当前 Admin router 与 Runtime 在同一 FastAPI app，并未实现设备/业务公网隔离；这是 TASK-401 的部署路由门禁，本报告不将其虚构为已实现。

## 7. Vue 配置中心与真实浏览器 E2E

代码审查结论：

- Route、Intent/Few-shot、Slot、Enum/Alias、Prompt Template、Model Config、Release 七个 Tab 均存在。
- 未保存状态禁用 Validate/Preview/Publish；reload 和 browser unload 有丢失提示。
- Save 失败不调用 `acceptDraft()`，所以本地输入和 dirty 状态保留；组件测试已断言。
- `issues[].field/message` 会在 alert 列表显示；Prompt Preview 展示后端返回的完整 `final_prompt`。
- 发布前展示 section before/after、Snapshot Hash、Fingerprint，并要求 note 确认。
- 历史详情/恢复、Active Model disable 错误显示、Draft 冲突错误显示均有真实 API 路径；Route name/enabled 不能在页面编辑。
- 配置页真实调用 `/api/admin/*`；组件测试使用 mock，但独立 Playwright 用例没有 route mocking，实际连接 Vite → FastAPI → MySQL。

前端规定顺序实际输出：

```text
npm ci
added 211 packages, audited 212 packages; 0 vulnerabilities

npm run lint
vue-tsc --noEmit                         [exit 0]

npm run test
Test Files 2 passed (2); Tests 6 passed (6)

npm run build
✓ 1604 modules transformed; built in 4.14s
warning: main JS chunk 1,050.27 kB (>500 kB)

npm run format
All matched files use Prettier code style!

npm run test
Test Files 2 passed (2); Tests 6 passed (6)
```

真实 E2E：

```text
CONFIG_E2E_DATABASE_URL=mysql+asyncmy://root@127.0.0.1:13326/ai_coach_task201_test_browser_review npm run test:e2e
ok 1 e2e/config.spec.ts ... real MySQL configuration: bootstrap, dynamic intent, publish, history and rollback
1 passed (11.5s)
```

E2E 局限（P2-2，证据缺口）：现有唯一浏览器用例覆盖导入、创建 Model、发布、动态 Intent/Alias/Few-shot/Enum、Preview、历史不变和回退；它没有在真实浏览器中制造 Draft 409 或 Active Model disable 409，也没有对字段错误定位做真后端 E2E。这些行为可从代码+组件+后端测试分别推导，但不得冒充为真浏览器已验证。

## 8. 后端与真实 MySQL 8 证据

环境：本机 MySQL Community Server 8.0.32，本轮在系统 TEMP 创建全新 datadir，只监听 `127.0.0.1:13326`；新建了独立 `ai_coach_task201_test_*_review` / `ai_coach_task002_test_201review` 库。没有使用 SQLite/Mock 替代事务，没有访问生产库。验证后 MySQL 已 normal shutdown，13326 无监听进程；临时 datadir 的递归删除命令被当前工具安全策略拒绝，因此停止后的临时文件仍保留在 `C:\Users\su\AppData\Local\Temp\aicoach-task201-review-66efc3aaded94da9a5dba62074b8b1a3`，未再尝试绕过策略删除。

正式门禁（`backend/`）：

```text
uv run --locked --extra dev ruff check .
All checks passed!

uv run --locked --extra dev ruff format --check .
52 files already formatted

MYSQL_CONFIG_TEST_DATABASE_URL=<isolated> MYSQL_TEST_DATABASE_URL=<isolated> \
uv run --locked --extra dev pytest -q -rs
........................................................................ [ 53%]
..............................................................           [100%]
1 existing Starlette/httpx deprecation warning; exit 0
```

`pytest --collect-only -q` 独立统计为 134 项：7 + 5 + 30 + 8 + 25 + 30 + 1 + 2 + 5 + 21。全量执行时两个 MySQL 环境变量都已配置，没有 skip。

显式 MySQL 套件：

```text
uv run --locked --extra dev pytest -o addopts='' -q -rs \
  tests/test_config_mysql.py tests/test_mysql_integration.py
.......... [100%]
10 passed, 1 warning in 16.62s
```

这 10 项确实实测了发布回滚/并发、历史不可变、Model disable 竞争、Draft/Model CAS、Hash 损坏、DOUBLE 精度、迁移中断恢复、后端 API 主流程，以及 TASK-002 migration/constraints/readiness 回归。但它们没有覆盖本报告 P1-1 的“省略 Publish token”路径，迁移用例也只选了 `30.1`；因此 10 passed 不能抵消两个独立反例。

## 9. TASK-102/201 接口兼容性预评估

已对齐部分：

- `effective_model_snapshot(ModelConfig)` 返回 TASK-102 同一 `ModelConfigSnapshot` 类型，包含 QwenProvider 需要的 base URL、params、timeout、retry、concurrency 和 mode。
- `release_configuration()` 在读回时重新验证 Business Snapshot、Model Hash 和 Fingerprint，返回 Release provenance + Business Snapshot + Model Snapshot。
- Business Hash / Model Hash / Fingerprint 的语义与 docs/03/07 一致。

### P1-3：IntentService 加载的 effective Model 与真正 Provider 仍可不同

- 位置：`backend/app/services/intent_service.py:118-129,144-147`。`IntentService` 构造时注入一个固定 Provider；每次 load 的 `model_config_snapshot` 只用于 `trace.model_config_id`，然后直接调用固定 `self._provider.invoke(prompt)`。
- `backend/app/providers/qwen.py:44-66,161-175` 表明 QwenProvider 在构造时绑定 Model Snapshot，后续 request 使用该对象的 model/base URL/timeout/retry/concurrency/params。
- 后果：Active Release 切换 Model Config 后，TASK-103 Loader 即使返回新 Snapshot，IntentService 仍可用旧 Provider 发请求，却把 Trace 标记为新 model ID。这会同时破坏“Runtime 使用 Release default model”和 Trace provenance。
- `RuntimeConfiguration` 目前也只有 `snapshot/model_config_snapshot`，不含 `release_id/config_snapshot_hash/release_fingerprint`；TASK-103 DB Trace 所需 provenance 尚无类型化边界。
- 最小修复：在 TASK-102/201 接口联查中确立单一真相源。可选方向是 Provider factory/registry 按 effective `ModelConfigSnapshot` 解析并缓存 Provider，或让 Provider 调用显式接收已验证 Snapshot；IntentService 必须校验真实 Provider 的 id/hash 与 Loader 一致。同时把 Release provenance 加入 RuntimeConfiguration/Trace 边界。
- 必须新增联查测试：Active Release 从 Model A 切换到 B，真实本地 HTTP server 收到 B 的 model/params，Trace 也记录 B 的 ID/hash/snapshot，不存在 A/B 混用。

因此，**允许并要求立即进行 TASK-102/201 接口联查与修复，但当前不允许宣布联查 PASS，也不允许开始 TASK-103**。

## 10. 问题分级、复现与最小修复

| ID | 级别 | 问题 | 位置 / 复现 | 最小修复 |
|---|---|---|---|---|
| P1-1 | P1 | Publish review token 可省略，可发布 Summary 后的未审阅 Draft | `schemas/config.py:37-42`；`config_service.py:297-303`；反例输出见 §3 | 两 token 改为后端必填/必须显式出现，无条件 CAS，新增真 MySQL 竞争回归 |
| P1-2 | P1 | 0003 不会在存量 Model/Release Hash 无法重建时 fail-closed，head/readiness 可绿灯但数据不可用 | `0003_model_timeout_double.py:17-35`；高精度旧 FLOAT 反例见 §5 | 升级前全量 hash/fingerprint 审计和受控恢复流程；有不一致即中止；补 Active 旧库样本 |
| P1-3 | P1 | Loader 的 Model Snapshot 与固定 Provider 可不同，Trace 可错标 | `intent_service.py:118-147`；`qwen.py:44-66,161-175` | Provider factory/显式 Snapshot 调用；强制 id/hash 一致；补 Release switch 真 HTTP 联查 |
| P2-1 | P2 | `params_json` 的 `0/0.0/-0.0` 未数值归一，语义等价值 Hash 不同 | `schemas/intent.py:40-47`；`schemas/config.py:143-175,191-193` | 先锁定数值 canonical contract，在存储/hash 前统一归一 |
| P2-2 | P2 | 真浏览器 E2E 未覆盖 Draft 409、Active disable 409 和字段定位 | `frontend/e2e/config.spec.ts:3-128` | 在隔离 MySQL 上新增多 context/page 冲突和 active disable 反例 |
| P2-3 | P2（遗留） | `validation_issues` 无长度上限 | `TASK-102_FINAL_INDEPENDENT_REVIEW.md §5` | TASK-103 DB Trace 前在 Trace 边界限长，保留 issue code |
| P2-4 | P2（遗留） | IntentService 依赖 Qwen 具体 `ProviderError` | `intent_service.py:16,169` | 增加新 Provider 前抽取 provider-neutral error protocol |
| P2-5 | P2（基线契约债） | `/ready` 必需表/列仍是手写常量，与 AGENTS §14.3 的 metadata 推导要求不一致 | `backend/app/db/readiness.py:9-158` | 从 `Base.metadata` 推导表/列集合，保留单次 information_schema 查询和 head 检查 |

P2-5 不是 `ead771e` 新增的回归，当前 0003 也没有新增列，所以本轮不将它单独升为 TASK-201 P1；但它与当前项目强制文字不一致，应在下一次 Schema 变更前关闭。

## 11. 剩余风险、UNVERIFIED 与后续门禁

### 必须在 TASK-103 前关闭

1. P1-1 强制 Publish Summary 审阅 token，并重跑真 MySQL 并发反例。
2. P1-2 完成生产存量 Model/Release hash 审计和 0003 升级 runbook/回归。
3. P1-3 完成 TASK-102/201 接口联查，保证 Loader/Provider/Trace 使用同一 effective Model Snapshot 和 Release provenance。
4. 保留的 P2-3：`validation_issues` 限长，并对真实异步 DB TraceSink 验证取消、rollback、连接释放和无失管任务。

### 仍然 UNVERIFIED

- `REAL_QWEN_SMOKE=UNVERIFIED`：未配置/读取 `DASHSCOPE_API_KEY`，没有验证真实账户、地域、选定模型的 `json_schema strict`、request-id 和完整 Prompt/Schema parse 链路。
- 生产库存量 FLOAT 的实际值分布、是否存在直接 SQL/历史脚本写入、是否有受影响 Active Release：UNVERIFIED；本轮只用受控旧库样本，没有连生产。
- 真浏览器中的 Draft 冲突、Active Model disable 错误提示和字段定位：UNVERIFIED（后端/组件分层测试通过，不等于 E2E）。
- TASK-401 公网/Admin 入口隔离和 DB 维护账号权限：未实现，按正式任务边界不作为 TASK-201 虚假 PASS，也不因此额外阻断本 Task。
- 非 MySQL 8 数据库的 0003 行为：UNVERIFIED 且不在项目支持范围。

本轮保留原有遗留问题：P2-3（原 P2-2 validation_issues 长度）、P2-4（原 P2-1 ProviderError 耦合）、`REAL_QWEN_SMOKE=UNVERIFIED`。没有因 TASK-202/301/401 未实现而扩大 TASK-201 失败范围。

## 12. 外部参考与最终判定

本轮以项目 `AGENTS/docs/tasks`、已锁定依赖的实际代码、MySQL 8.0.32 真实行为和 Chromium E2E 为依据。已阅读 `docs/09`，本次没有参考或复制第三方 classifier/LLMOps 实现，因为发布事务、本项目 Hash Contract 和 Alembic 存量数据才是审核对象。本轮也未因没有密钥而访问 Qwen 官方网络；其状态如实保留 UNVERIFIED。

必须明确回答：

1. **TASK-201 是否可以正式关闭？——否。** P1-1/P1-2/P1-3 关闭并独立复审前不得关闭。
2. **是否允许进行 TASK-102/201 接口联查？——允许且必须进行，但只作为当前 Task 缺陷修复/复审活动，不代表 TASK-201 已通过。**
3. **是否存在阻断 TASK-103 的问题？——是。** 至少 P1-3 直接阻断 Loader/Provider/Trace 接入；P1-1/P1-2 也使 Active Release 和生产升级前提不可信。另需在 DB Trace 前关闭原 P2-2。
4. **新增数据库迁移是否满足生产升级前提？——否。** DDL 和可重跑性通过，但缺少存量 hash/fingerprint 安全审计和不可恢复行的 fail-closed/runbook。
5. **最终结论：FAIL。** 不启动 TASK-103。

