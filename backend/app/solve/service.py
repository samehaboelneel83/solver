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

import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any, Iterator

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.solve.backends import NoBackend, choose, optimality_of
from app.solve.classify import classify
from app.solve.convexity import refine
from app.solve.compile import (
    _VIOLATION,
    DEFAULT_UPPER,
    Compiled,
    Constraint,
    Linear,
    Unsupported,
    compile_model,
    number,
    slack_by_constraint,
)
from app.solve.diagnose import DEFAULT_PROBE_SECONDS, explain
from app.solve.result import Solution
from app.settings_resolve import resolve

COMPILER_VERSION = "ir-compiler 1"

# A constraint can break in many places; the row keeps the worst few rather
# than every instance, because a `constraint_result` is read by a person.
_MAX_REPORTED_VIOLATIONS = 20

# How often a running worker says it is still alive. Reclaim is a multiple
# of this, not of the time limit: a slow solve that heartbeats is not stale.
HEARTBEAT_SECONDS = float(os.environ.get("WORKER_HEARTBEAT_SECONDS", "2.0"))


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
    time_limit: float | None = None,
    seed: int | None = None,
    solver: str | None = None,
) -> int:
    """Freeze the data and queue the work. Returns the run's id.

    **What is not given is resolved, not hardcoded.** The time limit, the seed
    and the solver come from settings when the caller does not name them --
    problem, then domain, then platform, then the built-in default (migration
    0014). A model that needs ninety seconds and one that needs three should
    not have to share a number baked into this function, and the run records
    where each value came from so a slow answer can be traced to the level
    that set it.

    **The snapshot happens here, not in the worker.** A run answers the
    question as it was asked: if an entity changes between submitting and
    solving, the answer must still be about the data the person was looking
    at. Freezing at submit is what makes that true, and it is why `run` can
    carry `dataset_id` before it carries a result.
    """
    scenario = db.execute(
        text(
            "SELECT s.id, s.model_version_id, s.patch, s.problem_id, mv.ir"
            "  FROM scenario s JOIN model_version mv ON mv.id = s.model_version_id"
            " WHERE s.id = :s"
        ),
        {"s": scenario_id},
    ).mappings().one_or_none()
    if scenario is None:
        raise LookupError(f"scenario {scenario_id} not found")

    settings = resolve(db, problem_id=scenario["problem_id"])
    from_settings = {}
    if time_limit is None:
        time_limit = float(settings["solve.time_limit_s"].value)
        from_settings["time_limit_s"] = settings["solve.time_limit_s"].source
    if seed is None:
        seed = int(settings["solve.seed"].value)
        from_settings["seed"] = settings["solve.seed"].source
    if solver is None and settings["solve.solver"].value is not None:
        solver = str(settings["solve.solver"].value)
        from_settings["requested_solver"] = settings["solve.solver"].source

    dataset_id = db.execute(
        text("SELECT snapshot_dataset(:v)"), {"v": scenario["model_version_id"]}
    ).scalar_one()

    # Classified against the frozen data, not the model alone: since
    # migration 0015 a fractional parameter can put an otherwise integral
    # model out of CP-SAT's reach, and the IR cannot see that.
    frozen = db.execute(
        text("SELECT data FROM dataset WHERE id = :d"), {"d": dataset_id}
    ).scalar_one()
    found = classify(patched(scenario["ir"], scenario["patch"] or {}), frozen)
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
                    # Which of the three levels supplied each value the caller
                    # did not. A run whose time limit nobody can account for
                    # is a run nobody can make faster.
                    **({"from_settings": from_settings} if from_settings else {}),
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
        text(
            "UPDATE run SET status = 'running', started_at = now(), heartbeat_at = now()"
            " WHERE id = :r"
        ),
        {"r": run_id},
    )
    db.commit()
    return run_id


class CannotCancel(Exception):
    """The run exists but is no longer in a state that can be stopped."""


def cancel_run(db: Session, run_id: int) -> str:
    """Ask a run to stop. Returns the status after the request.

    A queued run is cancelled here: nothing has started, so there is no
    worker to tell. A running run is asked; the worker records `cancelled`
    instead of an answer. A settled run is refused -- stopping a result
    already written would be rewriting history.
    """
    row = db.execute(
        text("SELECT status FROM run WHERE id = :r FOR UPDATE"), {"r": run_id}
    ).scalar_one_or_none()
    if row is None:
        raise LookupError(f"run {run_id} not found")
    if row == "queued":
        db.execute(
            text(
                "UPDATE run SET status = 'cancelled', cancel_requested = true,"
                "               finished_at = now() WHERE id = :r"
            ),
            {"r": run_id},
        )
        db.commit()
        return "cancelled"
    if row == "running":
        db.execute(
            text("UPDATE run SET cancel_requested = true WHERE id = :r"),
            {"r": run_id},
        )
        db.commit()
        return "running"
    raise CannotCancel("this run has already finished")


def _honour_cancel(db: Session, run_id: int) -> bool:
    """If the run was asked to stop, record `cancelled` and return True."""
    done = db.execute(
        text(
            "UPDATE run SET status = 'cancelled', finished_at = now()"
            " WHERE id = :r AND cancel_requested"
            "   AND status IN ('queued', 'running')"
            " RETURNING id"
        ),
        {"r": run_id},
    ).scalar_one_or_none()
    if done is None:
        return False
    db.commit()
    return True


def _cancelled_outcome(db: Session, run_id: int) -> RunOutcome:
    dataset_id = db.execute(
        text("SELECT dataset_id FROM run WHERE id = :r"), {"r": run_id}
    ).scalar_one()
    return RunOutcome(run_id, dataset_id, "cancelled", None, {})


@contextmanager
def _heartbeat(run_id: int, stop: threading.Event) -> Iterator[None]:
    """Touch `heartbeat_at` while this block runs, and set `stop` on cancel.

    Uses its own session: the solve holds `db` inside a library call, and a
    heartbeat that shared it would wait on the solve it is meant to outlive.
    """
    from app.core.db import SessionLocal

    def loop() -> None:
        while not stop.wait(HEARTBEAT_SECONDS):
            session = SessionLocal()
            try:
                asked = session.execute(
                    text(
                        "UPDATE run SET heartbeat_at = now()"
                        " WHERE id = :r AND status = 'running'"
                        " RETURNING cancel_requested"
                    ),
                    {"r": run_id},
                ).scalar_one_or_none()
                session.commit()
                if asked:
                    stop.set()
            except Exception:
                session.rollback()
            finally:
                session.close()

    threading.Thread(target=loop, daemon=True, name=f"run-{run_id}-heartbeat").start()
    try:
        yield
    finally:
        stop.set()


def execute_run(db: Session, run_id: int) -> RunOutcome:
    """Solve a claimed run and record what happened."""
    if _honour_cancel(db, run_id):
        return _cancelled_outcome(db, run_id)

    row = db.execute(
        text(
            "SELECT r.dataset_id, r.params, r.seed, s.patch, mv.ir, d.data"
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
    seed = row["seed"]
    dataset_id = row["dataset_id"]

    stop = threading.Event()
    with _heartbeat(run_id, stop):
        found = classify(ir, data)
        if _honour_cancel(db, run_id):
            return _cancelled_outcome(db, run_id)
        try:
            # Compiled before the solver is chosen: whether a quadratic
            # objective is convex is a fact about its numbers, and it decides
            # which backends may take the model at all.
            compiled = compile_model(ir, data)
        except Unsupported as exc:
            db.execute(
                text(
                    "UPDATE run SET status = 'error', error = :e, finished_at = now()"
                    " WHERE id = :r"
                ),
                {"e": str(exc), "r": run_id},
            )
            db.commit()
            return RunOutcome(run_id, dataset_id, "error", None, {})
        found = refine(found, compiled)
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
            if _honour_cancel(db, run_id):
                return _cancelled_outcome(db, run_id)
            result, reason = solve_compiled(
                backend, compiled, time_limit=time_limit, seed=seed, should_stop=stop.is_set
            )
            if reason is not None:
                db.execute(text("UPDATE run SET error = :e WHERE id = :r"), {"e": reason, "r": run_id})
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

        if _honour_cancel(db, run_id):
            return _cancelled_outcome(db, run_id)

    # Which solver ran, and why it was the one -- a result nobody can
    # attribute to a choice is not reproducible. Empty ranges ride along:
    # they are a fact about this compile, not a second table.
    extra = {"chosen_solver": backend.name, "why_solver": why}
    if compiled.empty_ranges:
        extra["empty_ranges"] = compiled.empty_ranges
    if compiled.objective_mode == "lex":
        extra["objective_mode"] = "lex"
        if result.assignments:
            extra["objective_terms"] = [
                {
                    "id": term_id,
                    "value": float(term.evaluated_at(result.assignments)),
                }
                for term_id, term in zip(
                    compiled.objective_term_ids, compiled.objective_terms, strict=True
                )
            ]
    db.execute(
        text(
            "UPDATE run SET solver = :s, params = params || CAST(:extra AS jsonb)"
            " WHERE id = :r"
        ),
        {"s": backend.name, "extra": _json(extra), "r": run_id},
    )
    _record(db, run_id, compiled, result)
    # What the answer may claim, as the backend that found it declares
    # (migration 0028): "optimal" from a local solver is not the same claim
    # as "optimal" from a global one, and the run must not blur the two.
    db.execute(
        text("UPDATE run SET optimality = :o WHERE id = :r"),
        {"o": optimality_of(backend, result.status), "r": run_id},
    )
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
        text(
            "UPDATE run SET status = 'running', started_at = now(), heartbeat_at = now()"
            " WHERE id = :r"
        ),
        {"r": run_id},
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
            # A hard constraint carrying a weight is refused by the
            # validator, so hardening must take it away and not merely
            # stop reading it.
            spec.pop("weight", None)
        elif spec["id"] in softened:
            spec["severity"] = "soft"
            spec["weight"] = int(softened[spec["id"]])
        constraints.append(spec)
    return {**ir, "constraints": constraints}


def _record(db: Session, run_id: int, compiled: Compiled, result: Solution) -> None:
    solved = result.status in ("optimal", "feasible")
    db.execute(
        text(
            "UPDATE run SET status = :st, solver_version = :sv, objective = :obj,"
            "               wall_time_s = :wall, finished_at = now(),"
            "               best_bound = :bound, gap = :gap"
            " WHERE id = :r"
        ),
        {
            "st": result.status,
            "sv": result.solver,
            "obj": result.objective,
            "wall": result.wall_seconds,
            "bound": result.best_bound if solved else None,
            "gap": gap_of(result.objective, result.best_bound) if solved else None,
            "r": run_id,
        },
    )

    if not solved:
        return

    db.execute(
        text(
            "INSERT INTO solution (run_id, assignments, reduced_costs)"
            " VALUES (:r, :a, CAST(:rc AS jsonb))"
        ),
        {
            "r": run_id,
            "a": _json(_assignments(compiled, result)),
            "rc": None if (packed := _reduced_costs(result)) is None else _json(packed),
        },
    )

    # One row per constraint, including the satisfied ones: "which rules held"
    # is as much a part of the answer as the roster, and a missing row would
    # be indistinguishable from a rule nobody checked.
    seen: dict[str, dict[str, Any]] = {}
    for spec_id in dict.fromkeys(c.id for c in compiled.constraints):
        seen[spec_id] = {"hard": True, "total": 0, "penalty": 0, "where": [], "slack": None}

    slacks = slack_by_constraint(compiled, result.assignments)
    duals = result.duals

    for spec_id, keys in compiled.violations.items():
        entry = seen.setdefault(
            spec_id, {"hard": True, "total": 0, "penalty": 0, "where": [], "slack": None}
        )
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
                "  penalty_paid, violations, slack, dual)"
                " VALUES (:r, :c, :l, :hard, :sat, :total, :pen, :v, :slack, :dual)"
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
                "slack": slacks.get(spec_id),
                "dual": None if duals is None else duals.get(spec_id, 0),
            },
        )


def _solve_lex(
    backend,
    compiled: Compiled,
    *,
    time_limit: float,
    workers: int,
    should_stop=None,
    seed: int | None = None,
) -> Solution:
    """Optimise terms in order, freezing each before the next.

    Backends stay dumb: each stage is an ordinary `Compiled` with one
    objective. Soft-constraint penalties are an implicit last term, so a
    planner's priorities are not traded against bending a rule until those
    priorities are already met.
    """
    stages: list[Linear] = [term.copy() for term in compiled.objective_terms]
    if compiled.penalty_objective.coeffs or compiled.penalty_objective.const:
        stages.append(compiled.penalty_objective.copy())
    if not stages:
        return backend.solve(
            compiled, time_limit=time_limit, workers=workers, should_stop=should_stop, seed=seed
        )

    deadline = time.monotonic() + time_limit
    freezes: list[Constraint] = []
    wall = 0.0
    result: Solution | None = None
    for i, term in enumerate(stages):
        remaining = max(0.05, deadline - time.monotonic())
        stage = replace(
            compiled,
            objective=term.copy(),
            constraints=[*compiled.constraints, *freezes],
        )
        result = backend.solve(
            stage, time_limit=remaining, workers=workers, should_stop=should_stop, seed=seed
        )
        wall += result.wall_seconds
        if result.status != "optimal" or not result.assignments:
            return replace(result, wall_seconds=round(wall, 3))
        value = term.evaluated_at(result.assignments)
        if compiled.is_integral:
            relation, freeze_rhs = "=", number(round(value))
        else:
            # A continuous stage is held at its best give or take float
            # noise: exactly `=` a value read back from a floating-point
            # solve can be infeasible by 1e-12 and fail the next stage.
            slack = max(Decimal("1e-6") * abs(value), Decimal("1e-9"))
            if compiled.sense == "minimize":
                relation, freeze_rhs = "<=", value + slack
            else:
                relation, freeze_rhs = ">=", value - slack
        freezes.append(
            Constraint(
                id=f"_lex_{i}",
                index={},
                left=term.copy(),
                relation=relation,
                right=Linear(const=freeze_rhs),
            )
        )

    assert result is not None
    primary = None
    if compiled.objective_terms and result.assignments:
        raw = compiled.objective_terms[0].evaluated_at(result.assignments)
        primary = int(round(raw)) if compiled.is_integral else float(raw)
    # The last stage's bound is on the last stage's goal, not on the primary
    # term reported as the objective, so no gap can honestly be given.
    return replace(result, wall_seconds=round(wall, 3), objective=primary, best_bound=None)


def solve_compiled(
    backend, compiled: Compiled, *, time_limit: float, seed: int | None = None, should_stop=None
) -> tuple[Solution, str | None]:
    """Solve a compiled model as a run does, and say why if it is unbounded.

    Both objective modes, then the check for an answer resting on a ceiling
    the model never set (`_unbounded_ceilings`). The reason is None unless the
    status is `unbounded`. The golden suite calls this, so what it pins is
    what a run records.
    """
    started = time.monotonic()
    result = _solve(backend, compiled, time_limit, seed, should_stop)
    unbounded = _unbounded_ceilings(
        backend,
        compiled,
        result,
        max(0.5, time_limit - (time.monotonic() - started)),
        seed,
        should_stop,
    )
    if unbounded is None:
        return result, None
    return unbounded


def _solve(backend, compiled: Compiled, time_limit: float, seed, should_stop) -> Solution:
    if compiled.objective_mode == "lex":
        return _solve_lex(
            backend,
            compiled,
            time_limit=time_limit,
            workers=8,
            should_stop=should_stop,
            seed=seed,
        )
    return backend.solve(
        compiled, time_limit=time_limit, workers=8, should_stop=should_stop, seed=seed
    )


def _unbounded_ceilings(
    backend, compiled: Compiled, result: Solution, time_limit: float, seed, should_stop
) -> tuple[Solution, str] | None:
    """An answer resting on a ceiling the model never set, shown to be unbounded.

    Every variable without an upper bound gets `DEFAULT_UPPER`, so a goal that
    can improve forever comes back `optimal` at that ceiling -- an answer to a
    model nobody wrote. When the answer touches a defaulted ceiling, the model
    is solved once more with those ceilings a thousand times higher. If the
    goal improves, it was held back only by the guard: the run is `unbounded`,
    and the reason names the variables. If not, the ceiling was incidental and
    the answer stands.
    """
    if result.status not in ("optimal", "feasible") or result.objective is None:
        return None
    at_ceiling = sorted(
        key
        for key, spec in compiled.variables.items()
        if spec.default_upper
        and number(result.assignments.get(key, 0)) >= spec.upper - Decimal("1e-6")
    )
    if not at_ceiling:
        return None
    lifted = replace(
        compiled,
        variables={
            key: replace(spec, upper=spec.upper * 1000) if spec.default_upper else spec
            for key, spec in compiled.variables.items()
        },
    )
    again = _solve(backend, lifted, time_limit, seed, should_stop)
    if again.status not in ("optimal", "feasible") or again.objective is None:
        return None
    first, second = Decimal(str(result.objective)), Decimal(str(again.objective))
    tolerance = Decimal("1e-6") * max(Decimal(1), abs(first))
    improved = second < first - tolerance if compiled.sense == "minimize" else second > first + tolerance
    if not improved:
        return None
    names = ", ".join(
        f"{name}[{', '.join(index)}]" if index else name for name, index in at_ceiling[:5]
    )
    more = f" and {len(at_ceiling) - 5} more" if len(at_ceiling) > 5 else ""
    reason = (
        f"The goal can improve without limit. {names}{more} rose to "
        f"{DEFAULT_UPPER:,}, a ceiling the model never set, and raising that "
        "ceiling improved the goal again. Give it an upper bound, or add the "
        "rule that should hold it back."
    )
    blank = Solution(
        status="unbounded",
        optimal=False,
        objective=None,
        assignments={},
        wall_seconds=round(result.wall_seconds + again.wall_seconds, 3),
        solver=result.solver,
    )
    return blank, reason


def gap_of(objective, bound) -> float | None:
    """`|objective - bound| / max(|objective|, 1e-9)`: how far the answer may
    be from the best, as a fraction. 0 at a proven optimum; None when there is
    no bound to measure against. Sense-agnostic because of the absolute value.
    """
    if objective is None or bound is None:
        return None
    objective, bound = float(objective), float(bound)
    if objective == 0 and bound == 0:
        return 0.0
    gap = abs(objective - bound) / max(abs(objective), 1e-9)
    # Below the six places an objective is stored to, a gap is rounding.
    return 0.0 if gap < 1e-9 else gap


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


_REDUCED_COST_FLOOR = 1e-8


def _reduced_costs(result: Solution) -> dict[str, list[dict[str, Any]]] | None:
    """Non-zero reduced costs, grouped like the roster. None when this
    backend has nothing to say -- not an empty object, which would mean it
    looked and every decision was free."""
    if result.reduced_costs is None:
        return None
    out: dict[str, list[dict[str, Any]]] = {}
    for (name, index), value in sorted(result.reduced_costs.items()):
        if name == _VIOLATION or abs(value) < _REDUCED_COST_FLOOR:
            continue
        out.setdefault(name, []).append(
            {"index": list(index), "value": _json_number(value)}
        )
    return out


def _json_number(value: float) -> int | float:
    rounded = round(value)
    if abs(value - rounded) < _REDUCED_COST_FLOOR:
        return int(rounded)
    return float(value)


def _json(value: Any) -> str:
    import json

    return json.dumps(value)
