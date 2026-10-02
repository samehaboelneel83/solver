""""Why not?" -- a question about an answered run (queue R26).

A planner looks at a plan and asks why a cell is not otherwise: why isn't Ann on Monday early?
The question is a list of cells and the value each should have. It is answered by a **probe**:
a run of the same scenario on the *same frozen data* as the plan (not today's), with the asked
cells locked (`app.solve.locks`) and, among the plans that allow them, the one closest to the plan
asked about (`stay_close`, lex). So a probe answers "the least that has to change for this to be
so", and its **verdict** says one of:

- ``already`` -- the plan already has every asked cell at the asked value; no run is made;
- ``blocked`` -- no plan allows it: the conflict found by the diagnoser, in which the asked cells
  appear as the locks ``forced`` names (``lock:N``) beside the rules they fight;
- ``possible`` -- a plan allows it at this cost (``delta`` against the plan, whether that is
  ``proven``), moving ``change`` cells (the lex stay-close measure), with the cells it turned on
  and off;
- ``unanswered`` -- the probe ended without an answer (a time limit, an error); it says which,
  and never guesses.

A probe is a run like any other -- it takes a worker, counts against the organization's quota and
is metered -- and at most `OPEN_PROBES` of an organization's are open at once, so asking cannot
crowd out planning. A probe of a probe is refused: ask about a plan.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.solve.locks import PREFIX

#: How many of an organization's probes may be queued or running at once.
OPEN_PROBES = 3
#: How many cells one question may ask about.
MAX_CELLS = 20
#: How many turned-on and turned-off cells a verdict lists.
LISTED_CELLS = 50

#: The request keys a probe keeps from the plan's run: how it was solved, not what it found.
_KEPT = ("time_limit_s", "workers", "gap_rel", "cpsat_scaling", "symmetry", "separable", "pdlp", "memory",
         "probe", "portfolio", "lns", "lagrangian", "local_fallback", "rolling_horizon", "decompose",
         "connected_start", "metaheuristic", "network", "routing_start", "solver_params_setting", "tuned_from",
         "requested_solver", "robust", "classified_as", "why", "needs", "from_settings")


class NotAskable(Exception):
    """A question that cannot be asked of this run. `code` names why; `status` is the HTTP status."""

    def __init__(self, code: str, message: str, status: int = 422):
        super().__init__(message)
        self.code, self.status = code, status


def ask(db: Session, run_id: int, force: list[dict[str, Any]],
        override: list[dict[str, Any]] | None = None) -> tuple[int | None, dict[str, Any] | None]:
    """Queue a probe of `run_id` with the cells in `force` locked and the parameter values in
    `override` changed (a what-if, queue R27: on a copy of the frozen data, never the stored
    dataset), or answer at once when the plan already has every asked cell and nothing is
    changed. Returns (the probe's run id, None) or (None, the verdict)."""
    override = override or []
    if not force and not override:
        raise NotAskable("why_not_empty", "ask about at least one cell or one changed value")
    if len(force) + len(override) > MAX_CELLS:
        raise NotAskable("why_not_too_many",
                         f"ask about at most {MAX_CELLS} cells and values at once, not {len(force) + len(override)}")
    run = db.execute(
        text(
            "SELECT r.id, r.status, r.purpose, r.params, r.seed, r.scenario_id, r.dataset_id, r.solver,"
            "       r.compiler_version, s.patch, mv.ir, so.assignments"
            "  FROM run r JOIN scenario s ON s.id = r.scenario_id JOIN model_version mv ON mv.id = r.model_version_id"
            "  LEFT JOIN solution so ON so.run_id = r.id"
            " WHERE r.id = :r"
        ),
        {"r": run_id},
    ).mappings().one_or_none()
    if run is None:
        raise NotAskable("why_not_no_run", "run not found", 404)
    if run["purpose"] != "plan":
        raise NotAskable("why_not_of_a_probe", f"run {run_id} is itself a question; ask about the plan it asked of",
                         409)
    if run["status"] not in ("optimal", "feasible") or run["assignments"] is None:
        raise NotAskable("why_not_unanswered", f"run {run_id} has no plan to ask about (it is {run['status']})", 409)
    if (run["params"] or {}).get("pareto_steps"):
        raise NotAskable("why_not_front", "a trade-off front is many plans; ask about one of its points", 409)
    _check_cells(run["ir"], force)
    _check_overrides(run["ir"], override)

    used = {(name, tuple(row)) for name, rows in (run["assignments"] or {}).items() for row in rows}
    domains = {name: spec.get("domain") for name, spec in (run["ir"].get("variables") or {}).items()}
    if not override and all(domains[c["var"]] == "binary" and ((c["var"], tuple(c["index"])) in used) == (c["value"] == 1)
           for c in force):
        return None, {"kind": "already", "cells": force}

    from app.solve.service import _check_quota_before_snapshot, quota_of

    organization = db.execute(text("SELECT organization_id FROM run WHERE id = :r"), {"r": run_id}).scalar_one()
    # The organization's limits on time and CPU hold for a probe as for any run; the count of
    # waiting plans does not -- a probe has its own allowance, below.
    quota = {k: v for k, v in quota_of(db, organization).items() if k != "max_queued_runs"}
    _check_quota_before_snapshot(db, organization, quota, float((run["params"] or {}).get("time_limit_s", 10.0)))
    open_now = db.execute(
        text("SELECT count(*) FROM run WHERE purpose = 'why_not' AND status IN ('queued', 'running')")
    ).scalar_one()
    if open_now >= OPEN_PROBES:
        raise NotAskable("why_not_open", f"{open_now} questions are still being answered; at most {OPEN_PROBES} "
                         "at once -- wait for one to finish", 429)

    params = {k: v for k, v in (run["params"] or {}).items() if k in _KEPT}
    scenario_locks = list((run["patch"] or {}).get("lock") or [])
    params["probe_patch"] = {
        "lock": [*scenario_locks, *({"var": c["var"], "index": c["index"], "value": c["value"]} for c in force)],
        "stay_close": {"from_run": run_id, "mode": "lex"},
        **({"override": override} if override else {}),
    }
    params["forced"] = [f"{PREFIX}{len(scenario_locks) + n}" for n in range(1, len(force) + 1)]
    params["warm_start"] = False
    probe = db.execute(
        text(
            "INSERT INTO run (scenario_id, dataset_id, status, solver, compiler_version, params, seed,"
            "                 purpose, parent_run_id)"
            " VALUES (:s, :d, 'queued', :solver, :cv, CAST(:params AS jsonb), :seed, 'why_not', :parent)"
            " RETURNING id"
        ),
        {"s": run["scenario_id"], "d": run["dataset_id"], "solver": run["solver"], "cv": run["compiler_version"],
         "params": json.dumps(params), "seed": run["seed"], "parent": run_id},
    ).scalar_one()
    db.commit()
    return int(probe), None


def _check_cells(ir: dict[str, Any], force: list[dict[str, Any]]) -> None:
    """Each asked cell names a decision of the plan's model, with a key per set and a number."""
    variables = ir.get("variables") or {}
    for n, cell in enumerate(force):
        spec = variables.get(cell.get("var"))
        if not isinstance(spec, dict) or spec.get("domain") == "interval":
            raise NotAskable("why_not_unknown", f"cell {n + 1}: the model has no decision {cell.get('var')!r}")
        if len(cell.get("index") or []) != len(spec.get("index") or []):
            raise NotAskable("why_not_index_arity",
                             f"cell {n + 1}: {cell['var']!r} is indexed by {spec.get('index')}, so a cell names "
                             f"{len(spec.get('index') or [])} keys")


def _check_overrides(ir: dict[str, Any], override: list[dict[str, Any]]) -> None:
    """Each changed value names a number parameter of the plan's model, with a key per set."""
    parameters = ir.get("parameters") or {}
    for n, cell in enumerate(override):
        spec = parameters.get(cell.get("param"))
        if not isinstance(spec, dict) or spec.get("entity"):
            raise NotAskable("why_not_unknown",
                             f"value {n + 1}: the model has no number parameter {cell.get('param')!r}")
        if len(cell.get("index") or []) != len(spec.get("index") or []):
            raise NotAskable("why_not_index_arity",
                             f"value {n + 1}: {cell['param']!r} is indexed by {spec.get('index')}, so a value names "
                             f"{len(spec.get('index') or [])} keys")


def overridden(data: dict[str, Any], ir: dict[str, Any], override: list[dict[str, Any]]) -> dict[str, Any]:
    """A copy of the frozen data with some parameter values changed: a cell stored replaced, a
    cell not stored (which took the default) added. Keys by set name, or by position where a
    set repeats -- as the dataset keys them."""
    data = {**data, "parameters": {k: [dict(r) for r in rows] for k, rows in (data.get("parameters") or {}).items()}}
    for cell in override:
        sets = (ir.get("parameters") or {})[cell["param"]].get("index") or []
        names = sets if len(set(sets)) == len(sets) else [str(p) for p in range(len(sets))]
        key = {name: str(k) for name, k in zip(names, cell["index"])}
        rows = data["parameters"].setdefault(cell["param"], [])
        match = next((r for r in rows if all(str(r.get(n)) == v for n, v in key.items())), None)
        if match is None:
            rows.append({**key, "value": cell["value"]})
        else:
            match["value"] = cell["value"]
    return data


def settle(db: Session, run_id: int) -> None:
    """Write a settled probe's verdict. Nothing for a run that is not a probe."""
    probe = db.execute(
        text(
            "SELECT r.purpose, r.status, r.objective, r.params, r.conflict, r.conflict_minimal, r.error,"
            "       p.objective AS parent_objective, p.id AS parent,"
            "       ps.assignments AS before, rs.assignments AS after"
            "  FROM run r JOIN run p ON p.id = r.parent_run_id"
            "  LEFT JOIN solution ps ON ps.run_id = p.id LEFT JOIN solution rs ON rs.run_id = r.id"
            " WHERE r.id = :r"
        ),
        {"r": run_id},
    ).mappings().one_or_none()
    if probe is None or probe["purpose"] != "why_not":
        return
    params = probe["params"] or {}
    forced = params.get("forced") or []
    changed = (params.get("probe_patch") or {}).get("override")
    if probe["status"] == "infeasible":
        verdict: dict[str, Any] = {
            "kind": "blocked", "forced": forced, "conflict": probe["conflict"],
            "minimal": probe["conflict_minimal"],
            **({"note": params["conflict_note"]} if params.get("conflict_note") else {}),
        }
    elif probe["status"] in ("optimal", "feasible") and probe["after"] is not None:
        before, after = _cells(probe["before"]), _cells(probe["after"])
        objective, parent = probe["objective"], probe["parent_objective"]
        verdict = {
            "kind": "possible", "proven": probe["status"] == "optimal",
            "objective": _number(objective),
            "delta": _number(objective - parent) if objective is not None and parent is not None else None,
            "change": (params.get("stay_close") or {}).get("change"),
            "turned_on": [list(c) for c in sorted(after - before)][:LISTED_CELLS],
            "turned_off": [list(c) for c in sorted(before - after)][:LISTED_CELLS],
        }
    else:
        verdict = {"kind": "unanswered", "status": probe["status"], "error": probe["error"]}
    if changed:
        verdict["override"] = changed
    db.execute(text("UPDATE run SET verdict = CAST(:v AS jsonb) WHERE id = :r"),
               {"v": json.dumps(verdict), "r": run_id})
    db.commit()


def _cells(assignments: dict[str, list[list[str]]] | None) -> set[tuple]:
    return {(name, *row) for name, rows in (assignments or {}).items() for row in rows}


def _number(value: Decimal | None) -> int | float | None:
    if value is None:
        return None
    return int(value) if value == value.to_integral_value() else float(value)
