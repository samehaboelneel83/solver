"""Slope scaling for any model with fixed charges, read off the compiled model: facility location, lot sizing,
network design -- the same code, none of it named."""
from __future__ import annotations

import random

import pytest

from app.solve import compile_model, fixed_charge
from app.solve.backends import by_name
from app.solve.service import solve_compiled
from tests.test_benders import _facility


def _holds(compiled, values) -> bool:
    for c in compiled.constraints:
        gap = float(c.left.evaluated_at(values)) - float(c.right.evaluated_at(values))
        if (c.relation == "<=" and gap > 1e-6) or (c.relation == ">=" and gap < -1e-6) or (
                c.relation in ("=", "==") and abs(gap) > 1e-6):
            return False
    return all(float(v.lower) - 1e-9 <= float(values.get(k, 0)) <= float(v.upper) + 1e-9
               for k, v in compiled.variables.items())


def _optimum(compiled):
    result, _ = solve_compiled(by_name("highs"), compiled, time_limit=60, seed=1)
    assert result.status == "optimal"
    return float(result.objective)


def _lot_sizing(seed: int, periods: int = 12):
    """Produce in a period only with a set-up (a fixed charge), hold what is not sold, meet every demand."""
    rnd = random.Random(seed)
    demand = [rnd.randint(0, 40) for _ in range(periods)]
    big = sum(demand)
    v = lambda name: {"var": name, "index": []}  # noqa: E731
    variables = {}
    for t in range(periods):
        variables[f"setup{t}"] = {"index": [], "domain": "binary"}
        variables[f"make{t}"] = {"index": [], "domain": "continuous", "lower": 0, "upper": big}
        variables[f"stock{t}"] = {"index": [], "domain": "continuous", "lower": 0, "upper": big}
    constraints = []
    for t in range(periods):
        before = [v(f"stock{t - 1}")] if t else []
        constraints.append({"id": f"c_balance{t}", "severity": "hard", "relation": "=",
                            "left": {"add": [*before, v(f"make{t}")]},
                            "right": {"add": [{"const": demand[t]}, v(f"stock{t}")]}})
        constraints.append({"id": f"c_setup{t}", "severity": "hard", "relation": "<=", "left": v(f"make{t}"),
                            "right": {"mul": [{"const": big}, v(f"setup{t}")]}})
    terms = []
    for t in range(periods):
        terms += [{"mul": [{"const": rnd.randint(50, 150)}, v(f"setup{t}")]},
                  {"mul": [{"const": rnd.randint(1, 3)}, v(f"stock{t}")]},
                  {"mul": [{"const": rnd.randint(2, 5)}, v(f"make{t}")]}]
    return {"version": 2, "sets": [], "parameters": {}, "variables": variables, "constraints": constraints,
            "objective": {"sense": "minimize", "terms": [{"id": "o", "weight": 1, "expression": {"add": terms}}]}}


@pytest.mark.parametrize("seed", range(6))
@pytest.mark.parametrize("kind", ["facility", "facility, maximized", "lot sizing"])
def test_the_start_keeps_every_rule_and_is_near_the_optimum(kind, seed):
    if kind == "lot sizing":
        ir = _lot_sizing(seed)
    else:
        ir = _facility(seed, sites=10, customers=25, tight=seed % 2 == 1,
                       sense="maximize" if "maximized" in kind else "minimize")
    compiled = compile_model(ir, {})
    assert fixed_charge.applies(compiled) is None
    hint, record = fixed_charge.start(compiled, seconds=10)
    assert record.get("feasible"), record
    values = {k: hint.get(k, 0) for k in compiled.variables}
    assert _holds(compiled, values)
    ours, best = float(compiled.objective.evaluated_at(values)), _optimum(compiled)
    assert ours == pytest.approx(record["objective"], abs=1e-4)
    worse = (ours - best) if compiled.sense == "minimize" else (best - ours)
    assert -1e-6 <= worse <= 0.05 * abs(best), (kind, seed, ours, best)


def test_what_has_no_fixed_charge_is_said():
    ir = _lot_sizing(1)
    ir["constraints"] = [c for c in ir["constraints"] if not c["id"].startswith("c_setup")]
    assert "no yes/no decision" in fixed_charge.applies(compile_model(ir, {}))
    continuous = _facility(1)
    for spec in continuous["variables"].values():
        spec["domain"] = "continuous" if spec["domain"] == "binary" else spec["domain"]
        spec.setdefault("lower", 0)
        spec.setdefault("upper", 1)
    assert "no yes/no" in fixed_charge.applies(compile_model(continuous, {}))


from tests.test_quadratic import empty_queue  # noqa: E402,F401
from tests.test_v1_problem_run import db  # noqa: E402,F401


def test_a_run_of_a_fixed_charge_model_starts_from_slope_scaling(db, empty_queue, steps_first):  # noqa: F811
    from sqlalchemy import text

    from tests.test_run_events import _run

    run_id = _run(db, _facility(3, sites=10, customers=25, tight=True), "fixed charge run")
    row = db.execute(text("SELECT status, objective, params FROM run WHERE id = :r"), {"r": run_id}).mappings().one()
    assert row["status"] in ("optimal", "feasible")
    started = row["params"]["fixed_charge_start_run"]
    assert started["used"] is True and started["feasible"] and started["charges"] == 10, started
    assert float(row["objective"]) <= started["objective"] + 1e-6
