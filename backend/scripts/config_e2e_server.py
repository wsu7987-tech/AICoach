"""Reset a dedicated TASK-201 test database and serve the real API for Playwright.

Never point this at a production resource. The destructive reset requires the
explicit CONFIG_E2E_DATABASE_URL and ai_coach_task201_test_* database prefix.
"""

import asyncio
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import uvicorn
from sqlalchemy.engine import make_url

from app.core.settings import Settings
from app.db.base import Base
from app.db.database import Database
from app.db.models import ConfigDraft  # registers all metadata


class LocalQwenHandler(BaseHTTPRequestHandler):
    """Deterministic OpenAI-compatible localhost provider for browser acceptance."""

    request_no = 0
    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:  # noqa: N802 - stdlib callback
        type(self).request_no += 1
        number = type(self).request_no
        content = json.dumps(
            {
                "route": "training_business",
                "intents": [],
                "slots": [],
                "risk": None,
                "need_clarification": False,
                "clarification": None,
                "reason_summary": f"localhost response {number}",
                "evidence": [],
            }
        )
        body = json.dumps(
            {
                "id": f"chatcmpl-local-{number}",
                "object": "chat.completion",
                "model": "qwen-local",
                "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
                "system_fingerprint": f"local-{number}",
            }
        ).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.send_header("connection", "close")
        self.send_header("x-request-id", f"local-request-{number}")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


def start_local_provider() -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", 8011), LocalQwenHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


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
    os.environ["DASHSCOPE_API_KEY"] = "e2e-localhost-only"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"], capture_output=True, check=False
    )
    if result.returncode:
        raise SystemExit("test migration failed")
    asyncio.run(reset_database(value))
    provider = start_local_provider()
    try:
        uvicorn.run("app.main:app", host="127.0.0.1", port=8000, log_level="warning")
    finally:
        provider.shutdown()
        provider.server_close()
