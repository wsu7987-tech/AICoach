from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ConfigDraft

ROUTE_CONTRACT = frozenset(
    {
        "training_business",
        "information_query",
        "sports_knowledge",
        "safety",
        "dialogue_device_control",
        "social_chat",
        "unknown",
    }
)


class BootstrapValidationError(ValueError):
    """The file cannot be accepted as a business configuration draft."""


class BootstrapConflictError(RuntimeError):
    """An existing draft differs and must never be silently overwritten."""


class BootstrapPayload(BaseModel):
    """Only the documented business-snapshot top-level schema is accepted."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int
    routes: list[dict[str, Any]]
    intents: list[dict[str, Any]]
    slots: list[dict[str, Any]]
    enums: dict[str, Any]
    examples: list[dict[str, Any]]
    prompt_template: dict[str, Any]

    @field_validator("schema_version")
    @classmethod
    def supported_schema_version(cls, value: int) -> int:
        if value != 1:
            raise ValueError("only schema_version 1 is supported by bootstrap")
        return value

    @model_validator(mode="after")
    def validate_route_contract(self) -> BootstrapPayload:
        route_names: list[str] = []
        disabled: list[str] = []
        for route in self.routes:
            name = route.get("name")
            if not isinstance(name, str):
                raise ValueError("every route requires a string name")
            route_names.append(name)
            if route.get("enabled") is not True:
                disabled.append(name)
        if set(route_names) != ROUTE_CONTRACT or len(route_names) != len(ROUTE_CONTRACT):
            raise ValueError("routes must contain exactly the seven fixed Route Contract keys")
        if disabled:
            raise ValueError("all fixed Route Contract keys must be enabled")
        return self

    def canonical_json(self) -> str:
        return canonical_json(self.model_dump(mode="json"))


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def parse_bootstrap_json(raw: str) -> BootstrapPayload:
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BootstrapValidationError(f"invalid JSON: {exc.msg}") from exc
    try:
        return BootstrapPayload.model_validate(decoded)
    except ValidationError as exc:
        raise BootstrapValidationError(str(exc)) from exc


@dataclass(frozen=True)
class BootstrapImportResult:
    draft_id: int
    created: bool


async def import_bootstrap_draft(
    session: AsyncSession, payload: BootstrapPayload, updated_by: str = "bootstrap"
) -> BootstrapImportResult:
    """Create the singleton draft, no-op if identical, or reject a changed draft.

    The caller must own an enclosing transaction. No release/runtime-state records
    are created or changed by this operation.
    """

    existing = await session.scalar(select(ConfigDraft).where(ConfigDraft.id == 1))
    desired = payload.model_dump(mode="json")
    if existing is None:
        draft = ConfigDraft(
            id=1,
            schema_version=payload.schema_version,
            draft_json=desired,
            updated_by=updated_by,
        )
        session.add(draft)
        await session.flush()
        return BootstrapImportResult(draft_id=draft.id, created=True)

    if canonical_json(existing.draft_json) == payload.canonical_json():
        return BootstrapImportResult(draft_id=existing.id, created=False)
    raise BootstrapConflictError(
        "existing config_draft differs from bootstrap; refusing to overwrite edited draft"
    )
