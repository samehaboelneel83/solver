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

from app.solve.classify import classify
from app.solve.compile import _VIOLATION, Compiled, Unsupported, compile_model
from app.solve.cpsat import Solution, solve

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


def run_scenario(
    db: Session, scenario_id: int, *, time_limit: float = 10.0, seed: int = 1
) -> RunOutcome:
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
    data = db.execute(
        text("SELECT data FROM dataset WHERE id = :d"), {"d": dataset_id}
    ).scalar_one()

    ir = patched(scenario["ir"], scenario["patch"] or {})
    found = classify(ir)

    run_id = db.execute(
        text(
            "INSERT INTO run (scenario_id, dataset_id, status, solver, compiler_version,"
            "                 params, seed, started_at)"
            " VALUES (:s, :d, 'running', 'cp-sat', :cv, :params, :seed, now())"
            " RETURNING id"
        ),
        {
            "s": scenario_id,
            "d": dataset_id,
            "cv": COMPILER_VERSION,
            "params": _json({"time_limit_s": time_limit, "classified_as": found.model_class,
                             "why": found.reasons}),
            "seed": seed,
        },
    ).scalar_one()

    try:
        compiled = compile_model(ir, data)
        result = solve(compiled, time_limit=time_limit)
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

    _record(db, run_id, compiled, result)
    db.commit()
    return RunOutcome(
        run_id,
        dataset_id,
        result.status,
        result.objective,
        _assignments(compiled, result),
    )


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
