from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from app.bootstrap.service import (
    BootstrapConflictError,
    BootstrapValidationError,
    import_bootstrap_draft,
    parse_bootstrap_json,
)
from app.core.settings import get_settings
from app.db.database import Database


async def _run(file_path: Path, updated_by: str) -> tuple[int, str]:
    try:
        payload = parse_bootstrap_json(file_path.read_text(encoding="utf-8"))
    except OSError as exc:
        return 2, f"bootstrap file error: {exc}"
    except BootstrapValidationError as exc:
        return 2, f"bootstrap validation failed: {exc}"

    try:
        database = Database(get_settings())
    except ValueError as exc:
        return 2, f"database configuration error: {exc}"
    try:
        async with database.transaction() as session:
            result = await import_bootstrap_draft(session, payload, updated_by)
        action = "created" if result.created else "already current"
        return 0, f"bootstrap draft {action}: id={result.draft_id}"
    except BootstrapConflictError as exc:
        return 3, f"bootstrap conflict: {exc}"
    finally:
        await database.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="Import the initial AI Coach Draft only")
    parser.add_argument("--file", type=Path, required=True, help="bootstrap JSON file")
    parser.add_argument("--updated-by", default="bootstrap")
    args = parser.parse_args()
    code, message = asyncio.run(_run(args.file, args.updated_by))
    print(message, file=sys.stderr if code else sys.stdout)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
