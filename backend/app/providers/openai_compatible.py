"""Provider for services implementing the OpenAI-compatible chat API."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import httpx
import openai
from openai import AsyncOpenAI

from app.core.diagnostics import error_summary, sanitize
from app.core.errors import AppError, ErrorCode
from app.providers.types import (
    LLMAttempt,
    LLMResponse,
    ProviderCancelledError,
    diagnostic_attempts,
)
from app.schemas.intent import LLMStructuredIntentOutput, ModelConfigSnapshot, PromptBuildResult


class ProviderError(AppError):
    """Typed provider failure with every physical request made before failure."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        status_code: int,
        *,
        attempts: list[LLMAttempt],
        retry_after: int | None = None,
    ) -> None:
        super().__init__(code, error_summary(message), status_code, retry_after=retry_after)
        self.attempts = diagnostic_attempts(attempts)


class OpenAICompatibleProvider:
    """Bounded-retry client for an OpenAI-compatible endpoint."""

    def __init__(
        self,
        model_config: ModelConfigSnapshot,
        *,
        api_key: str,
        queue_wait_timeout: float,
        provider_name: str = "openai_compatible",
        backoff_base_seconds: float = 0.25,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._model_config = ModelConfigSnapshot.model_validate(
            model_config.model_dump(mode="json")
        )
        self._provider_name = provider_name
        self.base_url = model_config.base_url
        self.queue_wait_timeout = queue_wait_timeout
        self.backoff_base_seconds = backoff_base_seconds
        self._semaphore = asyncio.Semaphore(model_config.max_concurrency)
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=model_config.base_url,
            timeout=model_config.timeout_seconds,
            max_retries=0,
            http_client=http_client or httpx.AsyncClient(trust_env=False),
        )

    @property
    def model_config(self) -> ModelConfigSnapshot:
        return self._model_config.model_copy(deep=True)

    async def close(self) -> None:
        await self._client.close()

    @property
    def sdk_max_retries(self) -> int:
        return self._client.max_retries

    async def invoke(self, prompt: PromptBuildResult) -> LLMResponse:
        acquired = False
        try:
            try:
                await asyncio.wait_for(self._semaphore.acquire(), timeout=self.queue_wait_timeout)
                acquired = True
            except TimeoutError as exc:
                raise ProviderError(
                    ErrorCode.SERVICE_BUSY,
                    "provider concurrency queue wait timed out",
                    503,
                    attempts=[],
                    retry_after=max(1, int(self.queue_wait_timeout)),
                ) from exc
            return await self._invoke_after_acquire(prompt)
        except asyncio.CancelledError as exc:
            if isinstance(exc, ProviderCancelledError):
                raise
            raise ProviderCancelledError([]) from exc
        finally:
            if acquired:
                self._semaphore.release()

    async def _invoke_after_acquire(self, prompt: PromptBuildResult) -> LLMResponse:
        request = self._build_request(prompt)
        attempts: list[LLMAttempt] = []
        total_attempts = self.model_config.max_retries + 1
        for attempt_no in range(1, total_attempts + 1):
            started = time.perf_counter()
            try:
                completion = await self._client.chat.completions.create(**request)
                content = completion.choices[0].message.content or ""
                raw_response = self.sanitize(completion.model_dump(mode="json"))
                parsed_payload = self._parse_if_json(content)
                choice = completion.choices[0]
                attempts.append(
                    LLMAttempt(
                        attempt_no=attempt_no,
                        is_retry=attempt_no > 1,
                        provider=self._provider_name,
                        model=self.model_config.model,
                        params=self._safe_params(request),
                        raw_request=self.sanitize(request),
                        raw_response=raw_response,
                        parsed_payload=parsed_payload,
                        provider_request_id=getattr(completion, "_request_id", None),
                        model_version=getattr(completion, "model", None),
                        system_fingerprint=getattr(completion, "system_fingerprint", None),
                        finish_reason=choice.finish_reason,
                        usage=(
                            completion.usage.model_dump(mode="json") if completion.usage else None
                        ),
                        latency_ms=self._elapsed_ms(started),
                        status="succeeded",
                    )
                )
                return LLMResponse(
                    content=content,
                    attempts=attempts,
                    response_mode=self.model_config.structured_output_mode,
                )
            except asyncio.CancelledError as exc:
                attempts.append(self._cancelled_attempt(attempt_no, request, started))
                raise ProviderCancelledError(attempts) from exc
            except Exception as exc:
                code, status_code, retryable = self._classify_error(exc)
                attempts.append(self._failed_attempt(attempt_no, request, started, exc, code))
                if retryable and attempt_no < total_attempts:
                    try:
                        await asyncio.sleep(self.backoff_base_seconds * (2 ** (attempt_no - 1)))
                    except asyncio.CancelledError as cancellation:
                        raise ProviderCancelledError(attempts) from cancellation
                    continue
                raise ProviderError(
                    code,
                    self._safe_error_message(exc),
                    status_code,
                    attempts=attempts,
                    retry_after=self._retry_after(exc),
                ) from None
        raise AssertionError("bounded retry loop must return or raise")

    def _build_request(self, prompt: PromptBuildResult) -> dict[str, Any]:
        params = {
            key: value
            for key, value in self.model_config.params_json.items()
            if key not in {"max_tokens", "response_format", "model", "messages"}
        }
        request: dict[str, Any] = {
            "model": self.model_config.model,
            "messages": [message.model_dump(mode="json") for message in prompt.messages],
            **params,
            "response_format": self._response_format(),
        }
        request.pop("max_tokens", None)
        return request

    def _response_format(self) -> dict[str, Any]:
        if self.model_config.structured_output_mode == "json_object":
            return {"type": "json_object"}
        schema = LLMStructuredIntentOutput.model_json_schema()
        self._validate_json_schema(schema)
        return {
            "type": "json_schema",
            "json_schema": {
                "name": LLMStructuredIntentOutput.__name__,
                "strict": True,
                "schema": schema,
            },
        }

    def _validate_json_schema(self, schema: dict[str, Any]) -> None:
        """Adapter hook for an endpoint's documented schema restrictions."""

    sanitize = staticmethod(sanitize)

    @staticmethod
    def _parse_if_json(content: str) -> dict[str, Any] | None:
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _elapsed_ms(started: float) -> float:
        return round((time.perf_counter() - started) * 1000, 3)

    @staticmethod
    def _safe_params(request: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in request.items() if key not in {"messages", "model"}}

    def _failed_attempt(
        self,
        attempt_no: int,
        request: dict[str, Any],
        started: float,
        exc: Exception,
        code: ErrorCode,
    ) -> LLMAttempt:
        return LLMAttempt(
            attempt_no=attempt_no,
            is_retry=attempt_no > 1,
            provider=self._provider_name,
            model=self.model_config.model,
            params=self._safe_params(request),
            raw_request=self.sanitize(request),
            raw_response=self._error_response(exc),
            provider_request_id=getattr(exc, "request_id", None),
            latency_ms=self._elapsed_ms(started),
            status="failed",
            error_code=code,
            error_message=self._safe_error_message(exc),
        )

    def _cancelled_attempt(
        self, attempt_no: int, request: dict[str, Any], started: float
    ) -> LLMAttempt:
        return LLMAttempt(
            attempt_no=attempt_no,
            is_retry=attempt_no > 1,
            provider=self._provider_name,
            model=self.model_config.model,
            params=self._safe_params(request),
            raw_request=self.sanitize(request),
            latency_ms=self._elapsed_ms(started),
            status="cancelled",
            error_message="model request cancelled by caller",
        )

    @staticmethod
    def _classify_error(exc: Exception) -> tuple[ErrorCode, int, bool]:
        if isinstance(exc, openai.APITimeoutError):
            return ErrorCode.MODEL_TIMEOUT, 504, True
        if isinstance(exc, openai.RateLimitError):
            return ErrorCode.MODEL_RATE_LIMIT, 503, True
        if isinstance(exc, openai.InternalServerError):
            return ErrorCode.MODEL_PROVIDER_ERROR, 502, True
        if isinstance(exc, openai.APIConnectionError):
            return ErrorCode.MODEL_PROVIDER_ERROR, 502, True
        if isinstance(exc, openai.APIStatusError):
            return ErrorCode.MODEL_PROVIDER_ERROR, 502, exc.status_code >= 500
        return ErrorCode.MODEL_PROVIDER_ERROR, 502, False

    @staticmethod
    def _safe_error_message(exc: Exception) -> str:
        if isinstance(exc, openai.APIError):
            summary = {"type": type(exc).__name__}
            if isinstance(exc, openai.APIStatusError):
                summary["status_code"] = exc.status_code
            if exc.body is not None:
                summary["body"] = sanitize(exc.body)
            return error_summary(json.dumps(summary, ensure_ascii=False))
        return error_summary(f"{type(exc).__name__}: {exc}")

    @staticmethod
    def _error_response(exc: Exception) -> dict[str, Any] | None:
        response = getattr(exc, "response", None)
        if response is None:
            return None
        try:
            return OpenAICompatibleProvider.sanitize(response.json())
        except (ValueError, TypeError):
            return {"status_code": getattr(response, "status_code", None)}

    @staticmethod
    def _retry_after(exc: Exception) -> int | None:
        response = getattr(exc, "response", None)
        header = getattr(response, "headers", {}).get("retry-after") if response else None
        try:
            return int(header) if header is not None else None
        except ValueError:
            return None
