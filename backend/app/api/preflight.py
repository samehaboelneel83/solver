"""Before a run (Epic UX, U-5): will it solve, with what, and is anything there to solve it?

    GET /api/v1/workers                       online workers, runs solving and queued
    GET /api/v1/scenarios/{id}/preflight      the scenario's model on today's data:
                                              ready or not, and why; which solvers fit

The preflight does what a run's first steps do -- the scenario's patch applied,
the model compiled on the domain's live data (not a snapshot: nothing is
written), classified and refined -- and reports each thing that would stop the
run as a finding a planner can act on, before anything is queued. `ready` is
true when nothing would stop it: a finding of kind `warning` (a rule over an
empty set, say) is worth reading but does not.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models.iam import UserAccount

router = APIRouter(prefix="/api/v1", tags=["preflight"])

ONLINE_WITHIN_SECONDS = 90


def worker_status(db: Session) -> dict[str, Any]:
    row = db.execute(text(
        "SELECT (SELECT count(*) FROM worker_heartbeat WHERE last_seen > now() - make_interval(secs => :w)) AS online,"
        "       (SELECT max(last_seen) FROM worker_heartbeat) AS last_seen,"
        "       (SELECT count(*) FROM run WHERE status = 'running' AND heartbeat_at > now() - interval '60 seconds') AS solving,"
        "       (SELECT count(*) FROM run WHERE status = 'queued') AS queued"),
        {"w": ONLINE_WITHIN_SECONDS}).mappings().one()
    online, solving, queued = int(row["online"]), int(row["solving"]), int(row["queued"])
    if online:
        state = "ready"
        says = f"{online} {'worker is' if online == 1 else 'workers are'} online" + (
            f"; {queued} {'run is' if queued == 1 else 'runs are'} waiting" if queued else "; a new run starts at once")
    elif solving:
        state = "busy"
        says = "Every worker is busy solving; a new run waits its turn."
    else:
        state = "offline"
        says = ("No worker has been seen in the last minute and a half. A run can still be queued; it starts when a "
                "worker comes back. An administrator can check the worker service.")
    return {"state": state, "online": online, "solving": solving, "queued": queued, "last_seen": row["last_seen"], "says": says}


@router.get("/workers")
def workers(db: Session = Depends(get_db), _: UserAccount = Depends(get_current_user)) -> dict[str, Any]:
    return worker_status(db)


def _finding(kind: str, code: str, says: str, **extra: Any) -> dict[str, Any]:
    return {"kind": kind, "code": code, "says": says, **extra}


@router.get("/scenarios/{scenario_id}/preflight")
def preflight(scenario_id: int, db: Session = Depends(get_db), user: UserAccount = Depends(get_current_user)) -> dict[str, Any]:
    from app.settings_resolve import resolve
    from app.solve.licences import solver_list
    from app.solve.backends import fit
    from app.solve.classify import classify
    from app.solve.compile import Unsupported, compile_model
    from app.solve.convexity import refine
    from app.solve.preview import live_data
    from app.solve.service import patched

    scenario = db.execute(text(
        "SELECT s.id, s.patch, s.problem_id, p.domain_id, mv.ir, mv.version FROM scenario s"
        " JOIN model_version mv ON mv.id = s.model_version_id JOIN problem p ON p.id = s.problem_id WHERE s.id = :s"),
        {"s": scenario_id}).mappings().one_or_none()
    if scenario is None:
        raise HTTPException(404, "scenario not found")
    ir = patched(scenario["ir"], scenario["patch"] or {})
    findings: list[dict[str, Any]] = []

    # A newer published version the scenario does not use (operator trial F29): publishing never
    # moves a scenario, so without this the old model is solved and nothing says so.
    latest = db.execute(text(
        "SELECT id, version FROM model_version WHERE problem_id = :p ORDER BY version DESC LIMIT 1"),
        {"p": scenario["problem_id"]}).mappings().one()
    if latest["version"] > scenario["version"]:
        findings.append(_finding(
            "warning", "newer_version",
            f"This scenario solves version {scenario['version']}; version {latest['version']} is the latest published. "
            "Move the scenario to it to solve the model as it is now.",
            scenario_version=scenario["version"], latest_version=latest["version"], latest_version_id=latest["id"]))

    unexpressed = [c.get("id") for c in ir.get("constraints", [])
                   if not any(k in c for k in ("left", "no_overlap", "cumulative", "connected", "route"))]
    if unexpressed:
        findings.append(_finding("blocker", "rule_not_expressed",
                                 f"{', '.join(map(str, unexpressed))} {'has' if len(unexpressed) == 1 else 'have'} a name but no arithmetic, "
                                 "so nothing can check them. Express them in the Model editor and publish a new version.",
                                 rules=unexpressed))

    data = live_data(db, scenario["domain_id"], ir)
    for name in ir.get("sets", []):
        if not data.get("sets", {}).get(name):
            findings.append(_finding("warning", "set_empty",
                                     f"There are no {name} records yet, so every rule and decision over {name} is empty.", set=name))

    compiled = None
    try:
        compiled = compile_model(ir, data)
    except Unsupported as exc:
        findings.append(_finding("blocker", "does_not_compile", str(exc)))
    except Exception as exc:  # pragma: no cover -- a compiler bug is still a finding, not a 500
        findings.append(_finding("blocker", "does_not_compile", f"The model could not be built: {exc}"))

    for empty in (compiled.empty_ranges if compiled is not None else []):
        where = ", ".join(f"{k} = {v}" for k, v in (empty.get("index") or {}).items())
        findings.append(_finding("warning", "empty_range",
                                 f"{empty.get('constraint_id', 'A rule')} has a {empty.get('kind', 'range')} that matches nobody"
                                 f"{f' (at {where})' if where else ''}: it holds vacuously or counts as zero, often a data gap.",
                                 detail=empty))

    found = classify(ir, data)
    if compiled is not None:
        found = refine(found, compiled)
    settings = resolve(db, problem_id=scenario["problem_id"])
    allowed = set(solver_list(settings["solve.allowed_solvers"].value)) or None
    denied = set(solver_list(settings["solve.denied_solvers"].value)) or None
    solvers = fit(found, allowed=allowed, denied=denied)
    if not any(s["automatic"] for s in solvers):
        findings.append(_finding("blocker", "no_solver",
                                 f"No solver here takes this {found.model_class} model unasked. "
                                 + ("Some fit when asked for by name: " + ", ".join(s["name"] for s in solvers if s["fits"]) + "."
                                    if any(s["fits"] for s in solvers) else "See why each is kept out below.")))
    return {
        "scenario_id": scenario_id,
        "version": scenario["version"],
        "ready": not any(f["kind"] == "blocker" for f in findings),
        "findings": findings,
        "model_class": found.model_class,
        "planner": list(found.planner),
        "solvers": solvers,
        "workers": worker_status(db),
    }
