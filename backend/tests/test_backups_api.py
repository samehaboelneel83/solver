"""Backup status route (OAAS OPS01)."""

from __future__ import annotations

from pathlib import Path

from app.ops import backup as backup_ops
from app.seed import seed_admin, seed_workforce_demo
from tests.test_api_problems import auth_headers, client  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


def test_backup_status_is_operator_only(db, client, auth_headers, tmp_path, monkeypatch):  # noqa: F811
    seed_admin(db)
    monkeypatch.setenv("SOLVER_BACKUP_DIR", str(tmp_path))
    assert client.get("/api/v1/backups").status_code == 401
    seed_workforce_demo(db)
    response = client.get("/api/v1/backups", headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["reachable"] is True
    assert body["rpo_hours"] == 24
    assert body["latest"] is None
    assert body["dumps"] == []


def test_backup_status_reads_latest_manifest(db, client, auth_headers, tmp_path, monkeypatch):  # noqa: F811
    seed_admin(db)
    seed_workforce_demo(db)
    monkeypatch.setenv("SOLVER_BACKUP_DIR", str(tmp_path))
    night = __import__("datetime").date(2026, 9, 26)
    dump = backup_ops.dump_path(tmp_path, night=night)
    dump.parent.mkdir(parents=True)
    dump.write_bytes(b"fake")
    backup_ops.write_manifest(
        tmp_path, night=night, dump=dump, database="solver", bytes_written=4
    )
    response = client.get("/api/v1/backups", headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["latest"]["night"] == "2026-09-26"
    assert body["latest"]["dump"] == dump.name
    assert body["dumps"] == [dump.name]
    assert Path(body["root"]) == tmp_path
