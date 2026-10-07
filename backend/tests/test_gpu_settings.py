from fastapi.testclient import TestClient
from app.main import app
from tests.test_settings import auth_headers, ensure_admin_seeded  # noqa: F401


def test_gpu_settings_are_platform_only_and_validate_endpoint(auth_headers):
    client = TestClient(app)
    response = client.get("/api/v1/settings", headers=auth_headers)
    items = {r["key"]: r for r in response.json()["items"]}
    assert items["gpu.enabled"]["value"] is False
    for payload in [
        {"scope": "domain", "scope_id": 1, "key": "gpu.enabled", "value": True},
        {"scope": "platform", "key": "gpu.endpoint", "value": "file:///etc/passwd"},
        {"scope": "platform", "key": "gpu.endpoint", "value": "http://user:secret@host"},
        {"scope": "platform", "key": "gpu.memory_mb", "value": -1},
    ]:
        assert client.put("/api/v1/settings", headers=auth_headers, json=payload).status_code == 422
