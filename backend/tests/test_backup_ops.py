"""Backups and disaster recovery (queue R39): dump naming, retention, restore safety."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from app.ops import backup


def test_dump_path_uses_iso_date_and_custom_format(tmp_path: Path):
    p = backup.dump_path(tmp_path, night=date(2026, 9, 26))
    assert p == tmp_path / "dumps" / "solver-2026-09-26.dump"
    assert p.suffix == ".dump"


def test_wal_dir_lives_beside_dumps(tmp_path: Path):
    assert backup.wal_dir(tmp_path) == tmp_path / "wal"


def test_prune_keeps_only_recent_dumps(tmp_path: Path):
    dumps = tmp_path / "dumps"
    dumps.mkdir()
    keep_night = date(2026, 9, 26)
    for i in range(10):
        night = keep_night - timedelta(days=i)
        (dumps / f"solver-{night.isoformat()}.dump").write_bytes(b"x")
    removed = backup.prune_dumps(tmp_path, keep_days=7, today=keep_night)
    assert len(removed) == 3
    remaining = sorted(p.name for p in dumps.glob("solver-*.dump"))
    assert remaining == sorted(
        f"solver-{(keep_night - timedelta(days=i)).isoformat()}.dump" for i in range(7)
    )


def test_restore_target_must_be_solver_restore():
    assert backup.restore_db_name() == "solver_restore"
    with pytest.raises(ValueError, match="solver_restore"):
        backup.assert_safe_restore_db("solver")
    with pytest.raises(ValueError, match="solver_restore"):
        backup.assert_safe_restore_db("solver_test")
    backup.assert_safe_restore_db("solver_restore")


def test_refuse_live_database_name():
    with pytest.raises(ValueError, match="live"):
        backup.assert_not_live_db("solver")
    backup.assert_not_live_db("solver_restore")
    backup.assert_not_live_db("solver_test")


def test_rpo_rto_defaults():
    assert backup.RPO_HOURS == 24
    assert backup.RTO_HOURS == 4


def test_manifest_records_night_and_paths(tmp_path: Path):
    dump = backup.dump_path(tmp_path, night=date(2026, 9, 26))
    dump.parent.mkdir(parents=True)
    dump.write_bytes(b"abc")
    text = backup.write_manifest(
        tmp_path,
        night=date(2026, 9, 26),
        dump=dump,
        database="solver",
        bytes_written=3,
    )
    assert "RPO 24 h" in text
    assert "RTO 4 h" in text
    assert "solver-2026-09-26.dump" in text
    assert (tmp_path / "LATEST").read_text() == text
