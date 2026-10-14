import asyncio

import httpx
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.core.settings import Settings
from app.db.database import Database
from app.db.models import ManagedModel, ProviderCredential
from app.main import create_app
from tests.test_config_mysql import mysql_url as mysql_url


def _model(name: str, *, base_url: str = "https://example.com/v1", key: str = "sk-old-ABCD"):
    return {
        "display_name": name,
        "base_url": base_url,
        "api_key": key,
        "model_name": name.lower().replace(" ", "-"),
        "temperature": 0.1,
        "top_p": 0.8,
        "timeout_seconds": 30,
        "max_retries": 1,
        "max_concurrency": 4,
    }


def test_managed_model_lifecycle_and_secret_boundary(mysql_url) -> None:
    async def scenario() -> None:
        encryption_key = Fernet.generate_key().decode()
        settings = Settings(
            _env_file=None,
            database_url=mysql_url,
            credential_encryption_key=encryption_key,
            log_level="WARNING",
        )
        app = create_app(settings)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test/api/admin"
            ) as client:
                first_response = await client.post("/models", json=_model("Qwen Plus"))
                assert first_response.status_code == 201
                first = first_response.json()
                assert first["model_uid"].startswith("mdl_")
                assert first["is_default"] is True
                assert first["credential_hint"] == "••••ABCD"
                assert "api_key" not in first and "credential_ref" not in first
                assert "provider" not in first

                duplicate = _model("Duplicate", base_url="https://EXAMPLE.com:443/v1/")
                duplicate["model_name"] = "qwen-plus"
                response = await client.post("/models", json=duplicate)
                assert response.status_code == 409
                assert response.json()["error_code"] == "MODEL_ALREADY_EXISTS"

                updated_response = await client.patch(
                    f"/models/{first['model_uid']}",
                    json={
                        "display_name": "Qwen Plus New",
                        "api_key": "sk-new-WXYZ",
                        "temperature": 0.7,
                    },
                )
                assert updated_response.status_code == 200
                updated = updated_response.json()
                assert updated["model_uid"] == first["model_uid"]
                assert updated["model_name"] == first["model_name"]
                assert updated["base_url"] == first["base_url"]
                assert updated["credential_hint"] == "••••WXYZ"

                disabled_default = await client.post(f"/models/{first['model_uid']}/disable")
                assert disabled_default.status_code == 409

                second_response = await client.post(
                    "/models",
                    json=_model(
                        "Qwen Max", base_url="https://example.com/v1", key="sk-second-1234"
                    ),
                )
                assert second_response.status_code == 201
                second = second_response.json()
                assert (
                    await client.post(f"/models/{second['model_uid']}/default")
                ).status_code == 200
                assert (
                    await client.post(f"/models/{first['model_uid']}/disable")
                ).status_code == 200

                listing = (await client.get("/models")).json()
                serialized = str(listing)
                assert listing["default_model_uid"] == second["model_uid"]
                assert "sk-old" not in serialized and "sk-new" not in serialized
                assert "encrypted_secret" not in serialized and "credential_ref" not in serialized

        db = Database(settings)
        try:
            async with db.transaction() as session:
                model = await session.scalar(
                    select(ManagedModel).where(ManagedModel.model_uid == first["model_uid"])
                )
                credential = await session.get(ProviderCredential, model.credential_id)
                assert model.provider == "openai_compatible"
                assert "sk-new-WXYZ" not in credential.encrypted_secret
                assert (
                    app.state.credential_cipher.decrypt(credential.encrypted_secret)
                    == "sk-new-WXYZ"
                )
        finally:
            await db.dispose()

    asyncio.run(scenario())
