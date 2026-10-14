"""Compatibility adapter for historical Qwen ModelConfig records."""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.providers.openai_compatible import OpenAICompatibleProvider, ProviderError
from app.schemas.intent import ModelConfigSnapshot

__all__ = ["ProviderError", "QwenProvider"]


class QwenProvider(OpenAICompatibleProvider):
    """Keep the v1.2.5 Qwen contract on top of the generic protocol client."""

    def __init__(
        self,
        model_config: ModelConfigSnapshot,
        *,
        api_key: str,
        queue_wait_timeout: float,
        backoff_base_seconds: float = 0.25,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(
            model_config,
            api_key=api_key,
            queue_wait_timeout=queue_wait_timeout,
            provider_name="qwen",
            backoff_base_seconds=backoff_base_seconds,
            http_client=http_client,
        )

    def _validate_json_schema(self, schema: dict[str, Any]) -> None:
        if "minItems" in json.dumps(schema, sort_keys=True):
            raise ValueError("Qwen structured schema must not contain minItems")
