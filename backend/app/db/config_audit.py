"""Read-only, rerunnable audit of immutable configuration identities.

Run with configuration writers stopped. MySQL DDL commits implicitly, so an
application transaction cannot protect the interval between this audit and DDL.
Only row IDs and failure categories are reported, never configuration/secrets.
"""

import asyncio
import json

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

from app.core.settings import get_settings
from app.db.database import Database
from app.schemas.config import business_snapshot


class ConfigAuditError(RuntimeError):
    pass


def audit_configuration(connection: Connection) -> dict[str, int]:
    errors: list[str] = []
    release_count = 0
    releases: set[int] = set()
    for row in connection.execute(text("SELECT * FROM config_release ORDER BY id")).mappings():
        release_count += 1
        try:
            snapshot = row["snapshot_json"]
            if isinstance(snapshot, str):
                snapshot = json.loads(snapshot)
            _, digest = business_snapshot(snapshot)
            if digest != row["config_snapshot_hash"]:
                raise ValueError("release identity mismatch")
            releases.add(row["id"])
        except (ValueError, TypeError):
            errors.append(f"config_release:{row['id']}:RELEASE_HASH_OR_PAYLOAD")
    for row in connection.execute(
        text("SELECT id, active_release_id FROM runtime_state")
    ).mappings():
        active = row["active_release_id"]
        if active is not None and active not in releases:
            errors.append(f"runtime_state:{row['id']}:ACTIVE_REFERENCE")
    if errors:
        raise ConfigAuditError("CONFIG_AUDIT_FAILED " + ";".join(errors))
    return {"releases": release_count}


def audit_existing_configuration(connection: Connection) -> None:
    tables = set(inspect(connection).get_table_names())
    # Revisions through 0004 still contain the legacy ModelConfig-bound history.
    # Revision 0005 intentionally deletes that history, so legacy hashes must not
    # block the approved cleanup migration.
    if "model_config" in tables:
        return
    required = {"config_release", "runtime_state"}
    if required <= tables:
        audit_configuration(connection)
    elif required & tables or (
        "alembic_version" in tables
        and connection.scalar(text("SELECT COUNT(*) FROM alembic_version"))
    ):
        raise ConfigAuditError("CONFIG_AUDIT_FAILED missing configuration tables")


async def main() -> None:
    database = Database(get_settings())
    try:
        async with database.engine.connect() as connection:
            result = await connection.run_sync(audit_configuration)
        print(json.dumps({"status": "PASS", **result}))
    finally:
        await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())
