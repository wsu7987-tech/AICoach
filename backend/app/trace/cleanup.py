"""Delete expired Trace records without deleting Evaluation case results.

Run as ``python -m app.trace.cleanup`` from the backend deployment/CronJob.
"""

from __future__ import annotations

import asyncio

from app.core.settings import get_settings
from app.db.database import Database
from app.services.trace_store import cleanup_expired_traces


async def _run() -> int:
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL must be configured")
    if settings.eval_trace_retention_days < settings.trace_retention_days:
        raise RuntimeError("EVAL_TRACE_RETENTION_DAYS must be >= TRACE_RETENTION_DAYS")
    database = Database(settings)
    try:
        deleted = await cleanup_expired_traces(
            database.session_factory,
            trace_retention_days=settings.trace_retention_days,
            eval_trace_retention_days=settings.eval_trace_retention_days,
        )
    finally:
        await database.dispose()
    print(f"deleted_traces={deleted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run()))
