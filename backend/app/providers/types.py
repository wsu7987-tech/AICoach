"""Provider-neutral request outcome and protocol types."""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.core.errors import ErrorCode
from app.schemas.intent import PromptBuildResult


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


class LLMResponse(ProviderModel):
    content: str
    attempts: list[LLMAttempt]
    response_mode: str


class LLMProvider(Protocol):
    async def invoke(self, prompt: PromptBuildResult) -> LLMResponse: ...
