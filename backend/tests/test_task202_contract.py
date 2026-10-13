from app.schemas.debug import DebugAnalyzeInput, ReplayInput
from app.services.debug_service import diff


def trace(trace_id: str, raw: dict[str, object]) -> dict[str, object]:
    return {
        "trace_id": trace_id,
        "input": "我要做深蹲",
        "release": {"id": 1, "config_snapshot_hash": "a", "fingerprint": "b"},
        "model": {"id": 1, "hash": "model", "snapshot": {}},
        "runtime_result": {"route": "training_business"},
        "attempts": [{"final_prompt": "same", "raw_response": raw, "parsed_result": raw}],
    }


def test_debug_repeats_are_bounded_and_replay_mode_is_explicit() -> None:
    assert DebugAnalyzeInput(text="x", repeat=5).repeat == 5
    assert ReplayInput().mode == "historical"


def test_diff_marks_provider_divergence_with_same_prompt_and_model() -> None:
    result = diff(trace("left", {"content": "a"}), trace("right", {"content": "b"}))
    assert result["changes"]["prompt"]["changed"] is False
    assert result["changes"]["model"]["changed"] is False
    assert result["changes"]["raw_response"]["changed"] is True
    assert result["provider_divergence"] is True
