"""Operator backup status (OAAS OPS01 / queue R39 visibility).

Reads the ``LATEST`` manifest written by ``scripts/backup.sh dump``. The
directory is ``SOLVER_BACKUP_DIR`` (compose mounts it at ``/backups`` on
the API). When the mount is absent the route still answers — it says so —
so the Backups page can explain recovery without inventing a dump.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models.iam import UserAccount
from app.ops import backup as backup_ops

router = APIRouter(tags=["backups"])


def _root() -> Path:
    return Path(os.environ.get("SOLVER_BACKUP_DIR", "/backups"))


@router.get("/api/v1/backups")
def backup_status(
    db: Session = Depends(get_db),
    _user: UserAccount = Depends(get_current_user),
) -> dict[str, Any]:
    if not db.execute(text("SELECT app_is_operator()")).scalar_one():
        raise HTTPException(status_code=403, detail="backups are for operators")
    root = _root()
    latest = root / "LATEST"
    dumps = root / "dumps"
    wal = backup_ops.wal_dir(root)
    dump_names = sorted(p.name for p in dumps.glob("solver-*.dump")) if dumps.is_dir() else []
    manifest: dict[str, str] | None = None
    if latest.is_file():
        manifest = {}
        for line in latest.read_text(encoding="utf-8").splitlines():
            if "=" in line:
                key, _, value = line.partition("=")
                manifest[key.strip()] = value.strip()
            elif line.startswith("RPO"):
                manifest["rpo"] = line
            elif line.startswith("RTO"):
                manifest["rto"] = line
    return {
        "root": root.as_posix(),
        "reachable": root.is_dir(),
        "rpo_hours": backup_ops.RPO_HOURS,
        "rto_hours": backup_ops.RTO_HOURS,
        "latest": manifest,
        "dumps": dump_names[-14:],
        "dump_count": len(dump_names),
        "wal_present": wal.is_dir() and any(wal.iterdir()) if wal.is_dir() else False,
        "runbook": "docs/runbooks/backups.md",
    }
