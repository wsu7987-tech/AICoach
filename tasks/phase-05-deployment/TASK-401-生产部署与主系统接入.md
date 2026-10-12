# TASK-401 生产部署与主系统接入

## 依赖

TASK-301

## 阅读

- `docs/08-部署与主系统接入设计.md`

## 目标

把“本地可运行”提升为“测试/生产 K8s 可部署”。

## 实现

- backend Dockerfile（non-root 优先）
- frontend Dockerfile/static server
- K8s manifests：独立 `intent-api` Deployment/Service、`intent-worker` Deployment、`intent-web`；api/worker 共用 backend image
- ConfigMap/Secret refs
- resource requests/limits 可覆盖
- readiness/liveness
- rollingUpdate
- graceful SIGTERM / termination grace
- replicas 可配置；建议 intent-api=2、intent-worker=1 起步
- Alembic migration 执行方式明确（Job/init process，避免多 Pod 竞争）

## 网络边界

开工前先查看 `docs/08 §12`；未确认项按默认方案落地，并在 `PROJECT_STATUS.md` 记录。

必须给出两套路由示例/说明：

- Runtime business route：仅 `/api/v1/intent/*`
- Internal Admin route：Vue + `/api/admin/*`

业务/设备入口访问 `/api/admin/*` 必须 403/404/不可路由。最终 overlay 必须实际落地独立 internal Admin route，不能只写“任选一种保护方式”。

## 文档

包含：

- 环境变量
- Secret
- DB/migration
- bootstrap
- create Model Config
- publish first Release
- health/ready
- existing gateway integration
- rollback procedure
- log/trace distinction + Trace retention/cleanup CronJob（含 `EVAL_TRACE_RETENTION_DAYS`）
- `docs/08 §12` 部署决策表（默认方案或已确认结论）
- input/upload/provider queue limits
- smoke test

## 测试

- Docker builds
- manifests basic validation
- `/health`/`/ready`（`/ready` 不依赖 Active Release，保证首次配置/故障修复时 Admin 入口可用）
- `runtime_config_ready` + Runtime `CONFIG_NOT_READY` smoke
- shutdown smoke
- migration from clean DB

## DoD

不了解源码的部署人员可按文档完成测试环境部署；业务/Admin 边界明确。
