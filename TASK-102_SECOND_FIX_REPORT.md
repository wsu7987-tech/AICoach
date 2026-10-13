# TASK-102 第二轮精准修复报告

状态：**开发修复及本地验证完成，待独立增量复核**。本报告不是独立审批，不关闭 TASK-102，不启动 TASK-201/103。

## 1. Git 基线、提交与文件边界

- 基线：`ed2e8ae4eb329d4314e0347ca8d781f216bb8dc7`，分支 `main`。
- 修复代码 Git Commit SHA：`b34627f1395d5eaa419a5cc5130a7ec61208111f`。
- 本报告与测试输出另作证据提交，引用上述实际代码 SHA，避免在提交内容中伪造自引用 SHA。
- 开始时已有 PROJECT_STATUS.md 修改、两个未跟踪审核报告和 `review_artifacts/task102_incremental/`。工作期间这些原审核文件进入暂存区；本轮用 `git commit --only -- <明确文件清单>` 隔离提交，没有提交、撤销暂存或改写原审核文件。
- PROJECT_STATUS.md 仅更新 TASK-102 两行，保留此前 FAIL 的报告引用和其他任务内容。
- 原两个审核报告、原执行报告及 incremental 目录共 10 个文件的 SHA256 前后相同；清单见 `review_artifacts/task102_second_fix/original-artifact-hashes.json`。

实际修复文件：

| 文件 | 变更 |
|---|---|
| `backend/app/core/diagnostics.py` | 统一递归脱敏、UTF-8 截断、错误摘要上限 |
| `backend/app/core/settings.py` | 实现已有 Contract 配置名 `TRACE_RAW_MAX_BYTES`，默认 65,536 bytes，最小 256 |
| `backend/app/core/logging.py` | 现有 JSON formatter 的消息、异常文本、附加字段使用统一策略 |
| `backend/app/providers/types.py` | Attempt 诊断边界；取消载体附安全 Trace 副本与写入状态 |
| `backend/app/providers/qwen.py` | 复用统一策略；结构化 SDK 错误摘要；阻断原始异常链的默认输出 |
| `backend/app/services/intent_service.py` | 有界取消收尾；Sink 前完整 dump/reparse 脱敏；安全失败日志 |
| `backend/tests/test_diagnostic_boundaries.py` | 25 项补充回归，无 SDK HTTP mock 替代真实请求 |
| `PROJECT_STATUS.md` | TASK-102 待独立增量复核 |
| 本报告及 `review_artifacts/task102_second_fix/` | 本轮测试输出、JUnit、collection、基线复现摘要、原证据哈希 |

未修改数据库、Alembic、TASK-101 Schema/业务校验、PromptBuilder、依赖锁文件、既有测试或审核原件。

## 2. 先复现，再修复

确实存在 `review_artifacts/task102_incremental/test_review.py`，并存在原审核的输出/JUnit。
探针原文件 SHA256：`4BB0CA2D824A22465640BB04DB0806155CD57BFCCDF6CF2A6353006A59054638`。

实现改动前，在 backend 执行：

```text
uv run --locked --extra dev pytest -o addopts='' -q -rs --tb=short ../review_artifacts/task102_incremental/test_review.py
9 failed, 23 passed in 30.06s
```

退出 1。失败正好为 Sink block/repeat_cancel 两项、六项 full_diagnostic_redaction、diagnostics_have_size_limit 一项。
本轮复现摘要记录在 `baseline-reproduction.txt`；该文件明确是实测摘要，不冒充完整原始 traceback。
没有重建或修改审核探针，没有删除测试、削弱断言或增加 xfail。

## 3. P1-1：取消收尾机制及边界证明

原因：原实现捕获 ProviderCancelledError 后无期限等待 Sink，且普通 `except Exception` 无法处理第二次 CancelledError。再次取消会替换顶层诊断载体。

采用最小的同协程收尾：

1. 保留 Provider 传来的原 ProviderCancelledError 对象；已经产生的 Attempts 不重建为额外网络请求。
2. Sink 前将完整 Trace dump/reparse，创建安全副本，并把独立 JSON 副本放入取消异常的 `trace_diagnostic`。Sink 失败也不丢失这份可获得的诊断。
3. 在当前 service task 内 `asyncio.timeout(0.1)` 包围一次 `TraceSink.write()`，不创建子任务、不 shield、不手工 uncancel。
4. 正常返回记 `trace_write_status=written`；普通异常为 `failed`；期限到达为 `timed_out`；再次取消或 Sink 自身取消为 `interrupted`。后三者记录 `TRACE_PERSIST_FAILED`，日志只含内部 trace_id、状态和 Attempt 数。
5. 收尾捕获再次取消后不再 await，抛回原 ProviderCancelledError。测试使用 `is` 验证原对象身份，且 task.cancelled() 为 true。没有把取消变为 ProviderError 或业务 unknown。
6. 对模型已完成、取消发生于正常成功/失败 Trace 写入中的情况，也用取消载体保留此前 succeeded/failed Attempts；不伪造 cancelled 网络 Attempt。

为什么不会留下失管任务：write 与 service 共用一个协程栈；超时或再次取消直接展开 write 的 finally。没有额外 task/Future 的后台所有权和回收问题。测试在 service 结束后检查 `asyncio.all_tasks()`，再用同一个 Provider 发起下一次真实 HTTP 验证许可可复用。

为什么不继续重试：Provider 原有 semaphore finally 在进入 Service 收尾前已释放；收尾方法不调用 Provider。backoff 取消探针仍只观察到先前的一次失败 HTTP。

**有界保证的前提**：Sink 是协作式异步实现，正常让出事件循环，并在收到取消后及时清理、传播；已在 TraceSink 协议注释说明。对于 Event.wait/正常异步 I/O 阻塞，内部 100 ms deadline 会打断等待。同步阻塞事件循环或无限吞掉 CancelledError 的任意代码无法由进程内 asyncio 强制终止；本实现不声称对这类失效适配器提供硬实时保证，未来适配器必须验证这一要求。100 ms 是本轮尽力诊断收尾预算，测试 300 ms 是外部观察窗口，均不等于数据库 SLA。

**持久化声明**：written 仅表示适配器返回；当前适配器为 InMemoryTraceSink。failed/timed_out/interrupted 表示写入没有成功确认，可能有适配器侧部分副作用，不能推断数据库提交或回滚。安全副本仅由调用方持有，不是耐久存储；进程退出会丢失。本轮未实现 TraceStore。

取消专项证据：

| 情况 | 顶层结果 / 写入状态 | 当前调用 HTTP / Attempt / 确认保存 Trace |
|---|---|---|
| 普通异步 Sink 成功 | 同一取消异常 / written | 1 / 1 cancelled / 1 |
| Sink RuntimeError | 同一取消异常 / failed；安全日志 | 1 / 1 cancelled / 0 |
| Sink 永不置位 Event | 同一取消异常 / timed_out；<300 ms 完成 | 1 / 1 cancelled / 0 |
| Sink 进入后连续第二、第三次 cancel | 同一取消异常 / interrupted | 1 / 1 cancelled / 0 |
| Sink 自身抛 CancelledError | 同一取消异常 / interrupted | 1 / 1 cancelled / 0 |
| 成功 HTTP 后取消正在写入的 Sink | CancelledError 子类 / timed_out | 1 / 1 succeeded / 0 |
| 失败 HTTP 后取消正在写入的 Sink | CancelledError 子类 / timed_out | 1 / 1 failed / 0 |

前五个新增场景逐项验证 finally 已执行、无存活子任务、semaphore=1，随后独立新调用 HTTP/Attempt/Trace=1/1/1。原审核 raise/block/repeat_cancel 三项也全部通过。

## 4. P1-2：统一全诊断出口

原因：原 sanitizer 位于具体 Qwen 类，只有 raw 的部分调用路径使用。SDK 异常 str 中的 Python repr、Service 的业务校验错误、其他诊断副本绕过了它。

统一策略在 core/diagnostics.py：按敏感 key 递归清洗 dict/list/tuple；处理纯 JSON 字符串、嵌入文本中的 JSON/Python repr 键值、自然语言 `password is` / `token is` / `API key is`、Authorization Bearer 和带引号的值。输出为新副本，替换为 `[REDACTED]`，测试递归性、幂等性和不修改输入。普通 route/intent/status/error_code/request_id 仍保留。

SDK APIError 优先读取类型、HTTP 状态和结构化 body，脱敏后构造有界摘要；无 body 时仅记录类型等可得结构，不信任 str(exc) 的 repr。其他普通异常经过相同文本策略。Provider/Service 包装异常使用 `from None`，防止默认 traceback 又显示原始 SDK/Pydantic/business 错误。不会清除运行期原对象内存；显式遍历 Python `__context__` 或调试器读取原始业务数据不属于安全诊断接口。

| 诊断出口 | 处理及验证 |
|---|---|
| TraceRecord.text / request_id | Trace 构造及 Sink 边界统一脱敏；text 正常/取消探针通过；业务 IntentResult.text 保持原文 |
| LLMAttempt.raw_request（含 Prompt） | Attempt 构造清洗并限长；真实 Server 同时确认收到原始测试秘密 |
| LLMAttempt.raw_response | 递归清洗及限长；不改 completion.content |
| LLMAttempt.parsed_payload | Attempt 诊断副本清洗及限长；Service 仍从原始 response.content 解析和校验 |
| LLMAttempt.params | 同一构造边界，含取消场景的合法 user 参数 |
| ProviderError.message / args | 构造时统一 error_summary；结构化 SDK body、repr、2 MiB 探针 |
| LLMAttempt.error_message | 同一策略，成功/失败/取消 Attempt 均走模型边界 |
| IntentServiceError / TraceRecord.error_message | 业务 Intent 名称、结构错误、解析错误都不暴露原始错误链 |
| validation_issues.slot | Sink 前对 dump 后的嵌套数据清洗；新增 SLOT_SPAN_INVALID 含敏感 slot.value 测试 |
| metadata / usage / model 等 Attempt 字段 | 同一递归策略，普通 metadata/usage 与标识保留；原 HTTP metadata 断言通过 |
| ProviderCancelledError.attempts / trace_diagnostic | 已脱敏 Attempt 重解析及安全 Trace 副本；与普通出口同策略 |
| 日志、异常 traceback | 不打印原 Sink 异常；现有 JSON formatter 同策略；INFO/stdout/stderr 原探针三项、formatter 和三类 traceback 新测试 |

新增业务隔离测试：同一含凭据标签的 slot 在输入确实存在时，业务输出保留原 slot/value/span；不存在时仍按原 Contract 丢弃，并在脱敏后的 validation_issues 中保留 SLOT_SPAN_INVALID。没有为通过脱敏改变业务校验的输入或规则。

## 5. P2 诊断长度

- 错误摘要上限：`ERROR_SUMMARY_MAX_BYTES=4096`，涵盖 ProviderError、ServiceError、Attempt/Trace error_message；超限后缀 `...[truncated=true]`，标记也计入上限。
- raw_request/raw_response、parsed_payload、params、usage：使用现有 Contract 的 `TRACE_RAW_MAX_BYTES`，默认 65,536 bytes。整个字段超过上限变为 `{"truncated": true, "preview": "..."}`，保持原字段为 dict，无数据库结构变更。
- 以 `json.dumps(..., ensure_ascii=False)` 的 UTF-8 字节计数；preview 的 JSON 转义和封装开销也计算在内。截断时只保留完整 Unicode 字符。未来持久化应保持相同 UTF-8 序列化口径，若使用 ASCII 转义/外层再封装，需计算该层额外开销。
- 新测试用 `TRACE_RAW_MAX_BYTES=1024`，覆盖中文、emoji、换行、引号、反斜杠和截断幂等性；真实 HTTP 同时验证截断 raw/payload 不改变业务 result。
- 原 2 MiB 错误摘要探针通过，本轮关闭其本地复现问题，不把长度修复整体推迟到 TASK-103。
- 大字段截断后细节只保留 preview，不能再把该字段当完整模型 payload 使用；Route/Attempt 状态/错误码等独立字段不被截断包替换。限制作用于诊断副本，不限制 SDK 接收原始响应时的峰值内存。

## 6. 原 32 项探针及真实 HTTP 计数

最终仍执行原文件，退出 0：

```text
uv run --locked --extra dev pytest -o addopts='' -q -rs --tb=short --junitxml=../review_artifacts/task102_second_fix/probes-results.xml ../review_artifacts/task102_incremental/test_review.py
................................                                         [100%]
- generated xml file: D:\akae\AICoach\review_artifacts\task102_second_fix\probes-results.xml -
32 passed in 27.30s
```

原失败 8 项 P1 + 1 项 P2 全部转绿，原通过的 23 项无回归。未发现需要调整的审核断言。

| 探针组 | 数量 / 结果 |
|---|---|
| HTTP matrix | 7 passed |
| 两种 Structured Output | 2 passed |
| 在途/backoff/排队取消及排队超时 | 4 passed |
| Sink raise/block/repeat_cancel | 3 passed |
| sanitizer 负例及标识保留 | 5 passed |
| 全诊断出口 | 6 passed |
| 2 MiB 长度 | 1 passed |
| connect refusal | 1 passed |
| INFO 日志 success/error/cancel | 3 passed |

计数来自真实 localhost ThreadingHTTPServer 与实际 AsyncOpenAI/httpx；没有替换 SDK create。每项正常结束或 Provider 错误的 Service 调用写入一条内存 Trace：

| 场景 | Server 收到 HTTP | Attempts | 内存 Trace | 终态 |
|---|---:|---:|---:|---|
| 200 | 1 | 1 | 1 | success |
| 429 → 200 | 2 | 2 | 1 | success |
| 5xx 上限 | 3 | 3 | 1 | MODEL_PROVIDER_ERROR |
| timeout（0.2s 响应，0.05s timeout，retry=1） | 2 | 2 | 1 | MODEL_TIMEOUT |
| 400 | 1 | 1 | 1 | MODEL_PROVIDER_ERROR |
| retry=0 的 500 | 1 | 1 | 1 | MODEL_PROVIDER_ERROR |
| 收到 POST 后断开 TCP | 2 | 2 | 1 | MODEL_PROVIDER_ERROR |
| 在途取消 | 1 | 1 cancelled | 1 | CancelledError 子类 |
| backoff 取消 | 1 | 1 failed | 1 | CancelledError 子类 |
| 排队取消/超时（仅被排队调用） | 0 | 0 | 1 | CancelledError / SERVICE_BUSY |
| connect refusal | 0 | 2 failed | 接入内存 Sink，原探针未单独断言行数 | MODEL_PROVIDER_ERROR |

connect refusal 使用已 bind 未 listen 的端口；客户端 request hook=2，不能把这两次连接尝试冒充服务端接收 HTTP。matrix 逐次验证 SDK retry header=0、attempt_no/is_retry，成功响应验证 request id/model version/fingerprint/finish_reason/usage。
C12 两种模式均不发 max_tokens，strict schema 检查仍通过，无静默降级。

## 7. 全量门禁实际输出

工作目录：`D:\akae\AICoach\backend`。以下三条均退出 0，原始输出分别保存在 second_fix 下的 ruff-output.txt、format-output.txt、pytest-output.txt。

```text
uv run --locked --extra dev ruff check .
All checks passed!

uv run --locked --extra dev ruff format --check .
45 files already formatted

uv run --locked --extra dev pytest -q -rs
....................................................................ss.. [ 75%]
........................                                                 [100%]
============================== warnings summary ===============================
.venv\Lib\site-packages\fastapi\testclient.py:1
  D:\akae\AICoach\backend\.venv\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ===========================
SKIPPED [2] tests\test_mysql_integration.py:57: MYSQL_TEST_DATABASE_URL is not configured; MySQL 8 integration tests are skipped
```

pytest 配置已有 `-q`，原样门禁不会输出 passed 总数；另用 `--collect-only -q` 核对 96 项（见 collection-output.txt），结合上述无失败、2 skip，结果为 **94 passed / 2 skipped / 1 warning**。未为显示总数重复运行整套测试。

新增测试 25 项，原仓库测试 71 项保持。开发中两项新增 slot 测试最初因 fixture 误用非训练空 intents 而额外产生 INTENTS_EMPTY_NON_TRAINING；修正 fixture 为配置内 query_progress，保留完整原断言，未更改业务实现消除这条正确诊断。

两个 skip 均为既有测试：

- `test_mysql_migration_bootstrap_constraints_and_readiness`：未配置 MYSQL_TEST_DATABASE_URL，未运行隔离库 migration/bootstrap/readiness。
- `test_mysql_release_fingerprint_revision_preserves_existing_releases`：同一缺失条件，未运行历史 Release 保留验证。

Warning 为既有 FastAPI/Starlette TestClient httpx 弃用提示。本轮没有新加 skip/xfail/noqa。

## 8. DoD、外部参考与未完成项

| 项目 | 本轮结论 |
|---|---|
| 不依赖 FastAPI/MySQL 的 IntentService 完整单测 | 通过 |
| C11 真 HTTP/Attempt 数量、无 SDK 隐藏 retry | 通过，包括取消边界 |
| C12 构造与两种显式模式 | 本地通过 |
| 两个 P1 的独立原反例 | 本地全部通过，待独立人员复核 |
| 长度 P2 | 本地通过，无 DB 结构变更 |
| 全量 Ruff/Format/pytest | 通过，两个既有 MySQL skip 如上 |
| TASK-101 Runtime Contract | 回归通过，无 Schema/校验语义修改 |
| 真实 Qwen smoke | **UNVERIFIED**；本轮仅调用本地 HTTP Mock Server |
| TASK-102 关闭 / TASK-201 前置 | 未获独立批准，不满足开始下一 Task 的门禁 |

实际阅读：AGENTS、TASK-102 任务书、tasks/README、docs/02/03/06/09/10、两份独立审核、原执行报告，以及 Provider/IntentService/TraceSink/相关 Schema 和测试。

外部资料：

- 使用 OpenAI Docs 技能辅助核对；阅读 [锁定 SDK v1.109.1 官方 README](https://github.com/openai/openai-python/blob/v1.109.1/README.md) 的 Async、Retries、Timeouts、Request IDs、Raw Response，并检查本地安装 `_exceptions.py` 的 body/status/request_id 结构。未改 SDK 重试机制。
- 阅读 [Alibaba Structured Output 文档](https://help.aliyun.com/zh/model-studio/qwen-structured-output)，仅核对结构化输出与 max_tokens 边界；没有用文档冒充账户级 smoke。
- 阅读 [Python asyncio task/timeout 官方文档](https://docs.python.org/3.12/library/asyncio-task.html)，作为同任务超时、取消传播及协作式取消限制的依据。
- 未再次参考第三方 classifier：docs/09 将其列为可选局部资料，本轮没有新 Provider 设计，不复制 retry/sync client，不引入新依赖或大型日志框架。

仍存在的边界/风险：

1. 对不协作的 Sink 无进程内强制终止保证；未来 DB 适配器必须验证取消清理时限、事务语义和耐久性，不能把当前内存测试当成数据库保证。
2. 普通未取消写入的完整超时/Runtime 与 Debug/Replay/Eval 区分、保留期/清理和 DB Trace 属于 TASK-103，本轮未实施，也未宣称 C14 完整验收。
3. 统一策略覆盖明确标签/结构及本次已知秘密，不承诺识别任意无标签的秘密。第三方自定义日志 handler 或主动打印原始业务对象，仍须在接入时审计；本轮覆盖项目 formatter 和默认 INFO 出口。
4. SDK 原始响应、业务 request/content 在运行期必须保留用于发送和校验；诊断上限不是网络响应体或进程峰值内存上限。
5. ProviderError 对具体 Qwen 类的耦合（原 P2-1）按本轮范围保留；新增 Provider 前再处理。
6. 真实 Qwen 兼容性、隔离 MySQL、TASK-201/103 接口联查未完成。当前只交付修复证据，等待独立增量复核后再作后续决策。
