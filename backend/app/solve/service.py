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

import logging
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any, Iterator

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.solve.backends import NoBackend, by_name, choose, optimality_of
from app.solve.classify import classify
from app.solve.convexity import refine
from app.solve.lp import NotContinuous
from app.solve.compile import (
    DEFAULT_UPPER,
    Compiled,
    Constraint,
    Linear,
    Unsupported,
    compile_model,
    number,
    slack_by_constraint,
)
from app.solve.diagnose import DEFAULT_BUDGET, DEFAULT_PROBE_SECONDS
from app.solve import sandbox
from app.solve.result import Solution
from app.solve.scaling import admit as admit_scaled
from app.solve import blocks as block_rows
from app.solve import mccormick, pareto
from app.solve import allocation as allocation_rows
from app.solve import network as network_rows
from app.solve import partition as partition_rows
from app.solve import routing as routing_rows
from app.solve import horizon as horizon_rows
from app.solve import selector as selector_rows
from app.solve import lagrange as lagrange_rows
from app.solve import stochastic as stochastic_rows
from app.solve import lns as lns_rows
from app.solve import race as race_rows
from app.solve.fingerprint import fingerprint as fingerprint_of
from app.solve import robust as robust_rows
from app.solve import params as solver_param_table
from app.solve import symmetry as symmetry_rows
from app.solve import warm
from app.solve import locks as lock_rows
from app.solve.cache import key_of
from app.solve.cache import reuse as cache_reuse
from app.solve.reformulate import bigm, pwl_rewrite
from app.core.logs import bind as bind_log
from app.core import tracing
from app.settings_resolve import resolve

logger = logging.getLogger(__name__)

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
    reuse: bool = True,
    pareto_steps: int | None = None,
    robust: bool = False,
) -> int:
    """Freeze the data and queue the work. Returns the run's id.

    **A question already answered is not solved again** (`reuse`, on by
    default): when a run with the same model, data, patch and deciding
    settings was proven globally optimal, the new run is recorded already
    finished, pointing at it, and nothing is queued (`app.solve.cache`).

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
            "SELECT s.id, s.model_version_id, s.patch, s.problem_id, s.organization_id, mv.ir,"
            "       mv.ir_hash"
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
    workers = int(settings["solve.workers"].value)
    from_settings["workers"] = settings["solve.workers"].source
    gap_rel = float(settings["solve.gap_rel"].value)
    from_settings["gap_rel"] = settings["solve.gap_rel"].source
    cpsat_scaling = bool(settings["solve.cpsat_scaling"].value)
    from_settings["cpsat_scaling"] = settings["solve.cpsat_scaling"].source
    warm_start = bool(settings["solve.warm_start"].value)
    from_settings["warm_start"] = settings["solve.warm_start"].source
    symmetry = bool(settings["solve.symmetry"].value)
    from_settings["symmetry"] = settings["solve.symmetry"].source
    separable = bool(settings["solve.separable"].value)
    from_settings["separable"] = settings["solve.separable"].source
    memory = bool(settings["solve.memory"].value)
    from_settings["memory"] = settings["solve.memory"].source
    probe = bool(settings["solve.probe"].value)
    from_settings["probe"] = settings["solve.probe"].source
    portfolio = bool(settings["solve.portfolio"].value)
    from_settings["portfolio"] = settings["solve.portfolio"].source
    lns = bool(settings["solve.lns"].value)
    from_settings["lns"] = settings["solve.lns"].source
    lagrangian = bool(settings["solve.lagrangian"].value)
    from_settings["lagrangian"] = settings["solve.lagrangian"].source
    local_fallback = bool(settings["solve.local_fallback"].value)
    from_settings["local_fallback"] = settings["solve.local_fallback"].source
    stochastic_samples = int(settings["solve.stochastic_samples"].value or 0)
    from_settings["stochastic_samples"] = settings["solve.stochastic_samples"].source
    rolling_horizon = bool(settings["solve.rolling_horizon"].value)
    from_settings["rolling_horizon"] = settings["solve.rolling_horizon"].source
    decompose = bool(settings["solve.decompose"].value)
    from_settings["decompose"] = settings["solve.decompose"].source
    connected_start = bool(settings["solve.connected_start"].value)
    routing_start = bool(settings["solve.routing_start"].value)
    from_settings["routing_start"] = settings["solve.routing_start"].source
    network = bool(settings["solve.network"].value)
    from_settings["network"] = settings["solve.network"].source
    metaheuristic = bool(settings["solve.metaheuristic"].value)
    from_settings["metaheuristic"] = settings["solve.metaheuristic"].source
    from_settings["connected_start"] = settings["solve.connected_start"].source
    # A tuning search's result (queue R10), checked against the whitelist before the run is queued.
    tuned_params = str(settings["solve.solver_params"].value or "")
    from_settings["solver_params"] = settings["solve.solver_params"].source
    tuned_from = str(settings["solve.tuned_from"].value or "")
    try:
        solver_param_table.parse_setting(tuned_params)
    except ValueError as exc:
        raise SettingUnusable("solve.solver_params", f"the setting solve.solver_params cannot be used: {exc}") from exc
    pdlp = bool(settings["solve.pdlp"].value)
    from_settings["pdlp"] = settings["solve.pdlp"].source
    if solver is None and settings["solve.solver"].value is not None:
        solver = str(settings["solve.solver"].value)
        from_settings["requested_solver"] = settings["solve.solver"].source

    quota = quota_of(db, scenario["organization_id"])
    _check_quota_before_snapshot(db, scenario["organization_id"], quota, time_limit)

    dataset_id = db.execute(
        text("SELECT snapshot_dataset(:v)"), {"v": scenario["model_version_id"]}
    ).scalar_one()

    # Classified against the frozen data, not the model alone: since
    # migration 0015 a fractional parameter can put an otherwise integral
    # model out of CP-SAT's reach, and the IR cannot see that.
    frozen, data_hash = db.execute(
        text("SELECT data, data_hash FROM dataset WHERE id = :d"), {"d": dataset_id}
    ).one()
    found = classify(patched(scenario["ir"], scenario["patch"] or {}), frozen)
    if quota.get("max_vars") is not None:
        count = variable_count(scenario["ir"], frozen)
        if count > quota["max_vars"]:
            # Raised before the commit: the snapshot above is rolled back
            # with the refused run.
            raise QuotaExceeded(
                "max_vars",
                f"this model has {count:,} decisions and this organization's quota is "
                f"{quota['max_vars']:,}",
            )
    # The context the worker will continue: this span's, a child of the
    # request that submitted the run when there is one.
    with tracing.span("enqueue_run", scenario_id=scenario_id):
        trace_carrier = tracing.carrier()
    cache_key = key_of(
        ir_hash=scenario["ir_hash"],
        data_hash=data_hash,
        patch=scenario["patch"],
        solver=solver,
        seed=seed,
        gap_rel=gap_rel,
        cpsat_scaling=cpsat_scaling,
        compiler_version=COMPILER_VERSION,
    )
    request_params = {
        "time_limit_s": time_limit,
        "workers": workers,
        "gap_rel": gap_rel,
        "cpsat_scaling": cpsat_scaling,
        "warm_start": warm_start,
        "symmetry": symmetry,
        "separable": separable,
        "pdlp": pdlp,
        "memory": memory,
        "probe": probe,
        "portfolio": portfolio,
        "lns": lns,
        "lagrangian": lagrangian,
        "local_fallback": local_fallback,
        "stochastic_samples": stochastic_samples,
        "rolling_horizon": rolling_horizon,
        "decompose": decompose,
        "connected_start": connected_start,
        "metaheuristic": metaheuristic,
        "network": network,
        "routing_start": routing_start,
        **({"solver_params_setting": tuned_params, "tuned_from": tuned_from} if tuned_params else {}),
        **({"pareto_steps": pareto_steps} if pareto_steps else {}),
        **({"robust": True} if robust else {}),
        # The trace this run belongs to: the worker continues it
        # (app.core.tracing).
        "trace": trace_carrier,
        "classified_as": found.model_class,
        "why": found.reasons,
        "needs": sorted(found.needs),
        **({"requested_solver": solver} if solver else {}),
        # Which of the three levels supplied each value the caller
        # did not. A run whose time limit nobody can account for
        # is a run nobody can make faster.
        **({"from_settings": from_settings} if from_settings else {}),
    }
    if pareto_steps or robust:
        # A front is a different question from the goal's optimum, and its
        # own answer is one end of it; a robust answer is to a different
        # question too. Neither reused nor reusable.
        reuse, cache_key = False, None
    if reuse:
        reused = cache_reuse(
            db, key=cache_key, scenario_id=scenario_id, dataset_id=dataset_id, params=request_params
        )
        if reused is not None:
            db.commit()
            return reused
    run_id = db.execute(
        text(
            "INSERT INTO run (scenario_id, dataset_id, status, solver, compiler_version,"
            "                 params, seed, cache_key)"
            " VALUES (:s, :d, 'queued', 'cp-sat', :cv, :params, :seed, :k)"
            " RETURNING id"
        ),
        {
            "s": scenario_id,
            "d": dataset_id,
            "cv": COMPILER_VERSION,
            "params": _json(request_params),
            "seed": seed,
            "k": cache_key,
        },
    ).scalar_one()
    db.commit()
    return run_id


def claim_next(db: Session) -> int | None:
    """Take the next queued run, fairly across organizations, or nothing.

    **Fair.** The queue is shared by every organization, and oldest-first
    would let one that submits a hundred runs make everyone else wait behind
    all of them. So the next run is the oldest one of the organization with
    the fewest runs in progress, and an organization already at its
    `max_concurrent_runs` quota (migration 0034) is skipped until one ends.

    **One claim at a time.** Claims take a transaction-level advisory lock:
    a claim is two short statements, and serialising them is what makes the
    concurrency quota exact -- two workers counting at once could otherwise
    both see room for one more. `SKIP LOCKED` stays, so a worker never waits
    on a row another is updating.
    """
    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _CLAIM_LOCK})
    run_id = db.execute(
        text(
            "WITH running AS ("
            "    SELECT organization_id, count(*) AS n FROM run"
            "     WHERE status = 'running' GROUP BY organization_id"
            ")"
            " SELECT r.id FROM run r"
            "   LEFT JOIN running c ON c.organization_id = r.organization_id"
            "   LEFT JOIN iam.quota q ON q.organization_id = r.organization_id"
            "  WHERE r.status = 'queued'"
            "    AND (q.max_concurrent_runs IS NULL OR coalesce(c.n, 0) < q.max_concurrent_runs)"
            "  ORDER BY coalesce(c.n, 0), r.queued_at, r.id"
            "  FOR UPDATE OF r SKIP LOCKED LIMIT 1"
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


# Any fixed number, shared by every worker: the key of the claim lock.
_CLAIM_LOCK = 7_140_001


class QuotaExceeded(Exception):
    """A run this organization's quota does not allow. `quota` names the
    limit, so the refusal can say which one to raise."""

    def __init__(self, quota: str, message: str):
        super().__init__(message)
        self.quota = quota


def quota_of(db: Session, organization_id) -> dict[str, Any]:
    row = db.execute(
        text(
            "SELECT max_concurrent_runs, max_queued_runs, max_time_limit_s, max_vars,"
            "       cpu_seconds_month, requests_per_minute"
            "  FROM iam.quota WHERE organization_id = :o"
        ),
        {"o": organization_id},
    ).mappings().one_or_none()
    return dict(row) if row else {}


def month_usage(db: Session, organization_id) -> dict[str, Any]:
    row = db.execute(
        text(
            "SELECT cpu_seconds, runs FROM iam.usage_month"
            " WHERE organization_id = :o"
            "   AND month = date_trunc('month', now() AT TIME ZONE 'UTC')::date"
        ),
        {"o": organization_id},
    ).mappings().one_or_none()
    return dict(row) if row else {"cpu_seconds": 0.0, "runs": 0}


def _check_quota_before_snapshot(db: Session, organization_id, quota: dict, time_limit: float) -> None:
    """The limits that need no data: checked before anything is frozen."""
    if quota.get("max_time_limit_s") is not None and time_limit > quota["max_time_limit_s"]:
        raise QuotaExceeded(
            "max_time_limit_s",
            f"a time limit of {time_limit:g} s is over this organization's quota of "
            f"{quota['max_time_limit_s']:g} s",
        )
    if quota.get("max_queued_runs") is not None:
        queued = db.execute(
            text("SELECT count(*) FROM run WHERE organization_id = :o AND status = 'queued'"),
            {"o": organization_id},
        ).scalar_one()
        if queued >= quota["max_queued_runs"]:
            raise QuotaExceeded(
                "max_queued_runs",
                f"this organization already has {queued} runs waiting, its quota; "
                "one must start before another is queued",
            )
    if quota.get("cpu_seconds_month") is not None:
        used = month_usage(db, organization_id)["cpu_seconds"]
        if used >= quota["cpu_seconds_month"]:
            raise QuotaExceeded(
                "cpu_seconds_month",
                f"this organization has used {used:,.0f} of its {quota['cpu_seconds_month']:,.0f} "
                "CPU-seconds this month",
            )


def variable_count(ir: dict[str, Any], data: dict[str, Any]) -> int:
    """How many decisions the model has on this data: each variable once per
    combination of its index sets' members."""
    sets = data.get("sets") or {}
    total = 0
    for spec in (ir.get("variables") or {}).values():
        size = 1
        for set_name in spec.get("index", []):
            size *= len(sets.get(set_name, []))
        total += size
    return total


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


def _cancel_requested(db: Session, run_id: int) -> bool:
    return bool(
        db.execute(text("SELECT cancel_requested FROM run WHERE id = :r"), {"r": run_id}).scalar_one()
    )


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
            "SELECT r.dataset_id, r.params, r.seed, s.patch, s.problem_id, mv.ir, d.data"
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
    # Runs queued before migration 0030 carry neither; they keep what they
    # were solved with then.
    workers = int(params.get("workers", 8))
    gap_rel = float(params.get("gap_rel", 0.0))
    dataset_id = row["dataset_id"]
    # Parts of an earlier plan held fixed (queue R24), with what those runs decided.
    locks = (row["patch"] or {}).get("lock") or []
    if locks:
        params = {**params, "_locks": locks, "_lock_bases": _lock_bases(db, row["problem_id"], locks)}

    stop = threading.Event()
    events = RunEvents(run_id)
    try:
        # The trace the request that queued this run started, continued here.
        with tracing.continued(params.get("trace")), tracing.span("run", run_id=run_id):
            return _execute(db, run_id, events, ir, data, params, time_limit, seed, workers, gap_rel, dataset_id, stop)
    finally:
        # Whatever happened -- solved, refused, cancelled, crashed -- the
        # stream's last word is the status the run ended with.
        settled = db.execute(text("SELECT status FROM run WHERE id = :r"), {"r": run_id}).scalar_one_or_none()
        events.stage("settled", status=settled)
        events.close()


def _execute(
    db: Session,
    run_id: int,
    events: "RunEvents",
    ir: dict,
    data: dict,
    params: dict,
    time_limit: float,
    seed,
    workers: int,
    gap_rel: float,
    dataset_id: int,
    stop: threading.Event,
) -> RunOutcome:
    with _heartbeat(run_id, stop):
        # Each step as it starts, for whoever watches (the GenUI stream,
        # app.genui.translate): the pipeline is the agent.
        events.stage("started")
        found = classify(ir, data)
        if _honour_cancel(db, run_id):
            return _cancelled_outcome(db, run_id)
        try:
            # Compiled before the solver is chosen: whether a quadratic
            # objective is convex is a fact about its numbers, and it decides
            # which backends may take the model at all.
            events.stage("compiling", model_class=found.model_class)
            with tracing.span("compile") as compiling:
                compiled = unlocked = compile_model(ir, data)
                if params.get("_locks"):
                    if params.get("stochastic_samples") and stochastic_rows.wanted(ir):
                        raise Unsupported("locks are not kept by a stochastic solve: each future is compiled "
                                          "afresh; solve without sampled futures to keep them")
                    # Rows after the model's own, so a rule's position is the same with or without them.
                    compiled = lock_rows.apply(compiled, params["_locks"], params["_lock_bases"], data.get("sets") or {})
                compiling.set_attribute("variables", len(compiled.variables))
                compiling.set_attribute("rules", len(compiled.constraints))
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
        # The model's numbers, stored as soon as there is a model: a run that
        # fails later still says what it was (app.solve.fingerprint, Phase 17).
        numbers = _record_fingerprint(db, run_id, compiled)
        found = refine(found, compiled)
        # What the solver is given: the model itself, or its robust
        # counterpart (app.solve.robust) when the run asks for one.
        solving_model, robust_record, nominal = compiled, None, None
        if params.get("robust"):
            try:
                # Compared against a compile of the same IR, which has no lock rows.
                moving = robust_rows.deviations(ir, data, unlocked)
            except (robust_rows.NotRobust, Unsupported) as exc:
                db.execute(
                    text("UPDATE run SET status = 'error', error = :e, finished_at = now() WHERE id = :r"),
                    {"e": str(exc), "r": run_id},
                )
                db.commit()
                return RunOutcome(run_id, dataset_id, "error", None, {})
            robust_record = []
            if moving:
                solving_model, robust_record = robust_rows.rewrite(compiled, moving)
                # The protection is continuous: a whole-number model becomes mixed.
                found = replace(
                    found,
                    needs=found.needs | {"continuous"},
                    model_class="MILP" if found.model_class == "IP" else found.model_class,
                )
        if params.get("cpsat_scaling"):
            # Fractional data made whole exactly, so CP-SAT may take it
            # (migration 0039); a model that cannot be scaled says why.
            found = admit_scaled(found, compiled)
        if params.get("pdlp"):
            # A linear program past the size threshold goes to PDLP, whose
            # answer is optimal to a tolerance (app.solve.pdlp, migration 0051).
            from app.solve.pdlp import admit as admit_large

            found = admit_large(found, compiled)
        events.stage(
            "compiled",
            model_class=found.model_class,
            variables=len(compiled.variables),
            rules=len(compiled.constraints),
            **({"fingerprint": numbers} if numbers else {}),
        )
        race_candidates, race_record, race_skipped = None, None, None
        shadow = None
        # A tuning's options for this problem or domain (setting `solve.solver_params`, queue R10).
        tuned = solver_param_table.parse_setting(params.get("solver_params_setting"))
        # How the model splits (app.solve.blocks.structure, queue R4): recorded, not acted on.
        structure_record = block_rows.structure(compiled)
        portfolio_candidates, portfolio_record, portfolio_skipped = None, None, None
        lns_record = None
        lagrange_record = None
        local_record = None
        # A two-stage stochastic solve (setting `solve.stochastic_samples`,
        # app.solve.stochastic, queue R7): asked for, and a decision waits for the data.
        stochastic_wanted = bool(params.get("stochastic_samples")) and stochastic_rows.wanted(ir)
        stochastic_record, record_model = None, None
        horizon_record = None
        decomposition_record = None
        network_record = None
        start_record, start_key = None, "connected_start_run"
        search_record = None
        exact_failed = None
        if stochastic_wanted and stochastic_rows.chance_rules(ir):
            # A chance rule is switched per future (queue R8): the extensive form has
            # binaries, held by a big-M from declared bounds where there is no indicator.
            found = replace(
                found,
                needs=found.needs | {"integral", "indicator-bounded"},
                model_class="MILP" if "continuous" in found.needs else "IP",
            )
        try:
            with tracing.span("choose", model_class=found.model_class) as choosing:
                backend, why = choose(found, params.get("requested_solver"))
                # The learned selector's pick, recorded beside the rules' and acting on
                # nothing (shadow mode, app.solve.selector, queue R11).
                shadow = selector_rows.predict(numbers, sorted(_admissible(found)))
                recalled = None
                if params.get("memory") and not params.get("requested_solver"):
                    # The problem's own history, among what the rules admit
                    # for this model (app.solve.memory, queue 17a).
                    recalled = _recall(db, run_id, found)
                    if recalled is not None:
                        backend, why = by_name(recalled.solver), recalled.evidence
                if (params.get("portfolio") and not params.get("requested_solver") and recalled is None
                        and not stochastic_wanted
                        and not params.get("pareto_steps") and not params.get("robust")):
                    # Every admissible solver at once for the whole time
                    # (app.solve.race, queue R2) -- in place of the probe race.
                    candidates = sorted(_admissible(found), key=_rank_of)
                    portfolio_skipped = race_rows.should_portfolio(found.model_class, numbers, candidates)
                    portfolio_candidates = None if portfolio_skipped else candidates
                if (params.get("probe") and not params.get("requested_solver") and recalled is None
                        and portfolio_candidates is None and not stochastic_wanted
                        and not params.get("pareto_steps") and not params.get("robust")):
                    # Nothing to remember: race the admissible solvers
                    # briefly (app.solve.race, queue 17b).
                    candidates = sorted(_admissible(found), key=_rank_of)
                    race_skipped = race_rows.should_race(numbers, candidates, time_limit)
                    race_candidates = None if race_skipped else candidates
                choosing.set_attribute("solver", backend.name)
            bind_log(solver=backend.name)
            events.stage("chosen", solver=backend.name, why=why, model_class=found.model_class)
        except NoBackend as exc:
            db.execute(
                text(
                    "UPDATE run SET status = 'error', error = :e, finished_at = now() WHERE id = :r"
                ),
                {"e": str(exc), "r": run_id},
            )
            db.commit()
            return RunOutcome(run_id, dataset_id, "error", None, {})

        hint = None
        if params.get("warm_start") and backend.name in warm.HINTED:
            # The nearest earlier answer as a starting point (setting
            # `solve.warm_start`, app.solve.warm).
            prior = warm.prior_run(db, run_id)
            if prior is not None:
                hint = warm.hint_from(compiled, prior[1], prior[2]) or None
                db.execute(
                    text("UPDATE run SET params = params || CAST(:w AS jsonb) WHERE id = :r"),
                    {"w": _json({"warm_start_from": prior[0], "warm_start_hinted": len(hint or {})}), "r": run_id},
                )
                db.commit()  # not held through the solve: see `_record_fingerprint`
        kinds = {key for c in ir.get("constraints") or [] if isinstance(c, dict) for key in ("connected", "route")
                 if key in c}
        starter = None
        if params.get("connected_start") and "connected" in kinds:
            # A connected, balanced partition to start from (setting
            # `solve.connected_start`, app.solve.partition, queue R13).
            starter, start_key = partition_rows, "connected_start_run"
            why_not = partition_rows.applies(ir)
        elif params.get("routing_start") and "route" in kinds:
            # Routes from OR-Tools' routing search to start from (setting
            # `solve.routing_start`, app.solve.routing, queue R15b).
            starter, start_key = routing_rows, "routing_start_run"
            why_not = routing_rows.applies(ir, compiled)
        if starter is not None:
            if backend.name not in warm.HINTED:
                start_record = {"used": False, "why": f"{backend.name} takes no start"}
            elif why_not is not None:
                start_record = {"used": False, "why": why_not}
            elif hint:
                start_record = {"used": False, "why": "an earlier answer is the start"}
            else:
                hint, start_record = starter.start(
                    ir, data, compiled, seconds=min(starter.CEILING, starter.SHARE * time_limit))
                start_record = {"used": True, **start_record}
                hint = hint or None
                # The start's time is the run's: the solver gets what is left, so the run keeps its limit.
                time_limit = max(1.0, time_limit - float(start_record.get("seconds", 0)))

        points: list = []
        parts, blocks_record = None, None
        if params.get("pareto_steps"):
            # A trade-off front between the goal's two terms (app.solve.pareto):
            # each point solved in full, the first end standing as this run's
            # own answer. A model with no answer at all falls through to the
            # ordinary solve, so its verdict and explanation are the usual ones.
            try:
                pareto.admissible(compiled)
                events.stage("solving", solver=backend.name, time_limit_s=time_limit)
                points = sandbox.run(
                    "app.solve.sandbox:pareto_in_child",
                    {
                        "backend": backend.name,
                        # The robust counterpart when one was asked for: a
                        # robust front.
                        "compiled": solving_model,
                        "steps": int(params["pareto_steps"]),
                        "time_limit": time_limit,
                        "seed": seed,
                        "workers": workers,
                        "gap_rel": gap_rel,
                    },
                    time_limit=time_limit,
                    workers=workers,
                    should_stop=stop.is_set,
                )
            except (pareto.NotTwoGoals, Unsupported, sandbox.SandboxFailed) as exc:
                db.execute(
                    text("UPDATE run SET status = 'error', error = :e, finished_at = now() WHERE id = :r"),
                    {"e": str(exc), "r": run_id},
                )
                db.commit()
                return RunOutcome(run_id, dataset_id, "error", None, {})

        try:
            if _honour_cancel(db, run_id):
                return _cancelled_outcome(db, run_id)
            if points:
                result, reason = _point_solution(compiled, points[0]), None
                raise _Answered
            if portfolio_candidates:

                def entrant(name: str, seconds: float, share: int, stop_others):
                    try:
                        return sandbox.run(
                            "app.solve.sandbox:solve_in_child",
                            {"backend": name, "compiled": solving_model, "time_limit": seconds, "seed": seed,
                             "workers": share, "gap_rel": gap_rel, "symmetry": bool(params.get("symmetry")),
                             "hint": hint if name in warm.HINTED else None},
                            time_limit=seconds,
                            workers=share,
                            should_stop=stop.is_set,
                            # Beaten: its answer is not wanted, and a solver that
                            # does not look at `should_stop` would run to the end.
                            abandon=stop_others,
                        )[0]
                    except (Unsupported, sandbox.SandboxFailed):
                        return Solution("unknown", False, None, {}, seconds, name)

                events.stage("portfolio", solvers=portfolio_candidates, seconds=time_limit)
                raced = race_rows.run_portfolio(portfolio_candidates, entrant, workers=workers,
                                                time_limit=time_limit, sense=compiled.sense, rule=backend.name)
                backend, why, portfolio_record = by_name(raced.winner), raced.evidence, raced.record
                bind_log(solver=backend.name)
                events.stage("chosen", solver=backend.name, why=why, model_class=found.model_class)
                result, reason = raced.answer, None
                raise _Answered
            if race_candidates:

                def probe_one(name: str, seconds: float, share: int, stop_probe):
                    try:
                        return sandbox.run(
                            "app.solve.sandbox:solve_in_child",
                            {"backend": name, "compiled": solving_model, "time_limit": seconds, "seed": seed,
                             "workers": share, "gap_rel": gap_rel},
                            time_limit=seconds,
                            workers=share,
                            should_stop=lambda: stop.is_set() or stop_probe(),
                        )[0]
                    except (Unsupported, sandbox.SandboxFailed):
                        return Solution("unknown", False, None, {}, seconds, name)

                events.stage("probing", solvers=race_candidates, seconds=race_rows.probe_seconds(time_limit))
                raced = race_rows.run_race(race_candidates, probe_one, workers=workers, time_limit=time_limit,
                                           sense=compiled.sense, rule=backend.name)
                backend, why, race_record = by_name(raced.winner), raced.evidence, raced.record
                bind_log(solver=backend.name)
                events.stage("chosen", solver=backend.name, why=why, model_class=found.model_class)
                if raced.answer is not None:
                    # A probe proved it: that is the answer, solved once.
                    result, reason = raced.answer, None
                    raise _Answered
                time_limit = max(1.0, time_limit - raced.probe_s)
            events.stage("solving", solver=backend.name, time_limit_s=time_limit)
            if robust_record:
                # The nominal answer, for the price of robustness: the same
                # backend, the same clock, the model as written.
                nominal, _ = sandbox.run(
                    "app.solve.sandbox:solve_in_child",
                    {"backend": backend.name, "compiled": compiled, "time_limit": time_limit, "seed": seed,
                     "workers": workers, "gap_rel": gap_rel},
                    time_limit=time_limit,
                    workers=workers,
                    should_stop=stop.is_set,
                )
            # A template decomposition that is exact where it applies (setting
            # `solve.decompose`, app.solve.allocation, queue R12).
            allocate = (bool(params.get("decompose")) and not stochastic_wanted
                        and allocation_rows.applies(solving_model) is None)
            # A model that is a network, solved as one: proven, by min-cost flow (setting
            # `solve.network`, app.solve.network, queue R15a).
            # Whole-number networks only: on a continuous one an LP solver is nearly as quick and
            # also gives shadow prices, which min-cost flow does not (bench/results/2026-09-25-network.md).
            networked = (bool(params.get("network")) and not stochastic_wanted and not allocate
                         and any(v.is_integral for v in solving_model.variables.values())
                         and network_rows.applies(solving_model) is None)
            horizon_plan = None
            if params.get("rolling_horizon") and not stochastic_wanted and not networked:
                # Relax-and-fix over the model's time set (setting
                # `solve.rolling_horizon`, app.solve.horizon, queue R9).
                time_set = _time_set(db, run_id, solving_model)
                periods = [str(row["id"]) for row in (data.get("sets") or {}).get(time_set or "", [])]
                why_not = horizon_rows.applies(solving_model, time_set, periods)
                if why_not is None:
                    horizon_plan = (time_set, periods)
                else:
                    horizon_record = {"used": False, "why": why_not}
            if (params.get("separable") and not stochastic_wanted and horizon_plan is None and not allocate
                    and not networked):
                # Independent blocks solved at once (setting `solve.separable`,
                # app.solve.blocks) -- unless something ties them together.
                refused = block_rows.refusal(
                    solving_model,
                    symmetry=bool(params.get("symmetry")),
                    pareto=bool(params.get("pareto_steps")),
                    robust=bool(robust_record),
                )
                parts = block_rows.blocks(solving_model) if refused is None else None
                if refused is not None or not block_rows.worth_splitting(parts):
                    blocks_record = {"solved_whole": refused or "the model is one block"}
                    parts = None
            with tracing.span("solve", solver=backend.name, time_limit_s=time_limit) as solving:
                if allocate:
                    allocated = allocation_rows.solve(solving_model)
                    result, reason, decomposition_record = allocated.solution, None, allocated.record
                elif networked:
                    networked_run = network_rows.solve(solving_model)
                    result, reason, network_record = networked_run.solution, None, networked_run.record
                elif stochastic_wanted:
                    result, stochastic_record = sandbox.run(
                        "app.solve.sandbox:stochastic_in_child",
                        {"backend": backend.name, "ir": ir, "data": data, "compiled": solving_model,
                         "samples": params["stochastic_samples"], "time_limit": time_limit, "seed": seed,
                         "workers": workers, "gap_rel": gap_rel},
                        time_limit=time_limit,
                        workers=workers,
                        should_stop=stop.is_set,
                    )
                    reason = None
                    # The answer is the plan: the rules it answers for are the ones that read only it.
                    plan_keys = set(result.assignments)
                    record_model = replace(compiled, constraints=[
                        c for c in compiled.constraints if {*c.left.coeffs, *c.right.coeffs} <= plan_keys])
                elif horizon_plan is not None:
                    windows_on = backend.name if "continuous" in backend.provides else "highs"
                    result, horizon_record = sandbox.run(
                        "app.solve.sandbox:horizon_in_child",
                        {"backend": windows_on, "compiled": solving_model, "time_set": horizon_plan[0],
                         "periods": horizon_plan[1], "time_limit": time_limit, "seed": seed, "workers": workers,
                         "gap_rel": gap_rel},
                        time_limit=time_limit,
                        workers=workers,
                        should_stop=stop.is_set,
                    )
                    horizon_record = {"used": True, "windows_on": windows_on, **horizon_record}
                    reason = None
                elif parts is not None:

                    def run_one(piece, share, piece_hint):
                        return sandbox.run(
                            "app.solve.sandbox:solve_in_child",
                            {"backend": backend.name, "compiled": piece, "time_limit": time_limit, "seed": seed,
                             "workers": share, "gap_rel": gap_rel, "hint": piece_hint},
                            time_limit=time_limit,
                            workers=share,
                            should_stop=stop.is_set,
                        )

                    # No progress curve while blocks solve: each has its own
                    # incumbent, and one line through them would go backwards.
                    result, reason, blocks_record = block_rows.solve(
                        solving_model, parts, run_one, workers=workers, optimal_gap=OPTIMAL_GAP, hint=hint
                    )
                    solving.set_attribute("blocks", len(parts))
                elif params.get("lns") and lns_rows.applies(backend.name, solving_model) is None:
                    # Fix most of a stalled answer and solve the rest again
                    # (setting `solve.lns`, app.solve.lns, queue R3).
                    result, lns_record = sandbox.run(
                        "app.solve.sandbox:lns_in_child",
                        {
                            "backend": backend.name,
                            "compiled": solving_model,
                            "time_limit": time_limit,
                            "seed": seed,
                            "workers": workers,
                            "gap_rel": gap_rel,
                            "symmetry": bool(params.get("symmetry")),
                        },
                        time_limit=time_limit,
                        workers=workers,
                        on_progress=events.progress,
                        should_stop=stop.is_set,
                    )
                    reason = None
                else:
                    if params.get("lns"):
                        lns_record = {"used": False, "why": lns_rows.applies(backend.name, solving_model)}
                    # In a child process with a memory ceiling, a CPU allowance
                    # and a deadline (app.solve.sandbox, Phase 9): a model that
                    # outgrows them fails with a reason, not the worker.
                    began_solve = time.monotonic()
                    try:
                        result, reason = sandbox.run(
                            "app.solve.sandbox:solve_in_child",
                            {
                                "backend": backend.name,
                                "compiled": solving_model,
                                "time_limit": time_limit,
                                "seed": seed,
                                "workers": workers,
                                "gap_rel": gap_rel,
                                "hint": hint,
                                "symmetry": bool(params.get("symmetry")),
                                "solver_params": tuned.get(backend.name),
                            },
                            time_limit=time_limit,
                            workers=workers,
                            on_progress=events.progress,
                            should_stop=stop.is_set,
                        )
                    except sandbox.SandboxFailed as exc:
                        if not ((start_record or {}).get("feasible") or params.get("metaheuristic")):
                            raise
                        # The solver crashed, but the start keeps every rule (it is the
                        # answer), or a search may still find one; if not, the crash stands.
                        result, reason = Solution("unknown", False, None, {}, 0.0, backend.name), None
                        exact_failed = exc
                        if start_record is not None:
                            start_record["solver_failed"] = str(exc)
                    if (start_record or {}).get("feasible") and not result.assignments:
                        # The solver ended with nothing: the start is the answer (queue R13).
                        result = partition_rows.as_answer(solving_model, hint, backend.name,
                                                          time.monotonic() - began_solve)
                        start_record["answer"] = True
                solving.set_attribute("status", result.status)
            if reason is not None:
                db.execute(text("UPDATE run SET error = :e WHERE id = :r"), {"e": reason, "r": run_id})
            if (params.get("local_fallback") and backend.name == "scip" and result.status in ("unknown", "feasible")
                    and not stop.is_set()):
                # SCIP ended without a proof on a continuous nonlinear model:
                # IPOPT, from SCIP's answer when there is one (setting
                # `solve.local_fallback`, app.solve.ipopt, queue R6).
                result, backend, local_record = _local_fallback(solving_model, found, backend, result,
                                                                time_limit=time_limit, seed=seed, workers=workers,
                                                                should_stop=stop.is_set)
                bind_log(solver=backend.name)
            if (params.get("metaheuristic") and result.status == "unknown" and not result.assignments
                    and not stop.is_set()):
                # The exact solver ended with nothing: a search over whole answers, which
                # proves nothing but may find one (setting `solve.metaheuristic`,
                # app.solve.evolve, queue R14).
                result, backend, search_record = _metaheuristic_fallback(
                    solving_model, found, backend, result, hint=hint, time_limit=time_limit, seed=seed,
                    workers=workers, should_stop=stop.is_set)
                bind_log(solver=backend.name)
            if exact_failed is not None and not result.assignments:
                raise exact_failed
            if exact_failed is not None and search_record is not None:
                search_record["exact_failed"] = str(exact_failed)
            if params.get("lagrangian") and result.status == "feasible" and result.objective is not None:
                # An answer without a proof: a bound from relaxing the few rules
                # that tie the model's blocks (setting `solve.lagrangian`,
                # app.solve.lagrange, queue R5), kept only when it is tighter.
                result, lagrange_record = _lagrangian_bound(solving_model, structure_record, backend, result,
                                                            time_limit=time_limit, seed=seed, workers=workers,
                                                            should_stop=stop.is_set)
        except _Answered:
            pass
        except (Unsupported, sandbox.SandboxFailed, stochastic_rows.NotStochastic) as exc:
            # The model is valid and this compiler cannot express it, or its
            # solve outgrew the sandbox. Either is a failed run with a reason,
            # not a crash and not an empty answer.
            db.execute(
                text(
                    "UPDATE run SET status = 'error', error = :e, finished_at = now()"
                    " WHERE id = :r"
                ),
                {"e": str(exc), "r": run_id},
            )
            db.commit()
            return RunOutcome(run_id, dataset_id, "error", None, {})

        # Stopped while solving. An answer found before the stop is still an
        # answer -- throwing it away made "Stop" cost everything the solver
        # had done -- so it is kept, as `feasible` with its gap, and marked.
        # Only a stop with nothing in hand is `cancelled`.
        stopped = _cancel_requested(db, run_id)
        if stopped and not (result.status in ("optimal", "feasible") and result.assignments):
            if _honour_cancel(db, run_id):
                return _cancelled_outcome(db, run_id)

    # Which solver ran, and why it was the one -- a result nobody can
    # attribute to a choice is not reproducible. Empty ranges ride along:
    # they are a fact about this compile, not a second table.
    extra = {"chosen_solver": backend.name, "why_solver": why}
    if backend.proves == "approximate":
        # What "optimal" means for this answer: to this tolerance, not proven.
        from app.solve.lp import PDLP_TOLERANCE

        extra["tolerance"] = PDLP_TOLERANCE
    if any(c.when for c in compiled.constraints) and "indicator" not in backend.provides:
        # What the solver was actually given: the conditional rules as big-M
        # rows, and the largest M each needed (principle 7: say so).
        extra["reformulations"] = bigm(compiled)[1]
    if compiled.pwl and "pwl-native" not in backend.provides:
        extra["reformulations"] = [*extra.get("reformulations", []), *pwl_rewrite(compiled)[1]]
    if params.get("symmetry") and compiled.symmetry and backend.name in symmetry_rows.FOR:
        extra["symmetry_rows"] = symmetry_rows.order_rows(compiled)[1]
    if blocks_record is not None:
        extra["blocks"] = blocks_record
    if race_record is not None:
        extra["probes"] = race_record
    if race_skipped is not None:
        extra["probe_skipped"] = race_skipped
    if portfolio_record is not None:
        extra["portfolio_entrants"] = portfolio_record
    if portfolio_skipped is not None:
        extra["portfolio_skipped"] = portfolio_skipped
    if lns_record is not None:
        extra["lns_search"] = lns_record
    if structure_record is not None:
        extra["structure"] = structure_record
    if lagrange_record is not None:
        extra["lagrangian_bound"] = lagrange_record
    if local_record is not None:
        extra["local_fallback_run"] = local_record
    if stochastic_record is not None:
        extra["stochastic"] = stochastic_record
    if horizon_record is not None:
        extra["rolling_horizon_run"] = horizon_record
    if decomposition_record is not None:
        extra["decomposition"] = decomposition_record
    if network_record is not None:
        extra["network_run"] = network_record
    computed = _computed_sources(db, run_id, ir)
    if computed:
        extra["computed_inputs"] = computed
    if start_record is not None:
        extra[start_key] = start_record
    if search_record is not None:
        extra["metaheuristic_run"] = search_record
    if shadow is not None:
        extra["selector"] = {**shadow, "chosen": backend.name, "agree": shadow["pick"] == backend.name}
    applied = {**solver_param_table.ENABLED.get(backend.name, {}), **tuned.get(backend.name, {})}
    if applied:
        # The benchmark's winners, applied to every solve of this backend, and a tuning's for this problem.
        extra["solver_params"] = applied
    if stopped:
        extra["stopped_by_request"] = True
    if robust_record is not None:
        extra["robust"] = {"rows": robust_record}
        if robust_record and nominal is not None:
            extra["robust"].update(_price(nominal, result, compiled.sense))
        elif not robust_record:
            extra["robust"]["note"] = (
                "no rule reads a parameter declared uncertain within a range, so the robust answer "
                "is the nominal one"
            )
    if points:
        extra["pareto"] = {
            "terms": list(compiled.objective_term_ids),
            "steps": int(params["pareto_steps"]),
            "points": len(points),
        }
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
    events.stage("post_processing")
    with tracing.span("persist"):
        db.execute(
            text(
                "UPDATE run SET solver = :s, params = params || CAST(:extra AS jsonb)"
                " WHERE id = :r"
            ),
            {"s": backend.name, "extra": _json(extra), "r": run_id},
        )
        _record(db, run_id, record_model or compiled, result)
        if result.objective is not None:
            events.final(result.objective, result.best_bound, result.wall_seconds)
        # What the answer may claim, as the backend that found it declares
        # (migration 0028): "optimal" from a local solver is not the same claim
        # as "optimal" from a global one, and the run must not blur the two.
        db.execute(
            text("UPDATE run SET optimality = :o WHERE id = :r"),
            # A stochastic plan is best for the sampled futures: an estimate, never proven best.
            {"o": "approximate" if stochastic_record is not None and result.status == "optimal"
             else optimality_of(backend, result.status), "r": run_id},
        )
        if points:
            _record_front(db, run_id, compiled, backend, points)
    if result.status == "infeasible":
        # "No answer exists" is true and useless on its own. Which rules
        # cannot hold together is the thing a planner can act on, and it is
        # only findable here, where the compiled model still exists.
        with tracing.span("diagnose", solver=backend.name):
            _record_conflict(db, run_id, solving_model, backend, time_limit)
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
    status = db.execute(text("SELECT status FROM run WHERE id = :r"), {"r": run_id}).scalar_one()
    if status != "queued":
        # Answered from the result cache: already settled, nothing to solve.
        return _stored_outcome(db, run_id)
    db.execute(
        text(
            "UPDATE run SET status = 'running', started_at = now(), heartbeat_at = now()"
            " WHERE id = :r"
        ),
        {"r": run_id},
    )
    return execute_run(db, run_id)


def _stored_outcome(db: Session, run_id: int) -> RunOutcome:
    row = db.execute(
        text(
            "SELECT r.dataset_id, r.status, r.objective, s.assignments"
            "  FROM run r LEFT JOIN solution s ON s.run_id = r.id"
            " WHERE r.id = :r"
        ),
        {"r": run_id},
    ).mappings().one()
    objective = row["objective"]
    if objective is not None:
        objective = int(objective) if objective == objective.to_integral_value() else float(objective)
    return RunOutcome(run_id, row["dataset_id"], row["status"], objective, row["assignments"] or {})


def _lock_bases(db: Session, problem_id: int, locks: list[dict[str, Any]]) -> dict[int, "lock_rows.Base"]:
    """What each run a lock reads from decided -- only answered runs of this same problem; any
    other is left out, and the lock that names it is refused when the model is compiled."""
    wanted = sorted(lock_rows.runs_named(locks))
    if not wanted:
        return {}
    rows = db.execute(
        text(
            "SELECT r.id, s.assignments, s.amounts"
            "  FROM run r JOIN solution s ON s.run_id = r.id JOIN scenario sc ON sc.id = r.scenario_id"
            " WHERE r.id = ANY(:ids) AND sc.problem_id = :p AND r.status IN ('optimal', 'feasible')"
        ),
        {"ids": wanted, "p": problem_id},
    ).all()
    return {int(r[0]): lock_rows.Base(r[1] or {}, r[2]) for r in rows}


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

    amounts, truncated = _kept_amounts(compiled, result)
    if truncated:
        db.execute(text("UPDATE run SET params = params || CAST(:t AS jsonb) WHERE id = :r"),
                   {"t": _json(truncated), "r": run_id})
    db.execute(
        text(
            "INSERT INTO solution (run_id, assignments, reduced_costs, amounts)"
            " VALUES (:r, :a, CAST(:rc AS jsonb), CAST(:am AS jsonb))"
        ),
        {
            "r": run_id,
            "a": _json(_assignments(compiled, result)),
            "am": None if amounts is None else _json(amounts),
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
    gap_rel: float = 0.0,
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
            compiled,
            time_limit=time_limit,
            workers=workers,
            should_stop=should_stop,
            seed=seed,
            gap_rel=gap_rel,
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
            stage,
            time_limit=remaining,
            workers=workers,
            should_stop=should_stop,
            seed=seed,
            gap_rel=gap_rel,
        )
        wall += result.wall_seconds
        stage_gap = gap_of(result.objective, result.best_bound)
        if stage_gap is not None and stage_gap > OPTIMAL_GAP:
            result = replace(result, status="feasible", optimal=False)
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


class SettingUnusable(ValueError):
    """A setting whose value a run cannot use, named -- refused before the run is queued."""

    def __init__(self, key: str, message: str) -> None:
        super().__init__(message)
        self.key = key


def _computed_sources(db: Session, run_id: int, ir: dict[str, Any]) -> list[dict[str, Any]]:
    """Where the parameters and relationships this model reads came from, when the platform computed
    them from the map (queue R16a): each one's name and `source`. Typed-in data says nothing."""
    parameters = sorted((ir.get("parameters") or {}).keys())
    relationships = sorted(ir.get("relationships") or [])
    if not parameters and not relationships:
        return []
    rows = db.execute(
        text(
            "SELECT 'parameter' AS kind, pd.name, pd.source FROM parameter_def pd"
            "  JOIN problem p ON p.domain_id = pd.domain_id JOIN scenario s ON s.problem_id = p.id"
            "  JOIN run r ON r.scenario_id = s.id"
            " WHERE r.id = :r AND pd.source IS NOT NULL AND pd.name = ANY(:params)"
            " UNION ALL "
            "SELECT 'relationship', rt.name, rt.source FROM relationship_type rt"
            "  JOIN problem p ON p.domain_id = rt.domain_id JOIN scenario s ON s.problem_id = p.id"
            "  JOIN run r ON r.scenario_id = s.id"
            " WHERE r.id = :r AND rt.source IS NOT NULL AND rt.name = ANY(:rels)"
            " ORDER BY 1, 2"
        ),
        {"r": run_id, "params": parameters, "rels": relationships},
    ).all()
    return [{**source, "input": kind, "name": name} for kind, name, source in rows]


def _time_set(db: Session, run_id: int, compiled: Compiled) -> str | None:
    """The model's time set (queue R9): the first of its sets whose entity type the domain gives the
    role `time` and that some decision is indexed by."""
    names = db.execute(
        text(
            "SELECT et.name FROM entity_type et"
            "  JOIN problem p ON p.domain_id = et.domain_id"
            "  JOIN scenario s ON s.problem_id = p.id"
            "  JOIN run r ON r.scenario_id = s.id"
            " WHERE r.id = :r AND et.role = 'time'"
        ),
        {"r": run_id},
    ).scalars().all()
    indexed = {name for index in compiled.var_index_sets.values() for name in index}
    return next((name for name in sorted(names) if name in indexed), None)


#: The share of the time given to IPOPT after SCIP ends without a proof (queue R6).
LOCAL_SHARE = 0.25
#: The metaheuristic's share of the run's time after an exact solver ended with nothing (queue R14).
SEARCH_SHARE = 0.25
#: Which search, by what the model decides: set by bench/results/2026-09-25-metaheuristics.md.
SEARCH_CONTINUOUS, SEARCH_WHOLE = "ga", "ga"


def _metaheuristic_fallback(compiled, found, backend, result, *, hint, time_limit: float, seed, workers: int,
                            should_stop):
    """After an exact solver ended with no answer: a metaheuristic's, which keeps every rule and claims
    nothing -- `feasible`, no bound. Nothing found, or a model it cannot search, leaves the run as it was."""
    from app.solve.backends import by_name

    whole = any(v.is_integral for v in compiled.variables.values())
    method = SEARCH_WHOLE if whole else SEARCH_CONTINUOUS
    searcher = by_name(method)
    if found.model_class not in searcher.classes or (found.needs - searcher.provides):
        return result, backend, {"used": False, "why": f"{method} cannot take a {found.model_class} model like this"}
    seconds = max(1.0, SEARCH_SHARE * time_limit)
    try:
        searched, _ = sandbox.run(
            "app.solve.sandbox:solve_in_child",
            {"backend": method, "compiled": compiled, "time_limit": seconds, "seed": seed, "workers": workers,
             "gap_rel": 0.0, "hint": hint},
            time_limit=seconds, workers=workers, should_stop=should_stop,
        )
    except (Unsupported, NotContinuous, sandbox.SandboxFailed) as exc:
        return result, backend, {"used": False, "why": str(exc)}
    record = {"used": True, "method": method, "after": backend.name, "seconds": seconds, "status": searched.status,
              "objective": searched.objective}
    if not searched.assignments:
        return result, backend, {**record, "kept": False}
    return searched, searcher, {**record, "kept": True}


def _local_fallback(compiled, found, backend, result, *, time_limit: float, seed, workers: int, should_stop):
    """After SCIP ends without a proof on a continuous nonlinear model: IPOPT, from SCIP's answer.

    With no answer from SCIP, IPOPT's is the run's, and it claims what IPOPT proves -- `local`. With
    one, IPOPT polishes it: a better answer is kept, SCIP's global bound still stands over it, and it is
    optimal only if it meets that bound (then proven best, by SCIP's bound)."""
    from app.solve.backends import IPOPT

    if not IPOPT.is_available() or found.model_class not in IPOPT.classes or (found.needs - IPOPT.provides):
        return result, backend, {"used": False, "why": f"ipopt cannot take a {found.model_class} model like this"}
    seconds = max(1.0, LOCAL_SHARE * time_limit)
    hint = result.assignments or None
    try:
        local, _ = sandbox.run(
            "app.solve.sandbox:solve_in_child",
            {"backend": "ipopt", "compiled": compiled, "time_limit": seconds, "seed": seed, "workers": workers,
             "gap_rel": 0.0, "hint": hint},
            time_limit=seconds, workers=workers, should_stop=should_stop,
        )
    except (Unsupported, NotContinuous, sandbox.SandboxFailed) as exc:
        return result, backend, {"used": False, "why": str(exc)}
    record = {"used": True, "from": "scip's answer" if hint else "the middle of each range",
              "ipopt_status": local.status, "ipopt_objective": local.objective, "scip_objective": result.objective}
    if local.objective is None:
        return result, backend, {**record, "kept": False}
    if result.objective is None:
        # Nothing from SCIP: IPOPT's answer, worth what IPOPT proves.
        return local, IPOPT, {**record, "kept": True}
    # Better by more than rounding: IPOPT's answer is read back to six places.
    margin = 1e-7 * max(1.0, abs(float(result.objective)))
    better = (float(local.objective) < float(result.objective) - margin if compiled.sense == "minimize"
              else float(local.objective) > float(result.objective) + margin)
    if not better:
        return result, backend, {**record, "kept": False}
    gap = gap_of(local.objective, result.best_bound)
    proven = gap is not None and gap <= OPTIMAL_GAP
    polished = replace(result, objective=local.objective, assignments=local.assignments,
                       status="optimal" if proven else "feasible", optimal=proven,
                       wall_seconds=round(result.wall_seconds + local.wall_seconds, 3))
    return polished, backend, {**record, "kept": True}


def _lagrangian_bound(compiled, found, backend, result, *, time_limit: float, seed, workers: int, should_stop):
    """`result` with the Lagrangian bound when it is tighter than the solver's own, and what was tried."""
    why = lagrange_rows.applies(compiled, found)
    if why is not None:
        return result, {"used": False, "why": why}
    seconds = max(1.0, lagrange_rows.SHARE * time_limit)
    try:
        bound, record = sandbox.run(
            "app.solve.sandbox:lagrange_in_child",
            {"backend": backend.name, "compiled": compiled, "found": found, "answer": result.objective,
             "time_limit": seconds, "seed": seed, "workers": workers},
            time_limit=seconds, workers=workers, should_stop=should_stop,
        )
    except (Unsupported, sandbox.SandboxFailed) as exc:
        return result, {"used": False, "why": str(exc)}
    own = result.best_bound
    tighter = bound is not None and (own is None or (bound > own if compiled.sense == "minimize" else bound < own))
    record = {"used": True, **record, "solver_bound": own, "kept": tighter}
    if not tighter:
        return result, record
    proven = gap_of(result.objective, bound) is not None and gap_of(result.objective, bound) <= OPTIMAL_GAP
    return replace(result, best_bound=bound, status="optimal" if proven else result.status,
                   optimal=proven or result.optimal), record


def solve_compiled(
    backend,
    compiled: Compiled,
    *,
    time_limit: float,
    seed: int | None = None,
    should_stop=None,
    workers: int = 8,
    gap_rel: float = 0.0,
    on_progress=None,
    hint: dict | None = None,
    symmetry: bool = False,
    solver_params: dict | None = None,
) -> tuple[Solution, str | None]:
    """Solve a compiled model as a run does, and say why if it is unbounded.

    Both objective modes, then the check for an answer resting on a ceiling
    the model never set (`_unbounded_ceilings`). The reason is None unless the
    status is `unbounded`. The golden suite calls this, so what it pins is
    what a run records.

    **"Optimal" means the gap is closed.** A backend asked to stop within
    `gap_rel` of the best -- or one whose own default tolerance crept in --
    can report `optimal` with a bound that is not the answer. Whatever it
    says, an answer whose recorded gap exceeds `OPTIMAL_GAP` is `feasible`.
    """
    if any(c.when for c in compiled.constraints) and "indicator" not in backend.provides:
        # No native indicator: conditional rules as a big-M from declared
        # bounds (`reformulate.admit` routed only such a model here).
        compiled, _ = bigm(compiled)
    if compiled.pwl and "pwl-native" not in backend.provides:
        # Curves as linear rows: an epigraph where the goal allows, else the
        # incremental formulation (app.solve.reformulate).
        compiled, _ = pwl_rewrite(compiled)
    if (
        backend.name in mccormick.FOR
        and (compiled.objective_quadratic or any(c.quadratic for c in compiled.constraints))
        and mccormick.blocked(compiled) is None
    ):
        # Products of a yes-or-no decision as linear rows, exactly
        # (`mccormick.admit` routed such a model here). Any other product
        # reaching HiGHS is a convex continuous QP, which it solves itself.
        compiled, _ = mccormick.linearise(compiled)
    if symmetry and compiled.symmetry and backend.name in symmetry_rows.FOR:
        # Interchangeable entities ordered, for a backend that does not
        # detect symmetry itself (setting `solve.symmetry`).
        compiled, _ = symmetry_rows.order_rows(compiled)
    if (compiled.intervals or any(c.schedule for c in compiled.constraints)) and "scheduling" not in getattr(
        backend, "provides", ()
    ):
        # `choose` never routes one here; an empty row would be an answer
        # that ignores the rule.
        raise Unsupported(f"{backend.name} holds no scheduling rule or interval")
    knobs = {"seed": seed, "workers": workers, "gap_rel": gap_rel}
    if hint:
        # Only when there is one: a backend that takes none need not know.
        knobs["hint"] = hint
    if solver_params:
        knobs["solver_params"] = solver_params
    started = time.monotonic()
    # Only the first solve is watched: the re-solve that tests a ceiling
    # (`_unbounded_ceilings`) answers a different question, and a
    # lexicographic run's stages each optimise something else, so its
    # numbers would not belong on one curve.
    result = _solve(backend, compiled, time_limit, knobs, should_stop, on_progress)
    unbounded = _unbounded_ceilings(
        backend,
        compiled,
        result,
        max(0.5, time_limit - (time.monotonic() - started)),
        knobs,
        should_stop,
    )
    if unbounded is not None:
        return unbounded
    gap = gap_of(result.objective, result.best_bound)
    if result.status == "optimal" and gap is not None and gap > OPTIMAL_GAP:
        result = replace(result, status="feasible", optimal=False)
    return result, None


# The widest gap an answer may have and still be called optimal. Not zero:
# solvers prove optimality to their own feasibility tolerances, and a bound
# that differs from the answer in the eighth figure is that, not a gap.
OPTIMAL_GAP = 1e-6


def _solve(
    backend, compiled: Compiled, time_limit: float, knobs: dict, should_stop, on_progress=None
) -> Solution:
    if compiled.objective_mode == "lex":
        return _solve_lex(
            backend,
            compiled,
            time_limit=time_limit,
            should_stop=should_stop,
            **knobs,
        )
    return backend.solve(
        compiled, time_limit=time_limit, should_stop=should_stop, on_progress=on_progress, **knobs
    )


def _unbounded_ceilings(
    backend, compiled: Compiled, result: Solution, time_limit: float, knobs: dict, should_stop
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
    again = _solve(backend, lifted, time_limit, knobs, should_stop)
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


class RunEvents:
    """What a run did while it ran, written as it happens (migration 0036).

    Its own session: the run's is held inside a solver call for as long as
    the solve takes, and these rows are the point of being able to watch
    one. Progress is throttled to `EVERY_SECONDS`, keeping the latest of
    whatever arrived in between and writing it when the window passes or at
    the end, so a solver finding a thousand answers a second costs two rows.

    Each write notifies `run_<id>`, which is what an open events stream
    (`GET /runs/{id}/events`) waits on.
    """

    EVERY_SECONDS = 0.5

    def __init__(self, run_id: int):
        from app.core.db import SessionLocal

        self.run_id = run_id
        self.session = SessionLocal()
        self.lock = threading.Lock()
        self.seq = (
            self.session.execute(
                text("SELECT coalesce(max(seq), 0) FROM run_event WHERE run_id = :r"), {"r": run_id}
            ).scalar_one()
            + 1
        )
        self.last_write = 0.0
        self.pending: tuple[str, dict] | None = None

    def stage(self, name: str, **facts: Any) -> None:
        with self.lock:
            self._flush()
            self._write("stage", {"stage": name, **facts})

    def final(self, objective, bound, seconds: float) -> None:
        """The answer a run ended with, as a point of its own.

        A model small enough to be settled in presolve reports nothing while
        it solves -- there is no "while" -- and its curve would be empty.
        This gives every solved run at least the point it ended at.
        """
        with self.lock:
            self._flush()
            self._write(
                "incumbent",
                {
                    "t": round(float(seconds or 0), 3),
                    "objective": None if objective is None else float(objective),
                    "bound": None if bound is None else float(bound),
                },
            )

    def progress(self, kind: str, payload: dict) -> None:
        with self.lock:
            now = time.monotonic()
            if now - self.last_write >= self.EVERY_SECONDS:
                self._write(kind, payload)
            else:
                self.pending = (kind, payload)

    def close(self) -> None:
        with self.lock:
            self._flush()
        self.session.close()

    def _flush(self) -> None:
        if self.pending is not None:
            kind, payload = self.pending
            self.pending = None
            self._write(kind, payload)

    def _write(self, kind: str, payload: dict) -> None:
        try:
            self.session.execute(
                text(
                    "INSERT INTO run_event (run_id, seq, kind, payload)"
                    " VALUES (:r, :s, :k, CAST(:p AS jsonb))"
                ),
                {"r": self.run_id, "s": self.seq, "k": kind, "p": _json(payload)},
            )
            self.session.execute(
                text("SELECT pg_notify('run_' || :r, :s)"), {"r": str(self.run_id), "s": str(self.seq)}
            )
            self.session.commit()
            self.seq += 1
            self.last_write = time.monotonic()
        except Exception:  # pragma: no cover -- watching must not break solving
            self.session.rollback()
            logger.warning("could not record a run event", exc_info=True)


def _admissible(found) -> set[str]:
    """Every available backend the rules let take this model and that proves
    its optimum: memory and the probe race compare proofs, and an
    approximate answer (PDLP) is none."""
    from app.solve.backends import REGISTRY

    names = set()
    for candidate in REGISTRY:
        if candidate.proves != "global":
            continue
        try:
            choose(found, candidate.name)
            names.add(candidate.name)
        except NoBackend:
            continue
    return names


def _rank_of(name: str) -> tuple[int, str]:
    return (by_name(name).rank, name)


def _recall(db: Session, run_id: int, found):
    from app.solve.memory import RECENT, recall

    admissible = _admissible(found)
    history = db.execute(
        text(
            "SELECT r.solver, r.wall_time_s FROM run r JOIN scenario s ON s.id = r.scenario_id"
            " WHERE s.problem_id = (SELECT s2.problem_id FROM run r2 JOIN scenario s2 ON s2.id = r2.scenario_id WHERE r2.id = :r)"
            # A proven optimum only: an approximate one (PDLP) says nothing
            # about which solver proves this problem fastest.
            "   AND r.id <> :r AND r.status = 'optimal' AND r.optimality = 'global'"
            "   AND r.reused_from IS NULL AND r.wall_time_s IS NOT NULL"
            "   AND r.params->>'pareto_of' IS NULL"
            " ORDER BY r.id DESC LIMIT :n"
        ),
        {"r": run_id, "n": RECENT},
    ).all()
    return recall([(solver, seconds) for solver, seconds in history], admissible)


def _record_fingerprint(db: Session, run_id: int, compiled: Compiled) -> dict | None:
    try:
        numbers = fingerprint_of(compiled)
    except Exception:  # noqa: BLE001 -- a fact for later must never fail the run
        logger.warning("could not fingerprint run %s", run_id, exc_info=True)
        return None
    db.execute(
        text("UPDATE run SET params = params || CAST(:f AS jsonb) WHERE id = :r"),
        {"f": _json({"fingerprint": numbers}), "r": run_id},
    )
    # Committed now, not with the answer: an uncommitted write holds the
    # run's row for the whole solve, and a request to stop it (another
    # session's UPDATE) would wait until the solve had ended.
    db.commit()
    return numbers


def _price(nominal: Solution, robust: Solution, sense: str) -> dict[str, Any]:
    """What protection costs: the robust goal against the nominal one, both
    as found (proven or not), and the difference in the goal's own terms."""
    out: dict[str, Any] = {"nominal_status": nominal.status, "nominal": nominal.objective}
    if nominal.objective is not None and robust.objective is not None:
        worse = (robust.objective - nominal.objective) * (1 if sense == "minimize" else -1)
        out["price"] = worse
        if nominal.objective:
            out["price_share"] = round(worse / abs(nominal.objective), 6)
    return out


class _Answered(Exception):
    """The answer is already in hand (a Pareto front's first end): skip the solve."""


def _point_solution(compiled: Compiled, point) -> Solution:
    """A front point as a run's answer: the model's whole goal as its value,
    its status as proven or not, and no bound (the bound of its last solve
    was on one term, not on the goal)."""
    value = compiled.objective.evaluated_at(point.solution.assignments)
    objective = int(value) if compiled.is_integral and value == value.to_integral_value() else float(value)
    return replace(point.solution, status=point.status, optimal=point.status == "optimal",
                   objective=objective, best_bound=None)


def _record_front(db: Session, run_id: int, compiled: Compiled, backend, points) -> None:
    """Each point as a run of its own, already finished, and the front."""
    parent = db.execute(
        text("SELECT scenario_id, dataset_id, seed, compiler_version FROM run WHERE id = :r"), {"r": run_id}
    ).mappings().one()
    for seq, point in enumerate(points, start=1):
        child = db.execute(
            text(
                "INSERT INTO run (scenario_id, dataset_id, status, solver, compiler_version, params, seed, started_at)"
                " VALUES (:s, :d, 'running', :solver, :cv, CAST(:params AS jsonb), :seed, now())"
                " RETURNING id"
            ),
            {
                "s": parent["scenario_id"],
                "d": parent["dataset_id"],
                "solver": backend.name,
                "cv": parent["compiler_version"],
                "seed": parent["seed"],
                "params": _json({"pareto_of": run_id, "pareto_point": seq, "epsilon": point.epsilon,
                                 "chosen_solver": backend.name}),
            },
        ).scalar_one()
        solution = _point_solution(compiled, point)
        _record(db, child, compiled, solution)
        db.execute(
            text("UPDATE run SET optimality = :o WHERE id = :r"),
            {"o": optimality_of(backend, solution.status), "r": child},
        )
        db.execute(
            text(
                "INSERT INTO pareto_point (run_id, seq, first_value, second_value, epsilon, status, point_run_id)"
                " VALUES (:r, :seq, :a, :b, :e, :st, :child)"
            ),
            {"r": run_id, "seq": seq, "a": point.first, "b": point.second, "e": point.epsilon,
             "st": point.status, "child": child},
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
    probe_seconds = min(DEFAULT_PROBE_SECONDS, max(1.0, time_limit / 4))
    try:
        # Sandboxed like the solve: diagnosis solves the model many times.
        conflict = sandbox.run(
            "app.solve.sandbox:explain_in_child",
            {"backend": backend.name, "compiled": compiled, "probe_seconds": probe_seconds},
            time_limit=probe_seconds,
            deadline_s=probe_seconds * DEFAULT_BUDGET + 30,
        )
    except sandbox.SandboxFailed as exc:
        db.execute(
            text("UPDATE run SET params = params || CAST(:note AS jsonb) WHERE id = :r"),
            {"note": _json({"conflict_note": f"the diagnosis could not finish: {exc}"}), "r": run_id},
        )
        return
    db.execute(
        text(
            "UPDATE run SET conflict = :c, conflict_minimal = :m,"
            "               params = params || CAST(:note AS jsonb)"
            " WHERE id = :r"
        ),
        {
            "c": _json(conflict.items),
            "m": conflict.minimal,
            "note": _json(
                {
                    "conflict_note": conflict.note,
                    "conflict_method": conflict.method,
                    "conflict_probes": conflict.probes,
                    "conflict_seconds": conflict.seconds,
                }
            ),
            "r": run_id,
        },
    )


def _assignments(compiled: Compiled, result: Solution) -> dict[str, list[list[str]]]:
    """The answer in the domain's own words: which index tuples each variable
    took. Violation variables are not part of the roster and are reported
    through `constraint_result` instead."""
    out: dict[str, list[list[str]]] = {name: [] for name in compiled.var_index_sets}
    for (name, index), value in sorted(result.assignments.items()):
        # Violations and the auxiliaries a curve stands for are not decisions
        # anyone made; `__` names are the compiler's own.
        if not name.startswith("__") and value:
            out.setdefault(name, []).append(list(index))
    return out


#: Past this many used whole or fractional cells, a run keeps no amounts (queue R23): the roster
#: still says which were used, and `params.amounts_truncated` says how many there were.
AMOUNT_CELLS = 200_000


def _kept_amounts(compiled: Compiled, result: Solution) -> tuple[dict[str, list[dict[str, Any]]] | None, dict]:
    """The amounts a run keeps, and the note for `run.params` when it keeps none because there are too many."""
    amounts = _amounts(compiled, result)
    cells = sum(len(rows) for rows in amounts.values())
    if cells > AMOUNT_CELLS:
        return None, {"amounts_truncated": cells}
    return amounts, {}


def _amounts(compiled: Compiled, result: Solution) -> dict[str, list[dict[str, Any]]]:
    """How much each whole-number or continuous decision took, where it took any (queue R17):
    what a heat matrix, bars or a line are drawn from. A yes-or-no decision says all it has
    to say in `_assignments`."""
    out: dict[str, list[dict[str, Any]]] = {}
    for (name, index), value in sorted(result.assignments.items()):
        variable = compiled.variables.get((name, index))
        if name.startswith("__") or not value or variable is None or variable.domain == "binary":
            continue
        out.setdefault(name, []).append({"index": list(index), "value": _json_number(value)})
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
        if name.startswith("__") or abs(value) < _REDUCED_COST_FLOOR:
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
