"""Stable intent contracts and pure validation helpers for the router.

This module deliberately has no database, FastAPI, or provider dependency.  It
is the boundary shared by the future provider, release loader, runtime API and
evaluation worker.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

RouteKey = Literal[
    "training_business",
    "information_query",
    "sports_knowledge",
    "safety",
    "dialogue_device_control",
    "social_chat",
    "unknown",
]

FIXED_ROUTE_KEYS: tuple[RouteKey, ...] = (
    "training_business",
    "information_query",
    "sports_knowledge",
    "safety",
    "dialogue_device_control",
    "social_chat",
    "unknown",
)
FIXED_ROUTE_KEY_SET = frozenset(FIXED_ROUTE_KEYS)
# Kept as a named constant for callers that need a set-style membership check.
ROUTE_CONTRACT = FIXED_ROUTE_KEY_SET


def canonical_json(value: object) -> str:
    """Serialize JSON-compatible data in the one format used for hashes."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_canonical(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IntentAnalyzeRequest(ContractModel):
    request_id: str | None = Field(default=None, min_length=1, max_length=128)
    text: str = Field(min_length=1)
    conversation_id: str | None = Field(default=None, min_length=1, max_length=128)
    context: dict[str, Any] = Field(default_factory=dict)

    @field_validator("text")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must not be blank or whitespace-only")
        return value


class IntentCandidate(ContractModel):
    name: str = Field(min_length=1)
    zh: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class SlotValue(ContractModel):
    name: str = Field(min_length=1)
    zh: str = Field(min_length=1)
    value: str = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def valid_span_order(self) -> SlotValue:
        if self.end < self.start:
            raise ValueError("slot end must be greater than or equal to start")
        return self


class RiskInfo(ContractModel):
    type: str = Field(min_length=1)
    zh: str = Field(min_length=1)
    level: Literal["low", "medium", "high"]


class EvidenceItem(ContractModel):
    """Debug-only evidence retained in Trace, never returned by Runtime."""

    type: str = Field(min_length=1)
    text: str = Field(min_length=1)


def _validate_clarification(
    route: RouteKey,
    need_clarification: bool,
    clarification: str | None,
    *,
    allow_training_normalization: bool = False,
) -> None:
    if not need_clarification and clarification is not None:
        raise ValueError("clarification must be null when need_clarification is false")
    if need_clarification and (clarification is None or not clarification.strip()):
        raise ValueError("clarification must be a non-empty string when need_clarification is true")
    if (
        route == "training_business"
        and (need_clarification or clarification is not None)
        and not allow_training_normalization
    ):
        raise ValueError("training_business cannot require clarification")


def _validate_intent_order(intents: list[IntentCandidate]) -> None:
    if any(
        intents[index].confidence < intents[index + 1].confidence
        for index in range(len(intents) - 1)
    ):
        raise ValueError("intents must be ordered by descending confidence")


class IntentResult(ContractModel):
    """The public runtime result. It intentionally contains no debug fields."""

    request_id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1)
    route: RouteKey
    intents: list[IntentCandidate]
    slots: list[SlotValue] = Field(default_factory=list)
    risk: RiskInfo | None
    need_clarification: bool
    clarification: str | None = None

    @model_validator(mode="after")
    def valid_runtime_invariants(self) -> IntentResult:
        _validate_intent_order(self.intents)
        _validate_clarification(self.route, self.need_clarification, self.clarification)
        return self


class LLMStructuredIntentOutput(ContractModel):
    """Strict model output, including trace-only reasoning and evidence."""

    route: RouteKey
    intents: list[IntentCandidate]
    slots: list[SlotValue] = Field(default_factory=list)
    risk: RiskInfo | None
    need_clarification: bool
    clarification: str | None = None
    reason_summary: str | None = None
    evidence: list[EvidenceItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_llm_invariants(self) -> LLMStructuredIntentOutput:
        _validate_intent_order(self.intents)
        _validate_clarification(
            self.route,
            self.need_clarification,
            self.clarification,
            allow_training_normalization=True,
        )
        return self


class RouteDefinition(ContractModel):
    name: RouteKey
    zh: str = Field(min_length=1)
    description: str = Field(min_length=1)
    enabled: bool


class IntentDefinition(ContractModel):
    name: str = Field(min_length=1)
    zh: str = Field(min_length=1)
    route: RouteKey
    description: str = Field(min_length=1)
    enabled: bool
    aliases: list[str] = Field(default_factory=list)
    mapping_note: str | None = None

    @field_validator("aliases")
    @classmethod
    def aliases_must_not_be_blank(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError("intent aliases must not be blank")
        return value


class SlotDefinition(ContractModel):
    name: str = Field(min_length=1)
    zh: str = Field(min_length=1)
    description: str = Field(min_length=1)
    value_type: Literal["string", "enum"]
    enabled: bool
    enum_group: str | None = None

    @model_validator(mode="after")
    def enum_group_matches_value_type(self) -> SlotDefinition:
        if self.value_type == "enum" and not self.enum_group:
            raise ValueError("enum slot requires enum_group")
        if self.value_type == "string" and self.enum_group is not None:
            raise ValueError("string slot cannot declare enum_group")
        return self


class EnumValueDefinition(ContractModel):
    canonical: str = Field(min_length=1)
    display: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    enabled: bool = True

    @field_validator("aliases")
    @classmethod
    def aliases_must_not_be_blank(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError("enum aliases must not be blank")
        return value


class ExampleDefinition(ContractModel):
    text: str = Field(min_length=1)
    route: RouteKey
    intent: str | None = Field(default=None, min_length=1)
    enabled: bool = True


class PromptTemplate(ContractModel):
    system: str = Field(min_length=1)
    rules: list[str] = Field(default_factory=list)

    @field_validator("rules")
    @classmethod
    def rules_must_not_be_blank(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError("prompt rules must not be blank")
        return value


class RuntimeConfigSnapshot(ContractModel):
    """The complete, immutable business configuration consumed at runtime."""

    schema_version: Literal[1]
    routes: list[RouteDefinition]
    intents: list[IntentDefinition]
    slots: list[SlotDefinition]
    enums: dict[str, list[EnumValueDefinition]]
    examples: list[ExampleDefinition]
    prompt_template: PromptTemplate

    @model_validator(mode="after")
    def valid_business_config(self) -> RuntimeConfigSnapshot:
        route_names = [route.name for route in self.routes]
        if set(route_names) != FIXED_ROUTE_KEY_SET or len(route_names) != len(FIXED_ROUTE_KEYS):
            raise ValueError("routes must contain exactly the seven fixed Route Contract keys")
        if any(not route.enabled for route in self.routes):
            raise ValueError("all fixed Route Contract routes must be enabled")

        _ensure_unique([item.name for item in self.intents], "intent names")
        names: dict[str, str] = {}
        for intent in self.intents:
            for label in (intent.name, intent.zh, *intent.aliases):
                label = label.strip()
                if not label:
                    raise ValueError("intent name/zh/alias must not be blank")
                owner = names.setdefault(label, intent.name)
                if owner != intent.name:
                    raise ValueError(f"intent name/zh/alias conflict: {label}")
        _ensure_unique([item.name for item in self.slots], "slot names")
        for group_name, values in self.enums.items():
            if not group_name.strip():
                raise ValueError("enum group names must not be blank")
            _ensure_unique(
                [item.canonical for item in values], f"enum {group_name} canonical values"
            )
        for slot in self.slots:
            if slot.value_type == "enum" and slot.enum_group not in self.enums:
                raise ValueError(f"slot {slot.name} references an unknown enum_group")

        intents_by_name = {item.name: item for item in self.intents}
        for example in self.examples:
            if example.intent is None:
                continue
            intent = intents_by_name.get(example.intent)
            if intent is None:
                raise ValueError(f"example references unknown intent {example.intent}")
            if intent.route != example.route:
                raise ValueError("example intent route must match example route")
        return self

    @property
    def active_intents(self) -> list[IntentDefinition]:
        return [item for item in self.intents if item.enabled]

    @property
    def active_slots(self) -> list[SlotDefinition]:
        return [item for item in self.slots if item.enabled]

    def canonical_hash(self) -> str:
        return sha256_canonical(self.model_dump(mode="json"))


def validate_runtime_config_snapshot(
    snapshot: RuntimeConfigSnapshot | dict[str, Any],
) -> RuntimeConfigSnapshot:
    """Validate a release/draft business snapshot at the pure-contract boundary."""

    if isinstance(snapshot, RuntimeConfigSnapshot):
        # Pydantic accepts an instance as already valid. Reconstructing from its
        # JSON representation deliberately catches later in-memory mutation.
        return RuntimeConfigSnapshot.model_validate(snapshot.model_dump(mode="json"))
    return RuntimeConfigSnapshot.model_validate(snapshot)


def _ensure_unique(values: list[str], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must be unique")


class ModelConfigSnapshot(ContractModel):
    """Non-secret, immutable model settings frozen with a release/run."""

    id: int = Field(gt=0)
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    base_url: str = Field(min_length=1)
    params_json: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("params_json", "params"),
    )
    timeout_seconds: float = Field(gt=0)
    max_retries: int = Field(ge=0)
    max_concurrency: int = Field(gt=0)
    structured_output_mode: Literal["json_schema", "json_object"]
    credential_ref: str = Field(min_length=1)
    model_config_hash: str = Field(min_length=64, max_length=64)
    enabled: bool = True

    @model_validator(mode="after")
    def structured_output_does_not_send_max_tokens(self) -> ModelConfigSnapshot:
        if self.params_json.get("max_tokens") is not None:
            raise ValueError("max_tokens must be null or omitted for structured output")
        return self


class PromptMessage(ContractModel):
    role: Literal["system", "user"]
    content: str


class PromptBuildResult(ContractModel):
    messages: list[PromptMessage] = Field(min_length=1)
    final_prompt: str = Field(min_length=1)
    prompt_hash: str = Field(min_length=64, max_length=64)
    metadata: dict[str, Any]


class OutputValidationIssue(ContractModel):
    code: Literal[
        "SLOT_SPAN_INVALID",
        "INTENTS_EMPTY_NON_TRAINING",
        "CLARIFICATION_FORCED_OFF",
    ]
    slot: SlotValue | None = None
    # Trace-only marker.  It is never part of the public IntentResult contract.
    truncated: bool = False


class ValidatedIntentOutput(ContractModel):
    result: IntentResult
    validation_issues: list[OutputValidationIssue] = Field(default_factory=list)


class BusinessOutputValidationError(ValueError):
    """A schema-valid model output contradicts the current business snapshot."""


def validate_llm_output(
    output: LLMStructuredIntentOutput,
    snapshot: RuntimeConfigSnapshot,
    *,
    request_id: str,
    text: str,
) -> ValidatedIntentOutput:
    """Apply dynamic business validation and repair/drop invalid UTF-16 slot spans.

    Slot span errors are intentionally non-fatal: a uniquely located value is
    repaired, otherwise that slot is omitted and a Trace-ready issue is returned.
    All other snapshot contradictions are fatal business validation errors.
    """

    config = validate_runtime_config_snapshot(snapshot)
    intent_by_name = {item.name: item for item in config.active_intents}
    normalized_intents: list[IntentCandidate] = []
    for candidate in output.intents:
        configured = intent_by_name.get(candidate.name)
        if configured is None:
            raise BusinessOutputValidationError(f"intent {candidate.name} is not enabled")
        if configured.route != output.route:
            raise BusinessOutputValidationError(
                f"intent {candidate.name} does not belong to route {output.route}"
            )
        normalized_intents.append(
            IntentCandidate(name=configured.name, zh=configured.zh, confidence=candidate.confidence)
        )

    slots_by_name = {item.name: item for item in config.active_slots}
    issues: list[OutputValidationIssue] = []
    if not output.intents and output.route != "training_business":
        issues.append(OutputValidationIssue(code="INTENTS_EMPTY_NON_TRAINING"))

    normalized_need_clarification = output.need_clarification
    normalized_clarification = output.clarification
    if output.route == "training_business" and output.need_clarification:
        normalized_need_clarification = False
        normalized_clarification = None
        issues.append(OutputValidationIssue(code="CLARIFICATION_FORCED_OFF"))

    normalized_slots: list[SlotValue] = []
    for slot in output.slots:
        configured_slot = slots_by_name.get(slot.name)
        if configured_slot is None:
            raise BusinessOutputValidationError(f"slot {slot.name} is not enabled")
        enum_value: EnumValueDefinition | None = None
        if configured_slot.value_type == "enum":
            assert configured_slot.enum_group is not None
            enum_value = _find_enum_value(config.enums[configured_slot.enum_group], slot.value)
            if enum_value is None:
                raise BusinessOutputValidationError(
                    f"slot {slot.name} value is not in enum {configured_slot.enum_group}"
                )
        normalized_slot = SlotValue(
            name=configured_slot.name,
            zh=configured_slot.zh,
            value=slot.value,
            start=slot.start,
            end=slot.end,
            confidence=slot.confidence,
        )
        repaired = _validate_or_repair_span(text, normalized_slot, enum_value)
        if repaired is None:
            issues.append(OutputValidationIssue(code="SLOT_SPAN_INVALID", slot=normalized_slot))
        else:
            normalized_slots.append(repaired)

    return ValidatedIntentOutput(
        result=IntentResult(
            request_id=request_id,
            text=text,
            route=output.route,
            intents=normalized_intents,
            slots=normalized_slots,
            risk=output.risk,
            need_clarification=normalized_need_clarification,
            clarification=normalized_clarification,
        ),
        validation_issues=issues,
    )


def _find_enum_value(values: list[EnumValueDefinition], value: str) -> EnumValueDefinition | None:
    for enum_value in values:
        if enum_value.enabled and value in _enum_forms(enum_value):
            return enum_value
    return None


def _enum_forms(value: EnumValueDefinition) -> tuple[str, ...]:
    return (value.canonical, value.display, *value.aliases)


def _validate_or_repair_span(
    text: str, slot: SlotValue, enum_value: EnumValueDefinition | None
) -> SlotValue | None:
    accepted_values = _enum_forms(enum_value) if enum_value is not None else (slot.value,)
    existing = _utf16_substring(text, slot.start, slot.end)
    if existing is not None and existing in accepted_values:
        return slot

    matches = _find_unique_value_span(text, accepted_values)
    if matches is None:
        return None
    start, end = matches
    return slot.model_copy(update={"start": start, "end": end})


def _find_unique_value_span(text: str, values: tuple[str, ...]) -> tuple[int, int] | None:
    """Find exactly one semantic occurrence, preferring the longest form at an offset."""

    offsets = _utf16_offsets(text)
    by_start: dict[int, int] = {}
    for value in set(values):
        if not value:
            continue
        search_from = 0
        while True:
            char_start = text.find(value, search_from)
            if char_start < 0:
                break
            char_end = char_start + len(value)
            start, end = offsets[char_start], offsets[char_end]
            by_start[start] = max(by_start.get(start, end), end)
            search_from = char_start + 1
    if len(by_start) != 1:
        return None
    start, end = next(iter(by_start.items()))
    return start, end


def _utf16_offsets(text: str) -> list[int]:
    offsets = [0]
    current = 0
    for character in text:
        current += 2 if ord(character) > 0xFFFF else 1
        offsets.append(current)
    return offsets


def _utf16_substring(text: str, start: int, end: int) -> str | None:
    offsets = _utf16_offsets(text)
    try:
        start_index = offsets.index(start)
        end_index = offsets.index(end)
    except ValueError:
        return None
    if end_index < start_index:
        return None
    return text[start_index:end_index]
