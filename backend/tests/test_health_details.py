"""The Health page and the rebuild script's last word: every part, whether it
works, and -- when it does not -- the command that brings it back."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

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


def _as_the_app():
    """A session as the role the running app has (0032/0037): it may not read alembic_version."""
    session = SessionLocal()
    session.execute(text("SET ROLE solver_app"))
    return session


def test_the_app_role_reads_the_version_and_one_failed_check_does_not_fail_the_next():
    """The Health page on a real install: 'The migration version could not be read
    (ProgrammingError)' -- the app's role may not read alembic_version -- and then
    'The worker's heartbeat could not be read', only because the failed statement
    had left the transaction aborted."""
    _heartbeat(alive=True)
    denied = _as_the_app()
    try:
        with pytest.raises(ProgrammingError):
            denied.execute(text("SELECT version_num FROM alembic_version"))
    finally:
        denied.rollback()
        denied.close()

    with patch("app.api.health.SessionLocal", _as_the_app), patch("app.api.health.get_clickhouse_client") as client:
        client.return_value.command.return_value = 1
        body = TestClient(app).get("/api/health/details").json()
    assert [(c["name"], c["ok"]) for c in body["checks"]] == [
        ("Database", True), ("Database version", True), ("Worker", True), ("Analytics store", True)]

    class Broken:
        """The version query fails as a database error would; the worker check must still answer."""
        def __init__(self):
            self.session = _as_the_app()

        def execute(self, statement, *args, **kwargs):
            if "schema_version" in str(statement):
                return self.session.execute(text("SELECT * FROM no_such_table"))
            return self.session.execute(statement, *args, **kwargs)

        def __getattr__(self, name):
            return getattr(self.session, name)

    with patch("app.api.health.SessionLocal", Broken), patch("app.api.health.get_clickhouse_client") as client:
        client.return_value.command.return_value = 1
        checks = {c["name"]: c for c in TestClient(app).get("/api/health/details").json()["checks"]}
    assert checks["Database version"]["ok"] is False and "ProgrammingError" in checks["Database version"]["says"]
    assert checks["Worker"]["ok"] is True
    _heartbeat(alive=False)
