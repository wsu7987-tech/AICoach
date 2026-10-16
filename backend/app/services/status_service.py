"""Independent, bounded diagnostics. No provider calls or configuration mutations."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.readiness import ReadinessChecker
from app.db.database import Database
from app.db.models import EvaluationRun, ManagedModel, RuntimeModelState, RuntimeState
from app.db.models import IntentRequestTrace as Trace
from app.providers.openai_compatible import ProviderError
from app.schemas.config import ConfigStatus, StatusCheck, StatusModel, StatusRelease
from app.services import config_service
from app.services.intent_service import BusinessRuntimeConfiguration
from app.services.runtime_model import DatabaseManagedModelLoader

logger = logging.getLogger(__name__)
CHECK_TIMEOUT_SECONDS = 5
CheckResult = tuple[StatusCheck, dict[str, Any]]


def check(
    state: Literal["ready", "not_ready", "unavailable"], code: str, message: str
) -> StatusCheck:
    return StatusCheck(state=state, code=code, message=message)


async def bounded(name: str, operation: Callable[[], Awaitable[CheckResult]]) -> CheckResult:
    try:
        async with asyncio.timeout(CHECK_TIMEOUT_SECONDS):
            return await operation()
    except TimeoutError:
        logger.warning("STATUS_CHECK_TIMEOUT check=%s", name)
        return check("unavailable", "CHECK_TIMEOUT", "检查超时，请稍后刷新"), {}
    except Exception as error:
        # Exception messages may include SQL values or credential details.
        logger.warning("STATUS_CHECK_FAILED check=%s type=%s", name, type(error).__name__)
        return check("unavailable", "CHECK_FAILED", "暂时无法读取，请检查服务日志"), {}


async def service_check(checker: ReadinessChecker) -> CheckResult:
    report = await checker.check()
    return (
        check("ready", "SERVICE_READY", "数据库连接与表结构就绪")
        if report.ready
        else check("not_ready", "DEPENDENCY_NOT_READY", "数据库连接或表结构未就绪"),
        {"service_ready": report.ready},
    )


async def release_check(sessions: async_sessionmaker) -> CheckResult:
    async with sessions() as session:
        state = await session.get(RuntimeState, 1)
        active_id = state.active_release_id if state else None
        data: dict[str, Any] = {"active_release_id": active_id}
        if active_id is None:
            return check("not_ready", "RELEASE_MISSING", "尚未发布业务配置"), data
        try:
            release = await config_service.release_configuration(session, active_id)
            BusinessRuntimeConfiguration.from_release(release)
        except (config_service.ConfigError, ValueError):
            return check("not_ready", "RELEASE_INVALID", "当前发布配置无效，请检查并重新发布"), data
        data["active_release"] = StatusRelease(
            version=release["version"], note=release["note"], created_at=release["created_at"]
        )
        return check("ready", "RELEASE_READY", "当前发布配置可加载"), data


async def model_check(
    sessions: async_sessionmaker, loader: DatabaseManagedModelLoader | None
) -> CheckResult:
    async with sessions() as session:
        state = await session.get(RuntimeModelState, 1)
        model = (
            await session.get(ManagedModel, state.default_model_id)
            if state is not None and state.default_model_id is not None
            else None
        )
        if model is None:
            return check("not_ready", "DEFAULT_MODEL_MISSING", "尚未设置默认模型"), {}
        data = {
            "default_model": StatusModel(
                model_uid=model.model_uid,
                display_name=model.display_name,
                model_name=model.model_name,
                enabled=model.enabled,
            )
        }
        if not model.enabled:
            return check("not_ready", "DEFAULT_MODEL_DISABLED", "默认模型已停用"), data
        if loader is None:
            return check("unavailable", "LOADER_UNAVAILABLE", "模型加载器尚未初始化"), data
        try:
            # Same session keeps the displayed model and validated default consistent.
            # The decrypted credential never leaves the loader's result or enters the response.
            await loader.resolve(session, None)
        except ProviderError as error:
            if error.failure_stage == "credential":
                return check("not_ready", "CREDENTIAL_UNAVAILABLE", "默认模型凭据不可用"), data
            return check("not_ready", "MODEL_INVALID", "默认模型配置无效"), data
        return check("ready", "MODEL_READY", "默认模型参数与凭据可加载"), data


async def traffic_check(
    sessions: async_sessionmaker, source: str, since: datetime, until: datetime
) -> CheckResult:
    filters = (Trace.created_at >= since, Trace.created_at < until, Trace.source == source)
    async with sessions() as session:
        count, errors, cancelled, average, samples = (
            await session.execute(
                select(
                    func.count(Trace.id),
                    func.coalesce(func.sum(case((Trace.status == "failed", 1), else_=0)), 0),
                    func.coalesce(func.sum(case((Trace.status == "cancelled", 1), else_=0)), 0),
                    func.avg(Trace.latency_ms),
                    func.count(Trace.latency_ms),
                ).where(*filters)
            )
        ).one()
        # Nearest-rank P95: sort in the database and transfer only one value.
        p95 = None
        if samples:
            p95 = await session.scalar(
                select(Trace.latency_ms)
                .where(*filters, Trace.latency_ms.is_not(None))
                .order_by(Trace.latency_ms)
                .offset((samples * 95 + 99) // 100 - 1)
                .limit(1)
            )
    return check("ready", "TRAFFIC_READY", "调用统计已更新"), {
        "requests_24h": count,
        "errors_24h": int(errors),
        "cancelled_24h": int(cancelled),
        "error_rate": float(errors / count) if count else None,
        "latency_samples": samples,
        "avg_latency_ms": float(average) if average is not None else None,
        "p95_latency_ms": p95,
    }


async def evaluation_check(sessions: async_sessionmaker) -> CheckResult:
    async with sessions() as session:
        counts = dict(
            (
                await session.execute(
                    select(EvaluationRun.status, func.count(EvaluationRun.id))
                    .where(EvaluationRun.status.in_(("queued", "running")))
                    .group_by(EvaluationRun.status)
                )
            ).all()
        )
    return check("ready", "EVALUATION_READY", "评测任务统计已更新"), {
        "evaluation_queued": counts.get("queued", 0),
        "evaluation_running": counts.get("running", 0),
    }


async def summary(
    database: Database | None,
    checker: ReadinessChecker,
    loader: DatabaseManagedModelLoader | None,
    *,
    source: Literal["runtime", "debug", "replay", "evaluation"],
) -> ConfigStatus:
    now = datetime.now(UTC)
    since = now - timedelta(hours=24)
    data: dict[str, Any] = {"checked_at": now, "window_start": since, "source": source}
    if database is None:
        data["service_ready"] = False
        data["checks"] = {
            name: check("unavailable", "DATABASE_NOT_CONFIGURED", "数据库尚未配置，无法检查")
            for name in ("service", "release", "model", "traffic", "evaluation")
        }
        data["checks"]["service"] = check(
            "not_ready", "DATABASE_NOT_CONFIGURED", "数据库尚未配置"
        )
    else:
        sessions = database.session_factory
        operations = {
            "service": lambda: service_check(checker),
            "release": lambda: release_check(sessions),
            "model": lambda: model_check(sessions, loader),
            "traffic": lambda: traffic_check(
                sessions, source, since.replace(tzinfo=None), now.replace(tzinfo=None)
            ),
            "evaluation": lambda: evaluation_check(sessions),
        }
        results = await asyncio.gather(
            *(bounded(name, operation) for name, operation in operations.items())
        )
        data["checks"] = {}
        for name, (result, values) in zip(operations, results, strict=True):
            data["checks"][name] = result
            data.update(values)
    states = [data["checks"][name].state for name in ("release", "model")]
    data["runtime_config_ready"] = (
        False if "not_ready" in states else None if "unavailable" in states else True
    )
    return ConfigStatus(**data)
