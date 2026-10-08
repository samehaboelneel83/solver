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


#: How many places an empty-range finding names before "and N more".
_NAMED = 5


def empty_range_findings(empties: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One finding per rule and kind of range, however many of its instances matched nobody: a rule
    filtered to the few sites inside an outage area matches nobody at every other site, and fifteen
    lines saying so hide everything else. `detail` is the first instance, `instances` all of them."""
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for empty in empties:
        grouped.setdefault((str(empty.get("constraint_id", "A rule")), str(empty.get("kind", "range"))), []).append(empty)
    out = []
    for (rule, kind), items in grouped.items():
        places = [", ".join(f"{k} = {v}" for k, v in (e.get("index") or {}).items()) for e in items]
        places = [p for p in places if p]
        if len(items) == 1:
            where = f" (at {places[0]})" if places else ""
            says = f"{rule} has a {kind} that matches nobody{where}: it holds vacuously or counts as zero, often a data gap."
        else:
            named = "; ".join(places[:_NAMED]) + (f"; and {len(places) - _NAMED} more" if len(places) > _NAMED else "")
            says = (f"{rule} has a {kind} that matches nobody at {len(items)} places ({named}): there it holds vacuously "
                    "or counts as zero. Expected when the rule only concerns some of them; otherwise a data gap.")
        out.append(_finding("warning", "empty_range", says, detail=items[0], instances=len(items)))
    return out


_HOLDS = {"<=": lambda a, b: a <= b, ">=": lambda a, b: a >= b, "=": lambda a, b: a == b}


def _never_holds(compiled: Any) -> dict[str, list[Any]]:
    """Hard, unconditional rule instances with no decision left in either side
    whose numbers break the relation, by rule id. Soft rules carry a violation
    variable, so they are never constant and never listed."""
    out: dict[str, list[Any]] = {}
    for rule in compiled.constraints:
        if (rule.schedule is not None or rule.when is not None or rule.chance is not None or rule.quadratic
                or not rule.left.is_constant or not rule.right.is_constant):
            continue
        holds = _HOLDS.get(rule.relation)
        if holds is not None and not holds(rule.left.const, rule.right.const):
            out.setdefault(rule.id, []).append(rule)
    return out


def _num(value: Any) -> str:
    return format(value.normalize(), "f") if hasattr(value, "normalize") else str(value)


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


def data_findings(db: Session, domain_id: int, ir: dict[str, Any]) -> list[dict[str, Any]]:
    """Gaps in the data a model reads that no compiler sees (improvement plan 5.5): a parameter
    nobody has filled (every cell its default), and one computed from the map that left places out
    or is older than the places it was computed from."""
    names = list((ir.get("parameters") or {}).keys())
    if not names:
        return []
    rows = db.execute(text(
        "SELECT p.name, p.default_value, p.source, p.index_type_ids,"
        "       (SELECT count(*) FROM parameter_value v WHERE v.parameter_def_id = p.id) AS stored"
        "  FROM parameter_def p WHERE p.domain_id = :d AND p.name = ANY(:n)"), {"d": domain_id, "n": names}).mappings().all()
    out: list[dict[str, Any]] = []
    for row in rows:
        source = row["source"] or {}
        if row["stored"] == 0 and not source and (ir["parameters"].get(row["name"]) or {}).get("index"):
            out.append(_finding("warning", "parameter_unfilled",
                                f"{row['name']} has no values yet, so every cell is its default {_num(row['default_value'])}. "
                                "Fill it in under Data values, upload a file, or compute it from the map.",
                                parameter=row["name"]))
        missing = source.get("missing") or []
        if missing:
            out.append(_finding("warning", "computed_without_places",
                                f"{row['name']} was computed from the map without {len(missing)} "
                                f"{'record' if len(missing) == 1 else 'records'} that had no shape ({', '.join(map(str, missing[:5]))}"
                                f"{'…' if len(missing) > 5 else ''}): their cells are the default.",
                                parameter=row["name"], missing=missing[:50]))
        computed_at = source.get("computed_at")
        if source.get("shapes") and row["index_type_ids"]:
            # Where the places are, not when a record was last touched: a new field (a height, a
            # count) written on the same records is not a move.
            from app.spatial.ops import shapes_fingerprint

            if shapes_fingerprint(db, list(row["index_type_ids"])) != source["shapes"]:
                out.append(_finding("warning", "computed_stale",
                                    f"{row['name']} was computed from the map before some of its places moved, "
                                    "were added or were removed; compute it again (Data › Parameters › its “Compute again”) so it matches where they are now.",
                                    parameter=row["name"]))
        elif computed_at and row["index_type_ids"]:
            newer = db.execute(text(
                "SELECT count(*) FROM entity WHERE entity_type_id = ANY(:t) AND updated_at > CAST(:c AS timestamptz)"),
                {"t": list(row["index_type_ids"]), "c": computed_at}).scalar_one()
            if newer:
                out.append(_finding("warning", "computed_stale",
                                    f"{row['name']} was computed from the map before {newer} of its records changed; "
                                    "compute it again (Data › Parameters › its “Compute again”) so it matches where they are now.",
                                    parameter=row["name"]))
    return out


def model_findings(db: Session, domain_id: int, problem_id: int, ir: dict[str, Any],
                   patch: dict[str, Any] | None = None) -> dict[str, Any]:
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
                   if not any(k in c for k in ("left", "no_overlap", "cumulative", "connected", "route", "place"))]
    if unexpressed:
        findings.append(_finding("blocker", "rule_not_expressed",
                                 f"{', '.join(map(str, unexpressed))} {'has' if len(unexpressed) == 1 else 'have'} a name but no arithmetic, "
                                 "so nothing can check them. Express them in the Model editor and publish a new version.",
                                 rules=unexpressed))

    data = live_data(db, domain_id, ir)
    # A scenario's data what-ifs (records left out, numbers scaled or set) as the run will apply them,
    # so "Y1 is flooded" is checked here -- not found only after solving.
    from app.solve import whatif

    if whatif.has_data_changes(patch):
        data = whatif.apply(data, ir, patch)
    from app.solve.service import empty_decision_sets, empty_relationships

    for name in empty_relationships(ir, data):
        rel = name.removeprefix("relationship ")
        findings.append(_finding("blocker", "relationship_empty",
                                 f"The relationship {rel} has no links, and the model walks it: load them before solving.",
                                 relationship=rel))
    blocking = set(empty_decision_sets(ir, data))
    for name in ir.get("sets", []):
        if not data.get("sets", {}).get(name):
            # A set the decisions range over blocks Solve (the run would be refused); one only rules read warns.
            findings.append(_finding("blocker" if name in blocking else "warning", "set_empty",
                                     f"There are no {name} records yet, so every rule and decision over {name} is empty"
                                     + (": load them before solving." if name in blocking else "."), set=name))

    findings += data_findings(db, domain_id, ir)

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
    structure = None
    try:
        compiled = compile_model(ir, data)
    except Unsupported as exc:
        if not (missing and "so the term has no value" in str(exc)):
            findings.append(_finding("blocker", "does_not_compile", str(exc)))
    except Exception as exc:  # pragma: no cover -- a compiler bug is still a finding, not a 500
        findings.append(_finding("blocker", "does_not_compile", f"The model could not be built: {exc}"))

    findings += empty_range_findings(compiled.empty_ranges if compiled is not None else [])

    if compiled is not None:
        from app.solve.blocks import structure as decomposition_structure

        structure = decomposition_structure(compiled)

    # A hard rule that, on today's data, comes to numbers alone -- a sum that matched
    # nobody counts as 0, so "protein >= 20" reads 0 >= 20 -- and those numbers break it.
    # No plan can meet it, so a solve would only come back infeasible: say so first.
    for rule_id, broken in (_never_holds(compiled) if compiled is not None else {}).items():
        first = broken[0]
        where = ", ".join(f"{k} = {v}" for k, v in first.index.items())
        findings.append(_finding(
            "blocker", "rule_never_holds",
            f"{rule_id} can never hold{f' (at {where})' if where else ''}: on today's data it reads "
            f"{_num(first.left.const)} {first.relation} {_num(first.right.const)}, with no decision left in it"
            f"{'' if len(broken) == 1 else f', and so do {len(broken) - 1} more of its instances'}. "
            "No plan can meet it, so solving would only report infeasible. Usually a range that matches "
            "nobody: add the records it counts, or fix what the rule sums over.",
            rule=rule_id, instances=len(broken)))

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
        "structure": structure,
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

    checked = model_findings(db, scenario["domain_id"], scenario["problem_id"], ir, scenario["patch"] or {})
    findings.extend(checked["findings"])
    return {
        "scenario_id": scenario_id,
        "version": scenario["version"],
        "ready": not any(f["kind"] == "blocker" for f in findings),
        "findings": findings,
        "model_class": checked["model_class"],
        "planner": checked["planner"],
        "solvers": checked["solvers"],
        "structure": checked["structure"],
        "workers": worker_status(db),
    }
