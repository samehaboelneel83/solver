"""The conformance kit (queue R43): what an added solver must get right before the platform chooses
it unasked.

Every built-in already meets these; an adapter (`app.solve.adapters`) is run through the same
checks, each on a small model whose answer is worked out by hand in its comment:

- **answers** -- a linear program, a whole-number program, an equality, negative bounds, a model
  with no rules, one that asks nothing: the status and the objective, to 1e-6;
- **infeasible** and **unbounded** are said as such (or, for unbounded, as the platform's own
  "without limit" -- `solve_compiled` turns an answer resting on a ceiling nobody set into that);
- **every answer holds**: each value re-checked against every rule and bound (`evolve.holds`);
- **a bad hint** does not change the proven optimum;
- **the time limit**: a model too hard to finish is stopped in time, and says only what it knows;
- **a stop request** ends the solve early -- recorded as honoured or not; not honouring it is a
  note, not a failure (the sandbox still stops the solve at its limit).

A check the adapter does not take (its manifest does not claim the model's class or needs) is
skipped, not failed. **Passed** means no check failed and at least one answer was checked.

Where it runs: `python -m bench.conformance <adapter> [--store]`, or `POST /solvers/{name}/
conformance` by an operator. The result is stored per adapter and version (`solver_conformance`,
migration 0072); an adapter whose current version passed becomes eligible to be chosen unasked.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.solve import compile_model, evolve
from app.solve.classify import classify
from app.solve.convexity import refine

NO_DATA: dict[str, Any] = {"sets": {}, "parameters": {}, "parameter_defaults": {}, "relationships": {}}
#: Beyond a check's time limit, how long a solve may take before the check fails.
LATE_S = 10.0


def _v(name):
    return {"var": name, "index": []}


def _c(value):
    return {"const": value}


def _mul(a, b):
    return {"mul": [a, b]}


def _add(*terms):
    return {"add": list(terms)}


def _rule(rid, left, relation, right):
    return {"id": rid, "left": left, "relation": relation, "right": right, "severity": "hard"}


def _model(variables: dict, rules: list, sense: str | None = None, goal=None) -> dict:
    ir: dict[str, Any] = {"version": 1, "sets": [], "parameters": {},
                          "variables": {n: {"index": [], **spec} for n, spec in variables.items()},
                          "constraints": rules}
    if sense is not None:
        ir["objective"] = {"sense": sense, "terms": [{"id": "o_goal", "weight": 1, "expression": goal}]}
    return ir


INT = {"domain": "integer", "lower": 0, "upper": 10}
BIN = {"domain": "binary"}
REAL = {"domain": "continuous", "lower": 0, "upper": 100}

#: (name, model, status, objective) -- each worked by hand.
CASES: list[tuple[str, dict, str, Decimal | None]] = [
    # max 3x + 2y, x + y <= 4, x + 3y <= 6, both in 0..100: the vertex x = 4, y = 0 -> 12.
    ("lp", _model({"x": REAL, "y": REAL}, [
        _rule("c_a", _add(_v("x"), _v("y")), "<=", _c(4)),
        _rule("c_b", _add(_v("x"), _mul(_c(3), _v("y"))), "<=", _c(6))],
        "maximize", _add(_mul(_c(3), _v("x")), _mul(_c(2), _v("y")))), "optimal", Decimal(12)),
    # Knapsack: weights 5 4 3 2, values 10 7 5 3, capacity 9 -> the first two, 17.
    ("knapsack", _model({f"t{i}": BIN for i in range(4)}, [
        _rule("c_cap", _add(*(_mul(_c(w), _v(f"t{i}")) for i, w in enumerate((5, 4, 3, 2)))), "<=", _c(9))],
        "maximize", _add(*(_mul(_c(p), _v(f"t{i}")) for i, p in enumerate((10, 7, 5, 3))))), "optimal", Decimal(17)),
    # min x + y, 2x + 3y = 12, whole numbers in 0..10: (6, 0) -> 6, (3, 2) -> 5, (0, 4) -> 4.
    ("equality", _model({"x": INT, "y": INT}, [
        _rule("c_eq", _add(_mul(_c(2), _v("x")), _mul(_c(3), _v("y"))), "=", _c(12))],
        "minimize", _add(_v("x"), _v("y"))), "optimal", Decimal(4)),
    # min x, x whole in -5..5, x >= -3.5 -> -3.
    ("negative", _model({"x": {"domain": "integer", "lower": -5, "upper": 5}}, [
        _rule("c_floor", _v("x"), ">=", _c(-3.5))], "minimize", _v("x")), "optimal", Decimal(-3)),
    # max 2x + y with x + y <= 3.5 over mixed decisions: x whole in 0..10, y in 0..100 -> x = 3, y = 0.5: 6.5.
    ("mixed", _model({"x": INT, "y": REAL}, [
        _rule("c_sum", _add(_v("x"), _v("y")), "<=", _c(3.5))], "maximize", _add(_mul(_c(2), _v("x")), _v("y"))),
     "optimal", Decimal("6.5")),
    # x + y >= 3 with each at most 1: no answer.
    ("infeasible", _model({"x": BIN, "y": BIN}, [
        _rule("c_three", _add(_v("x"), _v("y")), ">=", _c(3))], "minimize", _add(_v("x"), _v("y"))), "infeasible", None),
    # max x, x >= 1, x continuous with no upper bound: without limit.
    ("unbounded", _model({"x": {"domain": "continuous", "lower": 0}}, [
        _rule("c_one", _v("x"), ">=", _c(1))], "maximize", _v("x")), "unbounded", None),
    # A rule and nothing asked: any answer that holds.
    ("feasibility", _model({"x": BIN}, [_rule("c_on", _v("x"), ">=", _c(1))]), "optimal", None),
]


def _hard(m: int = 5) -> dict:
    """A market split (Cornuejols and Dawande, 1998): m equalities over 10 (m - 1) yes-or-no
    decisions, each row's coefficients 0..99 and its right side half their sum. Branch and bound
    cannot finish one of this size in seconds, and nothing short of finishing says whether it has an
    answer -- what a time limit and a stop are tested on. (A pigeonhole, tried first, was proven in
    no time by every solver's own cuts.)"""
    import random

    rnd = random.Random("conformance-market-split")
    n = 10 * (m - 1)
    variables = {f"x{j}": BIN for j in range(n)}
    rules = []
    for i in range(m):
        a = [rnd.randint(0, 99) for _ in range(n)]
        rules.append(_rule(f"c_split{i}", _add(*(_mul(_c(a[j]), _v(f"x{j}")) for j in range(n))), "=", _c(sum(a) // 2)))
    return _model(variables, rules)


@dataclass
class Report:
    adapter: str
    version: str
    checks: list[dict[str, Any]] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return (not any(c["result"] == "fail" for c in self.checks)
                and any(c["result"] == "pass" and c["check"].startswith("answer:") for c in self.checks))

    def add(self, check: str, result: str, detail: str = "") -> None:
        self.checks.append({"check": check, "result": result, "detail": detail})


def run(backend, *, time_limit: float = 10.0) -> Report:
    """Every check on `backend`, solved through the path a run takes (`solve_compiled`)."""
    from app.solve.service import solve_compiled

    version = getattr(backend.manifest, "version", "") if backend.manifest is not None else "built-in"
    report = Report(backend.name, version)

    def takes(ir) -> tuple[bool, Any]:
        compiled = compile_model(ir, NO_DATA)
        found = refine(classify(ir, NO_DATA), compiled)
        return found.model_class in backend.classes and not (found.needs - backend.provides), compiled

    for name, ir, status, objective in CASES:
        ok, compiled = takes(ir)
        if not ok:
            report.add(f"answer:{name}", "skip", "not a model this solver claims")
            continue
        try:
            result, reason = solve_compiled(backend, compiled, time_limit=time_limit, seed=1)
        except Exception as exc:  # the adapter's failure is this check's
            report.add(f"answer:{name}", "fail", f"raised {type(exc).__name__}: {str(exc)[:300]}")
            continue
        report.add(f"answer:{name}", *_judge(compiled, result, reason, status, objective))

    ok, compiled = takes(CASES[1][1])
    if ok:
        bad = {key: 1.0 for key in compiled.variables}  # every item: over capacity
        try:
            result, _ = solve_compiled(backend, compiled, time_limit=time_limit, seed=1, hint=bad)
            verdict = _judge(compiled, result, None, "optimal", Decimal(17))
        except Exception as exc:
            verdict = ("fail", f"raised {type(exc).__name__}: {str(exc)[:300]}")
        report.add("bad_hint", *verdict)

    ok, compiled = takes(_hard())
    if ok:
        limit = 2.0
        started = time.monotonic()
        try:
            result, _ = solve_compiled(backend, compiled, time_limit=limit, seed=1)
            took = time.monotonic() - started
            if took > limit + LATE_S:
                report.add("time_limit", "fail", f"took {took:.1f} s against a limit of {limit:g} s")
            elif result.status in ("optimal", "feasible") and not evolve.holds(compiled, result.assignments):
                report.add("time_limit", "fail", f"said {result.status} with an answer that breaks a rule")
            else:
                report.add("time_limit", "pass", f"{result.status} in {took:.1f} s against {limit:g} s")
        except Exception as exc:
            report.add("time_limit", "fail", f"raised {type(exc).__name__}: {str(exc)[:300]}")

        flag = threading.Event()
        threading.Timer(0.5, flag.set).start()
        started = time.monotonic()
        try:
            result, _ = solve_compiled(backend, compiled, time_limit=8.0, seed=1, should_stop=flag.is_set)
            took = time.monotonic() - started
            honoured = took < 4.0
            report.add("stop", "pass" if honoured else "note",
                       f"stopped {took:.1f} s after the start, asked at 0.5 s" if honoured else
                       f"ran {took:.1f} s after a stop at 0.5 s: stopping relies on the sandbox's limit")
        except Exception as exc:
            report.add("stop", "fail", f"raised {type(exc).__name__}: {str(exc)[:300]}")
    return report


def _judge(compiled, result, reason, status: str, objective: Decimal | None) -> tuple[str, str]:
    if result.status != status:
        return "fail", f"said {result.status}, the answer is {status}" + (f" ({reason})" if reason else "")
    if status in ("optimal", "feasible"):
        if not evolve.holds(compiled, result.assignments):
            return "fail", "its answer breaks a rule or a bound"
        if objective is not None:
            got = Decimal(str(result.objective))
            if abs(got - objective) > Decimal("1e-6") * max(Decimal(1), abs(objective)):
                return "fail", f"said {got}, the optimum is {objective}"
    return "pass", status + (f" {objective}" if objective is not None else "")


def store(db, report: Report, ran_by: str | None) -> None:
    """Keep a report, and refresh which added solvers the rules may choose."""
    import json

    from sqlalchemy import text

    from app.solve import adapters

    db.execute(
        text("INSERT INTO solver_conformance (adapter, version, passed, checks, ran_by)"
             " VALUES (:a, :v, :p, CAST(:c AS jsonb), :u)"),
        {"a": report.adapter, "v": report.version, "p": report.passed, "c": json.dumps(report.checks), "u": ran_by},
    )
    db.commit()
    adapters.refresh_verified(db)


def latest(db) -> dict[str, dict[str, Any]]:
    """Each added solver's last report, by name."""
    from sqlalchemy import text

    rows = db.execute(
        text("SELECT DISTINCT ON (adapter) adapter, version, passed, checks, ran_by, ran_at"
             "  FROM solver_conformance ORDER BY adapter, ran_at DESC")
    ).mappings().all()
    return {r["adapter"]: dict(r) for r in rows}
