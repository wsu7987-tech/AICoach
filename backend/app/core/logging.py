import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from app.core.diagnostics import diagnostic_text, sanitize
from app.core.request_context import get_request_id


class JsonFormatter(logging.Formatter):
    """Small JSON formatter that avoids logging request payloads by default."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": diagnostic_text(record.getMessage()),
        }
        request_id = get_request_id()
        if request_id:
            payload["request_id"] = request_id
        for key in ("method", "path", "status_code", "duration_ms"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = diagnostic_text(self.formatException(record.exc_info))
        return json.dumps(sanitize(payload), ensure_ascii=False, default=str)


def configure_logging(level: str) -> None:
    root_logger = logging.getLogger()
    root_logger.setLevel(level.upper())

    if not root_logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        root_logger.addHandler(handler)
        return

    for handler in root_logger.handlers:
        if isinstance(handler, logging.StreamHandler):
            handler.setFormatter(JsonFormatter())
