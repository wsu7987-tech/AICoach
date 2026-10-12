import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas.intent import (
    BusinessOutputValidationError,
    IntentAnalyzeRequest,
    IntentCandidate,
    IntentResult,
    LLMStructuredIntentOutput,
    RuntimeConfigSnapshot,
    SlotValue,
    validate_llm_output,
    validate_runtime_config_snapshot,
)

BOOTSTRAP_PATH = Path(__file__).resolve().parents[2] / "bootstrap" / "initial-config.v1.json"


@pytest.fixture
def snapshot() -> RuntimeConfigSnapshot:
    document = json.loads(BOOTSTRAP_PATH.read_text(encoding="utf-8"))
    return RuntimeConfigSnapshot.model_validate(document)


def test_runtime_contract_and_request_accept_valid_values() -> None:
    request = IntentAnalyzeRequest(text="我要做深蹲", context={"locale": "zh-CN"})
    result = IntentResult(
        request_id="req_1",
        text=request.text,
        route="training_business",
        intents=[IntentCandidate(name="start_training", zh="开始训练", confidence=0.98)],
        slots=[
            SlotValue(name="exercise", zh="动作", value="深蹲", start=3, end=5, confidence=0.99)
        ],
        risk=None,
        need_clarification=False,
        clarification=None,
    )

    assert result.risk is None
    assert result.model_dump()["route"] == "training_business"


def test_training_business_supports_route_only_output_and_runtime_mapping(
    snapshot: RuntimeConfigSnapshot,
) -> None:
    output = LLMStructuredIntentOutput(
        route="training_business",
        intents=[],
        need_clarification=False,
        clarification=None,
    )

    validated = validate_llm_output(output, snapshot, request_id="req_1", text="开始训练")
    runtime = IntentResult(
        request_id="req_1",
        text="开始训练",
        route="training_business",
        intents=[],
        need_clarification=False,
        clarification=None,
    )
    schema = LLMStructuredIntentOutput.model_json_schema()

    assert validated.result.intents == []
    assert runtime.intents == []
    assert "minItems" not in schema["properties"]["intents"]
    assert "intents" in schema["required"]

    with pytest.raises(ValidationError, match="training_business cannot require clarification"):
        LLMStructuredIntentOutput(
            route="training_business",
            intents=[],
            need_clarification=True,
            clarification="请选择训练项目",
        )


def test_non_training_routes_require_an_intent() -> None:
    with pytest.raises(ValidationError, match="non-training routes require at least one intent"):
        LLMStructuredIntentOutput(
            route="social_chat",
            intents=[],
            need_clarification=False,
            clarification=None,
        )
    with pytest.raises(ValidationError, match="non-training routes require at least one intent"):
        IntentResult(
            request_id="req_1",
            text="你好",
            route="social_chat",
            intents=[],
            need_clarification=False,
            clarification=None,
        )


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_confidence_is_bounded(confidence: float) -> None:
    with pytest.raises(ValidationError):
        IntentCandidate(name="greeting", zh="问候", confidence=confidence)


def test_runtime_contract_rejects_debug_fields_and_invalid_input() -> None:
    with pytest.raises(ValidationError, match="reason_summary"):
        IntentResult.model_validate(
            {
                "request_id": "req_1",
                "text": "你好",
                "route": "social_chat",
                "intents": [{"name": "greeting", "zh": "问候", "confidence": 1}],
                "slots": [],
                "risk": None,
                "need_clarification": False,
                "clarification": None,
                "reason_summary": "must not be public",
            }
        )
    with pytest.raises(ValidationError, match="blank"):
        IntentAnalyzeRequest(text=" \n\t ")


@pytest.mark.parametrize(
    ("route", "need_clarification", "clarification"),
    [
        ("social_chat", False, "why?"),
        ("social_chat", True, None),
        ("social_chat", True, "  "),
        ("training_business", True, "请选择训练项目"),
        ("training_business", False, "请选择训练项目"),
    ],
)
def test_clarification_and_training_business_invariants(
    route: str, need_clarification: bool, clarification: str | None
) -> None:
    with pytest.raises(ValidationError):
        LLMStructuredIntentOutput(
            route=route,
            intents=[IntentCandidate(name="greeting", zh="问候", confidence=1)],
            need_clarification=need_clarification,
            clarification=clarification,
        )


@pytest.mark.parametrize("mutation", ["missing", "extra", "disabled"])
def test_snapshot_rejects_any_fixed_route_contract_change(mutation: str) -> None:
    document = json.loads(BOOTSTRAP_PATH.read_text(encoding="utf-8"))
    if mutation == "missing":
        document["routes"].pop()
    elif mutation == "extra":
        document["routes"].append(
            {"name": "new_route", "zh": "新路由", "description": "no", "enabled": True}
        )
    else:
        document["routes"][0]["enabled"] = False

    with pytest.raises(ValidationError):
        RuntimeConfigSnapshot.model_validate(document)


def test_secondary_intent_must_be_enabled_and_belong_to_output_route(
    snapshot: RuntimeConfigSnapshot,
) -> None:
    output = LLMStructuredIntentOutput(
        route="safety",
        intents=[IntentCandidate(name="start_training", zh="错误中文", confidence=1)],
        need_clarification=False,
    )

    with pytest.raises(BusinessOutputValidationError, match="does not belong"):
        validate_llm_output(output, snapshot, request_id="req_1", text="我想训练")

    disabled = snapshot.model_copy(deep=True)
    disabled.intents[0].enabled = False
    output = output.model_copy(
        update={
            "route": "training_business",
            "intents": [IntentCandidate(name="start_training", zh="开始训练", confidence=1)],
        }
    )
    with pytest.raises(BusinessOutputValidationError, match="not enabled"):
        validate_llm_output(output, disabled, request_id="req_1", text="我想训练")


def test_utf16_span_is_repaired_when_unique_and_dropped_when_ambiguous(
    snapshot: RuntimeConfigSnapshot,
) -> None:
    output = LLMStructuredIntentOutput(
        route="training_business",
        intents=[IntentCandidate(name="start_training", zh="开始训练", confidence=1)],
        slots=[
            SlotValue(name="body_part", zh="身体部位", value="胸", start=2, end=3, confidence=1)
        ],
        need_clarification=False,
    )

    repaired = validate_llm_output(output, snapshot, request_id="req_1", text="😀练胸")

    assert repaired.result.slots[0].start == 3
    assert repaired.result.slots[0].end == 4
    assert repaired.validation_issues == []

    dropped = validate_llm_output(output, snapshot, request_id="req_1", text="😀练胸胸")

    assert dropped.result.slots == []
    assert dropped.validation_issues[0].code == "SLOT_SPAN_INVALID"
    assert dropped.validation_issues[0].slot.start == 2


def test_valid_utf16_span_and_alias_are_retained(snapshot: RuntimeConfigSnapshot) -> None:
    output = LLMStructuredIntentOutput(
        route="training_business",
        intents=[IntentCandidate(name="start_training", zh="开始训练", confidence=1)],
        slots=[
            SlotValue(name="body_part", zh="身体部位", value="chest", start=3, end=5, confidence=1)
        ],
        need_clarification=False,
    )

    validated = validate_llm_output(output, snapshot, request_id="req_1", text="😀练胸部")

    assert validated.result.slots[0].value == "chest"
    assert validated.result.slots[0].start == 3
    assert validated.result.slots[0].end == 5


def test_unlocatable_slot_is_dropped_without_failing_intent_result(
    snapshot: RuntimeConfigSnapshot,
) -> None:
    output = LLMStructuredIntentOutput(
        route="training_business",
        intents=[],
        slots=[
            SlotValue(name="body_part", zh="身体部位", value="knee", start=0, end=1, confidence=1)
        ],
        need_clarification=False,
    )

    validated = validate_llm_output(output, snapshot, request_id="req_1", text="我要练胸")

    assert validated.result.slots == []
    assert len(validated.validation_issues) == 1
    assert validated.validation_issues[0].code == "SLOT_SPAN_INVALID"
    assert validated.validation_issues[0].slot.value == "knee"


def test_snapshot_validation_reconstructs_instances_before_returning_them(
    snapshot: RuntimeConfigSnapshot,
) -> None:
    validated = validate_runtime_config_snapshot(snapshot)

    assert validated is not snapshot
    assert validated == snapshot

    snapshot.routes[0].enabled = False
    with pytest.raises(ValidationError, match="all fixed Route Contract routes must be enabled"):
        validate_runtime_config_snapshot(snapshot)


def test_snapshot_validation_rejects_mutated_missing_route_and_invalid_dict(
    snapshot: RuntimeConfigSnapshot,
) -> None:
    snapshot.routes.pop()
    with pytest.raises(ValidationError, match="seven fixed Route Contract"):
        validate_runtime_config_snapshot(snapshot)

    invalid_document = snapshot.model_dump(mode="json")
    invalid_document["routes"] = []
    with pytest.raises(ValidationError, match="seven fixed Route Contract"):
        validate_runtime_config_snapshot(invalid_document)
