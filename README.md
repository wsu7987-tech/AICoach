# AI Coach Intent Router 一期项目执行包 v1.2.4（生产执行封版）

> 定位：**以上线为目标的生产项目，不是 Demo。** “精简”仅表示减少不必要的平台化层级、依赖和重复任务；不降低 Runtime Contract、失败处理、Trace、配置版本、测试、部署和访问边界要求。

## 一期最终目标

完成一个可独立部署、可被现有 Java 微服务/设备侧通过 HTTP 调用的 Intent Router，以及供研发使用的轻量后台：

```text
文本输入
  -> Active Config Release
  -> Dynamic Prompt Builder
  -> Qwen/OpenAI-compatible Provider
  -> Structured Output + Pydantic Validation
  -> Runtime Intent JSON
  -> Trace / Evaluation
```

后台保留 5 个一级菜单：

1. 单条调试
2. 批量测评
3. 调用观测
4. 配置中心
5. 服务状态

## 一期必须完成

- `POST /api/v1/intent/analyze` 稳定 Runtime API。
- 7 个一级 Route；训练业务一期只验收一级 Route。
- 非训练业务可输出二级 Intent、Slots、Risk、Clarification。
- Prompt = 固定模板 + 已发布配置动态组装。
- Qwen/OpenAI-compatible Provider，优先 JSON Schema Structured Output。
- 每次 Provider Attempt 可追溯；Secret 必须脱敏。
- 在线配置：Draft -> Publish -> Immutable Release Snapshot -> Active Release -> History；历史版本可复制为新 Draft 再发布，实现安全回退。
- 单条调试支持 repeat 1/3/5。
- Trace 列表/详情，以及轻量 Replay/Diff。
- Excel 批量测评、PASS/FAIL、稳定性、导出。
- MySQL 8 持久化、Alembic Migration。
- Docker + Kubernetes 部署产物。
- Runtime/Admin 网关访问边界。
- 自动化测试、E2E、真实 Provider Smoke Test。

## 一期明确不做

- 语音、多模态、ASR/翻译。
- 确定性 Safety Guard / 关键词硬路由，只保留未来扩展点说明。
- RAG、向量库、Redis、MQ。
- 多 Agent / 自由 Agent。
- 训练计划生成、训练业务缺参追问。
- 平台业务 API 的真实接入。
- 自建 LLMOps 平台、复杂权限系统、复杂监控系统。

## v1.2 关键技术决策

- **一期不把 LangGraph/LangChain 作为运行依赖。** Intent 是确定性 Service Pipeline；后续出现多节点状态编排时再引入。
- **配置简化为 JSON Draft + Immutable Release Snapshot**，不为每种配置创建大量独立业务表。
- **Model Config 独立版本化。** Runtime 使用 Release 指定的默认模型；Admin Debug/Evaluation 可显式覆盖模型，用于 A/B 与稳定性验证。
- **Replay/Diff 不删除，合并进调用观测任务**，不建设独立复杂平台。
- **Evaluation 使用 MySQL-backed Worker**，不依赖 Redis/MQ，并支持重启后恢复/继续处理未完成 Run。

## 阅读顺序

1. `docs/01-项目范围与执行计划.md`
2. `docs/02-系统架构设计.md`
3. `docs/03-Intent路由与动态Prompt设计.md`
4. `docs/06-API与数据结构设计.md`
5. `docs/07-数据库与配置版本设计.md`
6. `docs/04-后台页面与交互设计.md`
7. `docs/05-评测与验收方案.md`
8. `docs/08-部署与主系统接入设计.md`
9. `docs/09-参考项目与采用策略.md`
10. `AGENTS.md`
11. `tasks/README.md`

评估模板：`assets/AI_Coach_意图识别评估集_极简版_v0.5.xlsx`（v0.5 修复备注列下拉、扩展到 500 行、新增“意图归属参考”页）

初始业务配置：`bootstrap/initial-config.v1.json`

## Codex 执行

严格按 `tasks/README.md` 顺序执行。每个任务完成后必须：

- 更新 `PROJECT_STATUS.md`；
- 运行任务要求的测试；
- 输出修改文件、测试结果、未完成项、风险；
- 不得擅自引入 Redis/MQ/向量库/LangGraph 等一期非必要依赖。

## TASK-001 本地开发

后端使用 Python 3.12+，前端使用 Node.js 20+。

```powershell
python -m pip install -e "backend[dev]"
python -m pytest backend/tests
ruff check backend/app backend/tests
ruff format --check backend/app backend/tests

Set-Location frontend
npm install
npm run lint
npm run format
npm run build
```

启动服务：

```powershell
# backend
python -m uvicorn app.main:app --app-dir backend --reload

# frontend（另开一个终端）
Set-Location frontend
npm run dev
```

`GET /health` 仅表示进程存活；TASK-001 的 `GET /ready` 会明确返回 DB/config checker 尚未初始化（HTTP 503），不伪造生产 ready。Runtime 与 Admin 的骨架边界分别为 `/api/v1/` 和 `/api/admin/`，具体业务接口按任务顺序实现。

## 配置调整边界（v1.2.2 起，v1.2.4 沿用）

日常业务调整（新增/修改二级 Intent、Slot、Enum/Alias、Few-shot、Prompt Template、既有 Route 下映射）必须通过在线 Draft -> Validate -> Evaluation -> Publish 新 Release 完成，不要求修改 Python 代码。

固定 7 个一级 Route key 与 Runtime IntentResult Schema 属于对外 Contract；若后期确需调整，必须按 API/Schema 版本升级处理。

## v1.2.4 小修封版要点

- 修复 Kubernetes readiness 首次配置死锁：`/ready` 只表示服务面就绪，Runtime 配置状态改为 `runtime_config_ready`。
- Bootstrap 与 Draft/Snapshot 顶层 Schema 完全一致，不再混入 Route Contract/审批元数据。
- Evaluation 锁定 Top-1 二级 Intent、clarification 双向判定，并新增同 Dataset Run 对比、一级 Route 混淆矩阵、Per-route P/R/F1。
- 重写 GitHub 参考策略：OpenAI SDK/Qwen 官方资料升为核心依据；`sohaggain` 降级为局部参考且禁止照抄 retry/sync client；删除 manikanta；EpochFlow 仅保留 evaluator 指标思路。
- 增加 OpenTelemetry GenAI 命名、jsondiffpatch、FastAPI async 指南、FastAPI full-stack CI/Docker、MASSIVE 可选数据管线参考，不扩大一期 Runtime 依赖。
