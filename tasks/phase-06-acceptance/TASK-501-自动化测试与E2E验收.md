# TASK-501 自动化测试与 E2E 验收

## 依赖

TASK-401

## 目标

补齐跨模块测试并形成可重复上线验收报告。

## CI 自动化

Backend：

- Contract tests
- PromptBuilder
- Provider async client + SDK `max_retries=0` + retry/error/sanitizer + structured-output no-`max_tokens`
- IntentService
- Config Release/model config immutability + disable contract + release fingerprint
- Runtime API
- Trace attempts + SDK retry disabled + Trace fail-open/fail-closed + retention/truncation
- Replay/Diff
- Evaluation worker/recovery/judgement + frozen Release/Model + route stability + Top-1 intent + clarification 双向判定 + confusion matrix/P/R/F1 + Run compare

Frontend：

- Config publish critical flow
- Debug result/attempt display
- Trace detail
- Evaluation states
- Service status

CI 使用 Mock Provider，不消耗真实模型额度。

## E2E

1. clean MySQL migration
2. bootstrap draft（严格顶层 Schema，无 extra metadata）
3. `/ready` 已 ready；`runtime_config_ready=false`；Runtime 返回 `CONFIG_NOT_READY`，Admin 仍可访问
4. create Model Config
5. publish first Release；`runtime_config_ready=true`
6. debug “我要做深蹲”
7. inspect Trace / Attempt；真实 SDK retry 关闭
8. repeat 5 and stability
9. replay historical/current
10. diff traces
11. update Draft + publish new Release
12. verify new Runtime uses new Release
13. upload evaluation Excel
14. run evaluation + inspect FAIL Trace + export
15. verify confusion matrix + per-route P/R/F1
16. compare two Runs on same dataset，检查 PASS/FAIL/ERROR flip
17. direct Runtime HTTP call
18. restart backend; data persists and stale evaluation behavior is correct
19. business gateway can call Runtime but cannot access Admin API
20. active Model Config disable is rejected；切换 Active Release 后旧 Model Config 才可 disable
21. add/modify secondary Intent + alias/enum in Draft，依次 validate → Prompt Preview → 小规模回归 Evaluation → publish，Runtime 在 cache TTL 内切到新 Release，全程无需修改 Python 代码
22. running Evaluation 在 Active Release/Model enabled 状态变化后仍使用创建时冻结配置
23. trace persist failure：Runtime fail-open；Debug/Evaluation fail-closed
24. Trace cleanup 后 evaluation_case_result 仍存在，trace 链接显示“已过期”
25. real Qwen smoke：Structured Output 请求不发送 `max_tokens`；记录是否能取得 provider request id/raw header（不可用允许 null）

## 必测业务 Case

- 今天练胸 -> training_business
- 我要做深蹲 -> training_business
- 胸恢复了吗 -> information_query
- 深蹲怎么做 -> sports_knowledge
- 膝盖疼，但我还想练腿 -> safety
- 帮我连一下手表 -> dialogue_device_control
- 你好 -> social_chat
- unsupported/ambiguous -> unknown

业务 Case 的确定性 CI 使用 Mock Provider；另外执行一组**真实 Qwen smoke test**，验证 Provider/Structured Output/网络配置，不把真实模型结果作为 CI 唯一通过条件。

## 输出

生成 `ACCEPTANCE_REPORT.md`：

- 环境/version
- migration
- unit/integration/E2E results
- real provider smoke result
- known risks
- production rollout checklist

## DoD

核心失败会阻止发布；验收报告足以支持是否进入测试/生产环境的决策。
