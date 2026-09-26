"""Backups and disaster recovery (queue R39).

Nightly Postgres dumps land under ``SOLVER_BACKUP_DIR`` (default: a sibling
``solver-backups`` folder beside the repository). WAL segments archive into
the same tree. ClickHouse ``run_fact`` is rebuildable from Postgres and is
not backed up.

Documented starting targets: RPO 24 h, RTO 4 h.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

RPO_HOURS = 24
RTO_HOURS = 4
RESTORE_DB = "solver_restore"
LIVE_DB = "solver"
KEEP_DAYS_DEFAULT = 14


def dump_path(root: Path, *, night: date) -> Path:
    return root / "dumps" / f"solver-{night.isoformat()}.dump"


def wal_dir(root: Path) -> Path:
    return root / "wal"


def restore_db_name() -> str:
    return RESTORE_DB


def assert_safe_restore_db(name: str) -> None:
    if name != RESTORE_DB:
        raise ValueError(f"restore target must be {RESTORE_DB!r}, not {name!r}")


def assert_not_live_db(name: str) -> None:
    if name == LIVE_DB:
        raise ValueError(f"refusing to drop or overwrite the live database {LIVE_DB!r}")


def prune_dumps(
    root: Path,
    *,
    keep_days: int = KEEP_DAYS_DEFAULT,
    today: date | None = None,
) -> list[Path]:
    """Delete dump files older than keep_days. Returns paths removed."""
    today = today or date.today()
    cutoff = today - timedelta(days=keep_days - 1)
    dumps = root / "dumps"
    if not dumps.is_dir():
        return []
    removed: list[Path] = []
    for path in dumps.glob("solver-*.dump"):
        stem = path.stem  # solver-YYYY-MM-DD
        try:
            night = date.fromisoformat(stem.removeprefix("solver-"))
        except ValueError:
            continue
        if night < cutoff:
            path.unlink(missing_ok=True)
            removed.append(path)
    return removed


def write_manifest(
    root: Path,
    *,
    night: date,
    dump: Path,
    database: str,
    bytes_written: int,
) -> str:
    """Write LATEST beside the dumps; return the same text."""
    root.mkdir(parents=True, exist_ok=True)
    text = (
        f"night={night.isoformat()}\n"
        f"database={database}\n"
        f"dump={dump.name}\n"
        f"bytes={bytes_written}\n"
        f"wal_dir={wal_dir(root).as_posix()}\n"
        f"RPO {RPO_HOURS} h\n"
        f"RTO {RTO_HOURS} h\n"
        f"clickhouse=not backed up (rebuildable from Postgres)\n"
    )
    (root / "LATEST").write_text(text, encoding="utf-8")
    return text
