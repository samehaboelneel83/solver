"""A problem's acceptance cases (queue R29): questions with known answers, asked again of any model
version to show it still answers them.

A case is made from an answered run in one step: its frozen dataset, its scenario's patch, and its
answer as the expectation -- the status, the objective to 1e-6 relative (a person may loosen it),
and a time allowance. Running a case against a version queues a run with `purpose = 'suite'` on
the case's own dataset, under the version's `checks: version N` scenario (made once, patch empty:
the case's patch travels on the run, `params.case_patch`). When it settles, `settle` writes its
verdict: `passed`, and every reason it did not.

The dataset is the case's, never today's: a case asks the same question each time. A version that
reads something the frozen data lacks fails the case, and says so.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

#: The objective's tolerance a case made from a run starts with, relative.
DEFAULT_TOLERANCE = 1e-6
#: The least time a case is given, whatever its first answer took.
MIN_SECONDS = 30.0


class NotACase(Exception):
    """A case that cannot be made or run. `code` names why; `status` is the HTTP status."""

    def __init__(self, code: str, message: str, status: int = 422):
        super().__init__(message)
        self.code, self.status = code, status


def from_run(db: Session, run_id: int, name: str, by: str | None) -> int:
    """A case from an answered plan run: its data, its patch, its answer as what is expected."""
    run = db.execute(
        text(
            "SELECT r.status, r.objective, r.wall_time_s, r.dataset_id, r.purpose, s.problem_id, s.patch"
            "  FROM run r JOIN scenario s ON s.id = r.scenario_id WHERE r.id = :r"
        ),
        {"r": run_id},
    ).mappings().one_or_none()
    if run is None:
        raise NotACase("case_no_run", "run not found", 404)
    if run["purpose"] != "plan":
        raise NotACase("case_not_a_plan", f"run {run_id} is a question about a plan, not a plan", 409)
    if run["status"] not in ("optimal", "feasible", "infeasible", "unbounded"):
        raise NotACase("case_unanswered", f"run {run_id} has no answer to expect again (it is {run['status']})", 409)
    expect: dict[str, Any] = {
        "status": run["status"],
        "max_seconds": max(MIN_SECONDS, 3 * float(run["wall_time_s"] or 0)),
    }
    if run["objective"] is not None and run["status"] == "optimal":
        expect.update(objective=_number(run["objective"]), tolerance_rel=DEFAULT_TOLERANCE, tolerance_abs=0)
    return db.execute(
        text(
            "INSERT INTO suite_case (problem_id, name, dataset_id, patch, expect, created_from_run_id, created_by)"
            " VALUES (:p, :n, :d, CAST(:patch AS jsonb), CAST(:e AS jsonb), :r, :by) RETURNING id"
        ),
        {"p": run["problem_id"], "n": name, "d": run["dataset_id"], "patch": json.dumps(run["patch"] or {}),
         "e": json.dumps(expect), "r": run_id, "by": by},
    ).scalar_one()


def checks_scenario(db: Session, model_version_id: int) -> int:
    """The version's `checks: version N` scenario, made once: where its case runs are filed."""
    version = db.execute(
        text("SELECT problem_id, version FROM model_version WHERE id = :v"), {"v": model_version_id}
    ).mappings().one_or_none()
    if version is None:
        raise NotACase("case_no_version", f"model version {model_version_id} not found", 404)
    name = f"checks: version {version['version']}"
    found = db.execute(
        text("SELECT id FROM scenario WHERE problem_id = :p AND name = :n"), {"p": version["problem_id"], "n": name}
    ).scalar_one_or_none()
    if found is not None:
        return int(found)
    return int(db.execute(
        text("INSERT INTO scenario (problem_id, model_version_id, name) VALUES (:p, :v, :n) RETURNING id"),
        {"p": version["problem_id"], "v": model_version_id, "n": name},
    ).scalar_one())


def queue(db: Session, case_id: int, model_version_id: int | None = None) -> int:
    """Queue a case against a version (the problem's newest when none is named); the run's id."""
    case = db.execute(
        text("SELECT id, problem_id, dataset_id, patch, expect FROM suite_case WHERE id = :c"), {"c": case_id}
    ).mappings().one_or_none()
    if case is None:
        raise NotACase("case_not_found", "case not found", 404)
    if model_version_id is None:
        model_version_id = db.execute(
            text("SELECT id FROM model_version WHERE problem_id = :p ORDER BY version DESC LIMIT 1"),
            {"p": case["problem_id"]},
        ).scalar_one()
    owner = db.execute(text("SELECT problem_id FROM model_version WHERE id = :v"), {"v": model_version_id}).scalar_one_or_none()
    if owner != case["problem_id"]:
        raise NotACase("case_other_problem", f"model version {model_version_id} is not a version of this case's problem")
    scenario = checks_scenario(db, model_version_id)
    from app.solve.service import COMPILER_VERSION

    params = {"time_limit_s": float(case["expect"].get("max_seconds", MIN_SECONDS)), "workers": 8, "gap_rel": 0.0,
              "case_id": case_id, "case_patch": case["patch"] or {}, "model_version_id": model_version_id}
    run_id = db.execute(
        text(
            "INSERT INTO run (scenario_id, dataset_id, status, solver, compiler_version, params, seed, purpose)"
            " VALUES (:s, :d, 'queued', 'cp-sat', :cv, CAST(:params AS jsonb), 1, 'suite') RETURNING id"
        ),
        {"s": scenario, "d": case["dataset_id"], "cv": COMPILER_VERSION, "params": json.dumps(params)},
    ).scalar_one()
    db.commit()
    return int(run_id)


def judge(expect: dict[str, Any], status: str, objective: Decimal | None, error: str | None,
          wall: float | None, assignments: dict[str, list[list[str]]] | None) -> dict[str, Any]:
    """Passed, and every reason it did not."""
    reasons: list[str] = []
    if status != expect.get("status"):
        reasons.append(f"said {status}, expected {expect.get('status')}" + (f" ({error})" if error else ""))
    want = expect.get("objective")
    if want is not None and status == expect.get("status"):
        if objective is None:
            reasons.append(f"gave no objective, expected {want}")
        else:
            got, want = float(objective), float(want)
            allowed = max(float(expect.get("tolerance_abs", 0) or 0),
                          float(expect.get("tolerance_rel", DEFAULT_TOLERANCE) or 0) * max(1.0, abs(want)))
            if abs(got - want) > allowed:
                reasons.append(f"the objective is {_number(Decimal(str(got)))}, expected {_number(Decimal(str(want)))}"
                               f" within {allowed:g}")
    used = {(name, tuple(row)) for name, rows in (assignments or {}).items() for row in rows}
    for cell in expect.get("must_hold") or []:
        on = (cell["var"], tuple(str(k) for k in cell["index"])) in used
        if on != bool(cell.get("value", 1)):
            reasons.append(f"{cell['var']}{list(cell['index'])} is {'on' if on else 'off'}, expected "
                           f"{'on' if cell.get('value', 1) else 'off'}")
    limit = expect.get("max_seconds")
    if limit is not None and wall is not None and wall > float(limit):
        reasons.append(f"took {wall:.1f} s, allowed {float(limit):g} s")
    return {"passed": not reasons, "reasons": reasons}


def settle(db: Session, run_id: int) -> None:
    """Write a settled case run's verdict. Nothing for a run that is not one."""
    run = db.execute(
        text(
            "SELECT r.purpose, r.status, r.objective, r.error, r.wall_time_s, r.params, c.expect, so.assignments"
            "  FROM run r LEFT JOIN suite_case c ON c.id = (r.params ->> 'case_id')::bigint"
            "  LEFT JOIN solution so ON so.run_id = r.id WHERE r.id = :r"
        ),
        {"r": run_id},
    ).mappings().one_or_none()
    if run is None or run["purpose"] != "suite":
        return
    if run["expect"] is None:
        verdict = {"passed": False, "reasons": ["its case was deleted"]}
    else:
        verdict = judge(run["expect"], run["status"], run["objective"], run["error"], run["wall_time_s"], run["assignments"])
    verdict["case_id"] = (run["params"] or {}).get("case_id")
    db.execute(text("UPDATE run SET verdict = CAST(:v AS jsonb) WHERE id = :r"), {"v": json.dumps(verdict), "r": run_id})
    db.commit()


def _number(value) -> int | float:
    value = Decimal(str(value))
    return int(value) if value == value.to_integral_value() else float(value)
