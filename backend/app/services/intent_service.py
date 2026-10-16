"""The TASK-102 runtime pipeline, deliberately independent of FastAPI and MySQL."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.core.diagnostics import bounded_validation_issues, diagnostic_text, error_summary, sanitize
from app.core.errors import AppError, ErrorCode
from app.prompting.builder import PromptBuilder
from app.providers.factory import ModelProviderFactory, configuration_error, verify_managed_provider
from app.providers.openai_compatible import ProviderError
from app.providers.types import LLMAttempt, LLMProvider, ProviderCancelledError, diagnostic_attempts
from app.schemas.config import business_snapshot
from app.schemas.intent import (
    BusinessOutputValidationError,
    IntentAnalyzeRequest,
    IntentResult,
    IntentResultV2,
    LLMRecognitionOutput,
    LLMRecognitionOutputV2,
    OutputValidationIssue,
    RuntimeConfigSnapshot,
    validate_recognition_output,
    validate_recognition_output_v2,
)
from app.services.runtime_model import ResolvedManagedModel
from app.services.slot_extractor import (
    extract_slot_candidates,
    locate_action_ranges,
    scope_slot_candidates_to_actions,
)

logger = logging.getLogger(__name__)
CANCEL_TRACE_TIMEOUT_SECONDS = 0.1


class BusinessRuntimeConfiguration(BaseModel):
    """Active Release business inputs, independent from the execution model."""

    model_config = ConfigDict(extra="forbid")

    snapshot: RuntimeConfigSnapshot
    release_id: int = Field(gt=0)
    config_snapshot_hash: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_business_snapshot(self) -> BusinessRuntimeConfiguration:
        self.snapshot = RuntimeConfigSnapshot.model_validate(
            self.snapshot.model_dump(mode="json")
        )
        return self

    @classmethod
    def from_release(cls, release: dict[str, Any]) -> BusinessRuntimeConfiguration:
        """Build from a business-only immutable release."""

        return cls(
            snapshot=release["snapshot_json"],
            release_id=release["id"],
            config_snapshot_hash=release["config_snapshot_hash"],
        )


class RuntimeConfigLoader(Protocol):
    async def load(self) -> BusinessRuntimeConfiguration: ...


class ManagedModelLoader(Protocol):
    async def load(self, model_uid: str | None) -> ResolvedManagedModel: ...


class TraceRecord(BaseModel):
    """Sanitized diagnostic record passed to the durable TraceStore."""

    model_config = ConfigDict(extra="forbid")

    trace_id: str
    request_id: str
    text: str
    context: dict[str, Any] = Field(default_factory=dict)
    source: str = "runtime"
    parent_trace_id: str | None = None
    release_id: int | None = None
    config_snapshot_hash: str | None = None
    managed_model_snapshot: dict[str, Any] | None = None
    attempts: list[LLMAttempt] = Field(default_factory=list)
    validation_issues: list[OutputValidationIssue] = Field(default_factory=list)
    final_result: dict[str, Any] | None = None
    reason_summary: str | None = None
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    prompt: dict[str, Any] | None = None
    cancelled: bool = False
    error_code: ErrorCode | None = None
    error_message: str | None = None
    failure_stage: str | None = None

    @model_validator(mode="before")
    @classmethod
    def sanitize_diagnostics(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        clean = sanitize(value)
        for key in ("text", "request_id"):
            if key in clean:
                clean[key] = diagnostic_text(clean[key])
        if clean.get("error_message") is not None:
            clean["error_message"] = error_summary(clean["error_message"])
        if "validation_issues" in clean:
            clean["validation_issues"] = bounded_validation_issues(clean["validation_issues"])
        return clean


class TraceSink(Protocol):
    """Async writes must yield and propagate cancellation after prompt cleanup.

    No in-process asyncio timeout can preempt synchronous blocking or a coroutine
    that suppresses cancellation indefinitely. Implementations must not do either.
    """

    async def write(self, trace: TraceRecord) -> None: ...


class IntentServiceError(AppError):
    """Parser/schema/business validation error; never a fabricated unknown result."""

    def __init__(
        self, code: ErrorCode, message: str, *, attempts: list[LLMAttempt] | None = None
    ) -> None:
        super().__init__(code, error_summary(message), 502)
        self.attempts = diagnostic_attempts(attempts or [])


class InMemoryRuntimeConfigLoader:
    """Test-only loader with synthetic release identity; no DB/TTL loader here."""

    def __init__(self, snapshot: RuntimeConfigSnapshot) -> None:
        _, digest = business_snapshot(snapshot)
        self._configuration = BusinessRuntimeConfiguration(
            snapshot=snapshot,
            release_id=1,
            config_snapshot_hash=digest,
        )

    async def load(self) -> BusinessRuntimeConfiguration:
        return self._configuration


class InMemoryTraceSink:
    """Test-only TraceSink that preserves diagnostics outside IntentResult."""

    def __init__(self) -> None:
        self.records: list[TraceRecord] = []

    async def write(self, trace: TraceRecord) -> None:
        self.records.append(trace)


class IntentService:
    def __init__(
        self,
        config_loader: RuntimeConfigLoader,
        provider: LLMProvider | ModelProviderFactory,
        prompt_builder: PromptBuilder,
        trace_sink: TraceSink,
        managed_model_loader: ManagedModelLoader | None = None,
    ) -> None:
        self._config_loader = config_loader
        self._provider = provider
        self._prompt_builder = prompt_builder
        self._trace_sink = trace_sink
        self._managed_model_loader = managed_model_loader

    async def analyze(
        self,
        *,
        text: str,
        context: dict[str, Any] | None = None,
        request_id: str | None = None,
        model_uid: str | None = None,
        output_version: Literal[1, 2] = 1,
        execution_mode: Literal["runtime", "debug", "replay", "evaluation"] = "runtime",
        parent_trace_id: str | None = None,
    ) -> IntentResult | IntentResultV2:
        request = IntentAnalyzeRequest(
            request_id=request_id,
            text=text,
            model_uid=model_uid,
            context=context or {},
        )
        effective_request_id = request.request_id or str(uuid4())
        trace = TraceRecord(
            trace_id=str(uuid4()),
            request_id=effective_request_id,
            text=request.text,
            context=request.context,
            source=execution_mode,
            parent_trace_id=parent_trace_id,
        )
        try:
            try:
                loaded = await self._config_loader.load()
                # A loader may return a mutated Pydantic instance. Never trust it
                # or retain references that another request can change.
                config = BusinessRuntimeConfiguration.model_validate(
                    loaded.model_dump(mode="json")
                )
            except ValueError:
                raise configuration_error() from None
            trace.release_id = config.release_id
            trace.config_snapshot_hash = config.config_snapshot_hash
            if self._managed_model_loader is not None:
                if not isinstance(self._provider, ModelProviderFactory):
                    raise configuration_error()
                resolved = await self._managed_model_loader.load(request.model_uid)
                trace.managed_model_snapshot = resolved.snapshot.model_dump(mode="json")
                provider = self._provider.resolve_managed(
                    resolved.snapshot,
                    api_key=resolved.api_key,
                    credential_revision=resolved.credential_revision,
                )
                verify_managed_provider(provider, resolved.snapshot)
            else:
                if isinstance(self._provider, ModelProviderFactory):
                    raise configuration_error()
                provider = self._provider
            slot_candidates = extract_slot_candidates(request.text, config.snapshot)
            prompt = self._prompt_builder.build(
                config.snapshot,
                request.text,
                request.context,
                output_version=output_version,
                slot_candidates=slot_candidates,
            )
            trace.prompt = prompt.model_dump(mode="json")
            response = await provider.invoke(prompt)
            trace.attempts = response.attempts
            if output_version == 2:
                output = self._parse_output_v2(response.content, response.attempts)
                action_ranges = locate_action_ranges(
                    request.text,
                    [
                        (action.action_id, action.source_text)
                        for action in sorted(
                            output.actions, key=lambda item: item.order
                        )
                    ],
                )
                if len(output.actions) == 1:
                    candidates_by_action = {
                        output.actions[0].action_id: slot_candidates
                    }
                else:
                    candidates_by_action = scope_slot_candidates_to_actions(
                        slot_candidates, action_ranges
                    )
                validated = validate_recognition_output_v2(
                    output,
                    config.snapshot,
                    request_id=effective_request_id,
                    text=request.text,
                    slot_candidates_by_action=candidates_by_action,
                    action_ranges=action_ranges,
                )
            else:
                output = self._parse_output(response.content, response.attempts)
                validated = validate_recognition_output(
                    output,
                    config.snapshot,
                    request_id=effective_request_id,
                    text=request.text,
                    slot_candidates=slot_candidates,
                )
            trace.validation_issues = validated.validation_issues
            trace.final_result = validated.result.model_dump(mode="json")
            trace.reason_summary = output.reason_summary
            trace.evidence = [item.model_dump(mode="json") for item in output.evidence]
            await self._persist_success(trace, fail_open=execution_mode == "runtime")
            return validated.result
        except asyncio.CancelledError as exc:
            cancellation = (
                exc
                if isinstance(exc, ProviderCancelledError)
                else ProviderCancelledError(trace.attempts)
            )
            trace.attempts = cancellation.attempts
            trace.cancelled = True
            await self._persist_cancellation(trace, cancellation)
            raise cancellation from None
        except ProviderError as exc:
            trace.attempts = exc.attempts
            trace.error_code = exc.code
            trace.error_message = exc.message
            trace.failure_stage = exc.failure_stage or "provider_server"
            await self._persist_failure(trace, fail_open=execution_mode == "runtime")
            raise
        except IntentServiceError as exc:
            trace.attempts = exc.attempts
            trace.error_code = exc.code
            trace.error_message = exc.message
            trace.failure_stage = (
                "model_output"
                if exc.code == ErrorCode.MODEL_OUTPUT_PARSE_ERROR
                else "schema_validation"
            )
            await self._persist_failure(trace, fail_open=execution_mode == "runtime")
            raise
        except BusinessOutputValidationError as exc:
            error = IntentServiceError(
                ErrorCode.MODEL_OUTPUT_SCHEMA_ERROR, str(exc), attempts=trace.attempts
            )
            trace.error_code = error.code
            trace.error_message = error.message
            trace.failure_stage = "business_validation"
            await self._persist_failure(trace, fail_open=execution_mode == "runtime")
            raise error from None
        except AppError:
            raise
        except Exception:
            error = AppError(ErrorCode.INTERNAL_ERROR, "internal intent analysis error", 500)
            trace.error_code = error.code
            trace.error_message = error.message
            trace.failure_stage = "internal"
            await self._persist_failure(trace, fail_open=execution_mode == "runtime")
            raise error from None

    @staticmethod
    def _parse_output(content: str, attempts: list[LLMAttempt]) -> LLMRecognitionOutput:
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            raise IntentServiceError(
                ErrorCode.MODEL_OUTPUT_PARSE_ERROR,
                "model output is not valid JSON",
                attempts=attempts,
            ) from None
        if not isinstance(payload, dict):
            raise IntentServiceError(
                ErrorCode.MODEL_OUTPUT_SCHEMA_ERROR,
                "model output must be a JSON object",
                attempts=attempts,
            )
        try:
            return LLMRecognitionOutput.model_validate(payload)
        except ValidationError as exc:
            raise IntentServiceError(
                ErrorCode.MODEL_OUTPUT_SCHEMA_ERROR,
                _schema_error_message(exc),
                attempts=attempts,
            ) from None

    @staticmethod
    def _parse_output_v2(
        content: str, attempts: list[LLMAttempt]
    ) -> LLMRecognitionOutputV2:
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            raise IntentServiceError(
                ErrorCode.MODEL_OUTPUT_PARSE_ERROR,
                "model output is not valid JSON",
                attempts=attempts,
            ) from None
        if not isinstance(payload, dict):
            raise IntentServiceError(
                ErrorCode.MODEL_OUTPUT_SCHEMA_ERROR,
                "model output must be a JSON object",
                attempts=attempts,
            )
        try:
            return LLMRecognitionOutputV2.model_validate(payload)
        except ValidationError as exc:
            raise IntentServiceError(
                ErrorCode.MODEL_OUTPUT_SCHEMA_ERROR,
                _schema_error_message(exc),
                attempts=attempts,
            ) from None

    async def _persist_cancellation(
        self, trace: TraceRecord, cancellation: ProviderCancelledError
    ) -> None:
        # Reparse the complete diagnostic copy immediately before the Sink boundary.
        safe_trace = TraceRecord.model_validate(trace.model_dump(mode="json"))
        cancellation.trace_diagnostic = safe_trace.model_dump(mode="json")
        try:
            # No child task, shield, uncancel, or second HTTP request. A second
            # cancellation unwinds write() on this same stack; do not retry it.
            async with asyncio.timeout(CANCEL_TRACE_TIMEOUT_SECONDS):
                await self._trace_sink.write(safe_trace)
        except TimeoutError:
            cancellation.trace_write_status = "timed_out"
        except asyncio.CancelledError:
            cancellation.trace_write_status = "interrupted"
        except Exception:
            cancellation.trace_write_status = "failed"
        else:
            cancellation.trace_write_status = "written"
        if cancellation.trace_write_status != "written":
            # No exception text, user input or raw data in the fallback log.
            logger.warning(
                "TRACE_PERSIST_FAILED trace_id=%s status=%s attempts=%d",
                safe_trace.trace_id,
                cancellation.trace_write_status,
                len(safe_trace.attempts),
            )
        # There is no await after handling interruption. analyze() re-raises its
        # original ProviderCancelledError, preserving both identity and Attempts.

    async def _persist_success(self, trace: TraceRecord, *, fail_open: bool) -> None:
        try:
            await self._trace_sink.write(TraceRecord.model_validate(trace.model_dump(mode="json")))
        except Exception:
            logger.warning("TRACE_PERSIST_FAILED trace_id=%s", trace.trace_id)
            if not fail_open:
                raise AppError(ErrorCode.INTERNAL_ERROR, "trace persistence failed", 500) from None

    async def _persist_failure(self, trace: TraceRecord, *, fail_open: bool) -> None:
        try:
            await self._trace_sink.write(TraceRecord.model_validate(trace.model_dump(mode="json")))
        except asyncio.CancelledError:
            # This await runs inside an error handler, outside analyze's try block.
            # Preserve completed failed Attempts if cancellation arrives here too.
            cancellation = ProviderCancelledError(trace.attempts)
            trace.cancelled = True
            await self._persist_cancellation(trace, cancellation)
            raise cancellation from None
        except Exception:
            logger.warning("TRACE_PERSIST_FAILED trace_id=%s", trace.trace_id)
            if not fail_open:
                raise AppError(ErrorCode.INTERNAL_ERROR, "trace persistence failed", 500) from None


def _schema_error_message(exc: ValidationError) -> str:
    """Expose field-level contract failures without echoing model content."""

    descriptions: list[str] = []
    labels = {
        "missing": "缺失",
        "extra_forbidden": "不允许出现",
        "list_type": "应为数组",
        "dict_type": "应为对象",
        "model_type": "应为对象",
        "string_type": "应为字符串",
        "float_type": "应为数字",
        "bool_type": "应为布尔值",
    }
    for issue in exc.errors(include_url=False, include_context=False, include_input=False)[:6]:
        location = ".".join(str(part) for part in issue["loc"]) or "根对象"
        description = labels.get(issue["type"], "格式错误")
        descriptions.append(f"{location} {description}")
    detail = "；".join(descriptions) if descriptions else "字段结构错误"
    return f"模型返回字段不符合要求：{detail}"
