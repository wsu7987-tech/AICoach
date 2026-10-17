"""Evaluation dataset/run administration and reproducible result projections."""

from collections import Counter
from datetime import UTC, datetime
from math import ceil
from uuid import uuid4

from sqlalchemy import select

from app.db.models import EvaluationCaseResult, EvaluationDataset, EvaluationRun, IntentRequestTrace
from app.schemas.evaluation import DatasetCreate, ReviewInput, RunCreate
from app.schemas.intent import sha256_canonical
from app.services.config_service import ConfigError
from app.services.debug_service import configuration_for
from app.services.evaluation.frozen import (
    JUDGE_PROMPT,
    RULES_VERSION,
    freeze_model,
    implementation_digest,
)
from app.services.evaluation.metrics import labelled_metrics
from app.services.evaluation.rules import semantic_signature


def now():
    return datetime.now(UTC).replace(tzinfo=None)


async def require_run(session, run_id, *, lock=False):
    query = select(EvaluationRun).where(EvaluationRun.id == run_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    run = await session.scalar(query)
    if run is None:
        raise ConfigError("EVAL_RUN_NOT_FOUND", "评测任务不存在", 404)
    return run


def dataset_view(row):
    return {
        "id": row.id,
        "name": row.name,
        "version": row.version,
        "hash": row.hash,
        "case_count": len(row.normalized_cases_json),
        "source_filename": row.source_filename,
        "created_at": row.created_at,
    }


async def normalize_cases(session, body: DatasetCreate):
    cases = [case.model_dump(mode="json", exclude_unset=True) for case in body.cases]
    for case in cases:
        case.setdefault("tags", [])
        case.setdefault("context", {})
        case.setdefault("critical", False)
        expected = case.get("expected") or {}
        case["expected"] = {
            key: value for key, value in expected.items() if value is not None or key == "risk"
        }
        for action in case["expected"].get("actions") or []:
            for key in ("slots", "depends_on"):
                if action.get(key) is None:
                    action.pop(key, None)
    if not any((case.get("expected") or {}).get("actions") for case in cases):
        return cases
    configuration = await configuration_for(session, None)
    snapshot = configuration.snapshot

    def resolve(value, entries, label):
        matches = [
            entry
            for entry in entries
            if value in {entry.name, entry.zh, *getattr(entry, "aliases", [])}
        ]
        if len(matches) != 1:
            raise ConfigError(
                "EVAL_LABEL_INVALID", f"{label}：{value} 没有唯一匹配的已发布配置", 422
            )
        return matches[0]

    for case in cases:
        for index, action in enumerate((case.get("expected") or {}).get("actions") or [], 1):
            label = f"用例 {case['case_id']} 动作 {index}"
            route = resolve(
                action["route"],
                [item for item in snapshot.routes if item.enabled],
                f"{label} Route",
            )
            action["route"] = route.name
            if action.get("intent") is not None:
                intent = resolve(action["intent"], snapshot.active_intents, f"{label} Intent")
                if intent.route != route.name:
                    raise ConfigError(
                        "EVAL_LABEL_INVALID", f"{label} 的 Intent 不属于所填 Route", 422
                    )
                action["intent"] = intent.name
    return cases


async def create_dataset(session, body: DatasetCreate, filename="页面录入"):
    cases = await normalize_cases(session, body)
    cases.sort(key=lambda case: case["case_id"])
    row = EvaluationDataset(
        name=body.name,
        version=f"{now():%Y%m%d%H%M%S}-{uuid4().hex[:8]}",
        source_filename=filename[:512],
        hash=sha256_canonical(cases),
        normalized_cases_json=cases,
    )
    session.add(row)
    await session.flush()
    return dataset_view(row)


async def create_run(session, body: RunCreate, loader):
    dataset = await session.get(EvaluationDataset, body.dataset_id)
    if dataset is None:
        raise ConfigError("EVAL_DATASET_NOT_FOUND", "评测集不存在", 404)
    cases = dataset.normalized_cases_json
    if body.case_ids is not None:
        selected = set(body.case_ids)
        if len(selected) != len(body.case_ids) or not selected.issubset(
            {case["case_id"] for case in cases}
        ):
            raise ConfigError("EVAL_CASE_INVALID", "所选用例重复或不存在", 422)
        cases = [case for case in cases if case["case_id"] in selected]
    if body.parent_run_id:
        parent = await require_run(session, body.parent_run_id)
        if parent.dataset_id != dataset.id:
            raise ConfigError("EVAL_DATASET_MISMATCH", "复测必须使用原任务的评测集", 422)
        parent_ids = {case["case_id"] for case in parent.cases_json}
        if body.case_ids is None:
            cases = [case for case in cases if case["case_id"] in parent_ids]
        elif not set(body.case_ids).issubset(parent_ids):
            raise ConfigError("EVAL_CASE_INVALID", "复测不能包含原任务以外的用例", 422)
    configuration = await configuration_for(session, body.release_id)
    frozen = await freeze_model(session, loader, body.model_uid)
    judge = (
        await freeze_model(session, loader, body.judge_model_uid) if body.judge_model_uid else None
    )
    evaluation = {
        "model": frozen,
        "judge": judge,
        "judge_prompt": JUDGE_PROMPT,
        "rules_version": RULES_VERSION,
        "implementation_digest": implementation_digest(),
        "pass_threshold": body.pass_threshold,
        "output_version": 2,
    }
    row = EvaluationRun(
        name=body.name,
        dataset_id=dataset.id,
        dataset_hash=sha256_canonical(cases),
        cases_json=cases,
        release_id=configuration.release_id,
        config_snapshot_hash=configuration.config_snapshot_hash,
        config_snapshot_json=configuration.snapshot.model_dump(mode="json"),
        evaluation_config_json=evaluation,
        managed_model_uid=frozen["snapshot"]["model_uid"],
        managed_model_snapshot_json=frozen["snapshot"],
        repeat_count=body.repeat_count,
        worker_concurrency=body.worker_concurrency,
        parent_run_id=body.parent_run_id,
        status="queued",
        cancel_requested=False,
        progress_json={"completed": 0},
    )
    session.add(row)
    await session.flush()
    return run_view(row)


def run_view(run):
    config = run.evaluation_config_json
    judge = config.get("judge")
    return {
        "id": run.id,
        "name": run.name,
        "dataset_id": run.dataset_id,
        "dataset_hash": run.dataset_hash,
        "release_id": run.release_id,
        "model_uid": run.managed_model_uid,
        "model_label": run.managed_model_snapshot_json["display_name"],
        "judge_model_uid": judge["snapshot"]["model_uid"] if judge else None,
        "judge_label": judge["snapshot"]["display_name"] if judge else "人工复核",
        "repeat_count": run.repeat_count,
        "worker_concurrency": run.worker_concurrency,
        "pass_threshold": config["pass_threshold"],
        "status": run.status,
        "case_count": len(run.cases_json),
        "execution_count": len(run.cases_json) * run.repeat_count,
        "progress": run.progress_json or {"completed": 0},
        "parent_run_id": run.parent_run_id,
        "cancel_requested": run.cancel_requested,
        "error": run.error,
        "heartbeat_at": run.heartbeat_at,
        "created_at": run.created_at,
        "finished_at": run.finished_at,
        "rules_version": config["rules_version"],
        "implementation_digest": config["implementation_digest"],
        "config_snapshot_hash": run.config_snapshot_hash,
    }


def result_view(case, row, trace_ids):
    if row is None:
        return {
            "id": None,
            **case,
            "status": "not_run",
            "auto_status": "not_run",
            "repeat_index": 0,
            "actual": None,
            "issue_tags": [],
            "reason": "尚未执行",
            "request_id": None,
            "trace_id": None,
            "trace_state": "unavailable",
            "latency_ms": None,
            "reviews": [],
            "review_revision": 0,
            "verdict": {},
        }
    verdict = row.verdict_json
    review = row.review_json[-1] if row.review_json else None
    # Human review cannot erase assertion failures or execution errors.
    status = row.auto_status
    if (
        review
        and status not in {"error", "cancelled"}
        and not verdict.get("rules", {}).get("issues")
    ):
        status = review["decision"]
    tags = list(
        dict.fromkeys(
            [issue["tag"] for issue in verdict.get("rules", {}).get("issues", [])]
            + verdict.get("judge", {}).get("tags", [])
            + (["execution_error"] if row.auto_status == "error" else [])
            + (["judge_error"] if verdict.get("judge_error") else [])
        )
    )
    return {
        "id": row.id,
        **case,
        "repeat_index": row.repeat_index,
        "status": status,
        "auto_status": row.auto_status,
        "actual": row.actual_json,
        "verdict": verdict,
        "issue_tags": tags,
        "reason": review["reason"] if review else verdict.get("reason", row.error_message or ""),
        "request_id": row.request_id,
        "trace_id": row.trace_id,
        "trace_state": "available"
        if row.trace_id in trace_ids
        else "expired"
        if row.trace_id
        else "unavailable",
        "latency_ms": row.latency_ms,
        "reviews": row.review_json,
        "review_revision": row.review_revision,
    }


async def all_results(session, run):
    rows = list(
        (
            await session.scalars(
                select(EvaluationCaseResult).where(EvaluationCaseResult.run_id == run.id)
            )
        ).all()
    )
    trace_ids = {row.trace_id for row in rows if row.trace_id}
    existing = (
        set(
            (
                await session.scalars(
                    select(IntentRequestTrace.trace_id).where(
                        IntentRequestTrace.trace_id.in_(trace_ids)
                    )
                )
            ).all()
        )
        if trace_ids
        else set()
    )
    by_key = {(row.case_id, row.repeat_index): row for row in rows}
    result = []
    for case in run.cases_json:
        for index in range(run.repeat_count):
            item = result_view(case, by_key.get((case["case_id"], index)), existing)
            item["repeat_index"] = index
            if item["status"] == "not_run" and run.status == "cancelled":
                item["status"] = "cancelled"
                item["reason"] = "任务已取消，该条未执行"
            result.append(item)
    grouped = {}
    for item in result:
        grouped.setdefault(item["case_id"], []).append(item)
    for item in result:
        repeats = grouped[item["case_id"]]
        item["repeat_passed"] = sum(repeat["status"] == "pass" for repeat in repeats)
        item["repeat_count"] = run.repeat_count
    return result


def summary(run, items):
    primary = [item for item in items if item["repeat_index"] == 0]
    counts = Counter(item["status"] for item in primary)
    total = len(primary)
    percent = round(counts["pass"] * 100 / total, 2) if total else 0
    pending = sum(item["status"] in {"review", "not_run", "cancelled", "judging"} for item in items)
    final = run.status == "completed" and pending == 0 and len(items) == total * run.repeat_count
    critical_failures = sum(
        item.get("critical", False) and item["status"] != "pass" for item in items
    )
    latency = sorted(item["latency_ms"] for item in primary if item["latency_ms"] is not None)
    grouped = {}
    for item in items:
        grouped.setdefault(item["case_id"], []).append(item)
    stable = sum(
        all(item["actual"] is not None for item in group)
        and len({semantic_signature(item["actual"]) for item in group}) == 1
        for group in grouped.values()
    )
    by_tag = {}
    for item in primary:
        for tag in item["tags"] or ["未分类"]:
            entry = by_tag.setdefault(tag, {"total": 0, "passed": 0})
            entry["total"] += 1
            entry["passed"] += item["status"] == "pass"
    return {
        "total": total,
        "passed": counts["pass"],
        "failed": counts["fail"],
        "errors": counts["error"],
        "review": counts["review"],
        "judging": counts["judging"],
        "not_run": counts["not_run"] + counts["cancelled"],
        "pass_rate": percent,
        "final": final,
        "pending_executions": pending,
        "completed_executions": sum(
            item["status"] in {"pass", "fail", "review", "error"} for item in items
        ),
        "total_executions": total * run.repeat_count,
        "critical_failures": critical_failures,
        "acceptance": "passed"
        if final
        and counts["pass"] * 100 >= run.evaluation_config_json["pass_threshold"] * total
        and critical_failures == 0
        else "failed"
        if final
        else "incomplete",
        "average_latency_ms": round(sum(latency) / len(latency)) if latency else None,
        "p95_latency_ms": latency[max(0, ceil(len(latency) * 0.95) - 1)] if latency else None,
        "stable_cases": stable if run.repeat_count > 1 else None,
        "stability_rate": round(stable * 100 / total, 2)
        if total and run.repeat_count > 1
        else None,
        "by_tag": by_tag,
        "quality": labelled_metrics(primary),
        "recorded_tokens": sum(
            (item["verdict"].get("recognition_tokens") or 0)
            + sum(
                (attempt.get("usage") or {}).get("total_tokens", 0) or 0
                for attempt in item["verdict"].get("judge", {}).get("attempts", [])
            )
            for item in items
        ),
        "issue_counts": dict(
            Counter(
                tag for item in primary if item["status"] != "pass" for tag in item["issue_tags"]
            )
        ),
    }


def filter_results(
    items, *, status=None, tag=None, issue=None, keyword=None, bad_only=False, primary_only=False
):
    return [
        item
        for item in items
        if (not status or item["status"] == status)
        and (not tag or tag in item["tags"])
        and (not issue or issue in item["issue_tags"])
        and (
            not keyword
            or keyword.casefold()
            in " ".join(
                str(item[key]) for key in ("case_id", "question", "standard_answer", "reason")
            ).casefold()
        )
        and (not bad_only or item["status"] in {"fail", "error", "review"})
        and (not primary_only or item["repeat_index"] == 0)
    ]


async def review_result(session, run_id: int, result_id: int, body: ReviewInput):
    await require_run(session, run_id)
    row = await session.scalar(
        select(EvaluationCaseResult)
        .where(EvaluationCaseResult.id == result_id, EvaluationCaseResult.run_id == run_id)
        .with_for_update()
    )
    if row is None:
        raise ConfigError("EVAL_RESULT_NOT_FOUND", "评测结果不存在", 404)
    if row.review_revision != body.expected_revision:
        raise ConfigError("EVAL_REVIEW_CONFLICT", "该结果已被其他人复核，请刷新后重试")
    if row.auto_status not in {"pass", "fail", "review"} or row.verdict_json.get("rules", {}).get(
        "issues"
    ):
        raise ConfigError(
            "EVAL_REVIEW_BLOCKED", "执行错误或精确规则不符合不能人工改为通过，请修正标准答案或复测"
        )
    row.review_json = [
        *row.review_json,
        {
            "decision": body.decision,
            "reason": body.reason,
            "reviewer": body.reviewer,
            "created_at": now().isoformat(),
        },
    ]
    row.review_revision += 1
    row.passed = body.decision == "pass"


async def compare_runs(session, left_id: int, right_id: int):
    left, right = await require_run(session, left_id), await require_run(session, right_id)
    if left.dataset_hash != right.dataset_hash:
        raise ConfigError(
            "EVAL_COMPARE_DATASET",
            "只能直接对比相同用例和标准答案的任务；子集复测不能冒充完整集提升",
            422,
        )
    if (
        left.evaluation_config_json["rules_version"]
        != right.evaluation_config_json["rules_version"]
    ):
        raise ConfigError("EVAL_COMPARE_RULES", "判定规则版本不同，不能直接比较通过率", 422)
    first, second = await all_results(session, left), await all_results(session, right)
    a = {item["case_id"]: item for item in first if item["repeat_index"] == 0}
    b = {item["case_id"]: item for item in second if item["repeat_index"] == 0}
    changes = []
    for key in a:
        before, after = a[key]["status"], b[key]["status"]
        change = (
            "regression"
            if before == "pass" and after in {"fail", "error"}
            else "improvement"
            if before in {"fail", "error"} and after == "pass"
            else "unchanged"
            if before == after
            else "pending"
        )
        changes.append(
            {
                "case_id": key,
                "question": a[key]["question"],
                "before": before,
                "after": after,
                "change": change,
                "left_reason": a[key]["reason"],
                "right_reason": b[key]["reason"],
            }
        )
    judge_changed = left.evaluation_config_json.get("judge") != right.evaluation_config_json.get(
        "judge"
    )
    return {
        "left": {**run_view(left), "summary": summary(left, first)},
        "right": {**run_view(right), "summary": summary(right, second)},
        "changes": changes,
        "judge_changed": judge_changed,
        "warning": "评审模型或参数发生变化，差异包含评审口径影响" if judge_changed else None,
    }
