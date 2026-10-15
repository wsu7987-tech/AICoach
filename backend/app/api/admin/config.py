"""Thin Admin API; all mutations commit before a response is sent."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    ConfigDraft,
    ConfigRelease,
    ManagedModel,
    ModelConfig,
    RuntimeModelState,
    RuntimeState,
)
from app.schemas.config import (
    ConfigStatus,
    DraftPreview,
    DraftUpdate,
    DraftValidation,
    DraftView,
    ModelConfigCreate,
    PromptModulePreview,
    PromptModulePreviewResult,
    PublishedRelease,
    PublishInput,
    PublishSummary,
    ReleaseDetail,
    ReleaseHistory,
    RestoreInput,
)
from app.schemas.intent import ModelConfigSnapshot, PromptBuildResult
from app.services import config_service as service
from app.services import debug_service

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


@router.get("/model-configs", response_model=list[ModelConfigSnapshot])
async def list_models(
    session: Session, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)
):
    rows = await session.scalars(
        select(ModelConfig).order_by(ModelConfig.id.desc()).offset(offset).limit(limit)
    )
    return [service.effective_model_snapshot(row) for row in rows]


@router.post("/model-configs", status_code=201, response_model=ModelConfigSnapshot)
async def create_model(body: ModelConfigCreate, session: Session):
    return await service.create_model(session, body)


@router.get("/model-configs/{model_id}", response_model=ModelConfigSnapshot)
async def get_model(model_id: int, session: Session):
    row = await session.get(ModelConfig, model_id)
    if row is None:
        raise service.ConfigError("MODEL_NOT_FOUND", "Model Config 不存在", 404)
    return service.effective_model_snapshot(row)


@router.post("/model-configs/{model_id}/disable", response_model=ModelConfigSnapshot)
async def disable_model(model_id: int, session: Session):
    return await service.disable_model(session, model_id)


@router.get("/config/publish-summary", response_model=PublishSummary)
async def publish_summary(session: Session, default_model_config_id: int = Query(gt=0)):
    return await service.publish_summary(session, default_model_config_id)


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
    return await service.release_configuration(session, release_id)


@router.post("/releases/{release_id}/create-draft", response_model=DraftView)
async def restore_draft(release_id: int, body: RestoreInput, session: Session):
    return await service.restore_draft(session, release_id, body.expected_draft_hash)


@router.get("/status/summary", response_model=ConfigStatus)
async def status_summary(request: Request, session: Session):
    state = await session.get(RuntimeState, 1)
    active_id = state.active_release_id if state else None
    ready = False
    if active_id:
        try:
            await service.release_configuration(session, active_id)
            model_state = await session.get(RuntimeModelState, 1)
            managed_model = (
                await session.get(ManagedModel, model_state.default_model_id)
                if model_state is not None and model_state.default_model_id is not None
                else None
            )
            ready = bool(
                managed_model
                and managed_model.enabled
                and (managed_model.credential_id or managed_model.credential_ref)
            )
        except service.ConfigError:
            pass
    active = None
    default_model = None
    if active_id:
        try:
            configuration = await service.release_configuration(session, active_id)
            active = {
                key: configuration[key]
                for key in ("id", "version", "config_snapshot_hash", "release_fingerprint")
            }
            default_model = configuration["model_config_snapshot"]
        except service.ConfigError:
            pass
    # /ready is the authoritative service-plane definition, intentionally
    # independent from the Runtime configuration state.
    report = await request.app.state.readiness_checker.check()
    database = request.app.state.database
    metrics = (
        await debug_service.status(database.session_factory)
        if database is not None
        else {
            "requests_24h": 0,
            "errors_24h": 0,
            "avg_latency_ms": None,
            "p95_latency_ms": None,
            "evaluation_queued": 0,
            "evaluation_running": 0,
        }
    )
    return {
        "runtime_config_ready": ready,
        "active_release_id": active_id,
        "service_ready": bool(report and report.ready),
        "active_release": active,
        "default_model_config": default_model,
        **metrics,
    }
