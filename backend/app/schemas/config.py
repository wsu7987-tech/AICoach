"""Admin configuration inputs and canonical identities shared with release consumers."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.intent import (
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


class PromptModulePreview(AdminInput):
    module: Literal["routes", "intents", "intent", "slots", "slot", "enum"]
    intent_name: str | None = Field(default=None, min_length=1)
    slot_name: str | None = Field(default=None, min_length=1)
    enum_group: str | None = Field(default=None, min_length=1)


class PublishInput(AdminInput):
    note: str = Field(min_length=1, max_length=4000)
    expected_draft_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    # Required even for the first release (explicit null).
    expected_active_release_id: int | None = Field(gt=0)


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


class PromptModulePreviewResult(AdminOutput):
    module: Literal["routes", "intents", "intent", "slots", "slot", "enum"]
    content: str


class SectionChange(AdminOutput):
    section: str
    before: Any
    after: Any


class PublishSummary(AdminOutput):
    draft_hash: str
    active_release_id: int | None
    changes: list[SectionChange]


class ReleaseSummary(AdminOutput):
    id: int
    version: str
    note: str
    created_by: str
    created_at: datetime


class PublishedRelease(ReleaseSummary):
    snapshot_json: dict[str, Any]


class ReleaseDetail(PublishedRelease):
    pass


class ReleaseHistory(AdminOutput):
    active_release_id: int | None
    items: list[ReleaseSummary]


class ConfigStatus(AdminOutput):
    runtime_config_ready: bool
    active_release_id: int | None
    service_ready: bool = False
    active_release: dict[str, Any] | None = None
    default_model: dict[str, Any] | None = None
    requests_24h: int = 0
    errors_24h: int = 0
    avg_latency_ms: float | None = None
    p95_latency_ms: float | None = None
    evaluation_queued: int = 0
    evaluation_running: int = 0


def business_snapshot(
    value: RuntimeConfigSnapshot | dict[str, Any],
) -> tuple[dict[str, Any], str]:
    validated = validate_runtime_config_snapshot(value)
    # Serialize/reparse: callers own independent copies, never the draft's mutable JSON.
    payload = json.loads(canonical_json(validated.model_dump(mode="json")))
    return payload, sha256_canonical(payload)
