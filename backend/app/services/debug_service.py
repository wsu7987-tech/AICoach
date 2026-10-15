"""Bounded TASK-202 diagnostic workflow backed by production primitives."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Text, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AppError, ErrorCode
from app.db.models import EvaluationRun, IntentRequestTrace, LLMCallTrace, ModelConfig, RuntimeState
from app.prompting.builder import PromptBuilder
from app.providers.factory import ModelProviderFactory
from app.schemas.config import release_fingerprint
from app.schemas.intent import ModelConfigSnapshot
from app.services import config_service
from app.services.intent_service import IntentService, RuntimeConfiguration
from app.services.trace_store import DatabaseTraceStore


class FixedConfigurationLoader:
    def __init__(self, configuration: RuntimeConfiguration) -> None:
        self._configuration = configuration

    async def load(self) -> RuntimeConfiguration:
        return RuntimeConfiguration.model_validate(self._configuration.model_dump(mode="json"))


async def configuration_for(
    session: AsyncSession,
    release_id: int | None,
    model_config_id: int | None,
    historical_model: dict[str, Any] | None = None,
) -> RuntimeConfiguration:
    if release_id is None:
        state = await session.get(RuntimeState, 1)
        if state is None or state.active_release_id is None:
            raise AppError(ErrorCode.CONFIG_NOT_READY, "runtime configuration is not ready", 503)
        release_id = state.active_release_id
    release = await config_service.release_configuration(session, release_id)
    if historical_model is not None:
        model = ModelConfigSnapshot.model_validate(historical_model)
    elif model_config_id is not None:
        row = await session.get(ModelConfig, model_config_id)
        if row is None:
            raise config_service.ConfigError("MODEL_NOT_FOUND", "Model Config 不存在", 404)
        model = config_service.effective_model_snapshot(row)
        if not model.enabled:
            raise config_service.ConfigError(
                "MODEL_DISABLED", "已禁用版本不能用于新的调试或 Replay", 409
            )
    else:
        model = ModelConfigSnapshot.model_validate(release["model_config_snapshot"])
    return RuntimeConfiguration(
        snapshot=release["snapshot_json"],
        model_config_snapshot=model,
        release_id=release["id"],
        config_snapshot_hash=release["config_snapshot_hash"],
        model_config_hash=model.model_config_hash,
        release_fingerprint=release_fingerprint(
            release["config_snapshot_hash"], model.id, model.model_config_hash
        ),
    )


async def execute(
    sessions: async_sessionmaker,
    provider_factory: ModelProviderFactory,
    *,
    text: str,
    context: dict[str, Any],
    configuration: RuntimeConfiguration,
    repeat: int,
    mode: str,
    parent_trace_id: str | None = None,
) -> list[dict[str, Any]]:
    service = IntentService(
        FixedConfigurationLoader(configuration),
        provider_factory,
        PromptBuilder(),
        DatabaseTraceStore(sessions),
    )
    runs: list[dict[str, Any]] = []
    for _ in range(repeat):
        try:
            result = await service.analyze(
                text=text, context=context, execution_mode=mode, parent_trace_id=parent_trace_id
            )  # type: ignore[arg-type]
            trace = await latest_trace(sessions, mode, parent_trace_id)
            runs.append(
                {"ok": True, "runtime_result": result.model_dump(mode="json"), "trace": trace}
            )
        except AppError as error:
            if error.code == ErrorCode.INTERNAL_ERROR:
                raise
            runs.append({"ok": False, "error_code": error.code, "message": error.message})
    return runs


def _attempt(row: LLMCallTrace) -> dict[str, Any]:
    return {
        "attempt_no": row.attempt_no,
        "provider": row.provider,
        "model": row.model,
        "params": row.model_params_json,
        "final_prompt": row.final_prompt,
        "prompt_hash": row.prompt_hash,
        "raw_request": row.raw_request_json,
        "raw_response": row.raw_response_json,
        "parsed_result": row.parsed_result_json,
        "provider_request_id": row.provider_request_id,
        "model_version": row.provider_model_version,
        "system_fingerprint": row.system_fingerprint,
        "finish_reason": row.finish_reason,
        "tokens": {
            "input": row.input_tokens,
            "output": row.output_tokens,
            "total": row.total_tokens,
        },
        "latency_ms": row.latency_ms,
        "status": row.status,
        "error_code": row.error_code,
        "error_message": row.error_message,
        "truncated": {
            "prompt": row.final_prompt_truncated,
            "request": row.raw_request_truncated,
            "response": row.raw_response_truncated,
        },
    }


def _trace(row: IntentRequestTrace, attempts: list[LLMCallTrace]) -> dict[str, Any]:
    return {
        "trace_id": row.trace_id,
        "request_id": row.request_id,
        "parent_trace_id": row.parent_trace_id,
        "source": row.source,
        "input": row.input,
        "context": row.context_json,
        "created_at": row.created_at,
        "release": {
            "id": row.release_id,
            "config_snapshot_hash": row.config_snapshot_hash,
            "fingerprint": row.release_fingerprint,
        },
        "model": {
            "id": row.effective_model_config_id,
            "hash": row.model_config_hash,
            "snapshot": row.model_config_snapshot_json,
        },
        "runtime_result": row.final_result_json,
        "route": row.final_route,
        "reason_summary": row.reason_summary,
        "evidence": row.evidence_json,
        "validation": row.validation_json,
        "timeline": row.timeline_json,
        "latency_ms": row.latency_ms,
        "tokens": {
            "input": row.input_tokens,
            "output": row.output_tokens,
            "total": row.total_tokens,
        },
        "retry_count": row.retry_count,
        "status": row.status,
        "error": {"code": row.error_code, "message": row.error_message},
        "attempts": [_attempt(item) for item in attempts],
    }


async def trace_detail(sessions: async_sessionmaker, trace_id: str) -> dict[str, Any]:
    async with sessions() as session:
        row = await session.scalar(
            select(IntentRequestTrace).where(IntentRequestTrace.trace_id == trace_id)
        )
        if row is None:
            raise config_service.ConfigError("TRACE_NOT_FOUND", "Trace 不存在或已过期", 404)
        attempts = list(
            (
                await session.scalars(
                    select(LLMCallTrace)
                    .where(LLMCallTrace.trace_id == trace_id)
                    .order_by(LLMCallTrace.attempt_no)
                )
            ).all()
        )
        return _trace(row, attempts)


async def latest_trace(
    sessions: async_sessionmaker, source: str, parent_trace_id: str | None
) -> dict[str, Any]:
    async with sessions() as session:
        parent = (
            IntentRequestTrace.parent_trace_id == parent_trace_id
            if parent_trace_id
            else IntentRequestTrace.parent_trace_id.is_(None)
        )
        row = await session.scalar(
            select(IntentRequestTrace)
            .where(IntentRequestTrace.source == source, parent)
            .order_by(IntentRequestTrace.created_at.desc(), IntentRequestTrace.id.desc())
            .limit(1)
        )
        if row is None:
            raise AppError(ErrorCode.INTERNAL_ERROR, "debug trace was not persisted", 500)
    return await trace_detail(sessions, row.trace_id)


async def list_traces(sessions: async_sessionmaker, filters: dict[str, Any]) -> dict[str, Any]:
    columns = {
        "request_id": IntentRequestTrace.request_id,
        "trace_id": IntentRequestTrace.trace_id,
        "route": IntentRequestTrace.final_route,
        "status": IntentRequestTrace.status,
        "release_id": IntentRequestTrace.release_id,
        "model_config_id": IntentRequestTrace.effective_model_config_id,
    }
    async with sessions() as session:
        query = select(IntentRequestTrace)
        for key, column in columns.items():
            if filters.get(key) is not None:
                query = query.where(column == filters[key])
        if filters.get("intent"):
            query = query.where(
                IntentRequestTrace.final_result_json.cast(Text).contains(filters["intent"])
            )
        if filters.get("keyword"):
            needle = f"%{filters['keyword']}%"
            query = query.where(
                or_(
                    IntentRequestTrace.input.like(needle),
                    IntentRequestTrace.request_id.like(needle),
                )
            )
        if filters.get("start"):
            query = query.where(IntentRequestTrace.created_at >= filters["start"])
        if filters.get("end"):
            query = query.where(IntentRequestTrace.created_at <= filters["end"])
        total = await session.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = list(
            (
                await session.scalars(
                    query.order_by(IntentRequestTrace.created_at.desc())
                    .offset(filters["offset"])
                    .limit(filters["limit"])
                )
            ).all()
        )
    return {
        "total": total,
        "items": [
            {
                "trace_id": row.trace_id,
                "request_id": row.request_id,
                "parent_trace_id": row.parent_trace_id,
                "source": row.source,
                "input": row.input,
                "route": row.final_route,
                "release_id": row.release_id,
                "model_config_id": row.effective_model_config_id,
                "latency_ms": row.latency_ms,
                "status": row.status,
                "created_at": row.created_at,
            }
            for row in rows
        ],
    }


def _percentile(values: list[int], ratio: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * ratio)))
    return ordered[index]


async def intent_latency_analysis(
    sessions: async_sessionmaker,
    *,
    request_id: str,
    model_uid: str,
    sample_size: int,
) -> dict[str, Any]:
    """Return safe timing diagnostics for one Runtime request and its model baseline."""

    async with sessions() as session:
        current = await session.scalar(
            select(IntentRequestTrace)
            .where(
                IntentRequestTrace.request_id == request_id,
                IntentRequestTrace.source == "runtime",
            )
            .order_by(IntentRequestTrace.created_at.desc(), IntentRequestTrace.id.desc())
            .limit(1)
        )
        if current is None:
            raise config_service.ConfigError("TRACE_NOT_FOUND", "本次识别耗时记录不可用", 404)

        candidates = list(
            (
                await session.scalars(
                    select(IntentRequestTrace)
                    .where(
                        IntentRequestTrace.source == "runtime",
                        IntentRequestTrace.status == "success",
                        IntentRequestTrace.latency_ms.is_not(None),
                        IntentRequestTrace.id != current.id,
                    )
                    .order_by(IntentRequestTrace.created_at.desc())
                    .limit(max(200, sample_size * 10))
                )
            ).all()
        )

    matching = [
        row
        for row in candidates
        if (row.model_config_snapshot_json or {}).get("model_uid") == model_uid
    ][:sample_size]
    values = [int(row.latency_ms) for row in matching if row.latency_ms is not None]
    average = round(sum(values) / len(values)) if values else None
    timeline = current.timeline_json or {}
    return {
        "request_id": current.request_id,
        "trace_id": current.trace_id,
        "model_uid": model_uid,
        "current": {
            "provider_latency_ms": current.latency_ms,
            "attempt_count": int(timeline.get("attempt_count") or 0),
            "retry_count": current.retry_count,
            "input_tokens": current.input_tokens,
            "output_tokens": current.output_tokens,
            "total_tokens": current.total_tokens,
        },
        "baseline": {
            "sample_size": len(values),
            "average_ms": average,
            "p50_ms": _percentile(values, 0.5),
            "p95_ms": _percentile(values, 0.95),
            "min_ms": min(values) if values else None,
            "max_ms": max(values) if values else None,
        },
    }


def diff(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    fields = {
        "input": (left["input"], right["input"]),
        "release": (left["release"], right["release"]),
        "model": (left["model"], right["model"]),
        "runtime_result": (left["runtime_result"], right["runtime_result"]),
        "raw_response": (
            [a["raw_response"] for a in left["attempts"]],
            [a["raw_response"] for a in right["attempts"]],
        ),
        "parsed_result": (
            [a["parsed_result"] for a in left["attempts"]],
            [a["parsed_result"] for a in right["attempts"]],
        ),
        "attempts": (left["attempts"], right["attempts"]),
        "prompt": (
            [a["final_prompt"] for a in left["attempts"]],
            [a["final_prompt"] for a in right["attempts"]],
        ),
    }
    changes = {
        name: {"changed": before != after, "left": before, "right": after}
        for name, (before, after) in fields.items()
    }
    return {
        "left_trace_id": left["trace_id"],
        "right_trace_id": right["trace_id"],
        "changes": changes,
        "provider_divergence": changes["raw_response"]["changed"]
        and not changes["prompt"]["changed"]
        and not changes["model"]["changed"],
    }


async def status(sessions: async_sessionmaker) -> dict[str, Any]:
    since = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=24)
    async with sessions() as session:
        statement = select(
            func.count(IntentRequestTrace.id),
            func.coalesce(func.sum(IntentRequestTrace.status != "success"), 0),
            func.avg(IntentRequestTrace.latency_ms),
        ).where(IntentRequestTrace.created_at >= since)
        count, errors, average = (await session.execute(statement)).one()
        values = list(
            (
                await session.scalars(
                    select(IntentRequestTrace.latency_ms)
                    .where(
                        IntentRequestTrace.created_at >= since,
                        IntentRequestTrace.latency_ms.is_not(None),
                    )
                    .order_by(IntentRequestTrace.latency_ms)
                )
            ).all()
        )
        queued = (
            await session.scalar(
                select(func.count(EvaluationRun.id)).where(EvaluationRun.status == "queued")
            )
            or 0
        )
        running = (
            await session.scalar(
                select(func.count(EvaluationRun.id)).where(EvaluationRun.status == "running")
            )
            or 0
        )
    p95 = values[max(0, int((len(values) - 1) * 0.95))] if values else None
    return {
        "requests_24h": count,
        "errors_24h": errors,
        "avg_latency_ms": float(average) if average is not None else None,
        "p95_latency_ms": p95,
        "evaluation_queued": queued,
        "evaluation_running": running,
    }
