"""Transactional MySQL Trace persistence and retention cleanup."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, exists, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.diagnostics import diagnostic_payload, diagnostic_text, error_summary, sanitize
from app.db.models import EvaluationCaseResult, IntentRequestTrace, LLMCallTrace
from app.providers.types import LLMAttempt
from app.services.intent_service import TraceRecord


def _json(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return diagnostic_payload(value)
    return diagnostic_payload({"value": value})


def _truncated(value: Any) -> bool:
    return isinstance(value, dict) and bool(value.get("truncated"))


def _tokens(usage: dict[str, Any] | None, *names: str) -> int | None:
    if not usage:
        return None
    for name in names:
        value = usage.get(name)
        if isinstance(value, int) and value >= 0:
            return value
    return None


class DatabaseTraceStore:
    """Persist a request and every physical LLM Attempt in one transaction."""

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._sessions = session_factory

    async def write(self, trace: TraceRecord) -> None:
        # Reparse here as the final persistence boundary, including nested values
        # that a caller could otherwise mutate after IntentService validation.
        safe = TraceRecord.model_validate(trace.model_dump(mode="json"))
        async with self._sessions() as session:
            async with session.begin():
                request = self._request_row(safe)
                session.add(request)
                for attempt in safe.attempts:
                    session.add(self._attempt_row(safe, attempt))

    @staticmethod
    def _request_row(trace: TraceRecord) -> IntentRequestTrace:
        attempts = trace.attempts
        usages = [attempt.usage or {} for attempt in attempts]
        input_tokens = (
            sum(
                value or 0
                for value in (_tokens(item, "prompt_tokens", "input_tokens") for item in usages)
            )
            or None
        )
        output_tokens = (
            sum(
                value or 0
                for value in (
                    _tokens(item, "completion_tokens", "output_tokens") for item in usages
                )
            )
            or None
        )
        total_tokens = (
            sum(value or 0 for value in (_tokens(item, "total_tokens") for item in usages)) or None
        )
        status = "cancelled" if trace.cancelled else "failed" if trace.error_code else "success"
        return IntentRequestTrace(
            trace_id=trace.trace_id,
            request_id=trace.request_id,
            source=trace.source,
            input=diagnostic_text(trace.text),
            context_json=_json(trace.context),
            release_id=trace.release_id,
            config_snapshot_hash=trace.config_snapshot_hash,
            release_fingerprint=trace.release_fingerprint,
            effective_model_config_id=trace.model_config_id,
            model_config_hash=trace.model_config_hash,
            model_config_snapshot_json=_json(trace.model_config_snapshot),
            final_route=(trace.final_result or {}).get("route"),
            final_result_json=_json(trace.final_result),
            reason_summary=diagnostic_text(trace.reason_summary) if trace.reason_summary else None,
            evidence_json=_json({"items": trace.evidence}),
            validation_json=_json(
                {"issues": [item.model_dump(mode="json") for item in trace.validation_issues]}
            ),
            timeline_json=_json({"attempt_count": len(attempts), "cancelled": trace.cancelled}),
            latency_ms=round(sum(item.latency_ms for item in attempts)) if attempts else None,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            retry_count=sum(1 for item in attempts if item.is_retry),
            status=status,
            error_code=trace.error_code.value if trace.error_code else None,
            error_message=error_summary(trace.error_message) if trace.error_message else None,
        )

    @staticmethod
    def _attempt_row(trace: TraceRecord, attempt: LLMAttempt) -> LLMCallTrace:
        prompt = (trace.prompt or {}).get("final_prompt")
        prompt_text = diagnostic_text(prompt) if isinstance(prompt, str) else None
        raw_request = _json(attempt.raw_request)
        raw_response = _json(attempt.raw_response)
        return LLMCallTrace(
            trace_id=trace.trace_id,
            attempt_no=attempt.attempt_no,
            provider=diagnostic_text(attempt.provider, 64),
            model=diagnostic_text(attempt.model, 256),
            model_params_json=_json(attempt.params),
            final_prompt=prompt_text,
            prompt_hash=(trace.prompt or {}).get("prompt_hash"),
            raw_request_json=raw_request,
            raw_response_json=raw_response,
            final_prompt_truncated=bool(prompt_text and prompt_text.endswith("[truncated=true]")),
            raw_request_truncated=_truncated(raw_request),
            raw_response_truncated=_truncated(raw_response),
            provider_request_id=attempt.provider_request_id,
            provider_model_version=attempt.model_version,
            system_fingerprint=attempt.system_fingerprint,
            finish_reason=attempt.finish_reason,
            parsed_result_json=_json(attempt.parsed_payload),
            input_tokens=_tokens(attempt.usage, "prompt_tokens", "input_tokens"),
            output_tokens=_tokens(attempt.usage, "completion_tokens", "output_tokens"),
            total_tokens=_tokens(attempt.usage, "total_tokens"),
            latency_ms=round(attempt.latency_ms),
            status=attempt.status,
            error_code=attempt.error_code.value if attempt.error_code else None,
            error_message=error_summary(attempt.error_message) if attempt.error_message else None,
        )


async def cleanup_expired_traces(
    session_factory: async_sessionmaker,
    *,
    trace_retention_days: int,
    eval_trace_retention_days: int,
    now: datetime | None = None,
) -> int:
    """Delete expired request traces; database FK cascades their attempts only."""

    now = now or datetime.now(UTC).replace(tzinfo=None)
    normal_cutoff = now - timedelta(days=trace_retention_days)
    evaluation_cutoff = now - timedelta(days=eval_trace_retention_days)
    evaluation_link = exists(
        select(EvaluationCaseResult.id).where(
            EvaluationCaseResult.trace_id == IntentRequestTrace.trace_id
        )
    )
    expired = (IntentRequestTrace.created_at < normal_cutoff) & (
        ~evaluation_link | (IntentRequestTrace.created_at < evaluation_cutoff)
    )
    async with session_factory() as session:
        async with session.begin():
            result = await session.execute(delete(IntentRequestTrace).where(expired))
            return result.rowcount or 0


def trace_payload_hash(value: Any) -> str:
    """Stable helper for callers that need to correlate a sanitized payload."""

    return hashlib.sha256(
        json.dumps(sanitize(value), sort_keys=True, default=str).encode()
    ).hexdigest()
