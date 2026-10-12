import json
from pathlib import Path

import pytest

from app.bootstrap.service import BootstrapValidationError, parse_bootstrap_json
from app.db.models import ConfigDraft

BOOTSTRAP_PATH = Path(__file__).resolve().parents[2] / "bootstrap" / "initial-config.v1.json"


def test_initial_bootstrap_preserves_the_complete_business_config() -> None:
    raw = BOOTSTRAP_PATH.read_text(encoding="utf-8")
    payload = parse_bootstrap_json(raw)

    assert json.loads(payload.canonical_json()) == json.loads(raw)
    assert set(payload.model_dump()) == {
        "schema_version",
        "routes",
        "intents",
        "slots",
        "enums",
        "examples",
        "prompt_template",
    }


def test_unknown_bootstrap_top_level_field_is_rejected() -> None:
    document = json.loads(BOOTSTRAP_PATH.read_text(encoding="utf-8"))
    document["unapproved_metadata"] = True

    with pytest.raises(BootstrapValidationError, match="unapproved_metadata"):
        parse_bootstrap_json(json.dumps(document, ensure_ascii=False))


def test_bootstrap_cannot_modify_fixed_route_contract() -> None:
    document = json.loads(BOOTSTRAP_PATH.read_text(encoding="utf-8"))
    document["routes"][0]["enabled"] = False

    with pytest.raises(BootstrapValidationError, match="all fixed Route Contract"):
        parse_bootstrap_json(json.dumps(document, ensure_ascii=False))


def test_config_draft_uses_explicit_singleton_id() -> None:
    id_column = ConfigDraft.__table__.c.id

    assert id_column.autoincrement is False
