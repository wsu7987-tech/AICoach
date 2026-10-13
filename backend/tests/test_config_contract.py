"""TASK-201 pure contract tests, including C7 and deterministic identities."""

import copy
import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas.config import ModelConfigCreate, business_snapshot, model_hash, release_fingerprint
from app.schemas.intent import RuntimeConfigSnapshot


def document():
    path = Path(__file__).resolve().parents[2] / "bootstrap/initial-config.v1.json"
    return json.loads(path.read_text(encoding="utf-8"))


def model_input(**overrides):
    return {
        "name": "Qwen",
        "version": "1",
        "provider": "qwen",
        "model": "qwen-plus",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "params_json": {"temperature": 0.0},
        "timeout_seconds": 30,
        "max_retries": 1,
        "max_concurrency": 4,
        "structured_output_mode": "json_object",
        "credential_ref": "DASHSCOPE_API_KEY",
        **overrides,
    }


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d["routes"].pop(),
        lambda d: d["routes"].append({**d["routes"][0], "name": "eighth"}),
        lambda d: d["routes"][0].update(enabled=False),
        lambda d: d["intents"][0].update(route="missing"),
        lambda d: d["slots"][0].update(value_type="enum", enum_group="missing"),
        lambda d: d["examples"][0].update(intent="missing"),
        lambda d: d["intents"][1].update(name=d["intents"][0]["name"]),
        lambda d: d["intents"][1].update(zh=d["intents"][0]["zh"]),
        lambda d: d["intents"][1].update(aliases=[d["intents"][0]["name"]]),
        lambda d: d["intents"][1].update(aliases=[d["intents"][0]["zh"]]),
        lambda d: d["intents"][1].update(aliases=d["intents"][0]["aliases"]),
    ],
)
def test_invalid_business_configuration(mutation):
    payload = document()
    mutation(payload)
    with pytest.raises(ValidationError):
        business_snapshot(payload)


def test_c7_reparse_mutated_instance():
    config = RuntimeConfigSnapshot.model_validate(document())
    config.routes.pop()
    with pytest.raises(ValidationError):
        business_snapshot(config)


def test_hashes_are_canonical_and_separate():
    payload, digest = business_snapshot(document())
    reordered = dict(reversed(list(payload.items())))
    assert business_snapshot(reordered) == (payload, digest)
    assert (
        digest
        == hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    first = ModelConfigCreate(**model_input())
    second = ModelConfigCreate(**model_input(name="Other", version="2"))
    assert model_hash(first) == model_hash(second)
    changed = ModelConfigCreate(**model_input(timeout_seconds=10))
    assert model_hash(first) != model_hash(changed)
    assert (
        release_fingerprint(digest, 12, model_hash(first))
        == hashlib.sha256((digest + "12" + model_hash(first)).encode()).hexdigest()
    )
    original = copy.deepcopy(payload)
    payload["routes"].clear()
    assert business_snapshot(document())[0] == original


@pytest.mark.parametrize(
    "overrides",
    [
        {"params_json": {"api_key": "secret"}},
        {"params_json": {"extra_headers": {"Authorization": "secret"}}},
        {"params_json": {"max_tokens": 10}},
        {"params_json": {"messages": []}},
        {"base_url": "https://user:password@example.com/v1"},
        {"base_url": "https://example.com/v1?api_key=secret"},
        {"credential_ref": "sk-actual-api-key"},
        {"max_retries": -1},
    ],
)
def test_model_config_rejects_secrets_and_invalid_calls(overrides):
    with pytest.raises(ValidationError):
        ModelConfigCreate(**model_input(**overrides))


@pytest.mark.parametrize(
    "changes",
    [
        {"model": "qwen-turbo"},
        {"base_url": "https://example.com/v1"},
        {"params_json": {"temperature": 0.5}},
        {"timeout_seconds": 40},
        {"max_retries": 2},
        {"max_concurrency": 5},
        {"structured_output_mode": "json_schema"},
        {"credential_ref": "OTHER_KEY_REF"},
    ],
)
def test_every_supported_runtime_parameter_changes_model_hash(changes):
    assert model_hash(ModelConfigCreate(**model_input(**changes))) != model_hash(
        ModelConfigCreate(**model_input())
    )


def test_model_snapshot_metadata_and_omitted_max_tokens_do_not_change_hash():
    from app.schemas.intent import ModelConfigSnapshot

    config = ModelConfigCreate(**model_input())
    digest = model_hash(config)
    first = ModelConfigSnapshot(id=1, **config.model_dump(), model_config_hash=digest)
    second = first.model_copy(
        update={"id": 2, "name": "new name", "version": "v2", "enabled": False}
    )
    assert model_hash(first) == model_hash(second) == digest
    with_null = ModelConfigCreate(
        **model_input(params_json={"temperature": 0.0, "max_tokens": None})
    )
    assert model_hash(with_null) == digest
