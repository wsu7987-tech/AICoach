import pytest
from fastapi.testclient import TestClient

from app.core.settings import Settings
from app.main import create_app


@pytest.fixture
def client() -> TestClient:
    settings = Settings(_env_file=None, environment="test", log_level="WARNING")
    with TestClient(create_app(settings=settings)) as test_client:
        yield test_client
