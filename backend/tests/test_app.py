from fastapi.testclient import TestClient

from app.core.readiness import ReadinessChecker
from app.core.settings import Settings
from app.main import create_app


def test_app_import_and_health(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Request-ID"].startswith("req_")


def test_request_id_is_transmitted(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "upstream-123"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "upstream-123"


def test_error_envelope_for_unknown_route(client: TestClient) -> None:
    response = client.get("/does-not-exist", headers={"X-Request-ID": "error-case"})

    assert response.status_code == 404
    assert response.json() == {
        "request_id": "error-case",
        "status": "failed",
        "error_code": "INVALID_INPUT",
        "message": "Not Found",
    }
    assert response.headers["X-Request-ID"] == "error-case"


def test_runtime_and_admin_boundaries_are_separate(client: TestClient) -> None:
    runtime = client.get("/api/v1/")
    admin = client.get("/api/admin/")

    assert runtime.status_code == 200
    assert runtime.json()["scope"] == "runtime"
    assert admin.status_code == 200
    assert admin.json()["scope"] == "admin"


def test_ready_reports_database_as_unavailable_when_database_url_is_not_configured(
    client: TestClient,
) -> None:
    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {"database": "failed"},
        "message": "readiness checks failed",
    }


def test_ready_reports_database_as_unavailable_when_connection_fails() -> None:
    settings = Settings(
        _env_file=None,
        database_url="mysql+asyncmy://127.0.0.1:1/unavailable",
        environment="test",
        log_level="WARNING",
    )
    with TestClient(create_app(settings=settings)) as client:
        response = client.get("/ready")

    assert response.status_code == 503
    assert response.json()["checks"] == {"database": "failed"}


def test_ready_does_not_require_active_release_or_model_config() -> None:
    async def database_schema_is_ready() -> bool:
        return True

    checker = ReadinessChecker()
    checker.register("database", database_schema_is_ready)
    settings = Settings(_env_file=None, environment="test", log_level="WARNING")
    with TestClient(create_app(settings=settings, readiness_checker=checker)) as client:
        response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {"database": "ok"},
        "message": "ready",
    }
