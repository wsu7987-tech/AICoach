"""Deterministic, configuration-driven prompt construction."""

from __future__ import annotations

import hashlib
from typing import Any

from app.schemas.intent import (
    LLMStructuredIntentOutput,
    PromptBuildResult,
    PromptMessage,
    RuntimeConfigSnapshot,
    canonical_json,
)


class PromptBuilder:
    """Build a provider-agnostic messages payload without any I/O.

    The message content is canonical JSON so an identical snapshot, text, and
    context always produces byte-identical final_prompt and prompt_hash.
    """

    def build(
        self,
        snapshot: RuntimeConfigSnapshot | dict[str, Any],
        text: str,
        context: dict[str, Any] | None = None,
    ) -> PromptBuildResult:
        config = (
            snapshot
            if isinstance(snapshot, RuntimeConfigSnapshot)
            else RuntimeConfigSnapshot.model_validate(snapshot)
        )
        effective_config = _effective_config(config)
        system_payload = {
            "task": config.prompt_template.system,
            "rules": config.prompt_template.rules,
            "business_config": effective_config,
            "output_schema": LLMStructuredIntentOutput.model_json_schema(),
            "output_instruction": "Return exactly one JSON object conforming to output_schema.",
        }
        user_payload = {"context": context or {}, "text": text}
        messages = [
            PromptMessage(role="system", content=canonical_json(system_payload)),
            PromptMessage(role="user", content=canonical_json(user_payload)),
        ]
        messages_payload = [message.model_dump(mode="json") for message in messages]
        final_prompt = canonical_json(messages_payload)
        prompt_hash = hashlib.sha256(final_prompt.encode("utf-8")).hexdigest()
        return PromptBuildResult(
            messages=messages,
            final_prompt=final_prompt,
            prompt_hash=prompt_hash,
            metadata={
                "schema_version": config.schema_version,
                "config_snapshot_hash": config.canonical_hash(),
                "effective_config_hash": hashlib.sha256(
                    canonical_json(effective_config).encode("utf-8")
                ).hexdigest(),
                "output_schema_name": LLMStructuredIntentOutput.__name__,
            },
        )

    def preview(
        self,
        snapshot: RuntimeConfigSnapshot | dict[str, Any],
        text: str,
        context: dict[str, Any] | None = None,
    ) -> PromptBuildResult:
        """Admin-preview compatible alias; it is intentionally side-effect free."""

        return self.build(snapshot, text=text, context=context)


def _effective_config(snapshot: RuntimeConfigSnapshot) -> dict[str, Any]:
    active_intents = [item for item in snapshot.intents if item.enabled]
    active_intent_names = {item.name for item in active_intents}
    active_slots = [item for item in snapshot.slots if item.enabled]
    enum_groups_in_use = {
        item.enum_group for item in active_slots if item.value_type == "enum" and item.enum_group
    }
    return {
        "routes": [item.model_dump(mode="json") for item in snapshot.routes],
        "intents": [item.model_dump(mode="json") for item in active_intents],
        "slots": [item.model_dump(mode="json") for item in active_slots],
        "enums": {
            group: [item.model_dump(mode="json") for item in values if item.enabled]
            for group, values in snapshot.enums.items()
            if group in enum_groups_in_use
        },
        "examples": [
            item.model_dump(mode="json")
            for item in snapshot.examples
            if item.enabled and (item.intent is None or item.intent in active_intent_names)
        ],
    }
