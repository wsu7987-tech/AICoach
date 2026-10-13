"""Real MySQL legacy FLOAT corruption must stop before any upgrade DDL."""

import asyncio
import json
import os
import subprocess
import sys

import pytest
from sqlalchemy import text

from app.core.settings import Settings
from app.db.config_audit import audit_configuration
from app.db.database import Database
from app.schemas.config import ModelConfigCreate, business_snapshot, model_hash, release_fingerprint
from app.services import config_service
from tests.test_config_contract import document, model_input
from tests.test_config_mysql import mysql_url as mysql_url
from tests.test_config_mysql import reviewed_request


def migrate(url, *args):
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        env={**os.environ, "DATABASE_URL": url},
        capture_output=True,
        check=False,
    )


@pytest.mark.parametrize("timeout", [30.123456789, 0.123456789, 599.9999999])
def test_legacy_active_model_hash_loss_stops_before_ddl(mysql_url, timeout):
    assert migrate(mysql_url, "downgrade", "0002_release_fp_index").returncode == 0

    async def seed():
        db = Database(Settings(_env_file=None, database_url=mysql_url))
        try:
            async with db.transaction() as s:
                config = ModelConfigCreate(**model_input(timeout_seconds=timeout))
                values = config.model_dump(mode="json")
                values["params_json"] = json.dumps(values["params_json"])
                values["digest"] = model_hash(config)
                await s.execute(
                    text(
                        "INSERT INTO model_config (id,name,version,provider,model,base_url,"
                        "params_json,timeout_seconds,max_retries,max_concurrency,"
                        "structured_output_mode,credential_ref,model_config_hash,"
                        "enabled,created_at) "
                        "VALUES (1,:name,:version,:provider,:model,:base_url,:params_json,"
                        ":timeout_seconds,:max_retries,:max_concurrency,:structured_output_mode,"
                        ":credential_ref,:digest,1,NOW())"
                    ),
                    values,
                )
                snapshot, digest = business_snapshot(document())
                await s.execute(
                    text(
                        "INSERT INTO config_release (id,version,snapshot_json,config_snapshot_hash,"
                        "default_model_config_id,model_config_hash,release_fingerprint,note,"
                        "created_by,created_at) VALUES (1,'legacy',:snapshot,:digest,1,"
                        ":model_hash,:fingerprint,'legacy','test',NOW())"
                    ),
                    {
                        "snapshot": json.dumps(snapshot),
                        "digest": digest,
                        "model_hash": values["digest"],
                        "fingerprint": release_fingerprint(digest, 1, values["digest"]),
                    },
                )
                await s.execute(
                    text(
                        "INSERT INTO runtime_state (id,active_release_id,updated_at) "
                        "VALUES (1,1,NOW())"
                    )
                )
        finally:
            await db.dispose()

    async def inspect_and_cleanup():
        db = Database(Settings(_env_file=None, database_url=mysql_url))
        try:
            async with db.transaction() as s:
                version = await s.scalar(text("SELECT version_num FROM alembic_version"))
                columns = (await s.execute(text("SHOW COLUMNS FROM model_config"))).all()
                # Only destructive fixture cleanup in explicitly isolated test DB.
                await s.execute(text("DELETE FROM runtime_state"))
                await s.execute(text("DELETE FROM config_release"))
                await s.execute(text("DELETE FROM model_config"))
                return version, {row[0]: row[1] for row in columns}
        finally:
            await db.dispose()

    asyncio.run(seed())
    result = migrate(mysql_url, "upgrade", "head")
    repeated = migrate(mysql_url, "upgrade", "head")
    version, columns = asyncio.run(inspect_and_cleanup())
    assert result.returncode != 0, "corrupt legacy hash incorrectly upgraded to head"
    assert b"CONFIG_AUDIT_FAILED" in result.stderr
    assert repeated.returncode != 0 and b"CONFIG_AUDIT_FAILED" in repeated.stderr
    assert version == "0002_release_fp_index"
    assert columns["timeout_seconds"] == "float"
    assert "timeout_seconds_upgrade" not in columns


@pytest.mark.parametrize(
    "corruption", ["model", "business", "release_model", "fingerprint", "reference", "active"]
)
def test_already_head_audit_is_rerunnable_read_only_and_fail_closed(mysql_url, corruption):
    async def seed_and_corrupt():
        db = Database(Settings(_env_file=None, database_url=mysql_url))
        try:
            async with db.transaction() as s:
                await config_service.save_draft(s, document(), None)
                model = await config_service.create_model(s, ModelConfigCreate(**model_input()))
                await config_service.publish(s, await reviewed_request(s, model.id))
            async with db.engine.begin() as conn:
                assert await conn.run_sync(audit_configuration) == {"models": 1, "releases": 1}
                sql = {
                    "model": "UPDATE model_config SET timeout_seconds=30.1235",
                    "business": "UPDATE config_release SET config_snapshot_hash=REPEAT('0',64)",
                    "release_model": "UPDATE config_release SET model_config_hash=REPEAT('0',64)",
                    "fingerprint": "UPDATE config_release SET release_fingerprint=REPEAT('0',64)",
                    "reference": "UPDATE config_release SET default_model_config_id=999999",
                    "active": "UPDATE runtime_state SET active_release_id=999999",
                }[corruption]
                # Corruption fixture only; restore connection-local constraint checks.
                await conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
                try:
                    await conn.execute(text(sql))
                finally:
                    await conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))
        finally:
            await db.dispose()

    async def rows():
        db = Database(Settings(_env_file=None, database_url=mysql_url))
        try:
            async with db.engine.connect() as conn:
                return {
                    name: (await conn.execute(text(f"SELECT * FROM {name} ORDER BY 1"))).all()
                    for name in (
                        "model_config",
                        "config_release",
                        "runtime_state",
                        "alembic_version",
                    )
                }
        finally:
            await db.dispose()

    asyncio.run(seed_and_corrupt())
    before = asyncio.run(rows())
    for _ in range(2):
        result = migrate(mysql_url, "upgrade", "head")
        assert result.returncode != 0 and b"CONFIG_AUDIT_FAILED" in result.stderr
        assert asyncio.run(rows()) == before
    command = subprocess.run(
        [sys.executable, "-m", "app.db.config_audit"],
        env={**os.environ, "DATABASE_URL": mysql_url},
        capture_output=True,
        check=False,
    )
    assert command.returncode != 0 and b"CONFIG_AUDIT_FAILED" in command.stderr
    assert asyncio.run(rows()) == before


def test_migration_reentry_after_atomic_swap_before_head(mysql_url):
    assert migrate(mysql_url, "downgrade", "0002_release_fp_index").returncode == 0

    async def partial_swap():
        db = Database(Settings(_env_file=None, database_url=mysql_url))
        try:
            async with db.transaction() as s:
                model = await config_service.create_model(
                    s, ModelConfigCreate(**model_input(timeout_seconds=30.1))
                )
            async with db.engine.begin() as conn:
                await conn.execute(
                    text("ALTER TABLE model_config ADD COLUMN timeout_seconds_upgrade DOUBLE")
                )
                await conn.execute(
                    text(
                        "UPDATE model_config SET "
                        "timeout_seconds_upgrade=CAST(timeout_seconds AS CHAR)"
                    )
                )
                await conn.execute(
                    text(
                        "ALTER TABLE model_config DROP COLUMN timeout_seconds, "
                        "CHANGE COLUMN timeout_seconds_upgrade timeout_seconds DOUBLE NOT NULL"
                    )
                )
            return model.model_config_hash
        finally:
            await db.dispose()

    digest = asyncio.run(partial_swap())
    assert migrate(mysql_url, "upgrade", "head").returncode == 0
    assert migrate(mysql_url, "upgrade", "head").returncode == 0

    async def verify():
        db = Database(Settings(_env_file=None, database_url=mysql_url))
        try:
            async with db.engine.connect() as conn:
                assert (
                    await conn.scalar(text("SELECT model_config_hash FROM model_config")) == digest
                )
                assert await conn.scalar(text("SELECT timeout_seconds FROM model_config")) == 30.1
                assert (
                    await conn.scalar(text("SELECT version_num FROM alembic_version"))
                    == "0003_model_timeout_double"
                )
                assert await conn.run_sync(audit_configuration) == {"models": 1, "releases": 0}
        finally:
            await db.dispose()

    asyncio.run(verify())


def test_head_audit_refuses_missing_configuration_table(mysql_url):
    async def rename(source, target):
        db = Database(Settings(_env_file=None, database_url=mysql_url))
        try:
            async with db.engine.begin() as conn:
                await conn.execute(text(f"RENAME TABLE {source} TO {target}"))
        finally:
            await db.dispose()

    asyncio.run(rename("runtime_state", "runtime_state_audit_test"))
    try:
        result = migrate(mysql_url, "upgrade", "head")
        assert result.returncode != 0 and b"CONFIG_AUDIT_FAILED" in result.stderr
    finally:
        asyncio.run(rename("runtime_state_audit_test", "runtime_state"))
    assert migrate(mysql_url, "upgrade", "head").returncode == 0


def test_offline_0003_cannot_bypass_data_audit(mysql_url):
    result = migrate(mysql_url, "upgrade", "0002_release_fp_index:head", "--sql")
    assert result.returncode != 0
    assert b"requires an online CONFIG_AUDIT" in result.stderr
    assert b"ALTER TABLE" not in result.stdout
