"""Transactional configuration administration. Caller owns commit/rollback.

Every writer first locks the singleton runtime_state row (including its first
creation), then the draft/model rows. This order serializes publish, save,
restore and disable across processes, without process-local locks.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.dialects.mysql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ConfigDraft, ConfigRelease, RuntimeState
from app.prompting.builder import PromptBuilder
from app.schemas.config import (
    PublishInput,
    business_snapshot,
)
from app.schemas.intent import (
    PromptBuildResult,
    RuntimeConfigSnapshot,
    sha256_canonical,
)
from app.services.slot_extractor import extract_slot_candidates


class ConfigError(Exception):
    def __init__(
        self, code: str, message: str, status: int = 409, issues: list[dict[str, Any]] | None = None
    ):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status
        self.issues = issues or []


def validation_issues(error: ValidationError) -> list[dict[str, Any]]:
    return [
        {
            "field": ".".join(map(str, e["loc"])) or "draft_json",
            "message": e["msg"],
            "type": e["type"],
        }
        for e in error.errors(include_input=False, include_context=False, include_url=False)
    ]


def validate_business(
    value: RuntimeConfigSnapshot | dict[str, Any],
) -> tuple[dict[str, Any], str]:
    try:
        return business_snapshot(value)
    except ValidationError as error:
        raise ConfigError(
            "CONFIG_INVALID", "业务配置校验失败", 422, validation_issues(error)
        ) from None


def now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def lock_state(session: AsyncSession) -> RuntimeState:
    statement = insert(RuntimeState).values(id=1, updated_at=now())
    await session.execute(statement.on_duplicate_key_update(id=1))
    state = await session.scalar(
        select(RuntimeState)
        .where(RuntimeState.id == 1)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert state is not None
    return state


def draft_view(row: ConfigDraft | None) -> dict[str, Any]:
    if row is None:
        return {"draft_json": None, "draft_hash": None, "updated_at": None}
    return {
        "draft_json": copy.deepcopy(row.draft_json),
        "draft_hash": sha256_canonical(row.draft_json),
        "updated_at": row.updated_at,
    }


async def get_draft(session: AsyncSession) -> dict[str, Any]:
    return draft_view(await session.get(ConfigDraft, 1))


def check_draft_version(row: ConfigDraft | None, expected: str | None) -> None:
    actual = sha256_canonical(row.draft_json) if row else None
    if actual != expected:
        raise ConfigError("DRAFT_CONFLICT", "Draft 已被其他编辑更新，请重新载入后合并")


async def save_draft(
    session: AsyncSession,
    value: RuntimeConfigSnapshot | dict[str, Any],
    expected: str | None,
) -> dict[str, Any]:
    payload, _ = validate_business(value)
    await lock_state(session)
    row = await session.scalar(select(ConfigDraft).where(ConfigDraft.id == 1).with_for_update())
    check_draft_version(row, expected)
    if row is None:
        row = ConfigDraft(id=1, schema_version=1, draft_json=payload, updated_by="admin")
        session.add(row)
    else:
        row.draft_json, row.updated_at, row.updated_by = payload, now(), "admin"
    await session.flush()
    return draft_view(row)


async def require_draft(session: AsyncSession) -> ConfigDraft:
    row = await session.get(ConfigDraft, 1)
    if row is None:
        raise ConfigError("DRAFT_NOT_FOUND", "请先导入 Bootstrap 或保存 Draft", 404)
    return row


async def validate_draft(session: AsyncSession) -> dict[str, Any]:
    row = await require_draft(session)
    payload, digest = validate_business(row.draft_json)
    return {
        "valid": True,
        "config_snapshot_hash": digest,
        "issues": [],
        "counts": {
            key: len(payload[key]) for key in ("routes", "intents", "slots", "enums", "examples")
        },
    }


async def preview_prompt(
    session: AsyncSession,
    text: str,
    context: dict[str, Any],
) -> PromptBuildResult:
    row = await require_draft(session)
    payload, _ = validate_business(row.draft_json)
    snapshot = RuntimeConfigSnapshot.model_validate(payload)
    slot_candidates = extract_slot_candidates(text, snapshot)
    return PromptBuilder().preview(
        snapshot,
        text,
        context,
        slot_candidates=slot_candidates,
    )


async def preview_prompt_module(
    session: AsyncSession,
    module: str,
    intent_name: str | None = None,
    slot_name: str | None = None,
    enum_group: str | None = None,
) -> dict[str, str]:
    row = await require_draft(session)
    payload, _ = validate_business(row.draft_json)
    builder = PromptBuilder()
    if module == "routes":
        return {"module": module, "content": builder.preview_routes(payload)}
    if module == "intents":
        return {"module": module, "content": builder.preview_intents(payload)}
    if module == "intent" and intent_name:
        try:
            content = builder.preview_intent(payload, intent_name)
        except ValueError as error:
            raise ConfigError("CONFIG_INVALID", str(error), 422) from None
        return {"module": module, "content": content}
    if module == "slots":
        return {"module": module, "content": builder.preview_slots(payload)}
    if module == "slot" and slot_name:
        try:
            content = builder.preview_slot(payload, slot_name)
        except ValueError as error:
            raise ConfigError("CONFIG_INVALID", str(error), 422) from None
        return {"module": module, "content": content}
    if module == "enum" and enum_group:
        try:
            content = builder.preview_enum_group(payload, enum_group)
        except ValueError as error:
            raise ConfigError("CONFIG_INVALID", str(error), 422) from None
        return {"module": module, "content": content}
    raise ConfigError("INVALID_INPUT", "模块预览缺少对应的目标名称", 422)


def release_view(row: ConfigRelease, *, detail: bool = True) -> dict[str, Any]:
    fields = (
        "id",
        "version",
        "note",
        "created_by",
        "created_at",
    )
    result = {key: getattr(row, key) for key in fields}
    if detail:
        result["snapshot_json"] = copy.deepcopy(row.snapshot_json)
    return result


async def require_release(session: AsyncSession, release_id: int) -> ConfigRelease:
    row = await session.get(ConfigRelease, release_id)
    if row is None:
        raise ConfigError("RELEASE_NOT_FOUND", "Release 不存在", 404)
    return row


async def release_configuration(session: AsyncSession, release_id: int) -> dict[str, Any]:
    """Return one validated, immutable business configuration release."""
    release = await require_release(session, release_id)
    payload, _ = validate_business(release.snapshot_json)
    return {
        **release_view(release),
        "config_snapshot_hash": release.config_snapshot_hash,
        "snapshot_json": payload,
    }


async def publish_summary(session: AsyncSession) -> dict[str, Any]:
    row = await require_draft(session)
    payload, _ = validate_business(row.draft_json)
    state = await session.get(RuntimeState, 1)
    active = (
        await session.get(ConfigRelease, state.active_release_id)
        if state and state.active_release_id
        else None
    )
    before = active.snapshot_json if active else {}
    changes = [
        {"section": key, "before": before.get(key), "after": value}
        for key, value in payload.items()
        if before.get(key) != value
    ]
    return {
        "draft_hash": sha256_canonical(row.draft_json),
        "active_release_id": active.id if active else None,
        "changes": changes,
    }


async def publish(session: AsyncSession, request: PublishInput) -> dict[str, Any]:
    request = PublishInput.model_validate(request.model_dump(mode="json"))
    state = await lock_state(session)
    draft = await session.scalar(
        select(ConfigDraft)
        .where(ConfigDraft.id == 1)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if draft is None:
        raise ConfigError("DRAFT_NOT_FOUND", "请先创建 Draft", 404)
    check_draft_version(draft, request.expected_draft_hash)
    if request.expected_active_release_id != state.active_release_id:
        raise ConfigError("RELEASE_CONFLICT", "Active Release 已变化，请重新查看发布摘要")
    payload, digest = validate_business(draft.draft_json)
    release_count = await session.scalar(select(func.count(ConfigRelease.id))) or 0
    release = ConfigRelease(
        version=f"config-v{release_count + 1}",
        snapshot_json=payload,
        config_snapshot_hash=digest,
        note=request.note,
        created_by="admin",
    )
    session.add(release)
    await session.flush()
    # The immutable release insert and active pointer share one transaction.
    state.active_release_id, state.updated_at = release.id, now()
    await session.flush()
    return release_view(release)


async def restore_draft(
    session: AsyncSession,
    release_id: int,
    expected: str | None,
) -> dict[str, Any]:
    # save_draft takes the common writer lock and performs the CAS check.
    release = await release_configuration(session, release_id)
    return await save_draft(session, release["snapshot_json"], expected)
