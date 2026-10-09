"""Rows any model with on/off limits implies, read off the compiled model: the bound rises, the optimum stays."""
from __future__ import annotations

import random
from dataclasses import replace

import pytest

from app.solve import compile_model, strengthen
from app.solve.backends import by_name
from app.solve.compile import Variable
from app.solve.service import solve_compiled
from tests.test_benders import _facility
from tests.test_fixed_charge import _lot_sizing


def _uncapacitated(seed: int, sites: int = 12, customers: int = 30):
    """Facility location where any open site could serve everyone: the relaxation opens each a sliver."""
    rng = random.Random(seed)
    v = lambda n: {"var": n, "index": []}  # noqa: E731
    demand = [rng.randint(5, 30) for _ in range(customers)]
    big = sum(demand)
    variables = {f"open{i}": {"index": [], "domain": "binary"} for i in range(sites)}
    variables.update({f"ship{i}_{j}": {"index": [], "domain": "continuous", "lower": 0, "upper": big}
                      for i in range(sites) for j in range(customers)})
    rules = [{"id": f"d{j}", "severity": "hard", "relation": "=", "left": {"add": [v(f"ship{i}_{j}") for i in range(sites)]},
              "right": {"const": demand[j]}} for j in range(customers)]
    rules += [{"id": f"c{i}", "severity": "hard", "relation": "<=",
               "left": {"add": [v(f"ship{i}_{j}") for j in range(customers)]},
               "right": {"mul": [{"const": big}, v(f"open{i}")]}} for i in range(sites)]
    terms = [{"mul": [{"const": rng.randint(100, 600)}, v(f"open{i}")]} for i in range(sites)]
    terms += [{"mul": [{"const": rng.randint(1, 20)}, v(f"ship{i}_{j}")]} for i in range(sites) for j in range(customers)]
    return {"version": 2, "sets": [], "parameters": {}, "variables": variables, "constraints": rules,
            "objective": {"sense": "minimize", "terms": [{"id": "o", "weight": 1, "expression": {"add": terms}}]}}


def _solve(compiled):
    result, _ = solve_compiled(by_name("highs"), compiled, time_limit=60, seed=1)
    return result


def _relaxed(compiled) -> float:
    loose = {k: Variable(k, "continuous", v.lower, v.upper) for k, v in compiled.variables.items()}
    result = _solve(replace(compiled, variables=loose))
    assert result.status == "optimal"
    return float(result.objective)


@pytest.mark.parametrize("seed", range(4))
@pytest.mark.parametrize("kind", ["uncapacitated", "capacitated", "lot sizing"])
def test_the_rows_hold_at_the_optimum_and_raise_the_bound(kind, seed):
    ir = {"uncapacitated": lambda: _uncapacitated(seed), "capacitated": lambda: _facility(seed, 8, 20),
          "lot sizing": lambda: _lot_sizing(seed)}[kind]()
    compiled = compile_model(ir, {})
    assert strengthen.applies(compiled) is None
    stronger, record = strengthen.strengthen(compiled, seconds=10)
    assert len(stronger.constraints) == len(compiled.constraints) + record["added"]
    before, after = _solve(compiled), _solve(stronger)
    assert before.status == after.status == "optimal"
    assert float(after.objective) == pytest.approx(float(before.objective), abs=1e-6)
    assert _relaxed(stronger) >= _relaxed(compiled) - 1e-6
    if kind == "uncapacitated":
        # Each shipment within its customer's demand times its site: the relaxation closes most of the gap.
        assert record["added"] > 0 and record["bound_after"] > record["bound_before"] * 1.2, record


def test_what_has_no_on_off_limit_is_said():
    ir = _uncapacitated(1)
    ir["constraints"] = [c for c in ir["constraints"] if c["id"].startswith("d")]
    assert "no rule limits" in strengthen.applies(compile_model(ir, {}))


from tests.test_quadratic import empty_queue  # noqa: E402,F401
from tests.test_v1_problem_run import db  # noqa: E402,F401


def test_a_run_records_the_rows_it_added(db, empty_queue):  # noqa: F811
    from sqlalchemy import text

    from tests.test_run_events import _run

    run_id = _run(db, _uncapacitated(2), "strengthen run")
    row = db.execute(text("SELECT status, params FROM run WHERE id = :r"), {"r": run_id}).mappings().one()
    assert row["status"] == "optimal"
    record = row["params"]["strengthen_run"]
    assert record["added"] > 0 and record["bound_after"] >= record["bound_before"], record
