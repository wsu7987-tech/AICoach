from fastapi.testclient import TestClient


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


def test_ready_explicitly_reports_uninitialized_checks(client: TestClient) -> None:
    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {"database": "not_initialized", "config": "not_initialized"},
        "message": "DB/config checker not initialized",
    }
