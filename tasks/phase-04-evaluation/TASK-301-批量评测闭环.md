# TASK-301 批量评测闭环

## 依赖

TASK-202

## 阅读

- `docs/05-评测与验收方案.md`
- `assets/AI_Coach_意图识别评估集_极简版_v0.5.xlsx`
- `docs/09-参考项目与采用策略.md` 中 Promptfoo / EpochFlow evaluator / MASSIVE（可选压测）

## 目标

完成 Excel -> Dataset -> Run -> DB Worker -> Metrics -> FAIL Trace -> Export 的生产闭环。

## 导入

解析产品列：

- 用例编号
- 用户原话
- 期望一级路由
- 期望二级意图（可选）
- 期望追问内容/目标（可选）
- 备注

- 一级 Route 按 name/zh 映射；二级 Intent 按 name/zh/aliases 映射。规则以 `docs/05 §3` 为准：非训练行无匹配/多匹配/与一级路由不一致 → 导入阶段直接报可读错误；训练行二级意图不匹配只 warning。
- 模板 v0.5 的“期望二级意图”39 个下拉值 + 7 个一级路由全部能被 Bootstrap 配置匹配（写成自动化测试）。
- 文件/行列错误要可读。
- Dataset 计算 hash/version。

## Run 创建/冻结

创建 Run 必须选择 Dataset、Config Release（默认 Active/可选历史）、可选 Model Config Override、Repeat 1/3/5、Worker Concurrency，并立即冻结 dataset_hash、release_id、config_snapshot_hash、release_fingerprint、effective_model_config_id/model_config_hash/snapshot、repeat_count。

## Worker

- Run 状态存在 MySQL。
- 多 Pod claim，不重复执行。
- heartbeat/stale recovery。
- Case 结果幂等。
- concurrency 可配置。
- cancel 在 Case 边界生效。
- 每次 Case 调生产 IntentService 并产生 Trace。

## 判定

- training：只比较 route。
- 其他：route；expected intent 非空时固定比较 `actual.intents[0].name`（Top-1），后续候选不算命中。
- expected clarification 非空：要求 `need_clarification=true`；为空：要求 `need_clarification=false`；目标文本只人工 review，不用 LLM Judge。

## 指标/页面

- 主 Benchmark 指标统一使用每 Case `repeat_index=0`；额外 repeat 只用于 stability/distribution
- route accuracy
- 一级 Route confusion matrix
- per-route precision / recall / F1 + macro-F1
- safety recall
- secondary intent accuracy
- clarification trigger accuracy
- schema valid/error rate
- Avg/P95 latency
- route stability：同一 Case 所有 repeat 一级 Route 完全一致为 stable，并展示 Route 分布
- Case list / FAIL / ERROR / jump Trace
- Run compare：仅同一 `dataset_hash`，展示指标差异、混淆矩阵、逐 Case `PASS->FAIL/ERROR` 回归与 `FAIL/ERROR->PASS` 改善；repeat>1 同时展示通过数/Route 分布

## 导出

保留原列 + actual/pass/error/request_id/trace_id/latency/repeat。

## 测试

- Excel 正/反例（含：下拉全量值导入通过、route 与 intent 不一致报错、训练行 intent 不匹配仅 warning）
- 评测结果行在 Trace 被 cleanup 后仍可展示/导出（trace 显示“已过期”）
- 300 条 mock run
- worker restart recovery
- duplicate claim protection
- repeat 1/3/5 + frozen Release/Model，Active Release 后续切换不影响 Run
- training special rule
- Top-1 secondary intent（expected 只出现在 intents[1+] 仍 FAIL）
- clarification 正向/反向触发判定（expected 为空但模型追问必须 FAIL）
- confusion matrix + per-route P/R/F1 计算
- same-dataset Run compare + case flip
- export round-trip basic validation

## DoD

评估集可以稳定批跑；Pod 重启不静默丢 Run；所有结果可追溯；研发可直接比较同一 Dataset 的两个 Run 并看到一级 Route 混淆矩阵与逐 Route P/R/F1。
