"""Reset a dedicated TASK-201 test database and serve the real API for Playwright.

Never point this at a production resource. The destructive reset requires the
explicit CONFIG_E2E_DATABASE_URL and ai_coach_task201_test_* database prefix.
"""

import asyncio
import os
import subprocess
import sys

import uvicorn
from sqlalchemy.engine import make_url

from app.core.settings import Settings
from app.db.base import Base
from app.db.database import Database
from app.db.models import ConfigDraft  # registers all metadata


async def reset_database(url: str) -> None:
    assert ConfigDraft.__table__ in Base.metadata.sorted_tables
    database = Database(Settings(_env_file=None, database_url=url))
    try:
        async with database.transaction() as session:
            for table in reversed(Base.metadata.sorted_tables):
                await session.execute(table.delete())
    finally:
        await database.dispose()


if __name__ == "__main__":
    value = os.environ.get("CONFIG_E2E_DATABASE_URL", "")
    parsed = make_url(value)
    if (
        parsed.drivername != "mysql+asyncmy"
        or not parsed.database
        or not parsed.database.startswith("ai_coach_task201_test_")
    ):
        raise SystemExit("CONFIG_E2E_DATABASE_URL must name an isolated ai_coach_task201_test_* DB")
    os.environ["DATABASE_URL"] = value
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"], capture_output=True, check=False
    )
    if result.returncode:
        raise SystemExit("test migration failed")
    asyncio.run(reset_database(value))
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, log_level="warning")
