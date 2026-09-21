"""Run a scenario: freeze the data, solve, and record what happened.

This is the piece that makes solving a thing the *platform* does rather than
something a test calls. It fills the four tables migration 0007 created and
nothing has written to since: `dataset`, `run`, `solution`,
`constraint_result`.

**Reproducibility is the point of the shape.** A run points at an immutable
model version through its scenario, and at an immutable, content-hashed
dataset. It records the solver and its version, the time limit and the seed.
Two runs of the same triple are therefore comparable, and a result nobody can
attribute to a solver version is not a result (roadmap, Phase 3).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.solve.backends import NoBackend, choose
from app.solve.classify import classify
from app.solve.compile import _VIOLATION, Compiled, Unsupported, compile_model
from app.solve.diagnose import DEFAULT_PROBE_SECONDS, explain
from app.solve.result import Solution

COMPILER_VERSION = "ir-compiler 1"

# A constraint can break in many places; the row keeps the worst few rather
# than every instance, because a `constraint_result` is read by a person.
_MAX_REPORTED_VIOLATIONS = 20


@dataclass
class RunOutcome:
    run_id: int
    dataset_id: int
    status: str
    objective: int | None
    assignments: dict[str, list[list[str]]]


def enqueue_run(
    db: Session,
    scenario_id: int,
    *,
    time_limit: float = 10.0,
    seed: int = 1,
    solver: str | None = None,
) -> int:
    """Freeze the data and queue the work. Returns the run's id.

    **The snapshot happens here, not in the worker.** A run answers the
    question as it was asked: if an entity changes between submitting and
    solving, the answer must still be about the data the person was looking
    at. Freezing at submit is what makes that true, and it is why `run` can
    carry `dataset_id` before it carries a result.
    """
    scenario = db.execute(
        text(
            "SELECT s.id, s.model_version_id, s.patch, mv.ir"
            "  FROM scenario s JOIN model_version mv ON mv.id = s.model_version_id"
            " WHERE s.id = :s"
        ),
        {"s": scenario_id},
    ).mappings().one_or_none()
    if scenario is None:
        raise LookupError(f"scenario {scenario_id} not found")

    dataset_id = db.execute(
        text("SELECT snapshot_dataset(:v)"), {"v": scenario["model_version_id"]}
    ).scalar_one()

    found = classify(patched(scenario["ir"], scenario["patch"] or {}))
    run_id = db.execute(
        text(
            "INSERT INTO run (scenario_id, dataset_id, status, solver, compiler_version,"
            "                 params, seed)"
            " VALUES (:s, :d, 'queued', 'cp-sat', :cv, :params, :seed)"
            " RETURNING id"
        ),
        {
            "s": scenario_id,
            "d": dataset_id,
            "cv": COMPILER_VERSION,
            "params": _json(
                {
                    "time_limit_s": time_limit,
                    "classified_as": found.model_class,
                    "why": found.reasons,
                    "needs": sorted(found.needs),
                    **({"requested_solver": solver} if solver else {}),
                }
            ),
            "seed": seed,
        },
    ).scalar_one()
    db.commit()
    return run_id


def claim_next(db: Session) -> int | None:
    """Take the oldest queued run, or nothing.

    `FOR UPDATE SKIP LOCKED` is what makes a second worker safe: it takes the
    next row rather than waiting on the one already being claimed, so two
    workers never solve the same run and neither blocks the other.
    """
    run_id = db.execute(
        text(
            "SELECT id FROM run WHERE status = 'queued'"
            " ORDER BY queued_at, id FOR UPDATE SKIP LOCKED LIMIT 1"
        )
    ).scalar_one_or_none()
    if run_id is None:
        db.rollback()
        return None
    db.execute(
        text("UPDATE run SET status = 'running', started_at = now() WHERE id = :r"),
        {"r": run_id},
    )
    db.commit()
    return run_id


def execute_run(db: Session, run_id: int) -> RunOutcome:
    """Solve a claimed run and record what happened."""
    row = db.execute(
        text(
            "SELECT r.dataset_id, r.params, s.patch, mv.ir, d.data"
            "  FROM run r"
            "  JOIN scenario s ON s.id = r.scenario_id"
            "  JOIN model_version mv ON mv.id = s.model_version_id"
            "  JOIN dataset d ON d.id = r.dataset_id"
            " WHERE r.id = :r"
        ),
        {"r": run_id},
    ).mappings().one()

    ir = patched(row["ir"], row["patch"] or {})
    data = row["data"]
    params = row["params"] or {}
    time_limit = float(params.get("time_limit_s", 10.0))
    dataset_id = row["dataset_id"]

    found = classify(ir)
    try:
        backend, why = choose(found, params.get("requested_solver"))
    except NoBackend as exc:
        db.execute(
            text(
                "UPDATE run SET status = 'error', error = :e, finished_at = now() WHERE id = :r"
            ),
            {"e": str(exc), "r": run_id},
        )
        db.commit()
        return RunOutcome(run_id, dataset_id, "error", None, {})

    try:
        compiled = compile_model(ir, data)
        result = backend.solve(compiled, time_limit=time_limit, workers=8)
    except Unsupported as exc:
        # The model is valid and this compiler cannot express it. That is a
        # failed run with a reason, not a crash and not an empty answer.
        db.execute(
            text(
                "UPDATE run SET status = 'error', error = :e, finished_at = now()"
                " WHERE id = :r"
            ),
            {"e": str(exc), "r": run_id},
        )
        db.commit()
        return RunOutcome(run_id, dataset_id, "error", None, {})

    # Which solver ran, and why it was the one -- a result nobody can
    # attribute to a choice is not reproducible.
    db.execute(
        text(
            "UPDATE run SET solver = :s, params = params || CAST(:extra AS jsonb)"
            " WHERE id = :r"
        ),
        {"s": backend.name, "extra": _json({"chosen_solver": backend.name, "why_solver": why}), "r": run_id},
    )
    _record(db, run_id, compiled, result)
    if result.status == "infeasible":
        # "No answer exists" is true and useless on its own. Which rules
        # cannot hold together is the thing a planner can act on, and it is
        # only findable here, where the compiled model still exists.
        _record_conflict(db, run_id, compiled, backend, time_limit)
    db.commit()
    return RunOutcome(
        run_id,
        dataset_id,
        result.status,
        result.objective,
        _assignments(compiled, result),
    )


def run_scenario(
    db: Session, scenario_id: int, *, time_limit: float = 10.0, seed: int = 1
) -> RunOutcome:
    """Queue a run and solve it here and now.

    Kept for the seed, the tests and anything without a worker: it is
    `enqueue_run` followed immediately by `execute_run`, so it exercises the
    same path the worker takes rather than a second one that could drift.
    """
    run_id = enqueue_run(db, scenario_id, time_limit=time_limit, seed=seed)
    db.execute(
        text("UPDATE run SET status = 'running', started_at = now() WHERE id = :r"), {"r": run_id}
    )
    return execute_run(db, run_id)


def patched(ir: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Apply a scenario's patch to a model.

    `ProblemIR.patched()`'s three verbs, and what each one means here:
    `disable` drops a constraint, `harden` makes a soft one hard, and
    `soften` makes a hard one soft at the given penalty. The ids were checked
    against this version when the scenario was created, so an unknown id
    cannot arrive here.
    """
    if not patch:
        return ir
    disabled = set(patch.get("disable", []))
    hardened = set(patch.get("harden", []))
    softened = patch.get("soften", {}) or {}

    constraints = []
    for spec in ir.get("constraints", []):
        if spec["id"] in disabled:
            continue
        spec = dict(spec)
        if spec["id"] in hardened:
            spec["severity"] = "hard"
            spec.pop("penalty", None)
        elif spec["id"] in softened:
            spec["severity"] = "soft"
            spec["penalty"] = int(softened[spec["id"]])
        constraints.append(spec)
    return {**ir, "constraints": constraints}


def _record(db: Session, run_id: int, compiled: Compiled, result: Solution) -> None:
    solved = result.status in ("optimal", "feasible")
    db.execute(
        text(
            "UPDATE run SET status = :st, solver_version = :sv, objective = :obj,"
            "               wall_time_s = :wall, finished_at = now()"
            " WHERE id = :r"
        ),
        {
            "st": result.status,
            "sv": result.solver,
            "obj": result.objective,
            "wall": result.wall_seconds,
            "r": run_id,
        },
    )

    if not solved:
        return

    db.execute(
        text("INSERT INTO solution (run_id, assignments) VALUES (:r, :a)"),
        {"r": run_id, "a": _json(_assignments(compiled, result))},
    )

    # One row per constraint, including the satisfied ones: "which rules held"
    # is as much a part of the answer as the roster, and a missing row would
    # be indistinguishable from a rule nobody checked.
    seen: dict[str, dict[str, Any]] = {}
    for spec_id in dict.fromkeys(c.id for c in compiled.constraints):
        seen[spec_id] = {"hard": True, "total": 0, "penalty": 0, "where": []}

    for spec_id, keys in compiled.violations.items():
        entry = seen.setdefault(spec_id, {"hard": True, "total": 0, "penalty": 0, "where": []})
        entry["hard"] = False
        for key in keys:
            amount = result.assignments.get(key, 0)
            if amount:
                entry["total"] += amount
                entry["where"].append({"index": list(key[1][1:]), "by": amount})
        entry["penalty"] = entry["total"] * compiled.penalty_of.get(spec_id, 0)
        entry["where"].sort(key=lambda v: -v["by"])
        entry["where"] = entry["where"][:_MAX_REPORTED_VIOLATIONS]

    for spec_id, entry in seen.items():
        db.execute(
            text(
                "INSERT INTO constraint_result"
                " (run_id, constraint_id, label, hard, satisfied, total_violation,"
                "  penalty_paid, violations)"
                " VALUES (:r, :c, :l, :hard, :sat, :total, :pen, :v)"
            ),
            {
                "r": run_id,
                "c": spec_id,
                "l": spec_id,
                "hard": entry["hard"],
                "sat": entry["total"] == 0,
                "total": entry["total"],
                "pen": entry["penalty"],
                "v": _json(entry["where"]),
            },
        )


def _record_conflict(
    db: Session, run_id: int, compiled: Compiled, backend: Any, time_limit: float
) -> None:
    """Diagnose an infeasible run with the same backend that called it
    infeasible, so the explanation cannot disagree with the verdict.

    The probe clock is a fraction of the run's, not the whole of it: a
    diagnosis that took longer than the solve would be a second run wearing a
    different name.
    """
    conflict = explain(
        compiled,
        backend.solve,
        probe_seconds=min(DEFAULT_PROBE_SECONDS, max(1.0, time_limit / 4)),
    )
    db.execute(
        text(
            "UPDATE run SET conflict = :c, conflict_minimal = :m,"
            "               params = params || CAST(:note AS jsonb)"
            " WHERE id = :r"
        ),
        {
            "c": _json(conflict.items),
            "m": conflict.minimal,
            "note": _json({"conflict_note": conflict.note}),
            "r": run_id,
        },
    )


def _assignments(compiled: Compiled, result: Solution) -> dict[str, list[list[str]]]:
    """The answer in the domain's own words: which index tuples each variable
    took. Violation variables are not part of the roster and are reported
    through `constraint_result` instead."""
    out: dict[str, list[list[str]]] = {name: [] for name in compiled.var_index_sets}
    for (name, index), value in sorted(result.assignments.items()):
        if name != _VIOLATION and value:
            out.setdefault(name, []).append(list(index))
    return out


def _json(value: Any) -> str:
    import json

    return json.dumps(value)
