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
            SlotValue(
                name="exercise", zh="动作", value="深蹲", start=3, end=5, confidence=0.99
            )
        ],
        risk=None,
        need_clarification=False,
        clarification=None,
    )

    assert result.risk is None
    assert result.model_dump()["route"] == "training_business"


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
            SlotValue(
                name="body_part", zh="身体部位", value="胸", start=2, end=3, confidence=1
            )
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
            SlotValue(
                name="body_part", zh="身体部位", value="chest", start=3, end=5, confidence=1
            )
        ],
        need_clarification=False,
    )

    validated = validate_llm_output(output, snapshot, request_id="req_1", text="😀练胸部")

    assert validated.result.slots[0].value == "chest"
    assert validated.result.slots[0].start == 3
    assert validated.result.slots[0].end == 5
