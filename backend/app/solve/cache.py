"""The result cache: a question already answered is not solved again.

A run's answer is decided by the model it solves (the version's `ir_hash`),
the data it froze (the dataset's `data_hash`), the scenario's patch, and the
settings that change what counts as the answer: the solver asked for, the
seed, the gap accepted, whether CP-SAT may take a scaled model, and the
compiler that turned the model into rows. `key_of` hashes exactly those.
Not the time limit or the thread count: a *proven* optimum does not depend
on how long it was given or how many threads found it.

Only a proven global optimum is reused (`status = 'optimal'` and
`optimality = 'global'`): a time-limited answer is a hint, not an answer,
and an infeasible verdict is re-derived with its explanation rather than
copied. A reuse is a new run -- already finished, `reused_from` pointing at
the one that was solved, the answer and the rules' results copied, no queue
entry and no solve -- so the history still shows every question asked
(target roadmap Phase 12, migration 0042).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


def key_of(
    *,
    ir_hash: str,
    data_hash: str,
    patch: dict[str, Any] | None,
    solver: str | None,
    seed: int,
    gap_rel: float,
    cpsat_scaling: bool,
    compiler_version: str,
) -> str:
    material = {
        "ir": ir_hash,
        "data": data_hash,
        "patch": patch or {},
        "solver": solver,
        "seed": seed,
        "gap_rel": gap_rel,
        "cpsat_scaling": cpsat_scaling,
        "compiler": compiler_version,
    }
    return hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def reuse(db: Session, *, key: str, scenario_id: int, dataset_id: int, params: dict[str, Any]) -> int | None:
    """Record a new run answered by the newest proven optimum under `key`,
    and return its id -- or None when there is none to reuse."""
    found = db.execute(
        text(
            "SELECT id, params FROM run"
            " WHERE cache_key = :k AND status = 'optimal' AND optimality = 'global'"
            " ORDER BY id DESC LIMIT 1"
        ),
        {"k": key},
    ).mappings().one_or_none()
    if found is None:
        return None
    original = found["id"]
    # The original's record of how it was solved (why this solver, the
    # objective terms, reformulations), under this submit's own request.
    params_json = json.dumps({**(found["params"] or {}), **params, "reused_from": original}, default=str)
    run_id = db.execute(
        text(
            "INSERT INTO run (scenario_id, dataset_id, status, solver, solver_version, compiler_version,"
            "                 params, seed, objective, optimality, best_bound, gap, wall_time_s,"
            "                 started_at, finished_at, cache_key, reused_from)"
            " SELECT :s, :d, status, solver, solver_version, compiler_version,"
            "        CAST(:params AS jsonb), seed, objective, optimality, best_bound, gap, 0,"
            "        now(), now(), cache_key, id"
            "   FROM run WHERE id = :o"
            " RETURNING id"
        ),
        {"s": scenario_id, "d": dataset_id, "params": params_json, "o": original},
    ).scalar_one()
    db.execute(
        text(
            "INSERT INTO solution (run_id, assignments, reduced_costs, amounts, ranges)"
            " SELECT :r, assignments, reduced_costs, amounts, ranges FROM solution WHERE run_id = :o"
        ),
        {"r": run_id, "o": original},
    )
    db.execute(
        text(
            "INSERT INTO constraint_result (run_id, constraint_id, label, hard, satisfied, total_violation,"
            "                               penalty_paid, violations, slack, dual)"
            " SELECT :r, constraint_id, label, hard, satisfied, total_violation,"
            "        penalty_paid, violations, slack, dual"
            "   FROM constraint_result WHERE run_id = :o"
        ),
        {"r": run_id, "o": original},
    )
    return run_id
