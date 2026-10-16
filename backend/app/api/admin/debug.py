"""TASK-202 internal debug, trace, replay, diff and status endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin.config import session_dependency
from app.core.errors import AppError, ErrorCode
from app.schemas.debug import DebugAnalyzeInput, DiffInput, ReplayInput
from app.services import debug_service

router = APIRouter()
Session = Annotated[AsyncSession, Depends(session_dependency, scope="function")]


def _components(request: Request):
    database = request.app.state.database
    provider_factory = request.app.state.provider_factory
    managed_model_loader = request.app.state.managed_model_loader
    if database is None or provider_factory is None or managed_model_loader is None:
        raise AppError(ErrorCode.CONFIG_NOT_READY, "runtime configuration is not ready", 503)
    return database.session_factory, provider_factory, managed_model_loader


@router.post("/debug/analyze")
async def debug_analyze(body: DebugAnalyzeInput, request: Request, session: Session):
    sessions, factory, managed_model_loader = _components(request)
    configuration = await debug_service.configuration_for(session, release_id=body.release_id)
    results = await debug_service.execute(
        sessions,
        factory,
        managed_model_loader,
        text=body.text,
        context=body.context,
        configuration=configuration,
        model_uid=body.model_uid,
        repeat=body.repeat,
        mode="debug",
    )
    routes = [item["runtime_result"]["route"] for item in results if item["ok"]]
    return {
        "runs": results,
        "stability": {
            "success_count": len(routes),
            "route_distribution": dict(__import__("collections").Counter(routes)),
        },
    }


@router.get("/traces")
async def traces(
    request: Request,
    request_id: str | None = None,
    trace_id: str | None = None,
    keyword: str | None = None,
    route: str | None = None,
    intent: str | None = None,
    model_uid: str | None = Query(default=None, pattern=r"^mdl_[a-f0-9]{64}$"),
    release_id: int | None = Query(default=None, gt=0),
    status: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    sessions, _, _ = _components(request)
    return await debug_service.list_traces(sessions, locals())


@router.get("/traces/{trace_id}")
async def trace_detail(trace_id: str, request: Request):
    sessions, _, _ = _components(request)
    return await debug_service.trace_detail(sessions, trace_id)


@router.get("/intent/latency-analysis")
async def intent_latency_analysis(
    request: Request,
    request_id: str = Query(min_length=1, max_length=128),
    model_uid: str = Query(pattern=r"^mdl_[a-f0-9]{64}$"),
    sample_size: int = Query(default=20, ge=5, le=100),
):
    sessions, _, _ = _components(request)
    return await debug_service.intent_latency_analysis(
        sessions,
        request_id=request_id,
        model_uid=model_uid,
        sample_size=sample_size,
    )


@router.get("/intent/prompt")
async def intent_prompt(
    request: Request,
    request_id: str = Query(min_length=1, max_length=128),
    model_uid: str = Query(pattern=r"^mdl_[a-f0-9]{64}$"),
):
    sessions, _, _ = _components(request)
    return await debug_service.intent_prompt(
        sessions,
        request_id=request_id,
        model_uid=model_uid,
    )


@router.get("/intent/model-output")
async def intent_model_output(
    request: Request,
    request_id: str = Query(min_length=1, max_length=128),
    model_uid: str = Query(pattern=r"^mdl_[a-f0-9]{64}$"),
):
    sessions, _, _ = _components(request)
    return await debug_service.intent_model_output(
        sessions,
        request_id=request_id,
        model_uid=model_uid,
    )


@router.post("/traces/{trace_id}/replay")
async def replay(trace_id: str, body: ReplayInput, request: Request, session: Session):
    sessions, factory, managed_model_loader = _components(request)
    original = await debug_service.trace_detail(sessions, trace_id)
    release_id = None if body.mode == "active" else original["release"]["id"]
    historical_model_uid = (
        original["model"]["model_uid"] if body.mode == "historical" else None
    )
    configuration = await debug_service.configuration_for(session, release_id=release_id)
    results = await debug_service.execute(
        sessions,
        factory,
        managed_model_loader,
        text=original["input"],
        context=original["context"] or {},
        configuration=configuration,
        model_uid=body.model_uid or historical_model_uid,
        repeat=body.repeat,
        mode="replay",
        parent_trace_id=trace_id,
    )
    return {"parent_trace_id": trace_id, "mode": body.mode, "runs": results}


@router.post("/traces/diff")
async def diff(body: DiffInput, request: Request):
    sessions, _, _ = _components(request)
    return debug_service.diff(
        await debug_service.trace_detail(sessions, body.left_trace_id),
        await debug_service.trace_detail(sessions, body.right_trace_id),
    )
