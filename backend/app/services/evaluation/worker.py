"""Standalone MySQL-leased evaluation worker: python -m app.services.evaluation.worker."""

import asyncio
import hashlib
import logging
import signal
import time
from contextlib import suppress
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import and_, func, or_, select

from app.core.errors import AppError
from app.core.logging import configure_logging
from app.core.settings import get_settings
from app.db.database import Database
from app.db.models import EvaluationCaseResult, EvaluationRun
from app.db.readiness import DatabaseSchemaReadiness
from app.prompting.builder import PromptBuilder
from app.providers.factory import ModelProviderFactory
from app.security.credentials import CredentialCipher
from app.services.config_service import ConfigError
from app.services.debug_service import FixedConfigurationLoader
from app.services.evaluation.frozen import FrozenModelLoader, implementation_digest
from app.services.evaluation.judge import JudgeProvider, judge_result
from app.services.evaluation.rules import evaluate_rules
from app.services.evaluation.service import now
from app.services.intent_service import BusinessRuntimeConfiguration, IntentService
from app.services.trace_store import DatabaseTraceStore

logger = logging.getLogger(__name__)
TERMINAL_RESULTS = {"pass", "fail", "review", "error"}


class ClaimLost(Exception):
    pass


class CapturingTraceStore:
    """Capture this invocation's identity; never query a global 'latest trace'."""

    def __init__(self, sessions):
        self.store = DatabaseTraceStore(sessions)
        self.record = None

    async def write(self, trace):
        await self.store.write(trace)
        self.record = trace


class EvaluationWorker:
    def __init__(self, database, settings, stop=None):
        self.database = database
        self.sessions = database.session_factory
        self.settings = settings
        self.cipher = CredentialCipher(settings.credential_encryption_key)
        self.stop = stop or asyncio.Event()
        self.identity = f"eval-{uuid4().hex}"

    async def claim(self):
        async with self.database.transaction() as session:
            database_now = await session.scalar(select(func.utc_timestamp(6)))
            stale = database_now - timedelta(seconds=self.settings.eval_worker_lease_seconds)
            run = await session.scalar(
                select(EvaluationRun)
                .where(
                    or_(
                        EvaluationRun.status == "queued",
                        and_(
                            EvaluationRun.status == "running",
                            or_(
                                EvaluationRun.heartbeat_at < stale,
                                EvaluationRun.heartbeat_at.is_(None),
                            ),
                        ),
                    )
                )
                .order_by(EvaluationRun.created_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if run is None:
                return None
            run.status = "running"
            run.claimed_by = f"{self.identity}:{uuid4().hex}"
            run.heartbeat_at = database_now
            run.started_at = run.started_at or database_now
            return run

    async def locked_run(self, session, run):
        owned = await session.scalar(
            select(EvaluationRun).where(EvaluationRun.id == run.id).with_for_update()
        )
        if owned.status != "running" or owned.claimed_by != run.claimed_by:
            raise ClaimLost()
        return owned

    async def heartbeat(self, run, lost):
        try:
            while not lost.is_set():
                await asyncio.sleep(self.settings.eval_worker_lease_seconds / 3)
                async with self.database.transaction() as session:
                    owned = await self.locked_run(session, run)
                    owned.heartbeat_at = await session.scalar(select(func.utc_timestamp(6)))
        except asyncio.CancelledError:
            raise
        except Exception:
            lost.set()

    async def may_start(self, run, lost):
        if lost.is_set() or self.stop.is_set():
            return False
        async with self.sessions() as session:
            current = await session.get(EvaluationRun, run.id)
            if current.claimed_by != run.claimed_by or current.status != "running":
                lost.set()
                return False
            return not current.cancel_requested

    async def checkpoint(
        self,
        run,
        case,
        index,
        *,
        actual,
        status,
        verdict,
        request_id,
        trace_id,
        latency,
        error_code=None,
    ):
        async with self.database.transaction() as session:
            await self.locked_run(session, run)
            existing = await session.scalar(
                select(EvaluationCaseResult).where(
                    EvaluationCaseResult.run_id == run.id,
                    EvaluationCaseResult.case_id == case["case_id"],
                    EvaluationCaseResult.repeat_index == index,
                )
            )
            if existing is not None:
                return existing
            row = EvaluationCaseResult(
                run_id=run.id,
                case_id=case["case_id"],
                repeat_index=index,
                expected_json=case,
                actual_json=actual,
                passed=False if status == "error" else None,
                error_type=error_code,
                error_message=verdict.get("reason") if error_code else None,
                request_id=request_id,
                trace_id=trace_id,
                latency_ms=latency,
                auto_status=status,
                verdict_json=verdict,
                review_json=[],
                review_revision=0,
            )
            session.add(row)
            await session.flush()
            return row

    async def finalize(self, run, row, status, verdict):
        async with self.database.transaction() as session:
            owned = await self.locked_run(session, run)
            current = await session.get(EvaluationCaseResult, row.id)
            if current.auto_status not in TERMINAL_RESULTS:
                current.auto_status = status
                current.verdict_json = verdict
                current.passed = (
                    True if status == "pass" else False if status in {"fail", "error"} else None
                )
                await session.flush()
            completed = await session.scalar(
                select(func.count())
                .select_from(EvaluationCaseResult)
                .where(
                    EvaluationCaseResult.run_id == run.id,
                    EvaluationCaseResult.auto_status.in_(TERMINAL_RESULTS),
                )
            )
            owned.progress_json = {"completed": completed}

    async def execute_case(
        self, run, case, index, factory, model_loader, judge_loader, judge_provider
    ):
        async with self.sessions() as session:
            row = await session.scalar(
                select(EvaluationCaseResult).where(
                    EvaluationCaseResult.run_id == run.id,
                    EvaluationCaseResult.case_id == case["case_id"],
                    EvaluationCaseResult.repeat_index == index,
                )
            )
        if row is not None and row.auto_status in TERMINAL_RESULTS:
            return
        if row is None:
            # Detect changed/revoked credentials before entering the runtime exception wrapper.
            await model_loader.load(run.managed_model_uid)
            sink = CapturingTraceStore(self.sessions)
            configuration = BusinessRuntimeConfiguration(
                snapshot=run.config_snapshot_json,
                release_id=run.release_id,
                config_snapshot_hash=run.config_snapshot_hash,
            )
            service = IntentService(
                FixedConfigurationLoader(configuration),
                factory,
                PromptBuilder(),
                sink,
                model_loader,
            )
            case_digest = hashlib.sha256(case["case_id"].encode()).hexdigest()[:12]
            request_id = f"eval_{run.id}_{case_digest}_{index}_{uuid4().hex}"
            started = time.perf_counter()
            try:
                output = await service.analyze(
                    text=case["question"],
                    context=case.get("context", {}),
                    request_id=request_id,
                    model_uid=run.managed_model_uid,
                    output_version=2,
                    execution_mode="evaluation",
                )
                actual = output.model_dump(mode="json")
                rules = evaluate_rules(case.get("expected"), actual)
                verdict = {
                    "rules": rules,
                    "reason": "等待标准答案评审",
                    "recognition_tokens": sum(
                        (attempt.usage or {}).get("total_tokens", 0) or 0
                        for attempt in sink.record.attempts
                    )
                    if sink.record
                    else None,
                }
                row = await self.checkpoint(
                    run,
                    case,
                    index,
                    actual=actual,
                    status="judging",
                    verdict=verdict,
                    request_id=request_id,
                    trace_id=sink.record.trace_id if sink.record else None,
                    latency=round((time.perf_counter() - started) * 1000),
                )
            except (ClaimLost, ConfigError):
                raise
            except Exception as error:
                # Database/checkpoint errors must not be disguised as completed model errors.
                if not isinstance(error, AppError):
                    raise
                code = error.code.value if hasattr(error.code, "value") else str(error.code)
                verdict = {"reason": error.message, "execution_error": code}
                row = await self.checkpoint(
                    run,
                    case,
                    index,
                    actual=None,
                    status="error",
                    verdict=verdict,
                    request_id=request_id,
                    trace_id=sink.record.trace_id if sink.record else None,
                    latency=round((time.perf_counter() - started) * 1000),
                    error_code=code,
                )
                await self.finalize(run, row, "error", verdict)
                return
        verdict = dict(row.verdict_json)
        if verdict["rules"]["issues"]:
            verdict["reason"] = "；".join(issue["message"] for issue in verdict["rules"]["issues"])
            await self.finalize(run, row, "fail", verdict)
            return
        if judge_provider is None:
            verdict["reason"] = "精确规则未发现错误；自然语言标准答案需要人工复核"
            await self.finalize(run, row, "review", verdict)
            return
        await judge_loader.load(None)
        snapshot = run.config_snapshot_json
        vocabulary = {
            "routes": [
                {"name": item["name"], "zh": item["zh"], "description": item["description"]}
                for item in snapshot["routes"]
                if item["enabled"]
            ],
            "intents": [
                {"name": item["name"], "zh": item["zh"], "route": item["route"]}
                for item in snapshot["intents"]
                if item["enabled"]
            ],
        }
        try:
            judged = await judge_result(
                judge_provider,
                system_prompt=run.evaluation_config_json["judge_prompt"],
                case=case,
                actual=row.actual_json,
                vocabulary=vocabulary,
            )
            verdict["judge"] = judged
            verdict["reason"] = judged["reason"]
            status = judged["verdict"]
        except Exception as error:
            verdict["judge_error"] = type(error).__name__
            verdict["reason"] = "评审调用失败或返回格式无效，请人工复核；本条不计为通过"
            if hasattr(error, "attempts"):
                verdict["judge_attempts"] = [
                    attempt.model_dump(mode="json") for attempt in error.attempts
                ]
            status = "review"
        await self.finalize(run, row, status, verdict)

    async def finish(self, run, *, error=None):
        async with self.database.transaction() as session:
            owned = await self.locked_run(session, run)
            completed = await session.scalar(
                select(func.count())
                .select_from(EvaluationCaseResult)
                .where(
                    EvaluationCaseResult.run_id == run.id,
                    EvaluationCaseResult.auto_status.in_(TERMINAL_RESULTS),
                )
            )
            owned.progress_json = {"completed": completed}
            if error:
                owned.status, owned.error = "failed", error
            elif completed == len(run.cases_json) * run.repeat_count:
                owned.status = "completed"
            elif owned.cancel_requested:
                owned.status = "cancelled"
            else:
                owned.status = "queued"
            owned.claimed_by = None
            owned.heartbeat_at = None
            if owned.status != "queued":
                owned.finished_at = now()

    async def execute_run(self, run):
        lost = asyncio.Event()
        heartbeat = asyncio.create_task(self.heartbeat(run, lost))
        factory = ModelProviderFactory(queue_wait_timeout=self.settings.provider_queue_wait_timeout)
        judge_provider = None
        consumers = []
        try:
            if run.evaluation_config_json["implementation_digest"] != implementation_digest():
                raise ConfigError(
                    "EVAL_CODE_CHANGED",
                    "识别或判定程序版本已变化，请创建新任务，避免混合不同版本的结果",
                )
            frozen = run.evaluation_config_json
            model_loader = FrozenModelLoader(self.sessions, self.cipher, frozen["model"])
            judge_loader = (
                FrozenModelLoader(self.sessions, self.cipher, frozen["judge"])
                if frozen["judge"]
                else None
            )
            if judge_loader:
                resolved = await judge_loader.load(None)
                judge_provider = JudgeProvider(
                    resolved.snapshot,
                    api_key=resolved.api_key,
                    queue_wait_timeout=self.settings.provider_queue_wait_timeout,
                )
            queue = asyncio.Queue()
            for case in run.cases_json:
                for index in range(run.repeat_count):
                    queue.put_nowait((case, index))

            async def consume():
                while not queue.empty() and await self.may_start(run, lost):
                    try:
                        case, index = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        return
                    await self.execute_case(
                        run, case, index, factory, model_loader, judge_loader, judge_provider
                    )

            limit = min(
                run.worker_concurrency,
                self.settings.eval_worker_concurrency,
                run.managed_model_snapshot_json["max_concurrency"],
            )
            if frozen["judge"]:
                limit = min(limit, frozen["judge"]["snapshot"]["max_concurrency"])
            consumers = [asyncio.create_task(consume()) for _ in range(limit)]
            await asyncio.gather(*consumers)
            if not lost.is_set():
                await self.finish(run)
        except ClaimLost:
            lost.set()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            lost.set()
            for consumer in consumers:
                consumer.cancel()
            await asyncio.gather(*consumers, return_exceptions=True)
            message = (
                error.message
                if isinstance(error, ConfigError)
                else "Worker 执行失败，已保留结果；请检查服务日志并创建复测任务"
            )
            logger.error("evaluation run %s stopped: %s", run.id, type(error).__name__)
            with suppress(ClaimLost):
                await self.finish(run, error=message)
        finally:
            for consumer in consumers:
                if not consumer.done():
                    consumer.cancel()
            await asyncio.gather(*consumers, return_exceptions=True)
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat
            if judge_provider is not None:
                await judge_provider.close()
            await factory.close()

    async def run_forever(self):
        while not self.stop.is_set():
            try:
                run = await self.claim()
                if run:
                    await self.execute_run(run)
                    continue
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.error("evaluation worker database/claim error: %s", type(error).__name__)
            with suppress(TimeoutError):
                await asyncio.wait_for(
                    self.stop.wait(), timeout=self.settings.eval_worker_poll_seconds
                )


async def main():
    settings = get_settings()
    configure_logging(settings.log_level)
    database = Database(settings)
    try:
        if not await DatabaseSchemaReadiness(database.engine)():
            raise RuntimeError("数据库尚未迁移到当前版本，评测 Worker 未启动")
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop.set)
            except NotImplementedError:
                signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))
        await EvaluationWorker(database, settings, stop).run_forever()
    finally:
        await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())
