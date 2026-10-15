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


class LLMExtractedTextSlot(ContractModel):
    """Minimal text Slot emitted by the model; metadata and spans are server-owned."""

    name: str = Field(min_length=1)
    value: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


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
        _validate_clarification(
            self.route,
            self.need_clarification,
            self.clarification,
            allow_training_normalization=True,
        )
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
        _validate_clarification(
            "compound", self.need_clarification, self.clarification
        )
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
        _validate_clarification(
            "compound", self.need_clarification, self.clarification
        )
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
        _validate_clarification(
            "compound", self.need_clarification, self.clarification
        )
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


class IntentDefinition(ContractModel):
    name: str = Field(min_length=1)
    zh: str = Field(min_length=1)
    route: RouteKey = Field(min_length=1)
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
        route_name_set = set(route_names)
        _ensure_unique([example.text for example in self.examples], "example texts")
        for intent in self.intents:
            if intent.route not in route_name_set:
                raise ValueError(f"intent {intent.name} references unknown route {intent.route}")
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
        "INTENTS_EMPTY_NON_TRAINING",
        "CLARIFICATION_FORCED_OFF",
    ]
    slot: SlotValue | None = None
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
    program_slots: list[SlotValue] | None = None,
    slot_search_range: tuple[int, int] | None = None,
) -> ValidatedIntentOutput:
    """Validate lightweight model Slots and merge deterministic enum matches."""

    config = validate_runtime_config_snapshot(snapshot)
    slots_by_name = {item.name: item for item in config.active_slots}
    text_slots: list[SlotValue] = []
    for slot in output.slots:
        configured = slots_by_name.get(slot.name)
        if configured is None:
            raise BusinessOutputValidationError(f"slot {slot.name} is not enabled")
        if configured.value_type == "enum":
            # Enum Slots are server-owned. Ignore a redundant model emission so
            # an otherwise usable recognition result does not fail closed.
            continue
        span = _find_unique_value_span_in_range(
            text, slot.value, slot_search_range
        )
        text_slots.append(
            SlotValue(
                name=configured.name,
                zh=configured.zh,
                value=slot.value,
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
    merged = _merge_slots(validated.result.slots, program_slots or [])
    return ValidatedIntentOutput(
        result=validated.result.model_copy(update={"slots": merged}),
        validation_issues=validated.validation_issues,
    )


def validate_recognition_output_v2(
    output: LLMRecognitionOutputV2,
    snapshot: RuntimeConfigSnapshot,
    *,
    request_id: str,
    text: str,
    program_slots_by_action: dict[str, list[SlotValue]] | None = None,
    action_ranges: dict[str, tuple[int, int]] | None = None,
) -> ValidatedIntentOutputV2:
    """Validate lightweight action outputs and merge action-scoped enum matches."""

    actions: list[IntentAction] = []
    issues: list[OutputValidationIssue] = []
    scoped_program_slots = program_slots_by_action or {}
    scoped_action_ranges = action_ranges or {}
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
            program_slots=scoped_program_slots.get(action.action_id, []),
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


def _merge_slots(model_slots: list[SlotValue], program_slots: list[SlotValue]) -> list[SlotValue]:
    merged: dict[tuple[str, str, int, int], SlotValue] = {}
    for slot in [*model_slots, *program_slots]:
        merged[(slot.name, slot.value, slot.start, slot.end)] = slot
    return sorted(
        merged.values(),
        key=lambda slot: (slot.start, slot.end, slot.name, slot.value),
    )


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
