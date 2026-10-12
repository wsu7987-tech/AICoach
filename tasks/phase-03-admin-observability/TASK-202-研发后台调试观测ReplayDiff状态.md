# TASK-202 研发后台：调试 / 调用观测 / Replay / Diff / 服务状态

## 依赖

TASK-103, TASK-201

## 阅读

- `docs/04-后台页面与交互设计.md`
- `docs/09-参考项目与采用策略.md` 中 OpenTelemetry GenAI semantic conventions / jsondiffpatch / Langfuse/Phoenix 概念参考

## 目标

一次完成研发诊断闭环，不拆成多个平台化子任务。

## 单条调试

支持：

- text
- release（Active/历史）
- model config override（可选）
- repeat 1/3/5

每次 repeat 独立 trace_id。显示：Runtime result、reason/evidence、Prompt、Attempts、Raw、Validation、latency/token/error、稳定性分布。

## 调用观测

列表+过滤：request_id、trace_id、keyword、route、model、release、time、status。

详情：

- Runtime Result
- Config/Model snapshot
- Prompt
- Attempts
- Raw Request/Response
- Parsed/Validation
- Reason/Evidence
- Timeline/Error

## Replay

- historical snapshot replay
- current active release replay
- model override optional
- repeat 1/3/5
- new trace_id + parent_trace_id

## Diff

两 Trace 对比：

- input
- release/hash
- prompt hash/final prompt
- model config
- provider metadata
- attempts
- raw response
- parsed/final result

后端返回结构化 diff flags。前端可优先验证 `jsondiffpatch` 做 JSON/长文本可视化；若引入需固定版本并加组件测试，不兼容则退回简单高亮。不得为 Diff 建设独立平台。

## 服务状态

轻量页面：API/DB、Active Release、default model、24h count/error、Avg/P95、evaluation queued/running。

## 测试

- debug override 不影响 Runtime default
- replay lineage
- identical prompt/model but different provider response 可标记 Provider divergence
- admin trace 查询权限边界由部署 Task 最终验证

## DoD

研发可从单条问题一直定位到具体 Provider attempt，并可重复/对比验证非确定性。
