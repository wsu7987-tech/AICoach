import json
from pathlib import Path

import pytest

from app.bootstrap.service import BootstrapValidationError, parse_bootstrap_json
from app.db.models import ConfigDraft, ConfigRelease

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


def test_bootstrap_rejects_duplicate_route_names() -> None:
    document = json.loads(BOOTSTRAP_PATH.read_text(encoding="utf-8"))
    document["routes"].append(document["routes"][0].copy())

    with pytest.raises(BootstrapValidationError, match="route names must be unique"):
        parse_bootstrap_json(json.dumps(document, ensure_ascii=False))


def test_config_draft_uses_explicit_singleton_id() -> None:
    id_column = ConfigDraft.__table__.c.id

    assert id_column.autoincrement is False


def test_release_fingerprint_is_indexed_but_not_unique() -> None:
    fingerprint_column = ConfigRelease.__table__.c.release_fingerprint

    assert fingerprint_column.unique is None
    assert fingerprint_column.index is True
