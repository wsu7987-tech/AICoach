"""Small process-local provider cache; the effective snapshot is the sole input.

No eviction of clients with in-flight calls. Close after draining requests at
application shutdown. Capacity exhaustion is explicit, never an old-model fallback.
"""

import asyncio
from collections.abc import Callable

from app.core.errors import ErrorCode
from app.providers.qwen import ProviderError, QwenProvider
from app.providers.types import LLMProvider
from app.schemas.config import verified_model_snapshot
from app.schemas.intent import ModelConfigSnapshot


def configuration_error() -> ProviderError:
    return ProviderError(
        ErrorCode.CONFIG_NOT_READY,
        "effective model/provider configuration mismatch",
        503,
        attempts=[],
    )


def verify_provider(provider: LLMProvider, effective: ModelConfigSnapshot) -> None:
    try:
        bound = verified_model_snapshot(provider.model_config)
        expected = verified_model_snapshot(effective)
        if (bound.id, bound.model_config_hash) != (expected.id, expected.model_config_hash):
            raise ValueError("identity mismatch")
    except (ValueError, AttributeError):
        raise configuration_error() from None


class ModelProviderFactory:
    def __init__(
        self,
        credential_resolver: Callable[[str], str],
        *,
        queue_wait_timeout: float,
        max_entries: int = 128,
    ):
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        self._credentials = credential_resolver
        self._queue_wait_timeout = queue_wait_timeout
        self._max_entries = max_entries
        self._providers: dict[tuple[int, str], QwenProvider] = {}
        self._closed = False

    def resolve(self, snapshot: ModelConfigSnapshot) -> QwenProvider:
        try:
            effective = verified_model_snapshot(snapshot)
        except ValueError:
            raise configuration_error() from None
        if self._closed:
            raise configuration_error()
        key = (effective.id, effective.model_config_hash)
        provider = self._providers.get(key)
        if provider is None:
            if len(self._providers) >= self._max_entries:
                raise ProviderError(
                    ErrorCode.SERVICE_BUSY,
                    "provider cache capacity reached",
                    503,
                    attempts=[],
                    retry_after=1,
                )
            try:
                credential = self._credentials(effective.credential_ref)
                if not credential:
                    raise ValueError("missing credential")
                provider = QwenProvider(
                    effective, api_key=credential, queue_wait_timeout=self._queue_wait_timeout
                )
            except Exception:
                # Never expose secret resolver exception text.
                raise configuration_error() from None
            self._providers[key] = provider
        verify_provider(provider, effective)
        return provider

    async def close(self) -> None:
        self._closed = True
        try:
            results = await asyncio.gather(
                *(provider.close() for provider in self._providers.values()), return_exceptions=True
            )
            for result in results:
                if isinstance(result, BaseException):
                    raise result
        finally:
            self._providers.clear()
