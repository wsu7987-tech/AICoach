# TASK-102 第二轮修复｜最终独立增量复核

**结论：CONDITIONAL PASS。P1-1 PASS，P1-2 PASS，P2-2 FAIL。允许开始 TASK-201，但本报告发现的结构化诊断长度缺口必须在 TASK-103 数据库 Trace 持久化接入前修复并回归。**

两个原 P1 的反例已在未放宽的原 32 项探针下全部转绿，取消诊断、原始取消语义、全诊断脱敏和真实模型请求内容隔离都得到独立验证。但长响应中被业务校验复制到 `validation_issues` 的 slot 值没有任何长度上限；这是实际剩余 P2，不能因原 32 项全绿而宣称 P2-2 已完整关闭。

## 1. 审核基线与工作区

| 项目 | 独立观测 |
|---|---|
| 初始实现 | `ed30115e169fb4234789f37ba61d2d2bb68d220a` |
| 第一轮修复 | `ed2e8ae4eb329d4314e0347ca8d781f216bb8dc7` |
| 本次代码对象 | `b34627f1395d5eaa419a5cc5130a7ec61208111f` |
| 开发方报告/证据 | `6c1af9189bb2cf5d4d780f7300616205da796744` |
| 最终复核时 HEAD | `65ccd56b4d7f0410649d1fb0ab21105c476420d0` |
| 当前分支 | `main`，复核前相对 `origin/main` ahead 12 |
| 业务代码差异 | `ed2e8ae..b34627f`：8 files，599 insertions / 64 deletions |
| 差异卫生 | `git diff --check ed2e8ae..b34627f` 退出 0 |

复核开始时 HEAD 为 `6c1af91`，两份原独立报告与 `review_artifacts/task102_incremental/*` 是既有已暂存文件。复核期间 HEAD 变为 `65ccd56`，该提交只收录了上述原审核文档/产物，没有业务代码变更。本报告写入前工作区与 index 干净；写入后预期只有本文件未跟踪。本复核没有修改、暂存或提交业务代码，也没有启动 TASK-201。

已阅读 `AGENTS.md`、TASK-102 正式任务书、`tasks/README.md`、docs/02/03/06/09/10、两份既有独立复核、第二轮修复报告，以及 Provider、IntentService、TraceSink、统一 Sanitizer 和相关测试。本次是定向增量复核，未重复 TASK-102 全架构审计。

### 原独立探针完整性

- `review_artifacts/task102_incremental/test_review.py` 当前 SHA-256：`4BB0CA2D824A22465640BB04DB0806155CD57BFCCDF6CF2A6353006A59054638`。
- 该值与 `6c1af91` 保存的修复前原件哈希一致；当前文件和 `65ccd56` 中的 Git blob 也同为 `63380f39b4dec5dda5be0383a365441897a96013`。
- `6c1af91` 只新增第二轮报告及 `task102_second_fix` 证据，没有修改原探针的条件、断言、预期结果或执行方式。
- 本次使用原命令与原断言，未增加 `xfail/skip/noqa`，未修改 pytest 配置。

## 2. 定向结论

| 项目 | 结论 | 说明 |
|---|---|---|
| P1-1 取消链路 | **PASS** | 合作式 Sink 前提下，Attempt、Trace、原取消语义、许可释放与收尾都通过；非合作 Sink 边界见 §3. |
| P1-2 全诊断脱敏 | **PASS** | Provider 到 Sink 的所有指定诊断出口已统一脱敏，模型收到的真实业务内容未被改写。 |
| P2-2 诊断长度 | **FAIL** | raw/error 等主要字段已正确限长，但 `validation_issues[].slot.value` 可无界复制超长模型响应。 |
| 总体 | **CONDITIONAL PASS** | 无剩余 P0/P1；剩余 P2 不阻断 TASK-201 开发，但不允许把数据库 Trace 长度/耐久性宣称为已验证。 |

## 3. P1-1：取消链路——PASS

### 真实本地 HTTP 观测

| 场景 | 当前调用 HTTP | Attempts | Trace / 结果 |
|---|---:|---:|---|
| 在途取消 | 1 | 1 `cancelled` | 1 Trace；顶层仍是 `ProviderCancelledError` / `asyncio.CancelledError`，task 为 cancelled |
| backoff 取消 | 1 | 1 `failed` | 已完成 Attempt 进入 Sink；没有第 2 次 HTTP |
| 并发队列等待取消 | 0 新请求 | 0 | 空 Attempts 进入 Trace；没有虚构 HTTP Attempt |
| 并发队列超时 | 0 新请求 | 0 | `SERVICE_BUSY` |
| 取消后复用 Provider | 1 新请求 | 1 | 成功；semaphore 恢复为 1 |

Provider 在发出请求后收到取消会构造完整 cancelled Attempt；backoff 前的失败 Attempt 不被改写为 cancelled；队列等待时未发送 HTTP，因而不生成虚假 Attempt。Provider `finally` 在 Service 进入 Sink 收尾前释放 semaphore。

### TraceSink 行为

| Sink 行为 | 观测状态 | 原取消载体 |
|---|---|---|
| 立即/正常成功 | `written` | 同一 `ProviderCancelledError`，Attempts 与 `trace_diagnostic` 保留 |
| 普通异常 | `failed` + `TRACE_PERSIST_FAILED` | 保留，不打印 Sink 异常原文 |
| 可取消异步阻塞 | `timed_out` + `TRACE_PERSIST_FAILED` | 约 100 ms 内触发取消收尾 |
| 第二/第三次外部取消 | `interrupted` + `TRACE_PERSIST_FAILED` | 新增测试以对象身份断言原载体未丢失 |
| Sink 自身抛 `CancelledError` | `interrupted` | 保留 |

收尾在当前 service task 的同一协程栈中执行，使用 `asyncio.timeout(0.1)`；没有 `create_task`、`shield`、fire-and-forget 或手工 `uncancel`。因此当前实现没有需要额外持有/回收的后台子任务。原探针和新回归均在退出前检查 `asyncio.all_tasks()`，未观察到存活的失管任务。

### 合作式取消的成立条件与剩余风险

1. **当前的有界保证是有条件的。** Sink 必须是真正异步、定期让出 event loop，并在取消时完成简短清理后传播 `CancelledError`。调度误差外，普通 `Event.wait()`/异步 I/O 可被 100 ms deadline 打断。
2. **协议已明确规定该条件。** `TraceSink` docstring 要求实现让出事件循环、清理后传播取消，并明禁同步阻塞或无限抑制取消。
3. **不合作 Sink 会破坏 deadline。** 独立子进程实测：无限吞掉 `CancelledError` 的 Sink 在 0.623 s 时仍未退出，由父进程终止；吞掉一次取消后再延迟 0.2 s 返回的 Sink 总耗时 0.306 s，并因适配器正常返回而被记为 `written`。这是协议违约适配器的可预期后果，不是无条件硬实时保证。
4. **TASK-103 的 DB TraceSink 必须满足：** 库连接、连接池等待、SQL 执行、commit/rollback 都必须可取消且让出 event loop；取消时及时 rollback/释放连接并原样传播 `CancelledError`；不得在循环中吞取消；不得未确认 commit 就正常返回；若内部创建子任务，必须有明确所有者、取消并 await 回收。需用真实异步 DB driver 覆盖 pool wait/query/commit 取消和事务不确定边界。
5. **不虚构持久成功。** `failed/timed_out/interrupted` 都记录 `TRACE_PERSIST_FAILED`；取消异常上的 `trace_diagnostic` 只是调用方内存安全副本，不是耐久存储。`written` 只表示适配器正常返回；当前只验证 `InMemoryTraceSink`，未验证数据库提交、原子性或进程崩溃耐久性。

## 4. P1-2：全诊断脱敏——PASS

独立负例同时使用 `password is ...`、`token is ...`、`API key is ...`、`Authorization: Bearer ...`、嵌套 JSON/dict/list 和 Python repr 格式 SDK 错误。

| 出口 | 结果 |
|---|---|
| `LLMAttempt.raw_request/raw_response` | 递归脱敏，无测试秘密残留 |
| `LLMAttempt.parsed_payload` | 从原始 completion 构造诊断副本时脱敏；Service 解析仍使用原 content |
| `LLMAttempt.params/usage/metadata` | 经同一 Pydantic 诊断边界处理，取消场景也覆盖 |
| `ProviderError.message/args` 与 Attempt error | SDK APIError 优先使用结构化 body，Python repr 秘密被移除，错误链默认输出不重新暴露原始 body |
| `TraceRecord.text/error_message` | Sink 前 dump/reparse，普通和取消 Trace 均无泄漏 |
| `validation_issues` | 嵌套 slot/value 可脱敏；长度缺口另见 §5 |
| `ProviderCancelledError.attempts/trace_diagnostic` | 再次构造安全副本，重复取消不丢失 |
| Sink 与默认日志 | 不打印原 Sink 异常、用户输入或 raw；JSON formatter 同样使用统一策略 |

真实 localhost Server 同时证明：发给 AsyncOpenAI/httpx 的 request body 仍包含全部测试文本，而 Attempt/Trace/Sink/异常摘要不包含这些值。统一 Sanitizer 仅用于诊断副本，没有改写 Prompt、模型请求、业务解析或 `IntentResult.text/slot`。

## 5. P2-2：诊断长度——FAIL

已通过的部分：

- `ERROR_SUMMARY_MAX_BYTES=4096`；Provider/Service/Attempt/Trace 的 error message 超限后以 `...[truncated=true]` 结尾。
- `TRACE_RAW_MAX_BYTES` 默认 65,536 bytes，最小 256；`raw_request/raw_response/parsed_payload/params/usage` 按整段 UTF-8 JSON 字节数限制。
- 结构化大字段转为 `{"truncated": true, "preview": "..."}`，包含 envelope/JSON escaping 开销后仍不超限；是可安全序列化的 dict。
- 中文、emoji、引号、反斜线和换行回归通过，无 U+FFFD 替换字符；截断幂等。
- 限长只作用于诊断副本，正常 route/result、Attempt `status`、`error_code` 和物理 HTTP 计数未被覆盖。

独立反例（真实 localhost HTTP，未 mock SDK `create`）：模型返回一个含 200,000 字符无效 `exercise` slot value 的合法结构化响应。Service 按 Contract 丢弃该 slot 并写入 `SLOT_SPAN_INVALID`。观测为：

```text
HTTP=1, Attempts=1, Trace=1
raw_response_bytes=65536
parsed_payload_bytes=65536
validation_issues_bytes=200185
validation_issues[SLOT_SPAN_INVALID].slot.value chars=200000
```

`TraceRecord.sanitize_diagnostics()` 只对整个结构做脱敏，没有对 `validation_issues` 做字节上限处理。因此超长 response 虽在 Attempt 的两份 raw/parsed 副本中被截断，却可经业务校验路径在 Trace 中再保留一份无界值。这说明长度修复仍只覆盖了部分诊断副本，P2-2 不能通过。

建议在不改变业务 `ValidatedIntentOutput` 的前提下，在 Trace 边界对 `validation_issues` 整段或其嵌套可变文本创建有界诊断表示，并补充真实 HTTP 回归：整个 Sink 可序列化段不超限、标记正确、`SLOT_SPAN_INVALID` 代码与 Attempt 状态仍保留。

## 6. 原 32 项探针

从 `backend/` 实际执行：

```text
uv run --locked --extra dev pytest -o addopts='' -q -rs --tb=short ../review_artifacts/task102_incremental/test_review.py
................................                                         [100%]
32 passed in 27.27s
```

| 探针组 | 数量 | 结果 |
|---|---:|---|
| 真实 HTTP matrix：200 / 429→200 / 5xx bound / timeout / 400 / retry=0 / connection drop | 7 | PASS |
| `json_schema` / `json_object` | 2 | PASS |
| 在途取消、backoff 取消、队列取消、队列超时 | 4 | PASS |
| Sink raise / block / repeat_cancel | 3 | PASS |
| Sanitizer 负例与普通标识保留 | 5 | PASS |
| Trace text / parsed payload / provider error / business error / cancel trace / cancel params | 6 | PASS |
| 原 2 MiB error 长度探针 | 1 | PASS |
| connect refusal | 1 | PASS |
| INFO/stdout/stderr success / error / cancel | 3 | PASS |

关键计数由探针内断言真实 Server request 列表与 Attempt 列表：200 为 1/1，429→200 为 2/2，5xx 上限为 3/3，timeout retry=1 为 2/2，400 为 1/1，retry=0 为 1/1，收到 POST 后断连为 2/2。connect refusal 时 Server 接收数是 0，客户端 request hook/Attempts 是 2/2，没有冒充 Server 计数。

原 32 项全绿是两个 P1 关闭的重要证据；其 2 MiB 长度项只断言 `ProviderError.message` 未完整保留，不覆盖 §5 的 `validation_issues` 第二副本，因而不能抵消 P2-2 反例。

## 7. 全量门禁

工作目录：`D:\akae\AICoach\backend`。

```text
uv run --locked --extra dev ruff check .
All checks passed!

uv run --locked --extra dev ruff format --check .
45 files already formatted

uv run --locked --extra dev pytest -q -rs
....................................................................ss.. [ 75%]
........................                                                 [100%]
SKIPPED [2] tests\test_mysql_integration.py:57:
MYSQL_TEST_DATABASE_URL is not configured; MySQL 8 integration tests are skipped
```

三条命令均退出 0。`pytest --collect-only -q` 实测收集 96 项；结合全量运行的 2 skip，结果为 **94 passed / 2 skipped / 1 warning**。两个 skip 均是既有 MySQL 集成测试，未配置 `MYSQL_TEST_DATABASE_URL`；本次不把它们视为 TASK-102 阻断。warning 是既有 Starlette TestClient/httpx 弃用提示。

## 8. 剩余问题与后续决策

| 级别 | 数量 | 剩余项 |
|---|---:|---|
| P0 | 0 | 无 |
| P1 | 0 | 原 P1-1/P1-2 已关闭 |
| P2 | 2 | 本报告 P2-2：`validation_issues` 无界副本；原 P2-1：`IntentService` 仍导入 Qwen 具体 `ProviderError`，Provider-neutral 错误边界尚未抽离 |

原 P2-1 不阻断当前 Qwen-only 的 TASK-201，但添加第二 Provider 前必须修复。P2-2 不改变 Runtime 业务结果或错误码，因此不阻断 TASK-201 配置/Release 开发；但它直接影响未来 DB Trace 行大小，必须在 TASK-103 持久化前关闭。

`DASHSCOPE_API_KEY` 未配置，本次没有调用外部 Qwen，也没有读取或打印任何真实密钥。**REAL_QWEN_SMOKE=UNVERIFIED**。这不能被本地 HTTP 测试替代；本报告不声称账户/地域/模型的真实 full-schema 兼容性已通过。

**TASK-201 允许开始。** 条件是：

1. 不将本报告解读为已验证真实 Qwen 调用或 DB Trace 耐久性。
2. 在 TASK-103 前关闭 P2-2，并对真实 DB TraceSink 执行合作式取消、事务回滚/连接释放和无失管任务测试。
3. TASK-102 + TASK-201 完成后仍须按 `tasks/README.md` 执行 Provider/IntentService 与 ConfigRelease/ModelConfig 的接口联查。
4. 获得授权 API Key 后，在配置的 Release 激活前执行真实 Qwen Prompt + 完整 Schema + parse/business validation smoke。

本次结论以项目本地 Contract、实际代码、已锁定 SDK 的本地 HTTP 行为和 Python `asyncio.timeout` 的实际取消语义为依据。本轮未采用第三方 classifier 实现，因为定向问题是取消、诊断脱敏与长度，且第三方 retry/同步 client 不是本项目验收依据。本轮未对 Structured Output 架构重做外部审计，因为 `ed2e8ae..b34627f` 未修改该 Contract；其本地 C11/C12 回归仍全绿，真实 Qwen 状态如上保持 UNVERIFIED。
