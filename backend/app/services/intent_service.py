"""The TASK-102 runtime pipeline, deliberately independent of FastAPI and MySQL."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.core.diagnostics import diagnostic_text, error_summary, sanitize
from app.core.errors import AppError, ErrorCode
from app.prompting.builder import PromptBuilder
from app.providers.factory import ModelProviderFactory, configuration_error, verify_provider
from app.providers.qwen import ProviderError
from app.providers.types import LLMAttempt, LLMProvider, ProviderCancelledError, diagnostic_attempts
from app.schemas.config import business_snapshot, release_fingerprint, verified_model_snapshot
from app.schemas.intent import (
    BusinessOutputValidationError,
    IntentAnalyzeRequest,
    IntentResult,
    LLMStructuredIntentOutput,
    ModelConfigSnapshot,
    OutputValidationIssue,
    RuntimeConfigSnapshot,
    validate_llm_output,
)

logger = logging.getLogger(__name__)
CANCEL_TRACE_TIMEOUT_SECONDS = 0.1


class RuntimeConfiguration(BaseModel):
    """The immutable inputs required by one runtime execution."""

    model_config = ConfigDict(extra="forbid")

    snapshot: RuntimeConfigSnapshot
    model_config_snapshot: ModelConfigSnapshot
    release_id: int = Field(gt=0)
    config_snapshot_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    model_config_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    release_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def verify_provenance(self) -> RuntimeConfiguration:
        payload, digest = business_snapshot(self.snapshot)
        model = verified_model_snapshot(self.model_config_snapshot)
        if (
            digest != self.config_snapshot_hash
            or model.model_config_hash != self.model_config_hash
            or release_fingerprint(digest, model.id, model.model_config_hash)
            != self.release_fingerprint
        ):
            raise ValueError("Release provenance mismatch")
        self.snapshot = RuntimeConfigSnapshot.model_validate(payload)
        self.model_config_snapshot = model
        return self

    @classmethod
    def from_release(cls, release: dict[str, Any]) -> RuntimeConfiguration:
        return cls(
            snapshot=release["snapshot_json"],
            model_config_snapshot=release["model_config_snapshot"],
            release_id=release["id"],
            config_snapshot_hash=release["config_snapshot_hash"],
            model_config_hash=release["model_config_hash"],
            release_fingerprint=release["release_fingerprint"],
        )


class RuntimeConfigLoader(Protocol):
    async def load(self) -> RuntimeConfiguration: ...


class TraceRecord(BaseModel):
    """In-memory Trace representation; durable storage is TASK-103 scope."""

    model_config = ConfigDict(extra="forbid")

    trace_id: str
    request_id: str
    text: str
    model_config_id: int | None = None
    release_id: int | None = None
    config_snapshot_hash: str | None = None
    model_config_hash: str | None = None
    release_fingerprint: str | None = None
    model_config_snapshot: dict[str, Any] | None = None
    attempts: list[LLMAttempt] = Field(default_factory=list)
    validation_issues: list[OutputValidationIssue] = Field(default_factory=list)
    cancelled: bool = False
    error_code: ErrorCode | None = None
    error_message: str | None = None

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

    def __init__(self, snapshot: RuntimeConfigSnapshot, model_config: ModelConfigSnapshot) -> None:
        _, digest = business_snapshot(snapshot)
        self._configuration = RuntimeConfiguration(
            snapshot=snapshot,
            model_config_snapshot=model_config,
            release_id=1,
            config_snapshot_hash=digest,
            model_config_hash=model_config.model_config_hash,
            release_fingerprint=release_fingerprint(
                digest, model_config.id, model_config.model_config_hash
            ),
        )

    async def load(self) -> RuntimeConfiguration:
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
    ) -> None:
        self._config_loader = config_loader
        self._provider = provider
        self._prompt_builder = prompt_builder
        self._trace_sink = trace_sink

    async def analyze(
        self,
        *,
        text: str,
        context: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> IntentResult:
        request = IntentAnalyzeRequest(request_id=request_id, text=text, context=context or {})
        effective_request_id = request.request_id or str(uuid4())
        trace = TraceRecord(
            trace_id=str(uuid4()), request_id=effective_request_id, text=request.text
        )
        try:
            try:
                loaded = await self._config_loader.load()
                # A loader may return a mutated Pydantic instance. Never trust it
                # or retain references that another request can change.
                config = RuntimeConfiguration.model_validate(loaded.model_dump(mode="json"))
            except ValueError:
                raise configuration_error() from None
            trace.model_config_id = config.model_config_snapshot.id
            trace.release_id = config.release_id
            trace.config_snapshot_hash = config.config_snapshot_hash
            trace.model_config_hash = config.model_config_hash
            trace.release_fingerprint = config.release_fingerprint
            trace.model_config_snapshot = config.model_config_snapshot.model_dump(mode="json")
            provider = (
                self._provider.resolve(config.model_config_snapshot)
                if isinstance(self._provider, ModelProviderFactory)
                else self._provider
            )
            verify_provider(provider, config.model_config_snapshot)
            prompt = self._prompt_builder.build(config.snapshot, request.text, request.context)
            response = await provider.invoke(prompt)
            trace.attempts = response.attempts
            output = self._parse_output(response.content, response.attempts)
            validated = validate_llm_output(
                output,
                config.snapshot,
                request_id=effective_request_id,
                text=request.text,
            )
            trace.validation_issues = validated.validation_issues
            await self._persist_success(trace)
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
            await self._persist_failure(trace)
            raise
        except IntentServiceError as exc:
            trace.attempts = exc.attempts
            trace.error_code = exc.code
            trace.error_message = exc.message
            await self._persist_failure(trace)
            raise
        except BusinessOutputValidationError as exc:
            error = IntentServiceError(
                ErrorCode.MODEL_OUTPUT_SCHEMA_ERROR, str(exc), attempts=trace.attempts
            )
            trace.error_code = error.code
            trace.error_message = error.message
            await self._persist_failure(trace)
            raise error from None

    @staticmethod
    def _parse_output(content: str, attempts: list[LLMAttempt]) -> LLMStructuredIntentOutput:
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
            return LLMStructuredIntentOutput.model_validate(payload)
        except ValidationError:
            raise IntentServiceError(
                ErrorCode.MODEL_OUTPUT_SCHEMA_ERROR,
                "model output does not conform to LLMStructuredIntentOutput",
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

    async def _persist_success(self, trace: TraceRecord) -> None:
        try:
            await self._trace_sink.write(TraceRecord.model_validate(trace.model_dump(mode="json")))
        except Exception:
            # Runtime business success is fail-open when Trace persistence fails.
            logger.warning("TRACE_PERSIST_FAILED trace_id=%s", trace.trace_id)
            return

    async def _persist_failure(self, trace: TraceRecord) -> None:
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
            # TASK-103 will distinguish Runtime from Debug/Replay/Evaluation modes.
            logger.warning("TRACE_PERSIST_FAILED trace_id=%s", trace.trace_id)
            return
