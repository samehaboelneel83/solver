from fastapi.testclient import TestClient

from app.main import app


def test_health_returns_status_for_both_databases():
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"postgres", "clickhouse"}
    assert body["postgres"] in {"ok", "error"}
    assert body["clickhouse"] in {"ok", "error"}


def test_startup_uses_lifespan_not_on_event():
    assert app.router.lifespan_context is not None
    assert app.router.on_startup == []
