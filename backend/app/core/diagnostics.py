"""Sanitize diagnostic copies only; never use these values for business validation."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from app.core.settings import get_settings

ERROR_SUMMARY_MAX_BYTES = 4096
TRUNCATED = "...[truncated=true]"
_SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "apikey",
        "secret",
        "token",
        "password",
        "dbpassword",
        "accesstoken",
        "refreshtoken",
        "clientsecret",
    }
)
_LABEL = r"authorization|api[\s_-]*key|secret|token|(?:db[\s_-]?)?password"
_SECRET = re.compile(
    rf"(?ix)\b(?P<label>{_LABEL})\b(?P<join>['\"]?\s*(?:is\b|=|:)\s*)"
    r"(?P<value>\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|"
    r"(?:bearer\s+)?(?:\[REDACTED\]|[^\s,;\}\]\"']+))"
)
_BEARER = re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]+")


def _redact(match: re.Match[str]) -> str:
    value = match["value"]
    quote = value[0] if value.startswith(('"', "'")) else ""
    bearer = "Bearer " if value.lower().startswith("bearer ") else ""
    return f"{match['label']}{match['join']}{quote}{bearer}[REDACTED]{quote}"


def sanitize(value: Any) -> Any:
    """Recursive, idempotent key/prose/JSON/repr redaction of known credential forms."""
    if isinstance(value, Mapping):
        return {
            sanitize(str(key)): "[REDACTED]"
            if re.sub(r"[\s_-]", "", str(key).lower()) in _SENSITIVE_KEYS
            else sanitize(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, RecursionError):
            parsed = None
        if isinstance(parsed, (dict, list)):
            return json.dumps(sanitize(parsed), ensure_ascii=False, separators=(",", ":"))
        return _BEARER.sub("Bearer [REDACTED]", _SECRET.sub(_redact, value))
    return value


def diagnostic_text(value: str, limit: int | None = None) -> str:
    limit = limit if limit is not None else get_settings().trace_raw_max_bytes
    clean = sanitize(value)
    encoded = clean.encode("utf-8", errors="replace")
    if len(encoded) <= limit:
        return encoded.decode("utf-8")
    return encoded[: limit - len(TRUNCATED)].decode("utf-8", errors="ignore") + TRUNCATED


def error_summary(value: str) -> str:
    return diagnostic_text(value, ERROR_SUMMARY_MAX_BYTES)


def diagnostic_payload(value: dict[str, Any]) -> dict[str, Any]:
    """Bound the entire JSON segment, including its UTF-8 preview envelope."""
    clean = sanitize(value)
    limit = get_settings().trace_raw_max_bytes
    encoded = json.dumps(clean, ensure_ascii=False).encode("utf-8", errors="replace")
    if len(encoded) <= limit:
        return clean
    # Escaping the preview can expand it. Binary search counts the actual serialized
    # envelope, rather than assuming one character equals one byte.
    preview = encoded[:limit].decode("utf-8", errors="ignore")
    low, high = 0, len(preview)
    while low < high:
        middle = (low + high + 1) // 2
        candidate = {"truncated": True, "preview": preview[:middle]}
        if len(json.dumps(candidate, ensure_ascii=False).encode("utf-8")) <= limit:
            low = middle
        else:
            high = middle - 1
    return {"truncated": True, "preview": preview[:low]}


def bounded_validation_issues(value: Any) -> list[dict[str, Any]]:
    """Make the persisted validation diagnostic a bounded UTF-8 representation.

    This deliberately operates on the diagnostic copy only.  In particular it
    never changes the SlotValue used by business validation or the model request.
    The issue code is retained even when its nested slot needs truncation.
    """

    clean = sanitize(value)
    if not isinstance(clean, list):
        return []
    limit = get_settings().trace_raw_max_bytes
    result: list[dict[str, Any]] = []
    for raw_issue in clean:
        if hasattr(raw_issue, "model_dump"):
            raw_issue = raw_issue.model_dump(mode="json")
        if not isinstance(raw_issue, Mapping):
            continue
        issue = dict(raw_issue)
        slot = issue.get("slot")
        if isinstance(slot, Mapping) and isinstance(slot.get("value"), str):
            # Leave enough room for the issue envelope and other slot fields.
            issue["slot"] = dict(slot)
            issue["slot"]["value"] = diagnostic_text(slot["value"], max(256, limit // 2))
            if issue["slot"]["value"] != slot["value"]:
                issue["truncated"] = True
        candidate = [*result, issue]
        if len(json.dumps(candidate, ensure_ascii=False).encode("utf-8")) <= limit:
            result.append(issue)
            continue
        # Preserve the code even if the full slot envelope cannot fit.
        minimal = {"code": issue.get("code", "SLOT_SPAN_INVALID"), "truncated": True}
        if len(json.dumps([*result, minimal], ensure_ascii=False).encode("utf-8")) <= limit:
            result.append(minimal)
        break
    return result
