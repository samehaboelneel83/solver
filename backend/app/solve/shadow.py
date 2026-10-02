"""Shadow runs (queue R31): a candidate model version answers a share of real runs beside the one in
use, so its answers are seen on real questions before anyone relies on them.

When a plan run is queued and its problem names a candidate (`shadow.version`) and a share
(`shadow.rate`), the run is -- at that rate -- asked again of the candidate: a twin with
`purpose = 'shadow'` and `parent_run_id` the real run, on the same frozen dataset and the same
patch, filed under the candidate's `checks: version N` scenario, claimed after every plan and
question (queue R30), never in the planner's list. The share is decided per run from its id, so
which runs are shadowed is reproducible. A candidate that has not passed its problem's acceptance
cases is not shadowed; the real run records why.

When both have settled, the twin's `verdict` compares them: each status, the objective difference
(candidate minus real) and whether the candidate did at least as well for the goal's sense, the time
ratio, and how many chosen cells differ. A candidate that fails -- does not compile, errors -- is a
failed shadow, never an error on the real run. Cancelling the real run cancels its twin.
"""

from __future__ import annotations

import json
import statistics
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

#: The multiplier that spreads run ids over [0, 1) (Knuth's), for a reproducible share.
_SPREAD = 2654435761


def picked(run_id: int, rate: float) -> bool:
    """Whether a run is one of the share shadowed."""
    if rate <= 0:
        return False
    if rate >= 1:
        return True
    return ((run_id * _SPREAD) % 2**32) / 2**32 < rate


def twin(db: Session, run_id: int, problem_id: int, current_version: int, patch: dict, params: dict,
         settings) -> dict[str, Any] | None:
    """Queue the real run's twin when the settings ask for one. Returns what the real run records:
    `{"shadow_run": id}`, `{"shadow_skipped": why}`, or None when shadowing is off."""
    candidate = int(settings["shadow.version"].value or 0)
    rate = float(settings["shadow.rate"].value or 0)
    if candidate == 0 or rate <= 0:
        return None
    if not picked(run_id, rate):
        return None
    owner = db.execute(text("SELECT problem_id FROM model_version WHERE id = :v"), {"v": candidate}).scalar_one_or_none()
    if owner != problem_id:
        return {"shadow_skipped": f"shadow.version {candidate} is not a version of this problem"}
    if candidate == current_version:
        return {"shadow_skipped": "the candidate is the version this run already asks"}
    from app.solve import suite

    state = suite.version_checks(db, candidate)["state"]
    if state not in ("passed", "no cases"):
        return {"shadow_skipped": f"the candidate has not passed this problem's acceptance cases ({state})"}
    scenario = suite.checks_scenario(db, candidate)
    kept = {k: v for k, v in params.items() if k not in ("trace", "classified_as", "why", "needs", "warm_start")}
    shadow_params = {**kept, "case_patch": patch, "shadow_of": run_id, "model_version_id": candidate, "warm_start": False}
    shadow_id = db.execute(
        text(
            "INSERT INTO run (scenario_id, dataset_id, status, solver, compiler_version, params, seed, purpose, parent_run_id)"
            " SELECT :s, dataset_id, 'queued', solver, compiler_version, CAST(:p AS jsonb), seed, 'shadow', id"
            "   FROM run WHERE id = :r RETURNING id"
        ),
        {"s": scenario, "p": json.dumps(shadow_params), "r": run_id},
    ).scalar_one()
    return {"shadow_run": int(shadow_id)}


def settle(db: Session, run_id: int) -> None:
    """Compare a settled run with its twin once both have settled -- called when either settles."""
    row = db.execute(text("SELECT purpose, parent_run_id FROM run WHERE id = :r"), {"r": run_id}).mappings().one_or_none()
    if row is None:
        return
    if row["purpose"] == "shadow":
        pairs = [(row["parent_run_id"], run_id)]
    elif row["purpose"] == "plan":
        pairs = [(run_id, s) for s in db.execute(
            text("SELECT id FROM run WHERE parent_run_id = :r AND purpose = 'shadow'"), {"r": run_id}).scalars()]
    else:
        return
    for real, candidate in pairs:
        _compare(db, real, candidate)


def _compare(db: Session, real_id: int, shadow_id: int) -> None:
    runs = {
        r["id"]: r for r in db.execute(
            text(
                "SELECT r.id, r.status, r.objective, r.wall_time_s, r.error, so.assignments, mv.ir -> 'objective' ->> 'sense' AS sense"
                "  FROM run r JOIN scenario s ON s.id = r.scenario_id"
                "  JOIN model_version mv ON mv.id = r.model_version_id"
                "  LEFT JOIN solution so ON so.run_id = r.id WHERE r.id IN (:a, :b)"
            ),
            {"a": real_id, "b": shadow_id},
        ).mappings()
    }
    real, candidate = runs.get(real_id), runs.get(shadow_id)
    if real is None or candidate is None or any(r["status"] in ("queued", "running") for r in (real, candidate)):
        return
    verdict: dict[str, Any] = {"real": {"status": real["status"], "objective": _num(real["objective"])},
                               "shadow": {"status": candidate["status"], "objective": _num(candidate["objective"]),
                                          **({"error": candidate["error"][:500]} if candidate["error"] else {})},
                               "same_status": real["status"] == candidate["status"]}
    if real["objective"] is not None and candidate["objective"] is not None:
        delta = float(candidate["objective"]) - float(real["objective"])
        sense = real["sense"] or "minimize"
        slack = 1e-6 * max(1.0, abs(float(real["objective"])))
        verdict["delta"] = round(delta, 6)
        verdict["at_least_as_good"] = delta <= slack if sense == "minimize" else delta >= -slack
    if real["wall_time_s"] and candidate["wall_time_s"] is not None:
        verdict["time_ratio"] = round(float(candidate["wall_time_s"]) / max(float(real["wall_time_s"]), 1e-3), 3)
    if real["assignments"] is not None and candidate["assignments"] is not None:
        cells = lambda a: {(n, *row) for n, rows in a.items() for row in rows}  # noqa: E731
        verdict["moved"] = len(cells(real["assignments"]) ^ cells(candidate["assignments"]))
    db.execute(text("UPDATE run SET verdict = CAST(:v AS jsonb) WHERE id = :r"), {"v": json.dumps(verdict), "r": shadow_id})
    db.commit()


def report(db: Session, problem_id: int, limit: int = 20) -> dict[str, Any]:
    """The candidate's record on this problem's real runs, each candidate version apart."""
    rows = db.execute(
        text(
            "SELECT r.id, r.parent_run_id, r.status, r.verdict, (r.params ->> 'model_version_id')::bigint AS version_id"
            "  FROM run r JOIN scenario s ON s.id = r.scenario_id"
            " WHERE r.purpose = 'shadow' AND s.problem_id = :p ORDER BY r.id DESC"
        ),
        {"p": problem_id},
    ).mappings().all()
    versions: dict[int, dict[str, Any]] = {}
    for r in rows:
        v = versions.setdefault(r["version_id"], {"model_version_id": r["version_id"], "runs": 0, "compared": 0,
                                                 "at_least_as_good": 0, "worst": None, "ratios": [], "recent": []})
        v["runs"] += 1
        verdict = r["verdict"] or {}
        if verdict:
            v["compared"] += 1
            if verdict.get("at_least_as_good") or (verdict.get("delta") is None and verdict.get("same_status")):
                v["at_least_as_good"] += 1
            elif v["worst"] is None or abs(verdict.get("delta") or 0) > abs(v["worst"].get("delta") or 0):
                v["worst"] = {"real_run": r["parent_run_id"], "shadow_run": r["id"], **verdict}
            if verdict.get("time_ratio") is not None:
                v["ratios"].append(verdict["time_ratio"])
        if len(v["recent"]) < limit:
            v["recent"].append({"real_run": r["parent_run_id"], "shadow_run": r["id"], "status": r["status"], "verdict": verdict})
    out = []
    for v in versions.values():
        ratios = v.pop("ratios")
        v["median_time_ratio"] = statistics.median(ratios) if ratios else None
        v["share_at_least_as_good"] = round(v["at_least_as_good"] / v["compared"], 3) if v["compared"] else None
        out.append(v)
    return {"problem_id": problem_id, "candidates": out}


def _num(value):
    if value is None:
        return None
    f = float(value)
    return int(f) if f == int(f) else f
