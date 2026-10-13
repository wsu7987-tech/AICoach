"""Transactional configuration administration. Caller owns commit/rollback.

Every writer first locks the singleton runtime_state row (including its first
creation), then the draft/model rows. This order serializes publish, save,
restore and disable across processes, without process-local locks.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ConfigDraft, ConfigRelease, ModelConfig, RuntimeState
from app.prompting.builder import PromptBuilder
from app.schemas.config import (
    MODEL_RUNTIME_FIELDS,
    ModelConfigCreate,
    PublishInput,
    business_snapshot,
    model_hash,
    release_fingerprint,
)
from app.schemas.intent import (
    ModelConfigSnapshot,
    PromptBuildResult,
    RuntimeConfigSnapshot,
    sha256_canonical,
)


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
    return PromptBuilder().preview(payload, text, context)


def effective_model_snapshot(row: ModelConfig) -> ModelConfigSnapshot:
    """TASK-102/103 boundary; metadata is excluded from the independently checked hash.

    Does not reject disabled versions: frozen historical consumers may use them.
    New selections must check enabled separately.
    """
    try:
        fields = {key: getattr(row, key) for key in MODEL_RUNTIME_FIELDS}
        config = ModelConfigCreate(name=row.name, version=row.version, **fields)
        if model_hash(config) != row.model_config_hash:
            raise ConfigError("CONFIG_CORRUPT", "Model Config Hash 不一致", 409)
        return ModelConfigSnapshot(
            id=row.id,
            **config.model_dump(mode="json"),
            enabled=row.enabled,
            model_config_hash=row.model_config_hash,
        )
    except ValidationError:
        raise ConfigError("CONFIG_CORRUPT", "Model Config 参数无效", 409) from None


async def create_model(session: AsyncSession, config: ModelConfigCreate) -> ModelConfigSnapshot:
    config = ModelConfigCreate.model_validate(config.model_dump(mode="json"))
    await lock_state(session)
    existing = await session.scalar(
        select(ModelConfig.id).where(
            ModelConfig.name == config.name, ModelConfig.version == config.version
        )
    )
    if existing is not None:
        raise ConfigError("MODEL_VERSION_CONFLICT", "同名版本已存在，请创建新版本")
    row = ModelConfig(
        **config.model_dump(mode="json"), model_config_hash=model_hash(config), enabled=True
    )
    session.add(row)
    await session.flush()
    return effective_model_snapshot(row)


async def disable_model(session: AsyncSession, model_id: int) -> ModelConfigSnapshot:
    state = await lock_state(session)
    row = await session.get(ModelConfig, model_id, with_for_update=True)
    if row is None:
        raise ConfigError("MODEL_NOT_FOUND", "Model Config 不存在", 404)
    release = (
        await session.get(ConfigRelease, state.active_release_id)
        if state.active_release_id
        else None
    )
    if release and release.default_model_config_id == model_id:
        raise ConfigError(
            "MODEL_ACTIVE", "Active Release 正在引用该版本，请先发布使用其他模型的新 Release"
        )
    row.enabled = False
    await session.flush()
    return effective_model_snapshot(row)


def release_view(row: ConfigRelease, *, detail: bool = True) -> dict[str, Any]:
    fields = (
        "id",
        "version",
        "config_snapshot_hash",
        "default_model_config_id",
        "model_config_hash",
        "release_fingerprint",
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
    """Validated immutable inputs for the later TTL loader/trace integration."""
    release = await require_release(session, release_id)
    payload, digest = validate_business(release.snapshot_json)
    row = await session.get(ModelConfig, release.default_model_config_id)
    if row is None:
        raise ConfigError("CONFIG_CORRUPT", "Release Model Config 不存在")
    model = effective_model_snapshot(row)
    if (
        digest != release.config_snapshot_hash
        or model.model_config_hash != release.model_config_hash
        or release_fingerprint(digest, model.id, model.model_config_hash)
        != release.release_fingerprint
    ):
        raise ConfigError("CONFIG_CORRUPT", "Release Hash/Fingerprint 不一致")
    return {
        **release_view(release),
        "snapshot_json": payload,
        "model_config_snapshot": model.model_dump(mode="json"),
    }


async def publish_summary(session: AsyncSession, model_id: int) -> dict[str, Any]:
    row = await require_draft(session)
    payload, digest = validate_business(row.draft_json)
    model = await session.get(ModelConfig, model_id)
    if model is None:
        raise ConfigError("MODEL_NOT_FOUND", "请选择已有 Model Config", 404)
    if not model.enabled:
        raise ConfigError("MODEL_DISABLED", "已禁用版本不能用于新发布")
    frozen = effective_model_snapshot(model)
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
        "config_snapshot_hash": digest,
        "active_release_id": active.id if active else None,
        "default_model_config_id": model_id,
        "model_config_hash": frozen.model_config_hash,
        "release_fingerprint": release_fingerprint(digest, model_id, frozen.model_config_hash),
        "model_changed": active is None or active.default_model_config_id != model_id,
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
    model = await session.get(
        ModelConfig, request.default_model_config_id, with_for_update=True, populate_existing=True
    )
    if model is None:
        raise ConfigError("MODEL_NOT_FOUND", "Model Config 不存在", 404)
    if not model.enabled:
        raise ConfigError("MODEL_DISABLED", "已禁用版本不能用于新发布")
    frozen = effective_model_snapshot(model)
    release = ConfigRelease(
        version=f"release-{uuid4().hex}",
        snapshot_json=payload,
        config_snapshot_hash=digest,
        default_model_config_id=model.id,
        model_config_hash=frozen.model_config_hash,
        release_fingerprint=release_fingerprint(digest, model.id, frozen.model_config_hash),
        note=request.note,
        created_by="admin",
    )
    session.add(release)
    await session.flush()
    # The release insert, freeze marker and active pointer share the caller's transaction.
    model.immutable_from_at = model.immutable_from_at or now()
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
