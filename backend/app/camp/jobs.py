"""The worker's lane for camp solves: claim one, lay it out, store the answer.

A solve runs in a child process. The worker stays free to heartbeat, to see
a stop request and to end the child at its deadline; a solve that runs out of
memory fails alone. The child sends its progress lines and, at the end, the
result: the input and the layout as GeoJSON in local metres, the report and
the layout record -- everything the result page, the downloads and the
standalone map are made from, so none of them solves again.

A solve whose worker died is failed, not run again: a person asked for one
answer and can ask again.
"""
from __future__ import annotations

import logging
import multiprocessing as mp
import os
import queue
import time
from typing import Any

from sqlalchemy import text

logger = logging.getLogger("solver.worker.camp")

STALE_AFTER_SECONDS = 120
#: Allowed past the stage limits before the child is ended: the heuristic, the model build and validation.
GRACE_SECONDS = 180
SOLVERS = ("cpsat", "scip", "highs", "cbc", "heuristic")
DEFAULT_OPTIONS = {"solver": "cpsat", "beds_seconds": 120, "seconds": 60, "threads": 4}


def options_of(raw: dict[str, Any] | None) -> dict[str, Any]:
    out = dict(DEFAULT_OPTIONS)
    for key, value in (raw or {}).items():
        if key in out and value is not None:
            out[key] = value
    if out["solver"] not in SOLVERS:
        out["solver"] = "cpsat"
    out["beds_seconds"] = max(5, min(int(out["beds_seconds"]), 1800))
    out["seconds"] = max(5, min(int(out["seconds"]), 1800))
    out["threads"] = max(1, min(int(out["threads"]), os.cpu_count() or 4, 16))
    return out


def deadline_of(options: dict[str, Any]) -> float:
    """The most a solve may take: the beds stage and three later stages, plus the grace."""
    return options["beds_seconds"] + 3 * options["seconds"] + GRACE_SECONDS


def solve_problem(problem_data: dict[str, Any], options: dict[str, Any], log) -> dict[str, Any]:
    """Lay out one camp and return what is stored. Pure: no database."""
    from app.camp.engine import serial
    from app.camp.service import normalised
    from camp_layout import export
    from camp_layout.pipeline import solve
    from camp_layout.result import to_json

    problem = serial.from_dict(normalised(problem_data))
    run = solve(problem, options["solver"], time_limit=options["seconds"], threads=options["threads"],
                stage_limits={"beds": options["beds_seconds"]}, log=log)
    rep = export.report(run)
    return {
        "input": {"type": "FeatureCollection", "features": export.input_features(run)},
        "output": {"type": "FeatureCollection", "features": export.output_features(run)},
        "report": rep,
        "layout": to_json(run.layout),
        "origin_lonlat": list(problem.origin_lonlat),
        "beds": len(run.layout.beds),
        "valid": run.validation.ok,
    }


def _child(problem_data, options, out) -> None:  # pragma: no cover -- runs in the child process
    import json

    def log(*parts) -> None:
        out.put(("log", " ".join(str(p) for p in parts)))

    try:
        result = solve_problem(problem_data, options, log)
        out.put(("done", json.dumps(result, default=str)))
    except Exception as exc:  # noqa: BLE001 -- the parent records it
        out.put(("failed", str(exc)[:2000] or type(exc).__name__))


def claim_next(db) -> int | None:
    row = db.execute(text(
        "UPDATE camp_solve SET status = 'running', started_at = now(), heartbeat_at = now()"
        " WHERE id = (SELECT id FROM camp_solve WHERE status = 'queued' AND NOT cancel_requested"
        "             ORDER BY queued_at FOR UPDATE SKIP LOCKED LIMIT 1)"
        " RETURNING id")).scalar_one_or_none()
    db.commit()
    return row


def reclaim_stale(db) -> int:
    gone = db.execute(text(
        "UPDATE camp_solve SET status = 'failed', finished_at = now(),"
        " error = 'the worker stopped while laying this out; solve it again'"
        " WHERE status = 'running' AND heartbeat_at < now() - make_interval(secs => :s) RETURNING id"),
        {"s": STALE_AFTER_SECONDS}).scalars().all()
    db.execute(text("UPDATE camp_solve SET status = 'cancelled', finished_at = now()"
                    " WHERE status = 'queued' AND cancel_requested"))
    db.commit()
    return len(gone)


def _progress(db, solve_id: int, lines: list[str]) -> bool:
    """Append progress lines, beat, and say whether a stop was asked for."""
    import json

    stop = db.execute(text(
        "UPDATE camp_solve SET heartbeat_at = now(),"
        " progress = progress || CAST(:p AS jsonb) WHERE id = :i RETURNING cancel_requested"),
        {"p": json.dumps([{"at": round(time.time(), 1), "line": ln[:500]} for ln in lines]), "i": solve_id},
    ).scalar_one()
    db.commit()
    return bool(stop)


def execute(db, solve_id: int, *, poll: float = 0.5, heartbeat=None, beat_every: float = 15.0) -> str:
    """Solve one claimed camp in a child process; returns how it ended.
    `heartbeat`, when given, is called every `beat_every` seconds meanwhile: the
    worker's own sign of life (`app.worker.beat`), which a long solve would otherwise silence."""
    import json

    row = db.execute(text("SELECT problem, options FROM camp_solve WHERE id = :i"), {"i": solve_id}).mappings().one()
    options = options_of(row["options"])
    # Spawned, not forked: the worker holds a database connection and solver threads a fork would copy.
    ctx = mp.get_context("spawn")
    out = ctx.Queue()
    child = ctx.Process(target=_child, args=(row["problem"], options, out), daemon=True)
    child.start()
    deadline = time.monotonic() + deadline_of(options)
    beaten = time.monotonic()
    status, error, result = "failed", None, None
    try:
        while True:
            lines: list[str] = []
            ended = None
            try:
                while True:
                    kind, payload = out.get(timeout=poll if not lines else 0.01)
                    if kind == "log":
                        lines.append(payload)
                    else:
                        ended = (kind, payload)
                        break
            except queue.Empty:
                pass
            stop = _progress(db, solve_id, lines)
            if heartbeat is not None and time.monotonic() - beaten >= beat_every:
                beaten = time.monotonic()
                try:
                    heartbeat()
                except Exception:  # noqa: BLE001 -- a missed beat is not a failed solve
                    db.rollback()
            if ended is not None:
                kind, payload = ended
                if kind == "done":
                    status, result = "done", json.loads(payload)
                else:
                    status, error = "failed", payload
                break
            if stop:
                status, error = "cancelled", "stopped on request"
                break
            if time.monotonic() > deadline:
                status, error = "failed", "the solve took longer than its time limits allow"
                break
            if not child.is_alive() and out.empty():
                status, error = "failed", "the solve ended without an answer (out of memory?)"
                break
    finally:
        if child.is_alive():
            child.terminate()
            child.join(5)
            if child.is_alive():
                child.kill()
        child.join(1)
    db.execute(text(
        "UPDATE camp_solve SET status = :s, error = :e, result = CAST(:r AS jsonb), beds = :b, valid = :v,"
        " finished_at = now() WHERE id = :i"),
        {"s": status, "e": error, "r": json.dumps(result) if result else None,
         "b": result["beds"] if result else None, "v": result["valid"] if result else None, "i": solve_id})
    db.commit()
    return status


def work_once(db, heartbeat=None) -> int | None:
    """Claim and solve one camp, or None when none is waiting."""
    reclaim_stale(db)
    solve_id = claim_next(db)
    if solve_id is None:
        return None
    logger.info("camp solve %s claimed", solve_id)
    try:
        status = execute(db, solve_id, heartbeat=heartbeat)
        logger.info("camp solve %s %s", solve_id, status)
    except Exception:
        db.rollback()
        logger.exception("camp solve %s failed", solve_id)
        db.execute(text("UPDATE camp_solve SET status = 'failed', finished_at = now(),"
                        " error = 'the worker failed while laying this out; see the worker log' WHERE id = :i"),
                   {"i": solve_id})
        db.commit()
    return solve_id
