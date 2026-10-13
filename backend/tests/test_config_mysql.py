"""Real MySQL 8 acceptance; never substitute SQLite or mocks for transactions."""

import asyncio
import copy
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from sqlalchemy import event, func, select, text
from sqlalchemy.engine import make_url

from app.core.settings import Settings
from app.db.base import Base
from app.db.database import Database
from app.db.models import ConfigDraft, ConfigRelease, ModelConfig, RuntimeState
from app.main import create_app
from app.schemas.config import ModelConfigCreate, PublishInput
from app.services import config_service as service
from app.services.intent_service import RuntimeConfiguration
from tests.test_config_contract import document, model_input


@pytest.fixture
def mysql_url():
    value = os.getenv("MYSQL_CONFIG_TEST_DATABASE_URL")
    if not value:
        pytest.skip(
            "MYSQL_CONFIG_TEST_DATABASE_URL not configured; TASK-201 MySQL acceptance BLOCKED"
        )
    url = make_url(value)
    assert url.drivername == "mysql+asyncmy"
    assert url.database and url.database.startswith("ai_coach_task201_test_")
    # Dedicated prefix is mandatory: this fixture resets only the explicit test database.
    for args in (("upgrade", "head"),):
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            check=False,
            cwd=Path(__file__).resolve().parents[1],
            env={**os.environ, "DATABASE_URL": value},
            capture_output=True,
        )
        assert result.returncode == 0, "isolated test migration failed"

    async def clear():
        db = Database(Settings(_env_file=None, database_url=value))
        try:
            async with db.transaction() as session:
                for table in reversed(Base.metadata.sorted_tables):
                    await session.execute(table.delete())
        finally:
            await db.dispose()

    asyncio.run(clear())
    return value


def test_mysql_publish_atomicity_c7_c9_and_rollback(mysql_url):
    async def scenario():
        db = Database(Settings(_env_file=None, database_url=mysql_url))
        try:
            async with db.engine.connect() as conn:
                assert (await conn.scalar(text("SELECT VERSION()"))).startswith("8.")
            async with db.transaction() as s:
                draft = await service.save_draft(s, document(), None)
                model = await service.create_model(s, ModelConfigCreate(**model_input()))
            request = PublishInput(default_model_config_id=model.id, note="first")
            async with db.transaction() as s:
                first = await service.publish(s, request)
            async with db.transaction() as s:
                second = await service.publish(s, request)
            assert first["id"] != second["id"]
            for key in ("config_snapshot_hash", "model_config_hash", "release_fingerprint"):
                assert first[key] == second[key]
            assert first["version"] != second["version"]
            changed = document()
            changed["intents"].append(
                {
                    "name": "new_intent",
                    "zh": "新增意图",
                    "enabled": True,
                    "route": "social_chat",
                    "description": "动态新增",
                    "aliases": ["新别名"],
                }
            )
            changed["examples"].append(
                {"text": "新表达", "route": "social_chat", "intent": "new_intent"}
            )
            changed["enums"]["body_part"].append(
                {"canonical": "new_part", "display": "新部位", "aliases": ["新部位别名"]}
            )
            async with db.transaction() as s:
                edited = await service.save_draft(s, changed, draft["draft_hash"])
                assert (await service.release_configuration(s, first["id"]))[
                    "snapshot_json"
                ] == first["snapshot_json"]
                await service.validate_draft(s)
                preview = await service.preview_prompt(s, "新表达", {})
                assert "new_intent" in preview.final_prompt
            async with db.transaction() as s:
                third = await service.publish(s, request)
                assert third["config_snapshot_hash"] != first["config_snapshot_hash"]

            # Failure after the INSERT and pointer UPDATE really hit MySQL must roll both back.
            def fail_on_pointer(conn, cursor, statement, params, context, many):
                if statement.startswith("UPDATE runtime_state SET"):
                    raise RuntimeError("injected after pointer SQL")

            event.listen(db.engine.sync_engine, "after_cursor_execute", fail_on_pointer)
            try:
                with pytest.raises(RuntimeError, match="injected"):
                    async with db.transaction() as s:
                        await service.publish(s, request)
            finally:
                event.remove(db.engine.sync_engine, "after_cursor_execute", fail_on_pointer)
            async with db.transaction() as s:
                assert await s.scalar(select(func.count(ConfigRelease.id))) == 3
                assert (await s.get(RuntimeState, 1)).active_release_id == third["id"]
                restored = await service.restore_draft(s, first["id"], edited["draft_hash"])
                assert restored["draft_json"] == first["snapshot_json"]
                assert (await s.get(RuntimeState, 1)).active_release_id == third["id"]
            async with db.transaction() as s:
                rollback = await service.publish(s, request)
                assert rollback["release_fingerprint"] == first["release_fingerprint"]
                assert rollback["id"] not in {first["id"], second["id"], third["id"]}

            # Simulate corruption after construction/persistence. Publish reparses the dict.
            async with db.transaction() as s:
                row = await s.get(ConfigDraft, 1)
                corrupted = copy.deepcopy(row.draft_json)
                corrupted["routes"].pop()
                row.draft_json = corrupted
            with pytest.raises(service.ConfigError, match="校验"):
                async with db.transaction() as s:
                    await service.publish(s, request)
            async with db.transaction() as s:
                assert (await s.get(RuntimeState, 1)).active_release_id == rollback["id"]
                assert await s.scalar(select(func.count(ConfigRelease.id))) == 4
        finally:
            await db.dispose()

    asyncio.run(scenario())


def test_mysql_concurrent_first_publish_and_disable(mysql_url):
    async def scenario():
        db = Database(Settings(_env_file=None, database_url=mysql_url))
        try:
            async with db.transaction() as s:
                await service.save_draft(s, document(), None)
                model = await service.create_model(s, ModelConfigCreate(**model_input()))
                # First runtime-state creation is also tested under concurrency below.
                await s.execute(text("DELETE FROM runtime_state"))

            async def publish_one():
                async with db.transaction() as s:
                    return await service.publish(
                        s, PublishInput(default_model_config_id=model.id, note="concurrent")
                    )

            releases = await asyncio.gather(*(publish_one() for _ in range(8)))
            ids = {row["id"] for row in releases}
            assert len(ids) == 8
            assert len({row["version"] for row in releases}) == 8
            assert len({row["release_fingerprint"] for row in releases}) == 1
            async with db.transaction() as s:
                assert (await s.get(RuntimeState, 1)).active_release_id == max(ids)
                assert await s.scalar(select(func.count(ConfigRelease.id))) == 8
            with pytest.raises(service.ConfigError, match="Active Release"):
                async with db.transaction() as s:
                    await service.disable_model(s, model.id)
            async with db.transaction() as s:
                other = await service.create_model(s, ModelConfigCreate(**model_input(version="2")))

            async def disable_other():
                try:
                    async with db.transaction() as s:
                        await service.disable_model(s, other.id)
                    return "disabled"
                except service.ConfigError:
                    return "active"

            async def publish_other():
                try:
                    async with db.transaction() as s:
                        await service.publish(
                            s, PublishInput(default_model_config_id=other.id, note="race")
                        )
                    return "published"
                except service.ConfigError:
                    return "disabled"

            await asyncio.gather(disable_other(), publish_other())
            async with db.transaction() as s:
                state = await s.get(RuntimeState, 1)
                active = await s.get(ConfigRelease, state.active_release_id)
                assert (await s.get(ModelConfig, active.default_model_config_id)).enabled
        finally:
            await db.dispose()

    asyncio.run(scenario())


def test_mysql_immutable_records(mysql_url):
    async def scenario():
        db = Database(Settings(_env_file=None, database_url=mysql_url))
        try:
            async with db.transaction() as s:
                await service.save_draft(s, document(), None)
                model = await service.create_model(s, ModelConfigCreate(**model_input()))
                first = await service.publish(
                    s, PublishInput(default_model_config_id=model.id, note="freeze")
                )
            with pytest.raises(ValueError, match="immutable"):
                async with db.transaction() as s:
                    row = await s.get(ModelConfig, model.id)
                    row.model = "changed"
            with pytest.raises(ValueError, match="immutable"):
                async with db.transaction() as s:
                    row = await s.get(ConfigRelease, first["id"])
                    row.snapshot_json = {}
            async with db.transaction() as s:
                other = await service.create_model(s, ModelConfigCreate(**model_input(version="2")))
                await service.publish(
                    s, PublishInput(default_model_config_id=other.id, note="replace")
                )
                disabled = await service.disable_model(s, model.id)
                assert not disabled.enabled
                historical = await service.release_configuration(s, first["id"])
                inputs = RuntimeConfiguration(
                    snapshot=historical["snapshot_json"],
                    model_config_snapshot=historical["model_config_snapshot"],
                )
                assert inputs.model_config_snapshot.id == model.id
                assert not inputs.model_config_snapshot.enabled
                assert (
                    historical["model_config_snapshot"]["model_config_hash"]
                    == model.model_config_hash
                )
            with pytest.raises(service.ConfigError, match="禁用"):
                async with db.transaction() as s:
                    await service.publish(
                        s, PublishInput(default_model_config_id=model.id, note="invalid")
                    )
        finally:
            await db.dispose()

    asyncio.run(scenario())


def test_mysql_concurrent_edit_and_model_version_conflicts(mysql_url):
    async def scenario():
        db = Database(Settings(_env_file=None, database_url=mysql_url))
        try:
            async with db.transaction() as s:
                draft = await service.save_draft(s, document(), None)

            async def edit(label):
                changed = document()
                changed["prompt_template"]["system"] = label
                try:
                    async with db.transaction() as s:
                        await service.save_draft(s, changed, draft["draft_hash"])
                    return "saved"
                except service.ConfigError as error:
                    return error.code

            assert sorted(await asyncio.gather(edit("one"), edit("two"))) == [
                "DRAFT_CONFLICT",
                "saved",
            ]

            async def create():
                try:
                    async with db.transaction() as s:
                        await service.create_model(s, ModelConfigCreate(**model_input()))
                    return "created"
                except service.ConfigError as error:
                    return error.code

            assert sorted(await asyncio.gather(create(), create())) == [
                "MODEL_VERSION_CONFLICT",
                "created",
            ]
            async with db.transaction() as s:
                assert await s.scalar(select(func.count(ModelConfig.id))) == 1
                assert await s.scalar(select(func.count(ConfigRelease.id))) == 0
        finally:
            await db.dispose()

    asyncio.run(scenario())


def test_mysql_corrupt_model_hash_cannot_activate_release(mysql_url):
    async def scenario():
        db = Database(Settings(_env_file=None, database_url=mysql_url))
        try:
            async with db.transaction() as s:
                await service.save_draft(s, document(), None)
                model = await service.create_model(s, ModelConfigCreate(**model_input()))
            # Deliberately bypass application guards to simulate DB corruption.
            async with db.transaction() as s:
                await s.execute(
                    text("UPDATE model_config SET model_config_hash=:hash WHERE id=:id"),
                    {"hash": "0" * 64, "id": model.id},
                )
            with pytest.raises(service.ConfigError, match="Hash"):
                async with db.transaction() as s:
                    await service.publish(
                        s, PublishInput(default_model_config_id=model.id, note="corrupt")
                    )
            async with db.transaction() as s:
                assert await s.scalar(select(func.count(ConfigRelease.id))) == 0
                assert (await s.get(RuntimeState, 1)).active_release_id is None
        finally:
            await db.dispose()

    asyncio.run(scenario())


def test_mysql_fractional_timeout_preserves_immutable_hash(mysql_url):
    async def scenario():
        db = Database(Settings(_env_file=None, database_url=mysql_url))
        try:
            async with db.transaction() as s:
                created = await service.create_model(
                    s, ModelConfigCreate(**model_input(timeout_seconds=30.123456789))
                )
            async with db.transaction() as s:
                stored = service.effective_model_snapshot(await s.get(ModelConfig, created.id))
                assert stored.timeout_seconds == 30.123456789
                assert stored.model_config_hash == created.model_config_hash
        finally:
            await db.dispose()

    asyncio.run(scenario())
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "0002_release_fp_index"],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "DATABASE_URL": mysql_url},
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert b"cannot narrow model timeout" in result.stderr


def test_mysql_timeout_migration_preserves_existing_hash_and_recovers(mysql_url):
    def migrate(*args):
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=Path(__file__).resolve().parents[1],
            env={**os.environ, "DATABASE_URL": mysql_url},
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, "test migration failed"

    migrate("downgrade", "0002_release_fp_index")

    async def legacy_row():
        db = Database(Settings(_env_file=None, database_url=mysql_url))
        try:
            async with db.transaction() as s:
                model = await service.create_model(
                    s, ModelConfigCreate(**model_input(timeout_seconds=30.1))
                )
            # Simulate interruption after the new nullable column was added.
            async with db.engine.begin() as conn:
                await conn.execute(
                    text("ALTER TABLE model_config ADD COLUMN timeout_seconds_upgrade DOUBLE")
                )
            return model
        finally:
            await db.dispose()

    original = asyncio.run(legacy_row())
    migrate("upgrade", "head")
    migrate("upgrade", "head")

    async def verify():
        db = Database(Settings(_env_file=None, database_url=mysql_url))
        try:
            async with db.transaction() as s:
                stored = service.effective_model_snapshot(await s.get(ModelConfig, original.id))
                assert stored.timeout_seconds == 30.1
                assert stored.model_config_hash == original.model_config_hash
        finally:
            await db.dispose()

    asyncio.run(verify())


def test_mysql_admin_api_complete_workflow(mysql_url):
    async def scenario():
        app = create_app(Settings(_env_file=None, database_url=mysql_url, log_level="WARNING"))
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as c:
                prefix = "/api/admin"

                async def post(path, body=None, status=200):
                    response = await c.post(prefix + path, json=body)
                    assert response.status_code == status, response.text
                    return response.json()

                assert (await c.get("/ready")).status_code == 200
                assert (await c.get(prefix + "/config/draft")).json()["draft_json"] is None
                assert not (await c.get(prefix + "/status/summary")).json()["runtime_config_ready"]
                await post("/releases", {"note": "missing model"}, 422)
                draft = await post("/config/bootstrap", {"draft_json": document()}, 201)
                await post("/config/bootstrap", {"draft_json": document()}, 409)
                assert (await c.get(prefix + "/releases")).json()["items"] == []
                await post("/config/validate")
                preview = await post("/config/prompt-preview", {"text": "你好"})
                assert preview == await post("/config/prompt-preview", {"text": "你好"})
                model = await post("/model-configs", model_input(), 201)
                await post("/model-configs", model_input(), 409)
                assert (
                    await c.put(prefix + f"/model-configs/{model['id']}", json={})
                ).status_code == 405
                summary = (
                    await c.get(
                        prefix + "/config/publish-summary",
                        params={"default_model_config_id": model["id"]},
                    )
                ).json()
                assert summary["changes"] and summary["active_release_id"] is None
                body = {
                    "default_model_config_id": model["id"],
                    "note": "publish",
                    "expected_draft_hash": draft["draft_hash"],
                    "expected_active_release_id": None,
                }
                release = await post("/releases", body, 201)
                await post("/releases", body, 409)  # confirmation based on old Active
                assert (await c.get(prefix + "/status/summary")).json()["runtime_config_ready"]
                await post(f"/model-configs/{model['id']}/disable", status=409)
                changed = document()
                changed["prompt_template"]["system"] += " updated"
                updated = await c.put(
                    prefix + "/config/draft",
                    json={"draft_json": changed, "expected_draft_hash": draft["draft_hash"]},
                )
                assert updated.status_code == 200
                stale = await c.put(
                    prefix + "/config/draft",
                    json={"draft_json": document(), "expected_draft_hash": draft["draft_hash"]},
                )
                assert stale.status_code == 409
                detail = (await c.get(prefix + f"/releases/{release['id']}")).json()
                assert detail["snapshot_json"] == release["snapshot_json"]
                restored = await post(
                    f"/releases/{release['id']}/create-draft",
                    {"expected_draft_hash": updated.json()["draft_hash"]},
                )
                assert restored["draft_json"] == detail["snapshot_json"]
                rollback = await post(
                    "/releases", {"default_model_config_id": model["id"], "note": "rollback"}, 201
                )
                assert rollback["release_fingerprint"] == release["release_fingerprint"]
                assert (
                    await c.patch(prefix + f"/releases/{release['id']}", json={})
                ).status_code == 405
                assert (await c.get(prefix + "/releases", params={"limit": 1, "offset": 1})).json()[
                    "items"
                ][0]["id"] == release["id"]

    asyncio.run(scenario())
