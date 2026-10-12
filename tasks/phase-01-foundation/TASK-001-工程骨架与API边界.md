# TASK-001 工程骨架与 API 边界

## 目标

建立可持续开发和部署的 Vue + FastAPI Monorepo 骨架，先确定 Runtime/Admin API 边界、settings、错误模型与 request_id。

## 阅读

- `docs/01-项目范围与执行计划.md`
- `docs/02-系统架构设计.md`
- `docs/06-API与数据结构设计.md`
- `AGENTS.md`
- `docs/09-参考项目与采用策略.md` 中 FastAPI 工程参考；第三方小型 classifier 不作为工程骨架依据

## 实现

建议：

```text
frontend/
backend/
  app/
    api/runtime/
    api/admin/
    core/
    db/
    schemas/
    intent/
    llm/
    prompt/
    config_center/
    trace/
    evaluation/
  tests/
deploy/
```

要求：

- Vue3 + TS + Vite + Element Plus。
- FastAPI 可启动；async 路径不得直接执行 blocking I/O，后续模型 Provider 预留异步调用边界。
- `Settings` 使用 pydantic-settings；`.env.example` 无真实 Secret。
- `/api/v1` 与 `/api/admin` Router 分组从第一天分离。
- `request_id` middleware：接受上游 ID 或生成新 ID，并进入日志 context。
- 统一错误 envelope 与 error_code 基础类型。
- `GET /health` 只表示进程存活。
- `GET /ready` 先提供可扩展 checker；本 Task 可返回“DB/config checker not initialized”而不是伪 ready。
- 基础 structured logging 到 stdout。
- lint/format/test/build 命令固定到 README/Makefile 或 scripts。

## 不做

DB 表、LLM、Intent 业务、配置中心。

## 测试

- backend app import/start
- request_id 生成/透传
- error envelope
- frontend build

## DoD

clone 后按 README 可启动前后端；Runtime/Admin 路由命名空间已固定。
