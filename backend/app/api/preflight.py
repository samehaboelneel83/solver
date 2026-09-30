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


def missing_details(db: Session, domain_id: int, missing: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The gaps `app.solve.missing` found, with what a form needs to fill them
    in place: each record's id, label and version stamp, and the attribute's
    id, type, choices and default."""
    out = []
    for gap in missing:
        attribute = db.execute(text(
            "SELECT a.id, a.data_type, a.enum_values, a.default_value, t.id AS type_id"
            "  FROM entity_type t JOIN attribute_def a ON a.entity_type_id = ANY (entity_type_lineage(t.id))"
            " WHERE t.domain_id = :d AND t.name = :t AND a.name = :a LIMIT 1"),
            {"d": domain_id, "t": gap["set"], "a": gap["attribute"]}).mappings().one_or_none()
        records = db.execute(text(
            "SELECT e.id, e.key, e.label, e.updated_at FROM entity e JOIN entity_type t ON t.id = e.entity_type_id"
            " WHERE t.domain_id = :d AND e.key = ANY (:keys)"
            "   AND t.id = ANY (entity_type_family((SELECT id FROM entity_type WHERE domain_id = :d AND name = :t)))"
            " ORDER BY e.sort_order, e.key"),
            {"d": domain_id, "t": gap["set"], "keys": gap["records"]}).mappings().all()
        out.append({
            "set": gap["set"],
            "attribute": gap["attribute"],
            "attribute_id": attribute["id"] if attribute else None,
            "entity_type_id": attribute["type_id"] if attribute else None,
            "data_type": attribute["data_type"] if attribute else None,
            "enum_values": attribute["enum_values"] if attribute else None,
            "default_value": attribute["default_value"] if attribute else None,
            "records": [
                {"id": r["id"], "key": r["key"], "label": r["label"], "updated_at": r["updated_at"]} for r in records
            ],
        })
    return out


def model_findings(db: Session, domain_id: int, problem_id: int, ir: dict[str, Any]) -> dict[str, Any]:
    """What would stop a model solving on today's data, and what it is: the
    part of a preflight that does not depend on a scenario, so a problem's
    readiness can ask it of the latest version before any scenario exists."""
    from app.settings_resolve import resolve
    from app.solve.backends import fit
    from app.solve.classify import classify
    from app.solve.compile import Unsupported, compile_model
    from app.solve.convexity import refine
    from app.solve.licences import solver_list
    from app.solve.missing import missing_values
    from app.solve.preview import live_data

    findings: list[dict[str, Any]] = []
    unexpressed = [c.get("id") for c in ir.get("constraints", [])
                   if not any(k in c for k in ("left", "no_overlap", "cumulative", "connected", "route"))]
    if unexpressed:
        findings.append(_finding("blocker", "rule_not_expressed",
                                 f"{', '.join(map(str, unexpressed))} {'has' if len(unexpressed) == 1 else 'have'} a name but no arithmetic, "
                                 "so nothing can check them. Express them in the Model editor and publish a new version.",
                                 rules=unexpressed))

    data = live_data(db, domain_id, ir)
    for name in ir.get("sets", []):
        if not data.get("sets", {}).get(name):
            findings.append(_finding("warning", "set_empty",
                                     f"There are no {name} records yet, so every rule and decision over {name} is empty.", set=name))

    # Every record without a number the model reads, at once and with what it takes to fill
    # them in place -- rather than the compiler's refusal of the first one it meets.
    missing = missing_values(ir, data)
    for gap in missing_details(db, domain_id, missing):
        count = len(gap["records"])
        findings.append(_finding(
            "blocker", "missing_values",
            f"{count} {gap['set']} {'record has' if count == 1 else 'records have'} no {gap['attribute']}, which the model reads as a number.",
            missing=gap))

    compiled = None
    try:
        compiled = compile_model(ir, data)
    except Unsupported as exc:
        if not (missing and "so the term has no value" in str(exc)):
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
    settings = resolve(db, problem_id=problem_id)
    allowed = set(solver_list(settings["solve.allowed_solvers"].value)) or None
    denied = set(solver_list(settings["solve.denied_solvers"].value)) or None
    solvers = fit(found, allowed=allowed, denied=denied)
    if not any(s["automatic"] for s in solvers):
        findings.append(_finding("blocker", "no_solver",
                                 f"No solver here takes this {found.model_class} model unasked. "
                                 + ("Some fit when asked for by name: " + ", ".join(s["name"] for s in solvers if s["fits"]) + "."
                                    if any(s["fits"] for s in solvers) else "See why each is kept out below.")))
    return {
        "findings": findings,
        "model_class": found.model_class,
        "planner": list(found.planner),
        "solvers": solvers,
        "sets": {name: len(data.get("sets", {}).get(name) or []) for name in ir.get("sets", [])},
    }


@router.get("/scenarios/{scenario_id}/preflight")
def preflight(scenario_id: int, db: Session = Depends(get_db), user: UserAccount = Depends(get_current_user)) -> dict[str, Any]:
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

    checked = model_findings(db, scenario["domain_id"], scenario["problem_id"], ir)
    findings.extend(checked["findings"])
    return {
        "scenario_id": scenario_id,
        "version": scenario["version"],
        "ready": not any(f["kind"] == "blocker" for f in findings),
        "findings": findings,
        "model_class": checked["model_class"],
        "planner": checked["planner"],
        "solvers": checked["solvers"],
        "workers": worker_status(db),
    }
