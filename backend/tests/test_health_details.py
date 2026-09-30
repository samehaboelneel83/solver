"""The Health page and the rebuild script's last word: every part, whether it
works, and -- when it does not -- the command that brings it back."""
from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.db import SessionLocal
from app.main import app


def _heartbeat(alive: bool) -> None:
    db = SessionLocal()
    try:
        db.execute(text("DELETE FROM worker_heartbeat"))
        if alive:
            db.execute(text("INSERT INTO worker_heartbeat (worker_id, host, pid) VALUES ('w-health', 'here', 1)"))
        db.commit()
    finally:
        db.close()


def _broken_clickhouse():
    raise ConnectionError("no clickhouse")


def test_every_part_is_named_and_needs_no_login():
    _heartbeat(alive=True)
    with patch("app.api.health.get_clickhouse_client") as client:
        client.return_value.command.return_value = 1
        body = TestClient(app).get("/api/health/details").json()
    assert body["ready"] is True
    assert [(c["name"], c["ok"], c["fix"]) for c in body["checks"]] == [
        ("Database", True, None), ("Database version", True, None), ("Worker", True, None), ("Analytics store", True, None)]
    assert body["checks"][1]["says"].endswith("the newest.")


def test_a_part_that_is_down_says_how_to_bring_it_back():
    _heartbeat(alive=False)
    with patch("app.api.health.get_clickhouse_client", _broken_clickhouse):
        client = TestClient(app)
        body = client.get("/api/health/details").json()
        strict = client.get("/api/health/details?strict=true")
        words = client.get("/api/health/details?format=text")
    checks = {c["name"]: c for c in body["checks"]}
    assert body["ready"] is False
    assert checks["Worker"]["ok"] is False and "docker compose up -d worker" in checks["Worker"]["fix"]
    assert checks["Analytics store"]["needed"] is False and "Planning and solving still work" in checks["Analytics store"]["says"]
    assert strict.status_code == 503
    assert words.status_code == 200 and words.headers["content-type"].startswith("text/plain")
    lines = words.text.splitlines()
    assert "  OK   Database: PostgreSQL answers." in lines
    assert any(line.startswith("  DOWN Worker:") for line in lines)
    assert any(line.startswith("  WARN Analytics store:") for line in lines)
    assert lines[-1] == "Something needs fixing: see the DOWN lines."
    _heartbeat(alive=False)


def test_a_database_behind_its_migrations_is_named():
    with patch("app.api.health._migrations_head", return_value="9999"), \
         patch("app.api.health.get_clickhouse_client") as client:
        client.return_value.command.return_value = 1
        checks = {c["name"]: c for c in TestClient(app).get("/api/health/details").json()["checks"]}
    assert checks["Database version"]["ok"] is False
    assert "expects 9999" in checks["Database version"]["says"] and "rebuild.cmd" in checks["Database version"]["fix"]
