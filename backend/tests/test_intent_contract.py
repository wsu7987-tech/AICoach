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
        risk=None,
        need_clarification=False,
        clarification=None,
    )

    validated = validate_llm_output(output, snapshot, request_id="req_1", text="开始训练")
    runtime = IntentResult(
        request_id="req_1",
        text="开始训练",
        route="training_business",
        intents=[],
        risk=None,
        need_clarification=False,
        clarification=None,
    )
    schema = LLMStructuredIntentOutput.model_json_schema()

    assert validated.result.intents == []
    assert runtime.intents == []
    assert "minItems" not in schema["properties"]["intents"]
    assert "intents" in schema["required"]

    raw_training_clarification = LLMStructuredIntentOutput(
        route="training_business",
        intents=[],
        risk=None,
        need_clarification=True,
        clarification="请选择训练项目",
    )
    normalized = validate_llm_output(
        raw_training_clarification, snapshot, request_id="req_2", text="开始训练"
    )

    assert normalized.result.need_clarification is False
    assert normalized.result.clarification is None
    assert [issue.code for issue in normalized.validation_issues] == ["CLARIFICATION_FORCED_OFF"]


@pytest.mark.parametrize(
    "route",
    [
        "training_business",
        "information_query",
        "sports_knowledge",
        "safety",
        "dialogue_device_control",
        "social_chat",
        "unknown",
    ],
)
def test_all_routes_support_route_only_output(route: str, snapshot: RuntimeConfigSnapshot) -> None:
    output = LLMStructuredIntentOutput(
        route=route,
        intents=[],
        risk=None,
        need_clarification=False,
        clarification=None,
    )

    validated = validate_llm_output(output, snapshot, request_id="req_1", text="你好")
    runtime = IntentResult(
        request_id="req_1",
        text="你好",
        route=route,
        intents=[],
        risk=None,
        need_clarification=False,
        clarification=None,
    )

    assert runtime.intents == []
    assert validated.result.route == route
    expected_issue_codes = [] if route == "training_business" else ["INTENTS_EMPTY_NON_TRAINING"]
    assert [issue.code for issue in validated.validation_issues] == expected_issue_codes


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


def test_risk_is_required_but_null_is_valid_and_runtime_fields_are_exact() -> None:
    payload = {
        "request_id": "req_1",
        "text": "你好",
        "route": "social_chat",
        "intents": [],
        "slots": [],
        "risk": None,
        "need_clarification": False,
        "clarification": None,
    }

    result = IntentResult.model_validate(payload)

    assert set(result.model_dump()) == set(payload)
    with pytest.raises(ValidationError, match="risk"):
        IntentResult.model_validate({key: value for key, value in payload.items() if key != "risk"})
    with pytest.raises(ValidationError, match="risk"):
        LLMStructuredIntentOutput.model_validate(
            {
                key: value
                for key, value in payload.items()
                if key not in {"request_id", "text", "risk"}
            }
        )


@pytest.mark.parametrize(
    ("route", "need_clarification", "clarification"),
    [
        ("social_chat", False, "why?"),
        ("social_chat", True, None),
        ("social_chat", True, "  "),
    ],
)
def test_clarification_and_training_business_invariants(
    route: str, need_clarification: bool, clarification: str | None
) -> None:
    with pytest.raises(ValidationError):
        LLMStructuredIntentOutput(
            route=route,
            intents=[IntentCandidate(name="greeting", zh="问候", confidence=1)],
            risk=None,
            need_clarification=need_clarification,
            clarification=clarification,
        )


def test_snapshot_accepts_configured_route_addition() -> None:
    document = json.loads(BOOTSTRAP_PATH.read_text(encoding="utf-8"))
    document["routes"].append(
        {
            "name": "customer_service",
            "zh": "客户服务",
            "description": "客户服务请求",
            "enabled": True,
        }
    )
    document["intents"].append(
        {
            "name": "contact_support",
            "zh": "联系支持",
            "route": "customer_service",
            "description": "用户希望联系客服",
            "enabled": True,
            "aliases": [],
        }
    )

    snapshot = RuntimeConfigSnapshot.model_validate(document)

    assert snapshot.routes[-1].name == "customer_service"
    assert snapshot.intents[-1].route == "customer_service"


def test_secondary_intent_must_be_enabled_and_belong_to_output_route(
    snapshot: RuntimeConfigSnapshot,
) -> None:
    output = LLMStructuredIntentOutput(
        route="safety",
        intents=[IntentCandidate(name="start_training", zh="错误中文", confidence=1)],
        risk=None,
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


def test_utf16_span_is_repaired_when_unique_with_emoji(
    snapshot: RuntimeConfigSnapshot,
) -> None:
    output = LLMStructuredIntentOutput(
        route="training_business",
        intents=[IntentCandidate(name="start_training", zh="开始训练", confidence=1)],
        risk=None,
        slots=[
            SlotValue(name="body_part", zh="身体部位", value="胸", start=2, end=3, confidence=1)
        ],
        need_clarification=False,
    )

    repaired = validate_llm_output(output, snapshot, request_id="req_1", text="😀练胸")

    assert repaired.result.slots[0].start == 3
    assert repaired.result.slots[0].end == 4
    assert repaired.validation_issues == []


def test_utf16_span_is_repaired_when_unique(snapshot: RuntimeConfigSnapshot) -> None:
    output = LLMStructuredIntentOutput(
        route="training_business",
        intents=[IntentCandidate(name="start_training", zh="开始训练", confidence=1)],
        slots=[SlotValue(name="exercise", zh="动作", value="深蹲", start=0, end=2, confidence=1)],
        risk=None,
        need_clarification=False,
    )

    repaired = validate_llm_output(output, snapshot, request_id="req_1", text="我要做深蹲")

    assert repaired.result.slots[0].start == 3
    assert repaired.result.slots[0].end == 5
    assert repaired.validation_issues == []


def test_utf16_span_is_dropped_when_value_is_ambiguous(snapshot: RuntimeConfigSnapshot) -> None:
    output = LLMStructuredIntentOutput(
        route="training_business",
        intents=[IntentCandidate(name="start_training", zh="开始训练", confidence=1)],
        slots=[
            SlotValue(name="body_part", zh="身体部位", value="胸", start=2, end=3, confidence=1)
        ],
        risk=None,
        need_clarification=False,
    )

    dropped = validate_llm_output(output, snapshot, request_id="req_1", text="😀练胸胸")

    assert dropped.result.slots == []
    assert dropped.validation_issues[0].code == "SLOT_SPAN_INVALID"
    assert dropped.validation_issues[0].slot.start == 2


def test_valid_utf16_span_and_alias_are_retained(snapshot: RuntimeConfigSnapshot) -> None:
    output = LLMStructuredIntentOutput(
        route="training_business",
        intents=[IntentCandidate(name="start_training", zh="开始训练", confidence=1)],
        risk=None,
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
        risk=None,
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

    snapshot.routes.clear()
    with pytest.raises(ValidationError):
        validate_runtime_config_snapshot(snapshot)


def test_snapshot_validation_rejects_mutated_missing_route_and_invalid_dict(
    snapshot: RuntimeConfigSnapshot,
) -> None:
    snapshot.routes.clear()
    with pytest.raises(ValidationError):
        validate_runtime_config_snapshot(snapshot)

    invalid_document = snapshot.model_dump(mode="json")
    invalid_document["routes"] = []
    with pytest.raises(ValidationError):
        validate_runtime_config_snapshot(invalid_document)


@pytest.mark.parametrize("mutation", ["duplicate", "invalid_intent_route"])
def test_snapshot_validation_rejects_other_post_construction_mutations(
    snapshot: RuntimeConfigSnapshot, mutation: str
) -> None:
    if mutation == "duplicate":
        snapshot.routes.append(snapshot.routes[0].model_copy())
    else:
        snapshot.intents[0].route = "not_a_route"  # type: ignore[assignment]

    with pytest.raises(ValidationError):
        validate_runtime_config_snapshot(snapshot)


def test_output_rejects_a_disabled_or_unconfigured_route(
    snapshot: RuntimeConfigSnapshot,
) -> None:
    snapshot.routes[0].enabled = False
    disabled = LLMStructuredIntentOutput(
        route=snapshot.routes[0].name,
        intents=[],
        risk=None,
        need_clarification=False,
    )
    missing = disabled.model_copy(update={"route": "not_configured"})

    with pytest.raises(BusinessOutputValidationError, match="not enabled"):
        validate_llm_output(disabled, snapshot, request_id="req_1", text="你好")
    with pytest.raises(BusinessOutputValidationError, match="not enabled"):
        validate_llm_output(missing, snapshot, request_id="req_1", text="你好")
