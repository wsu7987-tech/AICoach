"""Small process-local provider cache; the effective snapshot is the sole input.

No eviction of clients with in-flight calls. Close after draining requests at
application shutdown. Capacity exhaustion is explicit, never an old-model fallback.
"""

import asyncio
import hashlib

from app.core.errors import ErrorCode
from app.providers.openai_compatible import OpenAICompatibleProvider, ProviderError
from app.providers.types import LLMProvider
from app.schemas.intent import canonical_json
from app.schemas.managed_model import ManagedModelRuntimeSnapshot


def configuration_error(*, failure_stage: str = "configuration") -> ProviderError:
    return ProviderError(
        ErrorCode.CONFIG_NOT_READY,
        "effective model/provider configuration mismatch",
        503,
        attempts=[],
        failure_stage=failure_stage,
    )


def verify_managed_provider(
    provider: LLMProvider,
    effective: ManagedModelRuntimeSnapshot,
) -> None:
    try:
        bound = provider.runtime_snapshot
        if not isinstance(bound, ManagedModelRuntimeSnapshot):
            raise ValueError("snapshot type mismatch")
        if bound.model_dump(mode="json") != effective.model_dump(mode="json"):
            raise ValueError("identity mismatch")
    except (ValueError, AttributeError):
        raise configuration_error() from None


class ModelProviderFactory:
    def __init__(
        self,
        *,
        queue_wait_timeout: float,
        max_entries: int = 128,
    ):
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        self._queue_wait_timeout = queue_wait_timeout
        self._max_entries = max_entries
        self._managed_providers: dict[
            tuple[str, str, str], OpenAICompatibleProvider
        ] = {}
        self._closed = False

    def resolve_managed(
        self,
        snapshot: ManagedModelRuntimeSnapshot,
        *,
        api_key: str,
        credential_revision: str,
    ) -> OpenAICompatibleProvider:
        effective = ManagedModelRuntimeSnapshot.model_validate(
            snapshot.model_dump(mode="json")
        )
        if self._closed or not effective.enabled:
            raise configuration_error()
        snapshot_hash = hashlib.sha256(
            canonical_json(effective.model_dump(mode="json")).encode()
        ).hexdigest()
        key = (effective.model_uid, snapshot_hash, credential_revision)
        provider = self._managed_providers.get(key)
        if provider is None:
            if len(self._managed_providers) >= self._max_entries:
                raise ProviderError(
                    ErrorCode.SERVICE_BUSY,
                    "provider cache capacity reached",
                    503,
                    attempts=[],
                    retry_after=1,
                    failure_stage="connection",
                )
            provider = OpenAICompatibleProvider(
                effective,
                api_key=api_key,
                queue_wait_timeout=self._queue_wait_timeout,
            )
            self._managed_providers[key] = provider
        verify_managed_provider(provider, effective)
        return provider

    async def close(self) -> None:
        self._closed = True
        try:
            results = await asyncio.gather(
                *(
                    provider.close()
                    for provider in self._managed_providers.values()
                ),
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, BaseException):
                    raise result
        finally:
            self._managed_providers.clear()
