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


def queue(
    db: Session,
    case_id: int,
    model_version_id: int | None = None,
    *,
    max_seconds: float | None = None,
    night: str | None = None,
) -> int:
    """Queue a case against a version (the problem's newest when none is named); the run's id.

    Suite runs never take the result cache: they insert without a `cache_key`, so a night that
    re-asks the same question always solves it again (queue R32).
    """
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

    limit = float(case["expect"].get("max_seconds", MIN_SECONDS))
    if max_seconds is not None:
        limit = min(limit, float(max_seconds))
    params: dict[str, Any] = {
        "time_limit_s": limit,
        "workers": 8,
        "gap_rel": 0.0,
        "case_id": case_id,
        "case_patch": case["patch"] or {},
        "model_version_id": model_version_id,
    }
    if night is not None:
        params["nightly"] = night
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


# -- the gate (queue R30) ----------------------------------------------------------------


def version_checks(db: Session, model_version_id: int) -> dict[str, Any]:
    """Where a version stands against its problem's cases: each case's latest run on this version,
    and overall -- `no cases`, `unchecked` (a case never run on it), `checking` (one still running),
    `failed` (one failed) or `passed` (every one passed).

    A case that passed the previous night's CI and fails tonight carries `nightly_regressed`
    (queue R32), so the Checks panel can mark it red with both nights' reasons.
    """
    problem = db.execute(text("SELECT problem_id FROM model_version WHERE id = :v"), {"v": model_version_id}).scalar_one_or_none()
    if problem is None:
        raise NotACase("case_no_version", f"model version {model_version_id} not found", 404)
    rows = db.execute(
        text(
            "SELECT c.id, c.name, r.id AS run_id, r.status, r.verdict"
            "  FROM suite_case c"
            "  LEFT JOIN LATERAL (SELECT id, status, verdict FROM run"
            "                      WHERE purpose = 'suite' AND (params ->> 'case_id')::bigint = c.id"
            "                        AND (params ->> 'model_version_id')::bigint = :v"
            "                      ORDER BY id DESC LIMIT 1) r ON true"
            " WHERE c.problem_id = :p ORDER BY c.name, c.id"
        ),
        {"p": problem, "v": model_version_id},
    ).mappings().all()
    regressions = _nightly_regressions(db, model_version_id)
    cases = []
    for row in rows:
        verdict = row["verdict"] or {}
        state = ("unchecked" if row["run_id"] is None else
                 "checking" if row["status"] in ("queued", "running") or not verdict else
                 "passed" if verdict.get("passed") else "failed")
        reasons = list(verdict.get("reasons", []))
        regressed = row["id"] in regressions
        if regressed and state == "passed":
            # Tonight's suite run may not yet be the latest night's row; still flag it.
            state = "failed"
        if regressed:
            reasons = regressions[row["id"]] + reasons
        cases.append({"case_id": row["id"], "name": row["name"], "run_id": row["run_id"], "state": state,
                      "reasons": reasons, "nightly_regressed": regressed})
    states = {c["state"] for c in cases}
    overall = ("no cases" if not cases else "failed" if "failed" in states else "checking" if "checking" in states
               else "unchecked" if "unchecked" in states else "passed")
    return {"model_version_id": model_version_id, "state": overall, "cases": cases}


def _nightly_regressions(db: Session, model_version_id: int) -> dict[int, list[str]]:
    """case_id -> reasons, for cases that passed the previous night and failed the latest night."""
    rows = db.execute(
        text(
            "SELECT case_id, night, passed, reasons FROM suite_nightly"
            " WHERE model_version_id = :v"
            " ORDER BY case_id, night DESC"
        ),
        {"v": model_version_id},
    ).mappings().all()
    by_case: dict[int, list] = {}
    for row in rows:
        by_case.setdefault(row["case_id"], []).append(row)
    out: dict[int, list[str]] = {}
    for case_id, nights in by_case.items():
        if len(nights) < 2:
            continue
        today, yesterday = nights[0], nights[1]
        if today["passed"] is False and yesterday["passed"] is True:
            reasons = list(today["reasons"] or [])
            out[case_id] = [
                "passed last night, fails tonight"
                + (f" ({'; '.join(reasons)})" if reasons else ""),
            ]
    return out


def published_version(db: Session, problem_id: int) -> int | None:
    """The version a planner's scenario of this problem points at (highest version number), or None."""
    return db.execute(
        text(
            "SELECT mv.id FROM model_version mv"
            "  JOIN scenario s ON s.model_version_id = mv.id"
            " WHERE mv.problem_id = :p AND s.name NOT LIKE 'checks: version %'"
            " ORDER BY mv.version DESC LIMIT 1"
        ),
        {"p": problem_id},
    ).scalar_one_or_none()


def nightly(
    db: Session,
    *,
    night,
    max_seconds: float | None = None,
    problem_ids: list[int] | None = None,
) -> list[dict[str, Any]]:
    """Re-ask every case of each problem's published version, cache off; write `suite_nightly`.

    Does not publish or unpublish any version. Returns one row per case asked.
    """
    from app.solve.service import claim_next, execute_run

    night_s = night.isoformat() if hasattr(night, "isoformat") else str(night)
    if problem_ids is not None:
        problems = list(problem_ids)
    else:
        problems = list(
            db.execute(text("SELECT DISTINCT problem_id FROM suite_case ORDER BY problem_id")).scalars().all()
        )
    results: list[dict[str, Any]] = []
    for problem_id in problems:
        version_id = published_version(db, problem_id)
        if version_id is None:
            continue
        cases = db.execute(
            text("SELECT id FROM suite_case WHERE problem_id = :p ORDER BY id"),
            {"p": problem_id},
        ).scalars().all()
        for case_id in cases:
            run_id = queue(
                db, case_id, version_id, max_seconds=max_seconds, night=night_s
            )
            while (claimed := claim_next(db)) is not None:
                execute_run(db, claimed)
                if claimed == run_id:
                    break
            row = db.execute(
                text(
                    "SELECT status, objective, wall_time_s, verdict FROM run WHERE id = :r"
                ),
                {"r": run_id},
            ).mappings().one()
            verdict = row["verdict"] or {}
            passed = bool(verdict.get("passed"))
            reasons = list(verdict.get("reasons") or [])
            objective = row["objective"]
            db.execute(
                text(
                    "INSERT INTO suite_nightly"
                    " (night, problem_id, model_version_id, case_id, status, objective, seconds,"
                    "  passed, reasons)"
                    " VALUES (:n, :p, :v, :c, :st, :obj, :sec, :pass, CAST(:reasons AS jsonb))"
                    " ON CONFLICT (night, case_id, model_version_id) DO UPDATE SET"
                    "  status = EXCLUDED.status, objective = EXCLUDED.objective,"
                    "  seconds = EXCLUDED.seconds, passed = EXCLUDED.passed,"
                    "  reasons = EXCLUDED.reasons"
                ),
                {
                    "n": night,
                    "p": problem_id,
                    "v": version_id,
                    "c": case_id,
                    "st": row["status"],
                    "obj": objective,
                    "sec": row["wall_time_s"],
                    "pass": passed,
                    "reasons": json.dumps(reasons),
                },
            )
            db.commit()
            results.append(
                {
                    "night": night_s,
                    "problem_id": problem_id,
                    "model_version_id": version_id,
                    "case_id": case_id,
                    "status": row["status"],
                    "objective": _number(objective) if objective is not None else None,
                    "seconds": row["wall_time_s"],
                    "passed": passed,
                    "reasons": reasons,
                }
            )
    return results


def check_version(db: Session, model_version_id: int) -> list[int]:
    """Queue every case of the version's problem against it, except one already being checked."""
    current = version_checks(db, model_version_id)
    return [queue(db, c["case_id"], model_version_id) for c in current["cases"] if c["state"] != "checking"]


def gate(db: Session, problem_id: int, model_version_id: int) -> str | None:
    """Why this version may not be put into use yet, or None. Only a version no scenario of the
    problem uses yet is held back; a problem with no cases, or `suite.required` off, holds none."""
    in_use = db.execute(
        text("SELECT 1 FROM scenario WHERE problem_id = :p AND model_version_id = :v AND name NOT LIKE 'checks: version %'"),
        {"p": problem_id, "v": model_version_id},
    ).first()
    if in_use is not None:
        return None
    from app.settings_resolve import resolve

    if not bool(resolve(db, problem_id=problem_id)["suite.required"].value):
        return None
    checks = version_checks(db, model_version_id)
    if checks["state"] in ("no cases", "passed"):
        return None
    version = db.execute(text("SELECT version FROM model_version WHERE id = :v"), {"v": model_version_id}).scalar_one()
    detail = "; ".join(
        f"{c['name']}: {c['state']}" + (f" ({', '.join(c['reasons'])})" if c["reasons"] else "")
        for c in checks["cases"] if c["state"] != "passed"
    )
    return (f"version {version} has not passed this problem's acceptance cases ({checks['state']}) -- {detail}. "
            "Run its checks, loosen a case, or turn the setting suite.required off")
