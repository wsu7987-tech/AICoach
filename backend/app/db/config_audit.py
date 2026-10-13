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
from app.schemas.config import (
    MODEL_RUNTIME_FIELDS,
    ModelConfigCreate,
    business_snapshot,
    model_hash,
    release_fingerprint,
)


class ConfigAuditError(RuntimeError):
    pass


def audit_configuration(connection: Connection) -> dict[str, int]:
    errors: list[str] = []
    models: dict[int, tuple[str, bool]] = {}
    model_count = release_count = 0
    for row in connection.execute(text("SELECT * FROM model_config ORDER BY id")).mappings():
        model_count += 1
        try:
            fields = {key: row[key] for key in MODEL_RUNTIME_FIELDS}
            if isinstance(fields["params_json"], str):
                fields["params_json"] = json.loads(fields["params_json"])
            config = ModelConfigCreate(name=row["name"], version=row["version"], **fields)
            digest = model_hash(config)
            if digest != row["model_config_hash"]:
                raise ValueError("hash mismatch")
            models[row["id"]] = (digest, bool(row["enabled"]))
        except (ValueError, TypeError):
            errors.append(f"model_config:{row['id']}:MODEL_HASH_OR_PAYLOAD")
    releases: dict[int, int] = {}
    for row in connection.execute(text("SELECT * FROM config_release ORDER BY id")).mappings():
        release_count += 1
        model_id = row["default_model_config_id"]
        try:
            snapshot = row["snapshot_json"]
            if isinstance(snapshot, str):
                snapshot = json.loads(snapshot)
            _, digest = business_snapshot(snapshot)
            model = models.get(model_id)
            if (
                model is None
                or model[0] != row["model_config_hash"]
                or digest != row["config_snapshot_hash"]
                or release_fingerprint(digest, model_id, model[0]) != row["release_fingerprint"]
            ):
                raise ValueError("release identity mismatch")
            releases[row["id"]] = model_id
        except (ValueError, TypeError):
            errors.append(f"config_release:{row['id']}:RELEASE_HASH_OR_REFERENCE")
    for row in connection.execute(
        text("SELECT id, active_release_id FROM runtime_state")
    ).mappings():
        active = row["active_release_id"]
        if active is not None and (active not in releases or not models[releases[active]][1]):
            errors.append(f"runtime_state:{row['id']}:ACTIVE_REFERENCE")
    if errors:
        raise ConfigAuditError("CONFIG_AUDIT_FAILED " + ";".join(errors))
    return {"models": model_count, "releases": release_count}


def audit_existing_configuration(connection: Connection) -> None:
    tables = set(inspect(connection).get_table_names())
    required = {"model_config", "config_release", "runtime_state"}
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
