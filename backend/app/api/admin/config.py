"""Thin Admin API; all mutations commit before a response is sent."""

from collections.abc import AsyncIterator
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    ConfigDraft,
    ConfigRelease,
    RuntimeState,
)
from app.schemas.config import (
    ConfigStatus,
    DraftPreview,
    DraftUpdate,
    DraftValidation,
    DraftView,
    PromptModulePreview,
    PromptModulePreviewResult,
    PublishedRelease,
    PublishInput,
    PublishSummary,
    ReleaseDetail,
    ReleaseHistory,
    RestoreInput,
)
from app.schemas.intent import PromptBuildResult
from app.services import config_service as service
from app.services import status_service

router = APIRouter()


async def session_dependency(request: Request) -> AsyncIterator[AsyncSession]:
    database = request.app.state.database
    if database is None:
        raise service.ConfigError("CONFIG_NOT_READY", "数据库尚未配置", 503)
    async with database.transaction() as session:
        yield session


Session = Annotated[AsyncSession, Depends(session_dependency, scope="function")]


@router.get("/config/draft", response_model=DraftView)
async def get_draft(session: Session):
    return await service.get_draft(session)


@router.put("/config/draft", response_model=DraftView)
async def save_draft(body: DraftUpdate, session: Session):
    return await service.save_draft(session, body.draft_json, body.expected_draft_hash)


@router.post("/config/bootstrap", status_code=201, response_model=DraftView)
async def import_bootstrap(body: DraftUpdate, session: Session):
    # The UI supplies the repository Bootstrap as an explicit import. No filesystem
    # dependency in the deployed image, and no implicit publish/model creation.
    await service.lock_state(session)
    if await session.get(ConfigDraft, 1) is not None:
        raise service.ConfigError("DRAFT_CONFLICT", "Draft 已存在，Bootstrap 不覆盖现有编辑")
    return await service.save_draft(session, body.draft_json, None)


@router.post("/config/validate", response_model=DraftValidation)
async def validate_draft(session: Session):
    return await service.validate_draft(session)


@router.post("/config/prompt-preview", response_model=PromptBuildResult)
async def preview_prompt(body: DraftPreview, session: Session):
    return await service.preview_prompt(session, body.text, body.context)


@router.post("/config/prompt-preview/module", response_model=PromptModulePreviewResult)
async def preview_prompt_module(body: PromptModulePreview, session: Session):
    return await service.preview_prompt_module(
        session,
        module=body.module,
        intent_name=body.intent_name,
        slot_name=body.slot_name,
        enum_group=body.enum_group,
    )


@router.get("/config/publish-summary", response_model=PublishSummary)
async def publish_summary(session: Session):
    return await service.publish_summary(session)


@router.post("/releases", status_code=201, response_model=PublishedRelease)
async def publish(body: PublishInput, session: Session):
    return await service.publish(session, body)


@router.get("/releases", response_model=ReleaseHistory)
async def list_releases(
    session: Session, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)
):
    rows = await session.scalars(
        select(ConfigRelease).order_by(ConfigRelease.id.desc()).offset(offset).limit(limit)
    )
    state = await session.get(RuntimeState, 1)
    return {
        "active_release_id": state.active_release_id if state else None,
        "items": [service.release_view(row, detail=False) for row in rows],
    }


@router.get("/releases/{release_id}", response_model=ReleaseDetail)
async def get_release(release_id: int, session: Session):
    configuration = await service.release_configuration(session, release_id)
    # Runtime integrity fields stay inside the service boundary. The product
    # detail API returns only the business snapshot and readable metadata.
    return {
        key: configuration[key]
        for key in ("id", "version", "note", "created_by", "created_at", "snapshot_json")
    }


@router.post("/releases/{release_id}/create-draft", response_model=DraftView)
async def restore_draft(release_id: int, body: RestoreInput, session: Session):
    return await service.restore_draft(session, release_id, body.expected_draft_hash)


@router.get("/status/summary", response_model=ConfigStatus)
async def status_summary(
    request: Request,
    source: Literal["runtime", "debug", "replay", "evaluation"] = "runtime",
):
    # Status must remain readable even when the database dependency is unavailable.
    return await status_service.summary(
        request.app.state.database,
        request.app.state.readiness_checker,
        request.app.state.managed_model_loader,
        source=source,
    )
