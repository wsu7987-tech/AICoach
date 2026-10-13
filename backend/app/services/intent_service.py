"""The TASK-102 runtime pipeline, deliberately independent of FastAPI and MySQL."""

from __future__ import annotations

import json
from typing import Any, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.errors import AppError, ErrorCode
from app.prompting.builder import PromptBuilder
from app.providers.qwen import ProviderError
from app.providers.types import LLMAttempt, LLMProvider
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


class RuntimeConfiguration(BaseModel):
    """The immutable inputs required by one runtime execution."""

    model_config = ConfigDict(extra="forbid")

    snapshot: RuntimeConfigSnapshot
    model_config_snapshot: ModelConfigSnapshot


class RuntimeConfigLoader(Protocol):
    async def load(self) -> RuntimeConfiguration: ...


class TraceRecord(BaseModel):
    """In-memory Trace representation; durable storage is TASK-103 scope."""

    model_config = ConfigDict(extra="forbid")

    trace_id: str
    request_id: str
    text: str
    model_config_id: int | None = None
    attempts: list[LLMAttempt] = Field(default_factory=list)
    validation_issues: list[OutputValidationIssue] = Field(default_factory=list)
    error_code: ErrorCode | None = None
    error_message: str | None = None


class TraceSink(Protocol):
    async def write(self, trace: TraceRecord) -> None: ...


class IntentServiceError(AppError):
    """Parser/schema/business validation error; never a fabricated unknown result."""

    def __init__(
        self, code: ErrorCode, message: str, *, attempts: list[LLMAttempt] | None = None
    ) -> None:
        super().__init__(code, message, 502)
        self.attempts = attempts or []


class InMemoryRuntimeConfigLoader:
    """Test-only loader. TASK-201 will provide the active-release implementation."""

    def __init__(self, snapshot: RuntimeConfigSnapshot, model_config: ModelConfigSnapshot) -> None:
        self._configuration = RuntimeConfiguration(
            snapshot=snapshot,
            model_config_snapshot=model_config,
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
        provider: LLMProvider,
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
            config = await self._config_loader.load()
            trace.model_config_id = config.model_config_snapshot.id
            prompt = self._prompt_builder.build(config.snapshot, request.text, request.context)
            response = await self._provider.invoke(prompt)
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
            raise error from exc

    @staticmethod
    def _parse_output(content: str, attempts: list[LLMAttempt]) -> LLMStructuredIntentOutput:
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise IntentServiceError(
                ErrorCode.MODEL_OUTPUT_PARSE_ERROR,
                "model output is not valid JSON",
                attempts=attempts,
            ) from exc
        if not isinstance(payload, dict):
            raise IntentServiceError(
                ErrorCode.MODEL_OUTPUT_SCHEMA_ERROR,
                "model output must be a JSON object",
                attempts=attempts,
            )
        try:
            return LLMStructuredIntentOutput.model_validate(payload)
        except ValidationError as exc:
            raise IntentServiceError(
                ErrorCode.MODEL_OUTPUT_SCHEMA_ERROR,
                "model output does not conform to LLMStructuredIntentOutput",
                attempts=attempts,
            ) from exc

    async def _persist_success(self, trace: TraceRecord) -> None:
        try:
            await self._trace_sink.write(trace)
        except Exception:
            # Runtime business success is fail-open when Trace persistence fails.
            return

    async def _persist_failure(self, trace: TraceRecord) -> None:
        try:
            await self._trace_sink.write(trace)
        except Exception:
            # TASK-103 will distinguish Runtime from Debug/Replay/Evaluation modes.
            return
