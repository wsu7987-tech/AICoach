"""Stable intent contracts and pure validation helpers for the router.

This module deliberately has no database, FastAPI, or provider dependency.  It
is the boundary shared by the future provider, release loader, runtime API and
evaluation worker.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

type RouteKey = str


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
    model_uid: str | None = Field(default=None, pattern=r"^mdl_[a-f0-9]{64}$")
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
    raw_value: str | None = Field(default=None, exclude=True)
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
    need_clarification: bool,
    clarification: str | None,
) -> None:
    if not need_clarification and clarification is not None:
        raise ValueError("clarification must be null when need_clarification is false")
    if need_clarification and (clarification is None or not clarification.strip()):
        raise ValueError("clarification must be a non-empty string when need_clarification is true")


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
        _validate_clarification(self.need_clarification, self.clarification)
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
        _validate_clarification(self.need_clarification, self.clarification)
        return self


class LLMExtractedTextSlot(ContractModel):
    """Minimal text Slot emitted by the model; metadata and spans are server-owned."""

    name: str = Field(min_length=1)
    value: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class SlotCandidate(ContractModel):
    """One deterministic candidate produced by a reusable base Slot."""

    slot_name: str = Field(min_length=1)
    slot_zh: str = Field(min_length=1)
    value: str = Field(min_length=1)
    source: str = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    confidence: float = Field(default=1, ge=0, le=1)


class LLMRecognitionOutput(ContractModel):
    """Runtime V1 model output after enum extraction moved into the program."""

    route: RouteKey
    intents: list[IntentCandidate]
    slots: list[LLMExtractedTextSlot] = Field(default_factory=list)
    risk: RiskInfo | None
    need_clarification: bool
    clarification: str | None = None
    reason_summary: str | None = None
    evidence: list[EvidenceItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_llm_invariants(self) -> LLMRecognitionOutput:
        _validate_intent_order(self.intents)
        _validate_clarification(self.need_clarification, self.clarification)
        return self


type IntentComposition = Literal["single", "parallel", "sequential", "alternative"]


class IntentAction(ContractModel):
    """One independently routable action in the V2 runtime result."""

    action_id: str = Field(pattern=r"^action_[1-9][0-9]*$")
    route: RouteKey
    intent: IntentCandidate | None
    slots: list[SlotValue] = Field(default_factory=list)
    order: int = Field(ge=1)
    depends_on: list[str] = Field(default_factory=list)


class IntentResultV2(ContractModel):
    """Compound-aware public result. Debug-only reasoning remains in Trace."""

    schema_version: Literal[2] = 2
    request_id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1)
    is_compound: bool
    composition: IntentComposition
    actions: list[IntentAction]
    risk: RiskInfo | None
    need_clarification: bool
    clarification: str | None = None

    @model_validator(mode="after")
    def valid_compound_runtime_invariants(self) -> IntentResultV2:
        _validate_action_plan(
            self.actions,
            is_compound=self.is_compound,
            composition=self.composition,
            need_clarification=self.need_clarification,
        )
        _validate_clarification(self.need_clarification, self.clarification)
        return self


class LLMIntentAction(ContractModel):
    """One action emitted by the model before business normalization."""

    action_id: str = Field(pattern=r"^action_[1-9][0-9]*$")
    route: RouteKey
    intent: IntentCandidate | None
    slots: list[SlotValue] = Field(default_factory=list)
    order: int = Field(ge=1)
    depends_on: list[str] = Field(default_factory=list)


class LLMStructuredIntentOutputV2(ContractModel):
    """Strict compound-aware model output, with trace-only diagnostics."""

    schema_version: Literal[2] = 2
    is_compound: bool
    composition: IntentComposition
    actions: list[LLMIntentAction]
    risk: RiskInfo | None
    need_clarification: bool
    clarification: str | None = None
    reason_summary: str | None = None
    evidence: list[EvidenceItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_compound_llm_invariants(self) -> LLMStructuredIntentOutputV2:
        _validate_action_plan(
            self.actions,
            is_compound=self.is_compound,
            composition=self.composition,
            need_clarification=self.need_clarification,
        )
        _validate_clarification(self.need_clarification, self.clarification)
        return self


class LLMRecognitionAction(ContractModel):
    """One model-classified action with the exact source fragment it covers."""

    action_id: str = Field(pattern=r"^action_[1-9][0-9]*$")
    source_text: str = Field(min_length=1)
    route: RouteKey
    intent: IntentCandidate | None
    slots: list[LLMExtractedTextSlot] = Field(default_factory=list)
    order: int = Field(ge=1)
    depends_on: list[str] = Field(default_factory=list)


class LLMRecognitionOutputV2(ContractModel):
    """Runtime V2 model output with lightweight text Slots only."""

    schema_version: Literal[2] = 2
    is_compound: bool
    composition: IntentComposition
    actions: list[LLMRecognitionAction]
    risk: RiskInfo | None
    need_clarification: bool
    clarification: str | None = None
    reason_summary: str | None = None
    evidence: list[EvidenceItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_compound_llm_invariants(self) -> LLMRecognitionOutputV2:
        _validate_action_plan(
            self.actions,
            is_compound=self.is_compound,
            composition=self.composition,
            need_clarification=self.need_clarification,
        )
        _validate_clarification(self.need_clarification, self.clarification)
        return self


def _validate_action_plan(
    actions: list[IntentAction] | list[LLMIntentAction] | list[LLMRecognitionAction],
    *,
    is_compound: bool,
    composition: IntentComposition,
    need_clarification: bool,
) -> None:
    if not actions:
        raise ValueError("actions must contain at least one action")
    expected_compound = len(actions) > 1
    if is_compound != expected_compound:
        raise ValueError("is_compound must match whether actions contains multiple items")
    if (composition == "single") != (len(actions) == 1):
        raise ValueError("single composition must contain exactly one action")

    action_ids = [action.action_id for action in actions]
    _ensure_unique(action_ids, "action ids")
    orders = [action.order for action in actions]
    _ensure_unique(orders, "action orders")
    if sorted(orders) != list(range(1, len(actions) + 1)):
        raise ValueError("action orders must be contiguous and start at 1")

    known_ids = set(action_ids)
    action_order = {action.action_id: action.order for action in actions}
    for action in actions:
        if len(action.depends_on) != len(set(action.depends_on)):
            raise ValueError(f"action {action.action_id} contains duplicate dependencies")
        for dependency in action.depends_on:
            if dependency not in known_ids:
                raise ValueError(f"action {action.action_id} references an unknown dependency")
            if action_order[dependency] >= action.order:
                raise ValueError(
                    f"action {action.action_id} must depend only on an earlier action"
                )

    if composition in {"single", "parallel", "alternative"} and any(
        action.depends_on for action in actions
    ):
        raise ValueError(f"{composition} composition cannot declare dependencies")
    if composition == "sequential" and any(
        not action.depends_on for action in actions if action.order > 1
    ):
        raise ValueError("every sequential action after the first must declare a dependency")
    if composition == "alternative" and not need_clarification:
        raise ValueError("alternative composition requires clarification")


class RouteDefinition(ContractModel):
    name: RouteKey = Field(min_length=1)
    zh: str = Field(min_length=1)
    description: str = Field(min_length=1)
    enabled: bool


class IntentRequiredSlot(ContractModel):
    slot_name: str = Field(min_length=1)
    field_name: str | None = Field(default=None, min_length=1)
    field_zh: str | None = Field(default=None, min_length=1)
    required: bool = False
    default_value: str | None = None
    note: str | None = None

    @field_validator("slot_name")
    @classmethod
    def trim_slot_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("required slot name must not be blank")
        return normalized

    @field_validator("default_value")
    @classmethod
    def normalize_default_value(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("field_name", "field_zh", "note")
    @classmethod
    def normalize_optional_field(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    def effective_name(self) -> str:
        return self.field_name or self.slot_name

    def effective_zh(self, slot: SlotDefinition) -> str:
        return self.field_zh or slot.zh


class IntentDefinition(ContractModel):
    name: str = Field(min_length=1)
    zh: str = Field(min_length=1)
    route: RouteKey = Field(min_length=1)
    description: str = Field(min_length=1)
    enabled: bool
    aliases: list[str] = Field(default_factory=list)
    mapping_note: str | None = None
    required_slots: list[IntentRequiredSlot] = Field(default_factory=list)

    @field_validator("aliases")
    @classmethod
    def aliases_must_not_be_blank(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError("intent aliases must not be blank")
        return value

    @model_validator(mode="after")
    def required_slots_must_be_unique(self) -> IntentDefinition:
        _ensure_unique(
            [requirement.effective_name() for requirement in self.required_slots],
            f"intent {self.name} parameter field names",
        )
        return self


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
    route: RouteKey = Field(min_length=1)
    intent: str | None = Field(default=None, min_length=1)
    enabled: bool = True

    @field_validator("text")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("example text must not be blank")
        return value


class PromptTemplate(ContractModel):
    system: str = Field(min_length=1)
    rules: list[str] = Field(default_factory=list)
    include_examples: bool = True

    @field_validator("rules")
    @classmethod
    def rules_must_not_be_blank(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError("prompt rules must not be blank")
        return value


class RuntimeConfigSnapshot(ContractModel):
    """The complete, immutable business configuration consumed at runtime."""

    schema_version: Literal[1]
    routes: list[RouteDefinition] = Field(min_length=1)
    intents: list[IntentDefinition]
    slots: list[SlotDefinition]
    enums: dict[str, list[EnumValueDefinition]]
    examples: list[ExampleDefinition]
    prompt_template: PromptTemplate

    @model_validator(mode="after")
    def valid_business_config(self) -> RuntimeConfigSnapshot:
        route_names = [route.name for route in self.routes]
        _ensure_unique(route_names, "route names")

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
        program_enum_groups = {
            slot.enum_group
            for slot in self.slots
            if slot.value_type == "enum" and slot.enum_group is not None
        }
        for group_name, values in self.enums.items():
            if not group_name.strip():
                raise ValueError("enum group names must not be blank")
            _ensure_unique(
                [item.canonical for item in values], f"enum {group_name} canonical values"
            )
            if group_name in program_enum_groups:
                expression_owner: dict[str, str] = {}
                for item in values:
                    for expression in _enum_forms(item):
                        expression = expression.strip()
                        if not expression:
                            raise ValueError(
                                f"enum {group_name} canonical/display/alias must not be blank"
                            )
                        owner = expression_owner.setdefault(expression, item.canonical)
                        if owner != item.canonical:
                            raise ValueError(
                                f"enum {group_name} expression conflict: {expression}"
                            )
        for slot in self.slots:
            if slot.enum_group is not None and slot.enum_group not in self.enums:
                raise ValueError(f"slot {slot.name} references an unknown enum_group")

        intents_by_name = {item.name: item for item in self.intents}
        slots_by_name = {item.name: item for item in self.slots}
        route_name_set = set(route_names)
        _ensure_unique([example.text for example in self.examples], "example texts")
        for intent in self.intents:
            if intent.route not in route_name_set:
                raise ValueError(f"intent {intent.name} references unknown route {intent.route}")
            for requirement in intent.required_slots:
                slot = slots_by_name.get(requirement.slot_name)
                if slot is None:
                    raise ValueError(
                        f"intent {intent.name} references unknown required slot "
                        f"{requirement.slot_name}"
                    )
                if not slot.enabled:
                    raise ValueError(
                        f"intent {intent.name} references disabled required slot "
                        f"{requirement.slot_name}"
                    )
                if requirement.default_value is not None and slot.value_type == "enum":
                    assert slot.enum_group is not None
                    allowed_defaults = {
                        value.canonical
                        for value in self.enums[slot.enum_group]
                        if value.enabled
                    }
                    if requirement.default_value not in allowed_defaults:
                        raise ValueError(
                            f"intent {intent.name} default for required slot "
                            f"{requirement.slot_name} must be an enabled canonical enum value"
                        )
        for example in self.examples:
            if example.route not in route_name_set:
                raise ValueError(f"example references unknown route {example.route}")
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
        "INTENTS_EMPTY",
        "REQUIRED_SLOT_DEFAULT_APPLIED",
        "REQUIRED_SLOT_MISSING",
    ]
    slot: SlotValue | None = None
    required_slot: str | None = None
    # Trace-only marker.  It is never part of the public IntentResult contract.
    truncated: bool = False


class ValidatedIntentOutput(ContractModel):
    result: IntentResult
    validation_issues: list[OutputValidationIssue] = Field(default_factory=list)


class ValidatedIntentOutputV2(ContractModel):
    result: IntentResultV2
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
    active_route_names = {item.name for item in config.routes if item.enabled}
    if output.route not in active_route_names:
        raise BusinessOutputValidationError(f"route {output.route} is not enabled")
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

    issues: list[OutputValidationIssue] = []
    if not output.intents:
        issues.append(OutputValidationIssue(code="INTENTS_EMPTY"))

    normalized_slots: list[SlotValue] = []
    selected_intent_name = normalized_intents[0].name if normalized_intents else None
    for slot in output.slots:
        resolved = _resolve_intent_parameter(
            config, selected_intent_name, slot.name
        )
        if resolved is None:
            raise BusinessOutputValidationError(f"slot {slot.name} is not enabled")
        configured_slot, requirement, field_name, field_zh = resolved
        raw_value = slot.raw_value or str(slot.value)
        enum_value: EnumValueDefinition | None = None
        if configured_slot.value_type == "enum":
            assert configured_slot.enum_group is not None
            enum_value = _find_enum_value(
                config.enums[configured_slot.enum_group], str(slot.value)
            )
            if enum_value is None and requirement is not None and requirement.note:
                enum_value = _find_enum_value(
                    config.enums[configured_slot.enum_group], raw_value
                )
            if enum_value is None:
                raise BusinessOutputValidationError(
                    f"slot {slot.name} value is not in enum {configured_slot.enum_group}"
                )
        normalized_slot = SlotValue(
            name=field_name,
            zh=field_zh,
            value=slot.value,
            raw_value=raw_value,
            start=slot.start,
            end=slot.end,
            confidence=slot.confidence,
        )
        repaired = _validate_or_repair_span(
            text, normalized_slot, enum_value, raw_value=raw_value
        )
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
            need_clarification=output.need_clarification,
            clarification=output.clarification,
        ),
        validation_issues=issues,
    )


def validate_llm_output_v2(
    output: LLMStructuredIntentOutputV2,
    snapshot: RuntimeConfigSnapshot,
    *,
    request_id: str,
    text: str,
) -> ValidatedIntentOutputV2:
    """Validate and normalize every action without imposing an action-count limit."""

    actions: list[IntentAction] = []
    issues: list[OutputValidationIssue] = []
    for action in sorted(output.actions, key=lambda item: item.order):
        candidate_intents = [action.intent] if action.intent is not None else []
        validated = validate_llm_output(
            LLMStructuredIntentOutput(
                route=action.route,
                intents=candidate_intents,
                slots=action.slots,
                risk=None,
                need_clarification=False,
                clarification=None,
                reason_summary=None,
                evidence=[],
            ),
            snapshot,
            request_id=request_id,
            text=text,
        )
        normalized_intent = (
            validated.result.intents[0] if validated.result.intents else None
        )
        actions.append(
            IntentAction(
                action_id=action.action_id,
                route=validated.result.route,
                intent=normalized_intent,
                slots=validated.result.slots,
                order=action.order,
                depends_on=action.depends_on,
            )
        )
        issues.extend(validated.validation_issues)

    return ValidatedIntentOutputV2(
        result=IntentResultV2(
            request_id=request_id,
            text=text,
            is_compound=output.is_compound,
            composition=output.composition,
            actions=actions,
            risk=output.risk,
            need_clarification=output.need_clarification,
            clarification=output.clarification,
        ),
        validation_issues=issues,
    )


def validate_recognition_output(
    output: LLMRecognitionOutput,
    snapshot: RuntimeConfigSnapshot,
    *,
    request_id: str,
    text: str,
    slot_candidates: list[SlotCandidate] | None = None,
    slot_search_range: tuple[int, int] | None = None,
) -> ValidatedIntentOutput:
    """Validate model bindings against deterministic base-Slot candidates."""

    config = validate_runtime_config_snapshot(snapshot)
    selected_intent_name = output.intents[0].name if output.intents else None
    candidates = slot_candidates or []
    text_slots: list[SlotValue] = []
    for slot in output.slots:
        resolved = _resolve_intent_parameter(
            config, selected_intent_name, slot.name
        )
        if resolved is None:
            raise BusinessOutputValidationError(f"slot {slot.name} is not enabled")
        configured, requirement, field_name, field_zh = resolved
        base_candidates = [
            candidate
            for candidate in candidates
            if candidate.slot_name == configured.name
        ]
        matching_candidates = [
            candidate
            for candidate in base_candidates
            if slot.value in {candidate.value, candidate.source}
        ]
        requires_candidate = configured.value_type == "enum"
        transformed_candidate = (
            base_candidates[0]
            if not matching_candidates
            and requirement is not None
            and requirement.note
            and len(base_candidates) == 1
            else None
        )
        if requires_candidate and not matching_candidates and transformed_candidate is None:
            raise BusinessOutputValidationError(
                f"slot {slot.name} value is not in candidates for {configured.name}"
            )
        candidate = (
            matching_candidates[0] if matching_candidates else transformed_candidate
        )
        span = (
            (candidate.start, candidate.end)
            if candidate is not None
            else _find_unique_value_span_in_range(text, slot.value, slot_search_range)
        )
        text_slots.append(
            SlotValue(
                name=field_name,
                zh=field_zh,
                value=(
                    slot.value
                    if transformed_candidate is not None
                    else candidate.value
                    if candidate is not None
                    else slot.value
                ),
                raw_value=candidate.source if candidate is not None else slot.value,
                start=span[0] if span is not None else 0,
                end=span[1] if span is not None else 0,
                confidence=slot.confidence,
            )
        )

    validated = validate_llm_output(
        LLMStructuredIntentOutput(
            route=output.route,
            intents=output.intents,
            slots=text_slots,
            risk=output.risk,
            need_clarification=output.need_clarification,
            clarification=output.clarification,
            reason_summary=output.reason_summary,
            evidence=output.evidence,
        ),
        config,
        request_id=request_id,
        text=text,
    )
    selected_intent = (
        validated.result.intents[0].name if validated.result.intents else None
    )
    normalized, required_questions, requirement_issues = _apply_required_slots(
        config,
        selected_intent,
        validated.result.slots,
    )
    need_clarification = validated.result.need_clarification or bool(required_questions)
    clarification = _combine_clarifications(
        required_questions,
        validated.result.clarification,
    )
    return ValidatedIntentOutput(
        result=validated.result.model_copy(
            update={
                "slots": normalized,
                "need_clarification": need_clarification,
                "clarification": clarification,
            }
        ),
        validation_issues=[*validated.validation_issues, *requirement_issues],
    )


def validate_recognition_output_v2(
    output: LLMRecognitionOutputV2,
    snapshot: RuntimeConfigSnapshot,
    *,
    request_id: str,
    text: str,
    slot_candidates_by_action: dict[str, list[SlotCandidate]] | None = None,
    action_ranges: dict[str, tuple[int, int]] | None = None,
) -> ValidatedIntentOutputV2:
    """Validate action outputs against action-scoped base-Slot candidates."""

    actions: list[IntentAction] = []
    issues: list[OutputValidationIssue] = []
    scoped_candidates = slot_candidates_by_action or {}
    scoped_action_ranges = action_ranges or {}
    required_questions: list[str] = []
    for action in sorted(output.actions, key=lambda item: item.order):
        candidate_intents = [action.intent] if action.intent is not None else []
        validated = validate_recognition_output(
            LLMRecognitionOutput(
                route=action.route,
                intents=candidate_intents,
                slots=action.slots,
                risk=None,
                need_clarification=False,
                clarification=None,
                reason_summary=None,
                evidence=[],
            ),
            snapshot,
            request_id=request_id,
            text=text,
            slot_candidates=scoped_candidates.get(action.action_id, []),
            slot_search_range=scoped_action_ranges.get(action.action_id),
        )
        normalized_intent = (
            validated.result.intents[0] if validated.result.intents else None
        )
        actions.append(
            IntentAction(
                action_id=action.action_id,
                route=validated.result.route,
                intent=normalized_intent,
                slots=validated.result.slots,
                order=action.order,
                depends_on=action.depends_on,
            )
        )
        if validated.result.need_clarification and validated.result.clarification:
            required_questions.append(validated.result.clarification)
        issues.extend(validated.validation_issues)

    need_clarification = output.need_clarification or bool(required_questions)
    clarification = _combine_clarifications(
        required_questions,
        output.clarification,
    )
    return ValidatedIntentOutputV2(
        result=IntentResultV2(
            request_id=request_id,
            text=text,
            is_compound=output.is_compound,
            composition=output.composition,
            actions=actions,
            risk=output.risk,
            need_clarification=need_clarification,
            clarification=clarification,
        ),
        validation_issues=issues,
    )


def _apply_required_slots(
    snapshot: RuntimeConfigSnapshot,
    intent_name: str | None,
    slots: list[SlotValue],
) -> tuple[list[SlotValue], list[str], list[OutputValidationIssue]]:
    if intent_name is None:
        return slots, [], []
    intent = next(
        (item for item in snapshot.active_intents if item.name == intent_name),
        None,
    )
    if intent is None or not intent.required_slots:
        return slots, [], []

    slots_by_name = {item.name: item for item in snapshot.active_slots}
    present_names = {slot.name for slot in slots}
    normalized = list(slots)
    missing_labels: list[str] = []
    issues: list[OutputValidationIssue] = []
    for requirement in intent.required_slots:
        field_name = requirement.effective_name()
        if field_name in present_names:
            continue
        definition = slots_by_name[requirement.slot_name]
        if requirement.default_value is None and requirement.required:
            field_zh = requirement.effective_zh(definition)
            missing_labels.append(f"{field_zh}（{field_name}）")
            issues.append(
                OutputValidationIssue(
                    code="REQUIRED_SLOT_MISSING",
                    required_slot=field_name,
                )
            )
            continue
        if requirement.default_value is None:
            continue
        defaulted = SlotValue(
            name=field_name,
            zh=requirement.effective_zh(definition),
            value=requirement.default_value,
            raw_value=None,
            start=0,
            end=0,
            confidence=1,
        )
        normalized.append(defaulted)
        present_names.add(field_name)
        issues.append(
            OutputValidationIssue(
                code="REQUIRED_SLOT_DEFAULT_APPLIED",
                slot=defaulted,
                required_slot=field_name,
            )
        )

    questions = (
        [f"请补充必填参数：{'、'.join(missing_labels)}"] if missing_labels else []
    )
    return normalized, questions, issues


def _resolve_intent_parameter(
    snapshot: RuntimeConfigSnapshot,
    intent_name: str | None,
    output_name: str,
) -> tuple[SlotDefinition, IntentRequiredSlot | None, str, str] | None:
    slots_by_name = {item.name: item for item in snapshot.active_slots}
    if intent_name is not None:
        intent = next(
            (item for item in snapshot.active_intents if item.name == intent_name),
            None,
        )
        if intent is not None:
            for requirement in intent.required_slots:
                if requirement.effective_name() != output_name:
                    continue
                definition = slots_by_name[requirement.slot_name]
                return (
                    definition,
                    requirement,
                    requirement.effective_name(),
                    requirement.effective_zh(definition),
                )
            if any(
                requirement.slot_name == output_name
                and requirement.effective_name() != output_name
                for requirement in intent.required_slots
            ):
                return None
    definition = slots_by_name.get(output_name)
    if definition is None:
        return None
    return definition, None, definition.name, definition.zh


def _combine_clarifications(
    required_questions: list[str],
    existing: str | None,
) -> str | None:
    questions = list(dict.fromkeys(required_questions))
    if existing and existing not in questions:
        questions.append(existing)
    return "；".join(questions) if questions else None


def _find_unique_value_span_in_range(
    text: str,
    value: str,
    search_range: tuple[int, int] | None,
) -> tuple[int, int] | None:
    if search_range is None:
        return None
    offsets = _utf16_offsets(text)
    try:
        char_start = offsets.index(search_range[0])
        char_end = offsets.index(search_range[1])
    except ValueError:
        return None
    scoped_text = text[char_start:char_end]
    first = scoped_text.find(value)
    if first < 0 or scoped_text.find(value, first + 1) >= 0:
        return None
    absolute_start = char_start + first
    absolute_end = absolute_start + len(value)
    return offsets[absolute_start], offsets[absolute_end]


def _find_enum_value(values: list[EnumValueDefinition], value: str) -> EnumValueDefinition | None:
    for enum_value in values:
        if not enum_value.enabled:
            continue
        if value in _enum_forms(enum_value):
            return enum_value
    return None


def _enum_forms(value: EnumValueDefinition) -> tuple[str, ...]:
    return (value.canonical, value.display, *value.aliases)


def _validate_or_repair_span(
    text: str,
    slot: SlotValue,
    enum_value: EnumValueDefinition | None,
    *,
    raw_value: str,
) -> SlotValue | None:
    accepted_values = (
        tuple(dict.fromkeys((raw_value, *_enum_forms(enum_value))))
        if enum_value is not None
        else (raw_value,)
    )
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
