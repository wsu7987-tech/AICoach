import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.prompting.builder import PromptBuilder
from app.schemas.intent import RuntimeConfigSnapshot

BOOTSTRAP_PATH = Path(__file__).resolve().parents[2] / "bootstrap" / "initial-config.v1.json"


def _snapshot() -> RuntimeConfigSnapshot:
    document = json.loads(BOOTSTRAP_PATH.read_text(encoding="utf-8"))
    return RuntimeConfigSnapshot.model_validate(document)


def test_prompt_is_deterministic_and_contains_dynamic_config_and_schema() -> None:
    snapshot = _snapshot()
    builder = PromptBuilder()

    first = builder.build(
        snapshot, text="😀深蹲怎么做？", context={"session": 1, "locale": "zh-CN"}
    )
    second = builder.preview(
        snapshot, text="😀深蹲怎么做？", context={"locale": "zh-CN", "session": 1}
    )
    system = json.loads(first.messages[0].content)

    assert first.final_prompt == second.final_prompt
    assert first.prompt_hash == second.prompt_hash
    assert system["business_config"]["intents"][0]["name"] == "start_training"
    assert system["business_config"]["enums"]["body_part"][0]["canonical"] == "chest"
    assert "LLMStructuredIntentOutput" in canonical_schema_text(system["output_schema"])
    assert json.loads(first.messages[1].content)["text"] == "😀深蹲怎么做？"


def test_disabled_business_configuration_is_not_injected() -> None:
    snapshot = _snapshot().model_copy(deep=True)
    snapshot.intents[0].enabled = False
    snapshot.slots[0].enabled = False
    snapshot.examples[1].enabled = False

    result = PromptBuilder().build(snapshot, text="我要做深蹲")
    system = json.loads(result.messages[0].content)
    effective = system["business_config"]

    assert "start_training" not in {item["name"] for item in effective["intents"]}
    assert "exercise" not in {item["name"] for item in effective["slots"]}
    assert all(item.get("intent") != "start_training" for item in effective["examples"])


def test_enabled_snapshot_change_changes_prompt_hash() -> None:
    original = _snapshot()
    changed = original.model_copy(deep=True)
    changed.intents[0].description = "这是修改后的训练意图描述"

    baseline = PromptBuilder().build(original, text="我要做深蹲")
    changed_result = PromptBuilder().build(changed, text="我要做深蹲")

    assert baseline.prompt_hash != changed_result.prompt_hash
    assert (
        baseline.metadata["config_snapshot_hash"] != changed_result.metadata["config_snapshot_hash"]
    )


def test_prompt_builder_revalidates_snapshot_instances_before_use() -> None:
    snapshot = _snapshot()
    expected = PromptBuilder().build(snapshot.model_dump(mode="json"), text="我要做深蹲")
    actual = PromptBuilder().build(snapshot, text="我要做深蹲")

    assert actual.final_prompt == expected.final_prompt
    assert actual.prompt_hash == expected.prompt_hash
    assert actual.metadata == expected.metadata

    snapshot.routes[0].enabled = False
    with pytest.raises(ValidationError, match="all fixed Route Contract routes must be enabled"):
        PromptBuilder().build(snapshot, text="我要做深蹲")


def test_prompt_builder_rejects_snapshot_with_a_missing_fixed_route() -> None:
    snapshot = _snapshot()
    snapshot.routes.pop()

    with pytest.raises(ValidationError, match="seven fixed Route Contract"):
        PromptBuilder().build(snapshot, text="我要做深蹲")


def canonical_schema_text(schema: object) -> str:
    return json.dumps(schema, ensure_ascii=False, sort_keys=True)
