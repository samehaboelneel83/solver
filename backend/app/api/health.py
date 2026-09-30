"""Is the platform up? (simplification plan, phase 5)

    GET /api/health           {"postgres": "ok"|"error", "clickhouse": ...} -- what scripts wait on
    GET /api/health/details   every part, whether it works, and the fix when it does not

The details are for a person: the rebuild script prints them and opens the
Health page, so a part that is down says so in words, with the command that
brings it back -- instead of a planner meeting it later as a run that never
starts. No login is needed (the page is read before anyone signs in), so
nothing here names data, users or secrets.
"""
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Response
from fastapi.responses import PlainTextResponse
from sqlalchemy import text

from app.core.db import SessionLocal, get_clickhouse_client

router = APIRouter(tags=["health"])

_ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


@router.get("/api/health")
def health() -> dict:
    result = {"postgres": "ok", "clickhouse": "ok"}

    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
    except Exception:
        result["postgres"] = "error"

    try:
        client = get_clickhouse_client()
        client.command("SELECT 1")
    except Exception:
        result["clickhouse"] = "error"

    return result


def _check(name: str, ok: bool, says: str, fix: str | None = None, *, needed: bool = True) -> dict[str, Any]:
    return {"name": name, "ok": ok, "needed": needed, "says": says, "fix": None if ok else fix}


def _migrations_head() -> str | None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(_ALEMBIC_INI))
    config.set_main_option("script_location", str(_ALEMBIC_INI.parent / "alembic"))
    return ScriptDirectory.from_config(config).get_current_head()


def checks() -> list[dict[str, Any]]:
    from app.api.preflight import worker_status

    out: list[dict[str, Any]] = []
    db = None
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        out.append(_check("Database", True, "PostgreSQL answers."))
    except Exception:
        out.append(_check("Database", False, "PostgreSQL does not answer, so nothing can be read or saved.",
                          "Start it with: docker compose up -d postgres -- then run scripts\\rebuild.cmd again."))
        db = None

    if db is not None:
        # Each check rolls back when it fails: one failed statement must not take the
        # next check down with it ("current transaction is aborted").
        try:
            current = db.execute(text("SELECT schema_version()")).scalar_one_or_none()
            head = _migrations_head()
            out.append(_check(
                "Database version", current == head,
                f"The database is at migration {current}, the newest." if current == head
                else f"The database is at migration {current}; this version of the platform expects {head}.",
                "Run scripts\\rebuild.cmd: it applies the missing migrations. If a migration fails, its message says which record stops it."))
        except Exception as exc:  # noqa: BLE001 -- any failure here is the same advice
            db.rollback()
            missing = "schema_version" in str(exc) and "does not exist" in str(exc)
            out.append(_check(
                "Database version", False,
                "The database is older than this version of the platform expects." if missing
                else f"The migration version could not be read ({type(exc).__name__}).",
                "Run scripts\\rebuild.cmd: it applies the missing migrations."))
        try:
            worker = worker_status(db)
            ok = worker["state"] != "offline"
            out.append(_check("Worker", ok, worker["says"] if ok else "No worker has been seen in the last minute and a half, so runs wait in the queue.",
                              "Start it with: docker compose up -d worker -- and if it stops again, docker compose logs worker says why."))
        except Exception:
            db.rollback()
            out.append(_check("Worker", False, "The worker's heartbeat could not be read.",
                              "Run scripts\\rebuild.cmd so the database is up to date, then check again."))
        finally:
            db.close()

    try:
        get_clickhouse_client().command("SELECT 1")
        out.append(_check("Analytics store", True, "ClickHouse answers.", needed=False))
    except Exception:
        out.append(_check("Analytics store", False,
                          "ClickHouse does not answer. Planning and solving still work; run history charts and analytics do not.",
                          "Start it with: docker compose up -d clickhouse -- a first start can take a minute.", needed=False))
    return out


@router.get("/api/health/details")
def health_details(response: Response, format: str = "json", strict: bool = False):
    """Every part and its fix. `strict` answers 503 while anything is down (for a script to wait on);
    `format=text` is one line a part, for a terminal."""
    found = checks()
    ready = all(c["ok"] for c in found)
    if strict and not ready:
        response.status_code = 503
    if format == "text":
        lines = []
        for c in found:
            mark = "OK  " if c["ok"] else ("DOWN" if c["needed"] else "WARN")
            lines.append(f"  {mark} {c['name']}: {c['says']}")
            if c["fix"]:
                lines.append(f"       fix: {c['fix']}")
        verdict = "Everything is working." if ready else (
            "Planning works; see the WARN line." if all(c["ok"] or not c["needed"] for c in found) else "Something needs fixing: see the DOWN lines.")
        return PlainTextResponse("\n".join([*lines, verdict, ""]), status_code=response.status_code or 200)
    return {"ready": ready, "checks": found}
