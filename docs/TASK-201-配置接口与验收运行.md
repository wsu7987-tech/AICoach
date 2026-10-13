# TASK-201 配置接口与验收运行

本说明补充 docs/06 的 Admin 接口；Runtime Contract 不变。接口只由内部 Admin 路由暴露，部署应沿用既有 Admin 入口限制。开发时 Vite 仅代理 `/api/admin` 到本机 8000。

## 请求与响应

所有路径以 `/api/admin` 开头。字段 Schema 可查 FastAPI OpenAPI；Response Model 定义在 `backend/app/schemas/config.py`。

| 方法/路径 | 输入与用途 |
|---|---|
| GET `/config/draft` | 返回 `draft_json/draft_hash/updated_at`；未创建时均 null |
| PUT `/config/draft` | `{draft_json, expected_draft_hash}`；新建 token 为 null，更新必须与读取值一致；Schema/业务校验失败不保存 |
| POST `/config/bootstrap` | `{draft_json}` 显式导入项目 Bootstrap；已有 Draft 拒绝覆盖，不创建 Model/Release |
| POST `/config/validate` | 校验当前已保存 Draft，返回 valid/hash/counts |
| POST `/config/prompt-preview` | `{text, context?}`；使用纯 PromptBuilder，返回 messages/final_prompt/prompt_hash/metadata；不调用模型 |
| GET/POST `/model-configs` | 列表/新建版本；列表支持 `offset/limit`，最大 200 |
| GET `/model-configs/{id}` | 读取 ModelConfigSnapshot |
| POST `/model-configs/{id}/disable` | 拒绝 Active Release 正在使用的版本 |
| GET `/config/publish-summary?default_model_config_id=...` | 返回 Draft Hash、Active ID、Model ID/Hash、预期 Fingerprint、section before/after |
| POST `/releases` | 必填 `{default_model_config_id, note}`；可带 `expected_draft_hash/expected_active_release_id`，UI 总是提交这两个审阅 token |
| GET `/releases` | 返回 `active_release_id/items`；按 ID 倒序，支持 `offset/limit`，最大 200 |
| GET `/releases/{id}` | 历史 Business Snapshot、有效 Model Snapshot 及三个 Hash；读取时校验一致性 |
| POST `/releases/{id}/create-draft` | `{expected_draft_hash}`；历史 Snapshot 复制到 Draft，不切换 Active |
| GET `/status/summary` | TASK-201 字段 `runtime_config_ready/active_release_id`；首次无 Release 为 false |

Model create 必填 name/version/provider/model/base_url/timeout_seconds/max_retries/max_concurrency/structured_output_mode/credential_ref；params_json 可省略。provider 当前为 qwen。参数白名单：temperature、top_p、seed、presence_penalty、frequency_penalty；null 参数在创建时省略，max_tokens 只接受 null/omit。阻止 credentials/query/fragment URL、真实 Key 字段、SDK transport/headers/messages/schema 覆盖。credential_ref 使用环境变量标识符。Secret 由后续 Provider 装配解析，配置管理不读取、不保存实际 Secret，也不代表真实 Qwen 兼容性通过。

Model 参数从创建开始即 append-only，只支持创建新版本；name+version 重复为冲突。Release version 为 `release-{uuid}`，身份使用自增 ID 与唯一 version；Hash/Fingerprint 不是身份、没有 UNIQUE。应用 ORM 额外拒绝历史 Release update/delete 和 Model 参数 update/delete；直接数据库维护权限仍需由部署限制，不将 ORM 事件声称为数据库防篡改机制。

部署先执行 Alembic 到 `0003_model_timeout_double`：原 FLOAT 会舍入高精度小数超时并破坏 Hash 一致性，因此改为 DOUBLE。迁移通过旧列的文本读回值复制，避免直接二进制扩展改变已存在版本的逻辑值；临时列与最终原子列交换支持中断后重跑。存在无法无损收窄的值时拒绝 downgrade，不修改历史 Hash。

## Admin 错误

Admin 返回 `error_code/message/issues[]`，业务校验 issues 含 field/message/type。字段路径与说明直接展示，响应不回显完整请求。

- 422：INVALID_INPUT（请求字段）；CONFIG_INVALID（Business Schema/引用/冲突）。
- 404：DRAFT_NOT_FOUND / MODEL_NOT_FOUND / RELEASE_NOT_FOUND。
- 409：DRAFT_CONFLICT / MODEL_VERSION_CONFLICT / MODEL_ACTIVE / MODEL_DISABLED / RELEASE_CONFLICT / CONFIG_CORRUPT。
- 503：CONFIG_NOT_READY（数据库未配置）。

这是 Admin 专用错误，不改变 docs/06 §3 的 Runtime error_code → HTTP 约定。

## 事务与接口交接

Admin mutation 使用独立 AsyncSession。首先 MySQL upsert + FOR UPDATE 锁 singleton runtime_state，再锁 Draft/Model，统一写锁顺序；首次并发发布也受保护。发布重新解析 Draft、计算 canonical Business Hash、校验 enabled Model 与不可变 Hash、写 Release、标记 Model 首次冻结、更新 Active，统一 commit/rollback。FastAPI function-scope dependency 在发送响应前完成提交。

`effective_model_snapshot(ModelConfig)` 返回 TASK-102 已有 `ModelConfigSnapshot`；`release_configuration(session, id)` 返回校验后的 Snapshot 与完整 Release provenance。历史 disabled Model 仍可读取，新的 Publish 不能选择；历史消费方应使用自己冻结的 Snapshot。TASK-103 在此边界上实现 TTL + Active ID 校验和 DB Trace 接入，本 Task 未实现 Runtime loader/API/TraceStore。

## 本地验证

后端统一在 backend 执行 `uv run --locked --extra dev ...`。需要 MySQL 8，测试会清理被明确指定的隔离测试库：

- `MYSQL_CONFIG_TEST_DATABASE_URL=mysql+asyncmy://.../ai_coach_task201_test_<唯一后缀>`：TASK-201 集成；前缀错误拒绝执行，未配置明确 skip/BLOCKED。
- `MYSQL_TEST_DATABASE_URL=mysql+asyncmy://.../ai_coach_task002_test_<唯一后缀>`：保留 TASK-002 既有迁移/约束/Readiness 测试，使用另一数据库。
- `CONFIG_E2E_DATABASE_URL=mysql+asyncmy://.../ai_coach_task201_test_<独立浏览器后缀>`：Playwright 启动脚本先 Alembic upgrade，再清空该专用库，通过真实 FastAPI/Vite/MySQL 跑操作；严禁与其他测试共享同一个正在使用的库。

后端：

```text
uv run --locked --extra dev ruff check .
uv run --locked --extra dev ruff format --check .
uv run --locked --extra dev pytest -q -rs
uv run --locked --extra dev pytest -o addopts='' -q -rs tests/test_config_mysql.py
```

前端（frontend）：

```text
npm ci
npm run lint
npm run test
npm run build
npx playwright install chromium
npm run test:e2e
```

E2E 会独占本机 8000/5173，拒绝复用未知进程；连接本地服务时绕过 npm Registry Proxy。前端测试工具已固定版本；Vite 6.4.3、plugin-vue 5.2.4、Vitest 4.1.11，Node 建议使用本次实际验证的 22.16.0。组件测试中的模拟接口仅验证组件状态；真实事务及浏览器操作独立使用 MySQL，不以 Mock 代替验收。
