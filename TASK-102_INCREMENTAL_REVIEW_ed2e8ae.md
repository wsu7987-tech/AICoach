# TASK-102 修复后独立增量复核 — ed2e8ae

**结论：FAIL。TASK-102 不允许关闭，TASK-201 前置条件未满足。**

修复对两个原 P1 均有实质改善，但没有完成端到端修复：取消诊断能到达立即返回的 InMemoryTraceSink，遇到阻塞或再次取消则没有受控收尾；已知自然语言秘密能从 raw 字段中移除，但完整 Attempt、Trace 和错误消息仍泄露相同秘密。本次仅审核并保留可重跑证据，没有修改业务代码或实施 TASK-201。

## 1. 基线与范围

- 审核 HEAD：`ed2e8ae4eb329d4314e0347ca8d781f216bb8dc7`。
- 原始提交：`ed30115e169fb4234789f37ba61d2d2bb68d220a`。
- 完整增量：6 files changed, 235 insertions(+), 11 deletions(-)。逐一读取了 execution report、providers/__init__.py、qwen.py、types.py、intent_service.py、test_provider_contract.py 的差异。
- 初始工作区只有未跟踪的 `TASK-102_INDEPENDENT_REVIEW.md`；未覆盖、移动或暂存它。审核前后 SHA256 相同：`BF51794115291EA9A044B0EF7EB6FC49F0D63CB3F0733B130DFD59AF54CD76D8`。
- `git diff --check ed30115..ed2e8ae` 通过。没有修改已有业务文件、测试、执行报告或 lockfile。
- 阅读 AGENTS、TASK-102、tasks/README、docs/02/03/06/09/10、原独立审核、执行报告、Provider/Service/Schema/PromptBuilder 相关代码及全部 Provider 测试。所谓新增 Sanitizer 实际仍是 `QwenProvider.sanitize` 静态方法，没有独立统一出口。
- 环境仅检查变量存在性：`DASHSCOPE_API_KEY=absent`、`MYSQL_TEST_DATABASE_URL=absent`。**REAL_QWEN_SMOKE=UNVERIFIED**。

## 2. 阻断发现

### P1-1：取消收尾仍可无限等待，重复取消丢失诊断载体

位置：`backend/app/services/intent_service.py:134`、`:137`、`:192`、`:194`。

`ProviderCancelledError` 被捕获后直接 `await self._persist_failure(trace)`；后者直接等待 Sink，没有 deadline、取消保护或受管理的收尾机制。`except Exception` 只能处理普通异常，不能保护第二次 `CancelledError`。

独立真实 HTTP 反例：

1. 本地 Server 已收到 POST，暂不返回响应；取消 service task。
2. Provider 产生一个 cancelled Attempt，并释放 semaphore；Sink 的 `write()` 进入一个永不置位的 `asyncio.Event.wait()`。
3. 使用不会取消被测任务的 `asyncio.wait({task}, timeout=0.3)` 观察：任务仍停在 service 第 137 行，未传播取消。0.3 秒是观察窗口，不是私自规定的生产 deadline；结合代码无任何内部 timeout、Event 永不返回，可确认该路径无结束保证。测试最后主动取消并 await 清理，未留下任务。
4. 在 Sink 已进入写入后再次 `task.cancel()`：调用方得到普通 `CancelledError`，原 ProviderCancelledError 的 `.attempts` 不再是顶层异常载体，Sink 保存数为 0。没有新增 HTTP。

测试：`test_cancel_sink_failure_boundary[block]`、`[repeat_cancel]`，均失败。立即抛出 RuntimeError 的 Sink 测试通过：异常被吞掉，原 ProviderCancelledError 继续传播，但没有持久化成功的证据，也没有失败观测记录。

**最小修复要求：**为取消诊断写入定义有界收尾，处理重复取消，保留原 Attempts/取消语义并记录写入失败；若使用 shield/子任务，必须持有、取消并回收它们，不能留下失管后台任务。补上这三类 Sink 行为测试。这里要求修复当前 service 协议边界，不要求提前实现数据库。

### P1-2：统一脱敏并未覆盖全部诊断出口

位置：`backend/app/providers/qwen.py:114`、`:125`、`:238`、`:272`、`:294`；`backend/app/services/intent_service.py:115`、`:153`、`:194`。

独立负例使用用户指定的四种测试文本，以及 JSON password/token/api_key、嵌套 dict/list、Prompt content 和模型 response。全部都是虚构凭据。

| 实际出口 | 实测结果与原因 |
|---|---|
| `raw_request` / 成功 `raw_response` | 已知自然语言与嵌套 JSON 秘密被替换成 `[REDACTED]`；这部分修复有效 |
| `TraceRecord.text` | 原始 `request.text` 直接保存；四个测试秘密仍在 Sink 中。正常成功和新取消路径都复现 |
| `LLMAttempt.parsed_payload` | 成功响应 content 直接 JSON parse，没有 sanitize；模型 `reason_summary` 含测试秘密时，raw_response 已脱敏，但同一 Attempt 的 parsed_payload 与 Sink 仍泄露 |
| `LLMAttempt.params` | `_safe_params` 只排除 messages/model，未脱敏。合法请求参数 `user=测试文本` 在 cancelled Attempt 和 Sink 中保持原文；真正发送请求与 sanitized raw_request 的值不同，证明诊断副本未统一处理 |
| Provider 异常文本 | 本地 400 返回 `{"error":{"password":...,"nested":[{"token":...},{"api_key":...}]}}`。SDK `str(exc)` 是 `Error code: 400 - {'error': ...}` 的 Python repr；既非纯 JSON，又因引号阻断现有正则，秘密进入 ProviderError.message、Attempt.error_message、TraceRecord.error_message。raw_response 的结构化脱敏不能保护这些副本 |
| Service 业务校验错误 | 模型输出不存在的 intent name `password is Tr0ub4dor`；`str(BusinessOutputValidationError)` 直接成为 service/trace 错误文本，没有经过 Sanitizer |

测试：`test_full_diagnostic_redaction` 的六个参数案例全部失败。`cancel_trace`、`cancel_params` 明确覆盖新取消链路，没有把取消场景排除在安全审核外。

**最小修复要求：**让所有准备交给 Sink 的诊断字段经过同一递归脱敏策略，包括 text、parsed_payload、params、validation diagnostics、各层 error_message；Provider 暴露的 Attempt 与错误字符串也应安全。SDK 错误优先从结构化 body 构造安全摘要，避免直接把带 repr 的 str(exc) 当成已安全文本。脱敏应作用于诊断副本，保持真正发送的业务请求和用于业务校验的原始模型内容不变。

这不是要求正则识别所有可能秘密：失败样例正是指定的已知标签和当前 SDK 实际生成的错误格式。

### 补充：诊断长度要求未满足（P2-2，原有边界，不作为新增独立 P1）

`sanitize`、LLMAttempt 字段、`_safe_error_message` 和 Sink 出口均没有长度限制。真实本地 400 响应提供 2 MiB message，实测 `ProviderError.message` 长度 **2,097,196**，整个内容保留；同样进入 Attempt/Trace，未标记 truncated。`test_diagnostics_have_size_limit` 失败。

2 MiB 只是探针，不是本审核定义的新 Contract 限额。执行报告将 raw-size retention 放在 TASK-103；本次如实记录当前“不存在明确长度上限”，不将未来数据库功能缺失单独升级为 P1。后续必须定义/落实 `TRACE_RAW_MAX_BYTES` 与截断标记，错误摘要也应有界。

原 P2-1（Service 仍依赖 Qwen 的 ProviderError）未改变，继续保持非阻断，新增 Provider 前处理。

## 3. 取消专项逐项结论

| 要求 | 观察结果 | 判定 |
|---|---|---|
| A：请求在途取消 | Server 确认收到 1 请求后才取消；1 个 cancelled Attempt，attempt_no=1/is_retry=false、latency>0、provider/model 正确；Sink 接收同一 Attempts，cancelled=true；任务最终处于 cancelled 状态，传播 CancelledError 子类；没有重试 | 基本路径 PASS |
| A：可获得 metadata | 此场景 Server 未返回 headers，request_id/raw_response 等为 null，未编造；成功场景验证 request id/model/fingerprint/finish_reason/usage；backoff 保留前次失败 request id | PASS 于本地可观测边界 |
| B：backoff 取消 | 通过协程实际已生成失败 Attempt 后才取消，非仅凭固定 sleep 猜测；1 HTTP、1 failed Attempt；Sink 保存；无第二次请求 | PASS |
| C：并发排队取消 | 首请求占满 semaphore，第二请求取消；被取消调用 0 Attempts、0 新 HTTP，Sink 记录空 Attempts；首请求完成后第三请求正常，许可回到 1 | PASS |
| D：Sink 普通异常 | 立即 RuntimeError 不会卡住或转换为业务 unknown；取消继续传播，但写入失败被静默吞掉 | 有限 PASS |
| D：Sink 阻塞/重复取消 | 无超时边界；重复取消中断保存并丢失顶层诊断载体 | FAIL / P1-1 |
| D：后台任务 | 当前业务实现没有 create_task/fire-and-forget；独立探针清理后无存活异步任务 | PASS，不抵消缺少有界收尾 |

InMemoryTraceSink 的 write 只有 list.append，不包含等待点，能证明 Service 把 Attempts 交到了内存适配器。它不能证明数据库事务提交、断连恢复、进程退出后的耐久性、原子性或写入 deadline，也不能模拟异步 I/O 中的再次取消。**内存写入成功不等于未来数据库持久化已获保证。** 本次不声称验证了 TASK-103 的 DB Trace/C14 完整行为。

## 4. C11/C12 真实 HTTP 回归

独立文件使用新建 `ThreadingHTTPServer`，真实 AsyncOpenAI/httpx 网络栈；没有 mock SDK create，也没有复用原测试的 HTTP fixture。每次调用结束均关闭 client，服务端资源和取消任务均清理。

| 场景 | Provider max_retries | Server 实际收到 | 可观察 Attempts | 结果 |
|---|---:|---:|---:|---|
| 200 | 0 | 1 | 1 | information_query，metadata/usage 正确 |
| 429 → 200 | 1 | 2 | 2 | 成功，序号 1/2，retry flag false/true |
| 5xx 上限 | 2 | 3 | 3 | MODEL_PROVIDER_ERROR |
| timeout（每次延迟 0.2，timeout 0.05） | 1 | 2 | 2 | MODEL_TIMEOUT |
| 400 | 2 | 1 | 1 | MODEL_PROVIDER_ERROR，不重试 |
| 重试配置为 0，500 | 0 | 1 | 1 | MODEL_PROVIDER_ERROR |
| 收到请求后断开 TCP | 1 | 2 | 2 | MODEL_PROVIDER_ERROR |
| 在途取消 | 2 | 1 | 1 cancelled | 无额外 retry，随后新业务调用成功 |
| backoff 取消 | 1 | 1 | 1 failed | Sink 保存前次失败 |
| 排队取消/排队超时 | 0 | 排队调用新增 0 | 排队调用 0 | 分别 CancelledError/SERVICE_BUSY；许可可复用 |
| TCP connect refusal | 1 | 0（无监听 HTTP Server） | 2 failed | httpx request hook 观察 2 次客户端调用尝试；MODEL_PROVIDER_ERROR |

最后一行用已 bind 但未 listen 的 localhost socket 保留端口，确保没有 HTTP Server 收到请求。**2 条 Attempt 代表连接失败的网络调用尝试，不代表服务端收到 2 次物理 HTTP。** 未把客户端 hook 计数冒充 Server 接收计数。

全部矩阵调用实际检查 SDK `max_retries=0`；Server 收到的 `x-stainless-retry-count` 每次均为 `0`，与 Provider 自己的重试和请求计数吻合。基础设施错误通过 IntentService 仍抛 typed error，未得到 unknown 业务结果。

C12：两种模式真实提交 body 均不含 max_tokens；json_schema strict=true，无 minItems；对照本次官方文档明确不支持的关键字列表，也未发现 multipleOf/uniqueItems/contains/minContains/maxContains/additionalItems/patternProperties/propertyNames。json_object 显式提交且 Prompt 包含 JSON。仓库既有 tests 进一步验证模型配置拒绝 max_tokens、400 后不静默切换模式、parse/schema 错误分离。

本次 C12 本地构造回归通过；本地 HTTP Server 不执行 Qwen schema 编译，不能证明真实账户/模型/地域兼容。官方当前文档对 minItems 的支持描述已变化，但本项目仍按固定 Contract 禁止发送，本次没有改 Contract。

## 5. 脱敏与日志验证范围

- 四种指定自然语言形式、Authorization Bearer、纯 JSON、嵌套 dict/list、Prompt 消息：直接 Sanitizer 独立负例通过。
- success/cancel 测试同时断言 Server 真正接收的四个秘密保持原值，诊断 raw_request 则为 `[REDACTED]`，证明没有改写模型业务请求。
- 成功 response 中的 reason_summary 经过 raw_response 清洗；parsed_payload 的独立副本失败，见 P1-2。
- route、intent、status、`INTENTS_EMPTY_NON_TRAINING`、request id 普通标识保留，未被误删。
- 三个独立 success/error/cancel 日志测试在默认 INFO 级别检查 caplog/stdout/stderr，未出现测试秘密。不能据此声称任意 DEBUG 配置、上层自行打印异常或未来 DB 日志都安全；本次没有虚构日志泄露已在默认运行中发生。

## 6. 工程门禁实际输出

在 `backend/` 原样执行，三条命令均退出 0：

```text
uv run --locked --extra dev ruff check .
All checks passed!

uv run --locked --extra dev ruff format --check .
43 files already formatted

uv run --locked --extra dev pytest -q -rs
...........................................ss..........................  [100%]
============================== warnings summary ===============================
.venv\Lib\site-packages\fastapi\testclient.py:1
  D:\akae\AICoach\backend\.venv\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ===========================
SKIPPED [2] tests\test_mysql_integration.py:57: MYSQL_TEST_DATABASE_URL is not configured; MySQL 8 integration tests are skipped
```

项目 pytest addopts 已含 `-q`，原样命令不显示总数。为准确核对数量和 skip 名称，另执行一次取消默认 addopts 的同一套件并导出 JUnit：

```text
uv run --locked --extra dev pytest -o addopts='' -q -rs --junitxml=../review_artifacts/task102_incremental/repository-results.xml
69 passed, 2 skipped, 1 warning in 26.02s
```

仓库测试总计 71：**69 PASS / 0 FAIL / 2 SKIP / 1 Warning**。两个既有 MySQL 测试均因隔离库变量未配置而 skip，没有连接共享数据库，且不自动构成本次阻断：

- `test_mysql_migration_bootstrap_constraints_and_readiness`：缺少 MYSQL_TEST_DATABASE_URL，未运行 migration/bootstrap/readiness 隔离库测试。
- `test_mysql_release_fingerprint_revision_preserves_existing_releases`：同样缺少 MYSQL_TEST_DATABASE_URL，未运行历史 Release 保留的迁移测试。

Warning 为 FastAPI/Starlette TestClient 的 httpx 弃用提示。

最终独立增量探针：

```text
uv run --locked --extra dev pytest -o addopts='' -q -rs --tb=short --junitxml=../review_artifacts/task102_incremental/final-independent-results.xml ../review_artifacts/task102_incremental/test_review.py
9 failed, 23 passed in 26.94s
```

共 32 项：**23 PASS / 9 FAIL / 0 SKIP / 0 Warning / 0 collection errors**，pytest 退出 1。失败是受测实现不满足断言，没有 xfail 或放宽门禁。9 项分布：取消 Sink 2、诊断脱敏 6、长度上限 1。第一次 28 项探针的中间结果也保留，最终以上述 32 项为准。

## 7. DoD 与关闭决定

| 项目 | 结论 |
|---|---|
| 无 FastAPI/MySQL 的完整 Service 单测 | PASS |
| 200/retry/timeout/400/connection/queue 错误分类、不伪装 unknown | PASS |
| C11 常规请求与 Attempt 对应、SDK 不重试 | PASS；完整取消持久化边界 FAIL |
| C12 请求构造和模式回归 | PASS locally；真实 Qwen UNVERIFIED |
| P1-1 修复完整性 | FAIL：A/B/C 修复有效，D 未完成 |
| P1-2 修复完整性 | FAIL：raw 脱敏有效，完整诊断仍泄露 |
| 诊断明确长度上限 | 未满足，须记录并补齐 |
| 仓库三项工程门禁 | PASS，不能替代独立负例 |
| TASK-102 允许关闭 | **否** |
| TASK-201 允许开始 | **否**；留在 TASK-102 修复和复审 |

本次实际文件变更：新增本报告；新增 `review_artifacts/task102_incremental/test_review.py` 及三次测试运行的 output/JUnit 文件（repository、independent、final-independent）；仅更新 PROJECT_STATUS 中 TASK-102 的审核状态。原独立报告、执行报告、业务代码与原测试保持原样，未提交或暂存。

## 8. 外部参考与未验证项

- 使用 OpenAI Docs 技能辅助核对；本项目明确要求的 [OpenAI Python v1.109.1 官方 README](https://github.com/openai/openai-python/blob/v1.109.1/README.md) 中 Async、Retries、Timeouts、Request IDs、Raw Response 已阅读，并检查安装版本 `_base_client.py` 的实际异步请求循环。SDK 默认重试说明只是背景，禁用结果以此次 Server 计数和 retry header 为证据。
- 阅读 [Alibaba Structured Output 官方文档](https://help.aliyun.com/zh/model-studio/qwen-structured-output) 的 strict/schema 关键字和 max_tokens 约束。文档不能替代真实 smoke；未对账户权限、地域或实际 Qwen schema 接受行为作 PASS 声明。
- 未再次参考第三方 classifier 实现：这次是既定两项 P1 的增量安全/取消审核，无新 Provider 设计，第三方业务和 retry 实现不构成验收依据。没有复制代码或增加依赖。
- DB Trace 原子提交、清理、耐久性和完整 Runtime/Admin 持久化策略未验证，属于后续 TASK-103；TASK-201/103 接口联查仍需执行。此次证据仅证明当前可观察行为，不预先签署未来实现。

存在执行报告“error paths all use this same sanitizer”的描述与实测不一致；本报告记录差异并保持 FAIL，没有修改 Contract 或擅自修复业务代码。
