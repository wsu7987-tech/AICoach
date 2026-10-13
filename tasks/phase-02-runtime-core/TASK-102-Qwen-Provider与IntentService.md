# TASK-102 Qwen Provider 与 IntentService

## 依赖

TASK-101

## 阅读

- `docs/02-系统架构设计.md`
- `docs/03-Intent路由与动态Prompt设计.md`
- `docs/09-参考项目与采用策略.md`
- `docs/10-契约不变量与验收样例.md`
- `openai/openai-python` 官方 README：Async / Retries / Timeouts / Request IDs / Raw Response
- Alibaba/Qwen Structured Output 官方文档
- `sohaggain/ai-text-classification-api/src/services/classifier.py`（**仅参考模块边界/typed error；禁止复制其 Tenacity retry 与同步 client**）

## 目标

完成可单元测试的生产核心：统一 Provider + IntentService，不接 Active Release/HTTP/DB Trace。

## 实现

### LLMProvider

统一接口，首实现 Qwen OpenAI-compatible：

- 优先 `AsyncOpenAI` 或等价异步 client；不得在 async FastAPI 路径直接调用同步 SDK
- 显式 timeout（不采用 SDK 默认 10 分钟）
- SDK client 明确 `max_retries=0`，禁止隐藏自动 retry（官方 SDK 默认会 retry，不能与 Provider retry 叠加）
- bounded retry 仅由 QwenProvider 自己实现（`max_retries` 为首次调用之外的重试次数，总 Attempt ≤ 1 + max_retries）
- exponential/backoff 可配置
- max concurrency semaphore
- `json_schema` / `json_object` 显式模式；启用 Structured Output 时不发送 `max_tokens`，Model Config 校验拒绝非空 `max_tokens`
- Provider typed errors
- 每一次真实 HTTP 模型调用生成且仅生成一条 `LLMAttempt`；attempt 在每次网络调用结束后独立记录 request/response/latency/error

Attempt 保存/返回：

- attempt_no/is_retry
- provider/model/params
- sanitized raw request/response
- provider request id/version/fingerprint/finish_reason（可用时）；优先读取 SDK `_request_id`/raw response metadata，但 Qwen 兼容接口拿不到时允许 null，真实 smoke test 记录结果
- token/latency/status/error
- parsed payload（可用时）

不得把异常转成 `unknown`。

### IntentService

依赖注入：

- `RuntimeConfigLoader` protocol
- `LLMProvider`
- `PromptBuilder`
- `TraceSink` protocol

Pipeline：load -> build -> invoke -> parse -> validate -> build result -> trace sink。

本 Task 使用 InMemory ConfigLoader + InMemory TraceSink 测试，不实现真实 DB wiring。

### Validator

验证 route/intents 是否属于当前 Snapshot、slot/confidence/risk/clarification 等。

## 测试

Mock Provider 覆盖：

- structured success
- `risk=null`
- safety + risk
- provider timeout + retry attempts
- 5xx/rate limit（Provider rate limit -> `MODEL_RATE_LIMIT`，Runtime HTTP 503 + Retry-After）
- malformed JSON
- schema invalid
- route not in release
- secret sanitizer
- concurrency limit 基础测试
- async client/event-loop 不被同步模型调用阻塞
- structured output 请求不包含 `max_tokens`

## v1.2.5 追加要求（Contract 先行）

1. **先写 Contract 测试再写实现**：C11 / C12（`docs/10 §6`）先红后绿。
2. **真实验证 retry 与 attempt 对应关系**：用一个会计数请求的本地 mock HTTP server（不是 mock 掉 SDK 方法），断言：SDK `max_retries=0`；一次业务调用在 N 次失败 + 1 次成功时，服务端实际收到 N+1 个请求，且恰好产生 N+1 条 `LLMAttempt`；总 Attempt ≤ 1 + max_retries。
3. **Qwen 能力核对**：对选定模型确认 `json_schema` strict 是否可用（真实 smoke，结果写入报告）；不可用则由 Model Config 显式选 `json_object`，不得静默降级。
4. 输出 Schema 不含 `minItems` 等不支持关键字；请求体不含 `max_tokens`。
5. `intents` 为 `0..n`：空 intents 不使请求失败（见 `docs/03 §3`）。
6. 门禁：`docs/10 §7` 三条命令全绿并贴输出；报告含“参考了/未参考”。

## DoD

`IntentService.analyze()` 在无 FastAPI/无 MySQL 情况下可被完整单测；所有失败显式分类。
