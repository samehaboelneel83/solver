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


# --- flow balances found in any model, and their cut-sets ---------------------------------------------------


def _flipped(ir):
    """The same model with every balance written the other way round (what goes out, less what comes in)."""
    import copy

    ir = copy.deepcopy(ir)
    for c in ir["constraints"]:
        if c["id"].startswith("c_balance"):
            c["left"], c["right"] = c["right"], c["left"]
    return ir


@pytest.mark.parametrize("seed", range(4))
@pytest.mark.parametrize("written", ["as is", "turned round"])
def test_lot_sizing_balances_are_found_and_their_cuts_close_the_gap(seed, written):
    from app.solve.flowcuts import Flows

    ir = _lot_sizing(seed, periods=20)
    compiled = compile_model(_flipped(ir) if written == "turned round" else ir, {})
    flows = Flows(compiled, strengthen.tightest(compiled))
    assert flows.ok and len(flows.demand) == 20 and len(flows.sink) == 20
    stronger, record = strengthen.strengthen(compiled, seconds=10)
    best = float(_solve(compiled).objective)
    assert float(_solve(stronger).objective) == pytest.approx(best)
    # Uncapacitated lot sizing: the (l, S) cut-sets describe its hull -- the relaxation reaches the optimum.
    assert record["flow_cuts"] > 0 and record["bound_after"] == pytest.approx(best, rel=1e-6), record


def _multi_item(seed: int, items: int = 4, periods: int = 8):
    rnd = random.Random(seed)
    v = lambda n: {"var": n, "index": []}  # noqa: E731
    demand = {(i, t): rnd.choice([0, rnd.randint(5, 30)]) for i in range(items) for t in range(periods)}
    cap = int(1.5 * sum(demand.values()) / periods) + 1
    variables, rules, terms = {}, [], []
    for i in range(items):
        big = sum(demand[i, t] for t in range(periods))
        for t in range(periods):
            variables[f"y{i}_{t}"] = {"index": [], "domain": "binary"}
            variables[f"x{i}_{t}"] = {"index": [], "domain": "continuous", "lower": 0, "upper": big}
            variables[f"s{i}_{t}"] = {"index": [], "domain": "continuous", "lower": 0, "upper": big}
            before = [v(f"s{i}_{t - 1}")] if t else []
            rules.append({"id": f"b{i}_{t}", "severity": "hard", "relation": "=",
                          "left": {"add": [*before, v(f"x{i}_{t}")]},
                          "right": {"add": [{"const": demand[i, t]}, v(f"s{i}_{t}")]}})
            rules.append({"id": f"u{i}_{t}", "severity": "hard", "relation": "<=", "left": v(f"x{i}_{t}"),
                          "right": {"mul": [{"const": big}, v(f"y{i}_{t}")]}})
            terms += [{"mul": [{"const": rnd.randint(50, 200)}, v(f"y{i}_{t}")]},
                      {"mul": [{"const": rnd.randint(1, 3)}, v(f"s{i}_{t}")]}]
    for t in range(periods):
        rules.append({"id": f"cap{t}", "severity": "hard", "relation": "<=",
                      "left": {"add": [v(f"x{i}_{t}") for i in range(items)]}, "right": {"const": cap}})
    return {"version": 2, "sets": [], "parameters": {}, "variables": variables, "constraints": rules,
            "objective": {"sense": "minimize", "terms": [{"id": "o", "weight": 1, "expression": {"add": terms}}]}}


@pytest.mark.parametrize("seed", range(4))
def test_shared_capacity_is_a_supply_and_the_optimum_stays(seed):
    from app.solve.flowcuts import Flows

    compiled = compile_model(_multi_item(seed), {})
    flows = Flows(compiled, strengthen.tightest(compiled))
    supplies = [i for i, d in flows.demand.items() if d < 0]
    assert len(supplies) == 8 and not set(supplies) & flows.sink  # each period's capacity sends, never keeps
    stronger, record = strengthen.strengthen(compiled, seconds=10)
    before, after = _solve(compiled), _solve(stronger)
    assert before.status == after.status == "optimal"
    assert float(after.objective) == pytest.approx(float(before.objective))
    assert record["bound_after"] > record["bound_before"]


@pytest.mark.parametrize("seed", range(3))
def test_a_network_design_written_by_the_join_rule_gets_its_cut_sets_without_it(seed, monkeypatch):
    from app.solve import join
    from tests.test_join import _capacitated, _graph

    monkeypatch.setattr(join, "CUTS", False)  # the rule's own cuts off: only what is read off the rows
    rnd = random.Random(seed)
    places, links = _graph(7, 900 + seed, extra=0.4)
    links = [(l, a, b, abs(c) + 3) for l, a, b, c in links]
    need = {p: rnd.randint(1, 4) for p in places if p != "p0"}
    compiled = compile_model(*_capacitated(places, links, {"p0"}, need, {l: rnd.choice([5, 9, 30]) for l, *_ in links}))
    stronger, record = strengthen.strengthen(compiled, seconds=10)
    assert record["flow_cuts"] > 0 and record["bound_after"] > record["bound_before"], record
    assert float(_solve(stronger).objective) == pytest.approx(float(_solve(compiled).objective))


def test_a_run_races_the_model_as_written_against_the_strengthened_one(db, empty_queue):  # noqa: F811
    from sqlalchemy import text

    from tests.test_run_events import _run

    run_id = _run(db, _multi_item(1), "two forms")
    row = db.execute(text("SELECT status, objective, params FROM run WHERE id = :r"), {"r": run_id}).mappings().one()
    assert row["status"] == "optimal"
    forms = row["params"]["strengthen_run"]["forms"]
    assert forms["won"] in ("as written", "with implied rows")
    assert {r["solver"] for r in forms["raced"]} == {"as written", "with implied rows"}
    best = float(_solve(compile_model(_multi_item(1), {})).objective)
    assert float(row["objective"]) == pytest.approx(best)
