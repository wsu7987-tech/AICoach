"""Admin configuration inputs and canonical identities shared with release consumers."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.intent import (
    ModelConfigSnapshot,
    RuntimeConfigSnapshot,
    canonical_json,
    sha256_canonical,
    validate_runtime_config_snapshot,
)


class AdminInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class DraftUpdate(AdminInput):
    draft_json: dict[str, Any]
    # Optimistic concurrency token returned by GET. null means create only.
    expected_draft_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class DraftPreview(AdminInput):
    text: str = Field(min_length=1, max_length=2000)
    context: dict[str, Any] = Field(default_factory=dict)


class PublishInput(AdminInput):
    default_model_config_id: int = Field(gt=0)
    note: str = Field(min_length=1, max_length=4000)
    expected_draft_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    # UI sends the previewed base to reject stale publish confirmations.
    expected_active_release_id: int | None = Field(default=None, gt=0)


class RestoreInput(AdminInput):
    expected_draft_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class AdminOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DraftView(AdminOutput):
    draft_json: dict[str, Any] | None
    draft_hash: str | None
    updated_at: datetime | None


class DraftValidation(AdminOutput):
    valid: Literal[True]
    config_snapshot_hash: str
    issues: list[dict[str, Any]]
    counts: dict[str, int]


class SectionChange(AdminOutput):
    section: str
    before: Any
    after: Any


class PublishSummary(AdminOutput):
    draft_hash: str
    config_snapshot_hash: str
    active_release_id: int | None
    default_model_config_id: int
    model_config_hash: str
    release_fingerprint: str
    model_changed: bool
    changes: list[SectionChange]


class ReleaseSummary(AdminOutput):
    id: int
    version: str
    config_snapshot_hash: str
    default_model_config_id: int
    model_config_hash: str
    release_fingerprint: str
    note: str
    created_by: str
    created_at: datetime


class PublishedRelease(ReleaseSummary):
    snapshot_json: dict[str, Any]


class ReleaseDetail(PublishedRelease):
    model_config_snapshot: ModelConfigSnapshot


class ReleaseHistory(AdminOutput):
    active_release_id: int | None
    items: list[ReleaseSummary]


class ConfigStatus(AdminOutput):
    runtime_config_ready: bool
    active_release_id: int | None


class ModelConfigCreate(AdminInput):
    name: str = Field(min_length=1, max_length=128, pattern=r"\S")
    version: str = Field(min_length=1, max_length=64, pattern=r"\S")
    provider: Literal["qwen"]
    model: str = Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9._:/-]+$")
    base_url: str = Field(min_length=1, max_length=2048)
    params_json: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: float = Field(gt=0, le=600)
    max_retries: int = Field(ge=0, le=5)
    max_concurrency: int = Field(gt=0, le=256)
    structured_output_mode: Literal["json_schema", "json_object"]
    credential_ref: str = Field(max_length=255, pattern=r"^[A-Z_][A-Z0-9_]*$")

    @field_validator("base_url")
    @classmethod
    def non_secret_endpoint(cls, value: str) -> str:
        url = urlsplit(value)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError(
                "base_url must be an HTTP(S) endpoint without credentials/query/fragment"
            )
        return value

    @field_validator("params_json")
    @classmethod
    def supported_call_parameters(cls, value: dict[str, Any]) -> dict[str, Any]:
        # Deliberately typed allowlist: arbitrary SDK kwargs can override credentials,
        # transport, messages, response schema, or carry secrets into persistence.
        allowed = {
            "temperature",
            "top_p",
            "seed",
            "presence_penalty",
            "frequency_penalty",
            "max_tokens",
        }
        if set(value) - allowed:
            raise ValueError(
                "unsupported params; use temperature/top_p/seed/presence_penalty/"
                "frequency_penalty; credentials belong in credential_ref"
            )
        if value.get("max_tokens") is not None:
            raise ValueError("max_tokens must be null or omitted for structured output")
        result = {key: item for key, item in value.items() if item is not None}
        for key, item in result.items():
            if isinstance(item, bool) or not isinstance(item, (int, float)):
                raise ValueError(f"{key} must be numeric")
            if key == "seed" and (not isinstance(item, int) or not 0 <= item <= 2**31 - 1):
                raise ValueError("seed must be an integer in 0..2147483647")
            if key == "temperature" and not 0 <= item <= 2:
                raise ValueError("temperature must be in 0..2")
            if key == "top_p" and not 0 < item <= 1:
                raise ValueError("top_p must be in (0,1]")
            if key.endswith("penalty") and not -2 <= item <= 2:
                raise ValueError(f"{key} must be in -2..2")
        return result


MODEL_RUNTIME_FIELDS = (
    "provider",
    "model",
    "base_url",
    "params_json",
    "timeout_seconds",
    "max_retries",
    "max_concurrency",
    "structured_output_mode",
    "credential_ref",
)


def model_hash(config: ModelConfigCreate | ModelConfigSnapshot) -> str:
    payload = config.model_dump(mode="json")
    return sha256_canonical({key: payload[key] for key in MODEL_RUNTIME_FIELDS})


def business_snapshot(
    value: RuntimeConfigSnapshot | dict[str, Any],
) -> tuple[dict[str, Any], str]:
    validated = validate_runtime_config_snapshot(value)
    # Serialize/reparse: callers own independent copies, never the draft's mutable JSON.
    payload = json.loads(canonical_json(validated.model_dump(mode="json")))
    return payload, sha256_canonical(payload)


def release_fingerprint(config_hash: str, model_id: int, model_config_hash: str) -> str:
    return hashlib.sha256(f"{config_hash}{model_id}{model_config_hash}".encode()).hexdigest()
