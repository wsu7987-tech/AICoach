"""Dataset, task, review and export API for the V2 evaluation workbench."""

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.api.admin.config import session_dependency
from app.db.models import EvaluationDataset, EvaluationRun
from app.schemas.evaluation import DatasetCreate, ReviewInput, RunCreate
from app.services.config_service import ConfigError
from app.services.evaluation import service
from app.services.evaluation.workbook import make_workbook, parse_workbook

router = APIRouter(prefix="/evaluation", tags=["evaluation"])

Session = Annotated[AsyncSession, Depends(session_dependency, scope="function")]


def download(content, name):
    return Response(
        content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"},
    )


@router.get("/template")
async def template():
    return download(await run_in_threadpool(make_workbook), "AI_Coach_批量评测模板.xlsx")


@router.get("/datasets")
async def datasets(
    session: Session, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)
):
    rows = (
        await session.scalars(
            select(EvaluationDataset)
            .order_by(EvaluationDataset.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    total = await session.scalar(select(func.count()).select_from(EvaluationDataset))
    return {"items": [service.dataset_view(row) for row in rows], "total": total}


@router.post("/datasets")
async def create_dataset(body: DatasetCreate, session: Session, request: Request):
    if len(body.cases) > request.app.state.settings.max_eval_cases:
        raise ConfigError("EVAL_TOO_MANY_CASES", "用例数超过配置限制", 422)
    return await service.create_dataset(session, body)


@router.post("/datasets/import")
async def import_dataset(
    request: Request,
    session: Session,
    name: str = Query(min_length=1, max_length=128),
    filename: str = Query(default="评测集.xlsx", max_length=512),
):
    settings = request.app.state.settings
    buffer = bytearray()
    async for chunk in request.stream():
        buffer.extend(chunk)
        if len(buffer) > settings.max_eval_file_bytes:
            raise ConfigError("EVAL_FILE_TOO_LARGE", "Excel 文件超过上传限制", 413)
    body = await run_in_threadpool(
        parse_workbook, bytes(buffer), name, min(settings.max_eval_cases, 500)
    )
    return await service.create_dataset(session, body, filename)


@router.get("/datasets/{dataset_id}")
async def dataset_detail(dataset_id: int, session: Session):
    row = await session.get(EvaluationDataset, dataset_id)
    if row is None:
        raise ConfigError("EVAL_DATASET_NOT_FOUND", "评测集不存在", 404)
    return {**service.dataset_view(row), "cases": row.normalized_cases_json}


@router.get("/datasets/{dataset_id}/export")
async def export_dataset(dataset_id: int, session: Session):
    row = await session.get(EvaluationDataset, dataset_id)
    if row is None:
        raise ConfigError("EVAL_DATASET_NOT_FOUND", "评测集不存在", 404)
    content = await run_in_threadpool(make_workbook, row.normalized_cases_json)
    return download(content, f"{row.name}.xlsx")


@router.get("/runs")
async def runs(
    session: Session, offset: int = Query(0, ge=0), limit: int = Query(30, ge=1, le=100)
):
    rows = (
        await session.scalars(
            select(EvaluationRun)
            .order_by(EvaluationRun.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    total = await session.scalar(select(func.count()).select_from(EvaluationRun))
    return {"items": [service.run_view(row) for row in rows], "total": total}


@router.post("/runs")
async def create_run(body: RunCreate, session: Session, request: Request):
    loader = request.app.state.managed_model_loader
    if loader is None:
        raise ConfigError("CONFIG_NOT_READY", "模型配置尚未就绪", 503)
    return await service.create_run(session, body, loader)


@router.get("/compare")
async def compare(session: Session, left: int = Query(gt=0), right: int = Query(gt=0)):
    return await service.compare_runs(session, left, right)


@router.get("/runs/{run_id}")
async def run_detail(run_id: int, session: Session):
    run = await service.require_run(session, run_id)
    results = await service.all_results(session, run)
    return {**service.run_view(run), "summary": service.summary(run, results)}


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: int, session: Session):
    run = await service.require_run(session, run_id, lock=True)
    if run.status in {"queued", "running"}:
        run.cancel_requested = True
        if run.status == "queued":
            run.status = "cancelled"
            run.finished_at = service.now()
    return service.run_view(run)


@router.get("/runs/{run_id}/results")
async def results(
    run_id: int,
    session: Session,
    status: str | None = None,
    tag: str | None = None,
    issue: str | None = None,
    keyword: str | None = None,
    bad_only: bool = False,
    primary_only: bool = False,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
):
    run = await service.require_run(session, run_id)
    items = await service.all_results(session, run)
    selected = service.filter_results(
        items,
        status=status,
        tag=tag,
        issue=issue,
        keyword=keyword,
        bad_only=bad_only,
        primary_only=primary_only,
    )
    return {
        "items": selected[offset : offset + limit],
        "total": len(selected),
        "case_ids": list(dict.fromkeys(item["case_id"] for item in selected)),
        "tags": sorted({tag for item in items for tag in item["tags"]}),
        "issue_tags": sorted({tag for item in items for tag in item["issue_tags"]}),
    }


@router.post("/runs/{run_id}/results/{result_id}/review")
async def review(run_id: int, result_id: int, body: ReviewInput, session: Session):
    await service.review_result(session, run_id, result_id, body)
    return {"saved": True}


@router.get("/runs/{run_id}/export")
async def export_run(
    run_id: int,
    session: Session,
    status: str | None = None,
    tag: str | None = None,
    issue: str | None = None,
    keyword: str | None = None,
    bad_only: bool = False,
    primary_only: bool = False,
):
    run = await service.require_run(session, run_id)
    all_items = await service.all_results(session, run)
    items = service.filter_results(
        all_items,
        status=status,
        tag=tag,
        issue=issue,
        keyword=keyword,
        bad_only=bad_only,
        primary_only=primary_only,
    )
    ids = {item["case_id"] for item in items}
    cases = [case for case in run.cases_json if case["case_id"] in ids]
    stats = service.summary(run, all_items)
    report = {
        "任务": run.name,
        "通过率口径": "首次执行通过用例 / 本任务全部用例，含执行错误；筛选不改变分母",
        "结论阶段": "最终通过率" if stats["final"] else "当前通过率，验收未完成",
        "通过率": f"{stats['pass_rate']}%",
        "全部用例数": stats["total"],
        "通过": stats["passed"],
        "不通过": stats["failed"],
        "执行错误": stats["errors"],
        "待复核": stats["review"],
        "导出用例数": len(cases),
        "导出执行记录数": len(items),
        "验收": {"passed": "达标", "failed": "未达标", "incomplete": "未完成"}[stats["acceptance"]],
        "验收目标通过率": f"{run.evaluation_config_json['pass_threshold']}%",
        "判定规则版本": run.evaluation_config_json["rules_version"],
        "识别模型": run.managed_model_snapshot_json["display_name"],
    }
    content = await run_in_threadpool(make_workbook, cases, items, report)
    return download(content, f"{run.name}-评测结果.xlsx")
