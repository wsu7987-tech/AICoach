# Codex 项目执行约束（v1.2.4）

## 1. 项目级原则

本项目是**生产上线项目**。目标是小而可靠的 Intent Router，不是演示工程，也不建设通用 AI 平台。

优先级：

1. Runtime Contract 稳定
2. 失败可观测、可定位
3. 配置可追溯、可回退
4. Provider 调用可替换
5. 测试与部署可重复
6. 在满足以上要求后再追求代码抽象

## 2. 技术栈

- Frontend：Vue 3 + TypeScript + Vite + Element Plus
- Backend：Python 3.12+ + FastAPI + Pydantic v2 + SQLAlchemy 2.x + Alembic
- DB：MySQL 8
- LLM：首期 Qwen / Alibaba Model Studio OpenAI-compatible API
- HTTP：httpx 或 OpenAI Python SDK（统一封装在 Provider 内）
- Test：pytest + frontend component tests + E2E
- Deployment：Docker + Kubernetes

一期**不强制使用 LangChain/LangGraph**。禁止仅为了技术栈完整性引入它们。

## 3. 强制架构规则

1. 所有模型调用只能经过 `LLMProvider`。
2. 所有 Prompt 只能经过 `PromptBuilder`。
3. Runtime 业务逻辑只能读取已发布的 `ConfigReleaseSnapshot`。
4. 一级 Route Contract 固定为 `training_business / information_query / sports_knowledge / safety / dialogue_device_control / social_chat / unknown`；key 不允许在配置中心修改、删除、新增或 disable（发布校验：routes 必须恰好为这 7 个且全部 enabled）。Runtime 代码中一级 Route 为固定常量；二级 Intent/Slot/Enum 才对 Snapshot 校验。Intent/Slot/Enum/Few-shot/描述/别名以及既有 Route key 下的映射由配置管理，不得写死在 Router 分支代码中。
5. Runtime 使用 Release 的 `default_model_config_id`；Admin Debug/Evaluation 允许显式模型覆盖。
6. 已被 Release/Trace/Evaluation 使用的 Model Config 不得原地修改；修改需创建新版本。Active Release 正在引用的 Model Config 不允许 disable；必须先发布并激活使用其他 Model Config 的新 Release。Running Evaluation 已冻结的 Model Config 即使之后被 disable，也必须继续按冻结 snapshot 执行。
7. 底层 OpenAI-compatible SDK 必须关闭自动 retry（`max_retries=0`）；所有 retry 由 `LLMProvider` 显式控制。一次真实 HTTP 模型请求 = 一条独立 `LLMAttempt`。FastAPI async 路径优先使用异步 SDK client（如 `AsyncOpenAI`）；不得把同步模型调用直接放进 async route/event loop。
8. Runtime API 与 Admin API 必须分组：`/api/v1/*` 与 `/api/admin/*`。
9. Admin API 不得通过设备/业务公网入口直接暴露；一期可不做应用内账号系统，但部署路由必须限制访问。
10. 数据库变更必须通过 Alembic。
11. Evaluation 必须复用生产 `IntentService`，不得另写一套路由逻辑。
12. Runtime `IntentResult` 固定包含 `risk`（允许 null），不得返回 Prompt/Raw/Reason/Evidence 等调试字段。

## 4. Provider 与 Structured Output

优先使用 Provider 原生 `json_schema` Structured Output + `strict=true`；若选定模型不支持：

- 必须由 Model Config 明确选择 `json_object`；
- 不允许在运行时静默降级而不记录；
- JSON Object 仍必须经过 Pydantic 二次校验；
- parse/schema 失败必须返回显式错误并写 Trace，不得伪造成 `unknown`。

Structured Output 额外约束：

- 当 `structured_output_mode` 为 `json_schema` 或 `json_object` 时，Provider 请求不得发送 `max_tokens`；Model Config 中该字段必须为 null/omit，避免 JSON 被截断。
- 若未来某模型必须设置输出 token 上限，需先通过独立兼容性验证并更新 Contract，不得直接绕过本规则。

Provider 必须支持：

- 显式 timeout（不得依赖 SDK 默认值）
- bounded retry（仅由 Provider 自己实现；SDK `max_retries=0`）
- configurable concurrency limit
- request/response metadata
- token usage（可用时）
- provider request id / model version / fingerprint / finish_reason（可用时）
- typed provider errors

## 5. Trace 与敏感信息

请求级至少保存：

- trace_id / request_id / source / input
- release_id / config_snapshot_hash / release_fingerprint
- effective_model_config_id + model_config_hash + model config snapshot
- final result / route
- validation result
- total latency/token/retry/error
- timeline JSON

Attempt 级至少保存：

- trace_id + attempt_no
- provider/model/params
- final_prompt
- raw_request / raw_response
- provider_request_id / model version / fingerprint / finish_reason（可用时）
- parsed payload（可用时）
- latency/token/status/error

入库前必须过滤 Authorization、API Key、Secret、Token、DB 密码等敏感值。Provider Header 默认不入库，仅允许白名单字段。

Trace 生产约束：
- `TRACE_RETENTION_DAYS` 控制保留天数；与 Evaluation Run 关联的 Trace 使用 `EVAL_TRACE_RETENTION_DAYS`（建议默认 ≥ 90 且不小于前者）。Trace 过期后 evaluation_case_result 不丢，trace 显示“已过期”。
- `TRACE_RAW_MAX_BYTES` 控制单段 Raw Prompt/Request/Response 最大持久化字节数；超限截断并标记 `truncated=true`。
- stdout/stderr 默认不打印完整用户输入、Final Prompt、Raw Request/Response。
- Raw Trace 仅允许内部 Admin 入口访问。
- 清理时 request trace 与 attempts 必须级联删除。
- Runtime：模型业务结果已成功但 Trace 最终持久化失败时 fail-open，返回业务成功并记录 `TRACE_PERSIST_FAILED`。
- Debug/Replay/Evaluation：Trace 写失败 fail-closed，execution/case 失败。

## 6. 配置与多副本

- 编辑态使用 `config_draft` JSON。
- 发布生成不可变 Business Config `config_release.snapshot_json + config_snapshot_hash`；Model Config 不进入 Business Snapshot。
- `default_model_config_id` 独立存储；发布时计算 `release_fingerprint = SHA256(config_snapshot_hash + default_model_config_id + immutable model_config_hash)`。
- Active Release 通过 `runtime_state.active_release_id` 原子切换。
- 多 Pod 不依赖进程内主动广播；Runtime Config Loader 采用短 TTL + Active Release ID 校验，保证最终一致。
- 历史 Release 永不修改。
- 回退方式：从历史 Snapshot 创建新 Draft/Release，不修改旧版本。

## 7. Evaluation 生产约束

- 不使用 FastAPI BackgroundTasks 作为唯一任务保障。
- 非训练业务的二级 Intent 自动判定固定比较 `actual.intents[0].name`（Top-1）；其他候选只用于诊断。
- 期望追问目标非空 -> `need_clarification=true`；为空 -> `need_clarification=false`。追问自然语言文本一期只人工 review。
- Benchmark 的 Route Accuracy / Confusion Matrix / Per-route P/R/F1 使用每个 Case 的 `repeat_index=0` 作为主样本；其余 repeat 只进入 Stability/Route 分布，避免 repeat 人为放大准确率权重。
- 使用 MySQL `evaluation_run` 状态 + Worker claim 机制。
- Case 执行幂等；服务重启后 stale run 可恢复或明确失败。
- 并发数可配置，避免压垮 Provider。
- 每次 Case 执行产生正常 Trace。
- 创建 Run 时必须冻结 dataset hash、release id/fingerprint、effective model config id/hash/snapshot、repeat_count、worker concurrency；Active Release 后续变化不得影响已创建 Run。

## 8. 错误原则

至少区分：

- INVALID_INPUT
- PAYLOAD_TOO_LARGE
- CONFIG_NOT_READY
- SERVICE_BUSY
- MODEL_TIMEOUT
- MODEL_RATE_LIMIT
- MODEL_PROVIDER_ERROR
- MODEL_OUTPUT_PARSE_ERROR
- MODEL_OUTPUT_SCHEMA_ERROR
- INTERNAL_ERROR

不得把基础设施/Provider 错误映射成业务 `unknown`。error_code 与 HTTP 状态码的对应关系以 `docs/06 §3` 表为准，不得自行调整。

## 9. 禁止事项

- 不新增 Redis/MQ/Vector DB。
- 不在前端直连模型。
- 不硬编码 API Key。
- 不实现关键词 Safety Router。
- 不引入多 Agent/RAG。
- 不保存隐藏推理链；仅保存模型实际返回的 `reason_summary/evidence` 或 Provider extras。
- 不因参考开源项目而复制其业务分类、关键词投票或 Agent 架构。

## 10. Readiness 与首次配置边界

- Kubernetes readiness 使用 `/ready`，只表示 **服务面可用**：进程可服务、DB/基础依赖可访问、Migration schema 可用；不得要求 Active Release 已存在。
- Runtime 配置是否可调用通过 `/api/admin/status/summary.runtime_config_ready` 暴露；无 Active Release/default Model Config 时为 false，`POST /api/v1/intent/analyze` 返回 `CONFIG_NOT_READY`。
- 这样首次部署和配置损坏恢复时，Admin API 仍可用来导入 Bootstrap、创建 Model Config、发布/修复 Release。

## 11. 外部参考优先级

1. 本项目 `AGENTS/docs/tasks` Contract。
2. OpenAI Python SDK 官方仓库/README 与 Alibaba Model Studio/Qwen 官方文档。
3. 经 `docs/09` 明确标注的局部参考实现。

外部小仓库不得覆盖本项目 retry、async、Trace、错误语义。`sohaggain/ai-text-classification-api` 仅参考模块边界/错误分类/测试方式，**禁止照抄其 Tenacity retry 和同步 OpenAI client**。

## 12. 每个 Task 的执行格式

1. 阅读 Task 指定文档和 `docs/09-参考项目与采用策略.md` 中相关参考。
2. 只实现当前 Task 范围。
3. 增加测试。
4. 执行测试。
5. 更新 `PROJECT_STATUS.md`。
6. 输出：修改文件、测试命令与结果、未完成项、风险、下一任务前置是否满足。

## 13. 配置快速调整与 Contract 变更边界

以下变更必须支持通过 Admin 配置中心完成，不改 Python 业务代码：

- 新增/修改二级 Intent；
- Intent 中文名、描述、aliases、Few-shot；
- Slot 定义、枚举值、表达别名；
- Prompt Template；
- 既有 7 个一级 Route key 下的 Intent 映射；
- Model Config 以“创建新版本”方式调整。

标准流程：`Edit Draft -> Validate -> Prompt Preview -> Evaluation -> Publish immutable Release -> Active`。

以下属于对外 Contract 变更，不能只改配置：

- 新增/删除/改名一级 Route key；
- 修改 Runtime `IntentResult` 字段/类型；
- 修改 Slot span 语义；
- 改变现有下游依赖的错误码/HTTP 语义。

Contract 变更必须升级 API/Schema 版本并补兼容与 E2E 测试。
