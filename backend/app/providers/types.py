"""Provider-neutral request outcome and protocol types."""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.diagnostics import diagnostic_payload, diagnostic_text, error_summary, sanitize
from app.core.errors import ErrorCode
from app.schemas.intent import PromptBuildResult
from app.schemas.managed_model import ManagedModelRuntimeSnapshot


class ProviderModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LLMAttempt(ProviderModel):
    """One physical HTTP request, never an SDK-internal retry aggregate."""

    attempt_no: int = Field(gt=0)
    is_retry: bool
    provider: str
    model: str
    params: dict[str, Any]
    raw_request: dict[str, Any]
    raw_response: dict[str, Any] | None = None
    parsed_payload: dict[str, Any] | None = None
    provider_request_id: str | None = None
    model_version: str | None = None
    system_fingerprint: str | None = None
    finish_reason: str | None = None
    usage: dict[str, Any] | None = None
    latency_ms: float = Field(ge=0)
    status: str
    error_code: ErrorCode | None = None
    error_message: str | None = None

    @model_validator(mode="before")
    @classmethod
    def sanitize_diagnostics(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        clean = sanitize(value)
        for key, item in clean.items():
            if key in {"params", "raw_request", "raw_response", "parsed_payload", "usage"}:
                if item is not None:
                    clean[key] = diagnostic_payload(item)
            elif isinstance(item, str):
                clean[key] = (
                    error_summary(item) if key == "error_message" else diagnostic_text(item)
                )
        return clean


def diagnostic_attempts(attempts: list[LLMAttempt]) -> list[LLMAttempt]:
    # Dump/reparse also protects against mutated or model_construct'ed instances.
    return [LLMAttempt.model_validate(item.model_dump(mode="json")) for item in attempts]


class LLMResponse(ProviderModel):
    content: str
    attempts: list[LLMAttempt]
    response_mode: str


class ProviderCancelledError(asyncio.CancelledError):
    """Cancellation that carries diagnostics for HTTP requests already sent.

    It remains an asyncio cancellation, so callers must not treat it as a
    model/provider business failure.  An empty list means cancellation happened
    before this Provider issued a physical HTTP request.
    """

    def __init__(self, attempts: list[LLMAttempt]) -> None:
        super().__init__("provider invocation cancelled")
        self.attempts = diagnostic_attempts(attempts)
        self.trace_diagnostic: dict[str, Any] | None = None
        self.trace_write_status: str = "not_attempted"


class LLMProvider(Protocol):
    @property
    def runtime_snapshot(self) -> ManagedModelRuntimeSnapshot: ...

    async def invoke(self, prompt: PromptBuildResult) -> LLMResponse: ...
