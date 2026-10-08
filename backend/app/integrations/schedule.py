"""Scheduled refresh of a workspace from its sources (migration 0116), driven by the ingestion worker.

Each tick looks for schedules that are due. A due schedule runs in two steps, so the worker never waits:
1. it starts an extraction of every database source the workspace is bound to (as the schedule's owner), and
   becomes `extracting`;
2. once those have settled, it compares the workspace with them (and with the latest version of each kept file),
   keeps the report, and -- in `apply` mode -- writes the changes and, with `solve`, queues a new run of every
   scenario that reads the data. Then it waits `every_hours` again.
It acts inside the owner's organization (row-level security on) and only with the owner's current permissions.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app import audit
from app.integrations import refresh

log = logging.getLogger(__name__)
#: An extraction step that has not settled after this long is given up (the next run tries again).
EXTRACTING_AT_MOST = timedelta(minutes=15)
#: Examples kept per change kind in a stored report.
KEPT_EXAMPLES = 5


def _next(after: datetime, every_hours: int, now: datetime) -> datetime:
    step = timedelta(hours=every_hours)
    nxt = after + step
    while nxt <= now:
        nxt += step
    return nxt


def compact(out: dict) -> dict:
    """A refresh's report, small enough to keep: counts, a few examples, the runs it queued."""
    return {"applied": out.get("applied"), "changes": out.get("changes"),
            "bindings": [{k: b.get(k) for k in ("source", "kind", "target", "counts", "same_extraction", "job_id",
                                                 "version", "from_version")}
                         | {kind: (b.get(kind) or [])[:KEPT_EXAMPLES] for kind in ("added", "changed", "removed")}
                         for b in out.get("bindings") or []],
            **({"runs": out["runs"]} if out.get("runs") else {}),
            **({"failed": out["failed"]} if out.get("failed") else {})}


def notice_for(workspace: str, mode: str, report: dict | None, error: str | None) -> tuple[str, str] | None:
    """What a scheduled refresh tells the person who set it: changes found (to review), changes applied (and runs
    queued), or why it could not finish. Nothing when there was nothing to say."""
    report = report or {}
    changes, runs = int(report.get("changes") or 0), len(report.get("runs") or [])
    where = f'"{workspace}"'
    if error:
        return (f"The scheduled refresh of {where} did not finish", error)
    if not changes:
        return None
    if report.get("applied"):
        return (f"The scheduled refresh of {where} applied {changes} change{'s' if changes != 1 else ''}",
                f"{runs} scenario{'s' if runs != 1 else ''} queued to solve again." if runs else
                "No scenario was solved again.")
    return (f"The scheduled refresh of {where} found {changes} change{'s' if changes != 1 else ''} to review",
            "Nothing was written: open the workspace's sources to see them and apply them.")


def tick(engine=None, now: datetime | None = None) -> int:
    """Advance every schedule that is due or extracting. Returns how many were advanced."""
    if engine is None:
        from app.core.db import engine
    now = now or datetime.now(timezone.utc)
    with Session(bind=engine) as db:  # system code: finds due schedules of every organization
        due = db.execute(text(
            "SELECT domain_id, organization_id FROM source_schedule WHERE enabled AND"
            " ((state = 'idle' AND next_at <= :now) OR state = 'extracting') ORDER BY next_at LIMIT 10"),
            {"now": now}).all()
    advanced = 0
    for domain_id, organization_id in due:
        try:
            advanced += _advance(engine, domain_id, organization_id, now)
        except Exception:  # noqa: BLE001 -- one workspace's failure must not stop the others
            log.exception("scheduled refresh of domain %s failed", domain_id)
    return advanced


def _advance(engine, domain_id: int, organization_id, now: datetime) -> int:
    from app.api.deps import capabilities_of
    from app.core.db import enter_tenant
    from app.models.iam import UserAccount

    with engine.connect() as connection:
        db = Session(bind=connection, autoflush=False)
        enter_tenant(db, organization_id)  # from here on, as the owner's organization (row-level security on)
        # Held until this step settles: a second worker skips this workspace meanwhile.
        row = db.execute(text("SELECT * FROM source_schedule WHERE domain_id = :d FOR UPDATE SKIP LOCKED"),
                         {"d": domain_id}).mappings().one_or_none()
        if row is None or not row["enabled"]:
            db.rollback()
            return 0
        row = dict(row)

        def settle(report: dict | None, error: str | None) -> int:
            db.rollback()
            db.execute(text(
                "UPDATE source_schedule SET state = 'idle', pending = '{}'::jsonb, last_at = :now,"
                " last_report = CAST(:r AS jsonb), last_error = :e, next_at = :next, updated_at = now()"
                " WHERE domain_id = :d"),
                {"now": now, "r": None if report is None else __import__("json").dumps(report, default=str),
                 "e": error, "next": _next(row["next_at"], row["every_hours"], now), "d": domain_id})
            name = db.execute(text("SELECT name FROM domain WHERE id = :d"), {"d": domain_id}).scalar() or f"workspace {domain_id}"
            told = notice_for(str(name), row["mode"], report, error)
            if told is not None:
                # The person who set the schedule hears what it did (migration 0119).
                db.execute(text("INSERT INTO notice (organization_id, user_id, kind, title, body, link)"
                                " VALUES (:o, :u, 'scheduled_refresh', :t, :b, :l)"),
                           {"o": row["organization_id"], "u": row["owner_id"], "t": told[0], "b": told[1],
                            "l": f"/domains/{domain_id}/data/sources"})
            db.commit()
            return 1

        owner = db.get(UserAccount, row["owner_id"])
        held = capabilities_of(db, owner) if owner is not None and getattr(owner, "is_active", True) else set()
        needed = {"integration.run"} | ({"domain.edit"} if row["mode"] == "apply" else set()) | (
            {"run.submit"} if row["solve"] else set())
        if not needed <= held:
            return settle(None, "the person who set this schedule may no longer " + ", ".join(sorted(needed - held))
                          + "; set it again")

        if row["state"] == "idle":
            pending = {}
            for (cid,) in db.execute(text(
                    "SELECT DISTINCT b.connection_id FROM source_binding b JOIN integration_connection c"
                    " ON c.id = b.connection_id WHERE b.domain_id = :d AND c.enabled"), {"d": domain_id}).all():
                active = db.execute(text("SELECT id FROM ingestion_job WHERE connection_id = :c"
                                         " AND state IN ('queued', 'running') LIMIT 1"), {"c": cid}).scalar()
                pending[str(cid)] = active or db.execute(text(
                    "INSERT INTO ingestion_job (connection_id, organization_id, requested_by) VALUES (:c, :o, :u)"
                    " RETURNING id"), {"c": cid, "o": row["organization_id"], "u": row["owner_id"]}).scalar_one()
            if pending:
                db.execute(text("UPDATE source_schedule SET state = 'extracting', pending = CAST(:p AS jsonb),"
                                " started_at = :now, updated_at = now() WHERE domain_id = :d"),
                           {"p": __import__("json").dumps(pending), "now": now, "d": domain_id})
                db.commit()
                return 1
            row["pending"] = {}  # only kept files: compare at once

        jobs = {int(c): int(j) for c, j in (row.get("pending") or {}).items()}
        states = {c: db.execute(text("SELECT state, error_code FROM ingestion_job WHERE id = :j"), {"j": j}).one()
                  for c, j in jobs.items()}
        if any(s.state in ("queued", "running") for s in states.values()):
            if row["started_at"] and now - row["started_at"] > EXTRACTING_AT_MOST:
                return settle(None, "the extractions did not finish within 15 minutes")
            db.rollback()
            return 0
        failed = [{"connection_id": c, "error_code": s.error_code or s.state} for c, s in states.items()
                  if s.state != "extracted"]
        ok_jobs = {c: jobs[c] for c, s in states.items() if s.state == "extracted"}
        files = {f["name"]: f["latest"] for f in refresh.files(db, domain_id)
                 if db.execute(text("SELECT 1 FROM source_binding WHERE domain_id = :d AND file_name = :n LIMIT 1"),
                               {"d": domain_id, "n": f["name"]}).first()}
        if not ok_jobs and not files:
            return settle({"failed": failed} if failed else None,
                          "no source could be read" if failed else "nothing in this workspace is bound to a source")
        try:
            out = refresh.run_refresh(
                db, domain_id, row["organization_id"], jobs=ok_jobs, files=files or None,
                connections=list(ok_jobs) or None, apply=row["mode"] == "apply",
                on_applied=lambda written: audit.record(
                    db, organization_id=row["organization_id"], actor_id=row["owner_id"],
                    action="domain.sources.refresh.scheduled", object_type="domain", object_id=domain_id,
                    after={"bindings": written}))
        except refresh.RefreshRefused as exc:
            return settle({"failed": failed} if failed else None, str(exc))
        if out["applied"] and row["solve"] and out["changes"]:
            out["runs"] = refresh.solve_again(db, domain_id, out)
        if failed:
            out["failed"] = failed
        return settle(compact(out), ("some sources could not be read: " + ", ".join(
            f'connection {f["connection_id"]} ({f["error_code"]})' for f in failed)) if failed else None)
