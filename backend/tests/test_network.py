"""The network lane (queue R15a): min-cost flow proves what HiGHS proves, and refuses what is not a network."""

from __future__ import annotations

import random

import pytest

from app.solve import compile_model, network
from app.solve.backends import by_name
from bench import network as families
from tests.test_quadratic import empty_queue  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401

NO_DATA = {"sets": {}, "parameters": {}, "parameter_defaults": {}, "relationships": {}}


def _both(compiled):
    ours = network.solve(compiled).solution
    theirs = by_name("highs").solve(compiled, time_limit=20, workers=2, seed=1)
    return ours, theirs


@pytest.mark.parametrize("family", sorted(families.FAMILIES))
@pytest.mark.parametrize("size", ["S", "M"])
def test_each_family_is_a_network_and_agrees_with_highs(family, size):
    ir, data = families.FAMILIES[family](size)
    compiled = compile_model(ir, data)
    assert network.applies(compiled) is None
    ours, theirs = _both(compiled)
    assert ours.status == theirs.status == "optimal"
    assert ours.optimal and ours.best_bound == ours.objective
    assert float(ours.objective) == pytest.approx(float(theirs.objective))
    # Whole flows, and every rule holds at them.
    assert all(float(v) == int(v) for v in ours.assignments.values())
    for c in compiled.constraints:
        gap = float(c.left.evaluated_at(ours.assignments) - c.right.evaluated_at(ours.assignments))
        assert {"<=": gap <= 1e-9, ">=": gap >= -1e-9}.get(c.relation, abs(gap) <= 1e-9), c.id


def _random_network(seed: int) -> dict:
    """Arcs between a few places, each with a cost and maybe a ceiling; each place's balance is a rule
    (=, <= or >=, a side possibly written negated), some arcs from or to the outside; min or max."""
    rnd = random.Random(seed)
    places, arcs = rnd.randint(2, 6), []
    for _ in range(rnd.randint(3, 12)):
        a, b = rnd.randrange(places + 1), rnd.randrange(places + 1)  # `places` is the outside
        if a != b:
            arcs.append((a, b))
    variables, terms = {}, []
    for i, _ in enumerate(arcs):
        var = {"index": [], "domain": rnd.choice(["continuous", "integer"]), "lower": rnd.choice([0, 0, 0, 1])}
        var["upper"] = var["lower"] + rnd.randint(1, 9)
        variables[f"x{i}"] = var
        terms.append({"id": f"o{i}", "weight": rnd.randint(-5, 9), "expression": {"var": f"x{i}", "index": []}})
    constraints = []
    for p in range(places):
        into = [{"var": f"x{i}", "index": []} for i, (a, b) in enumerate(arcs) if b == p]
        out = [{"mul": [{"const": -1}, {"var": f"x{i}", "index": []}]} for i, (a, b) in enumerate(arcs) if a == p]
        body = into + out
        if len(body) < 2:
            continue
        rhs, relation = rnd.randint(-3, 3), rnd.choice(["=", "<=", ">="])
        if rnd.random() < 0.4:  # written the other way round
            body = [{"mul": [{"const": -1}, t]} for t in body]
            rhs, relation = -rhs, {"<=": ">=", ">=": "<="}.get(relation, relation)
        constraints.append({"id": f"c{p}", "left": {"add": body}, "relation": relation, "right": {"const": rhs},
                            "severity": "hard"})
    return {"version": 2, "sets": [], "parameters": {}, "variables": variables, "constraints": constraints,
            "objective": {"sense": rnd.choice(["minimize", "maximize"]), "terms": terms}}


def test_random_networks_agree_with_highs():
    checked = 0
    for seed in range(120):
        compiled = compile_model(_random_network(seed), NO_DATA)
        if network.applies(compiled) is not None:
            continue
        ours, theirs = _both(compiled)
        assert ours.status == theirs.status, (seed, ours.status, theirs.status)
        if ours.status == "optimal":
            assert float(ours.objective) == pytest.approx(float(theirs.objective), abs=1e-6), seed
        checked += 1
    assert checked >= 100


def _transport(supply, demand, *, soft=False, cap=None):
    ir, data = families.transport("S")
    data["sets"]["plant"] = [{"id": f"p{i}", "supply": s} for i, s in enumerate(supply)]
    data["sets"]["customer"] = [{"id": f"c{j}", "demand": d} for j, d in enumerate(demand)]
    data["parameters"]["cost"] = [{"plant": f"p{i}", "customer": f"c{j}", "value": 1 + i + 2 * j}
                                  for i in range(len(supply)) for j in range(len(demand))]
    if soft:
        ir["constraints"][1] = {**ir["constraints"][1], "severity": "soft", "penalty": 100}
    if cap is not None:
        ir["variables"]["ship"]["upper"] = cap
    return compile_model(ir, data)


def test_too_little_supply_is_proven_infeasible():
    ours, theirs = _both(_transport([5, 5], [8, 8]))
    assert ours.status == theirs.status == "infeasible"


def test_a_soft_demand_is_met_as_far_as_it_pays():
    compiled = _transport([5, 5], [8, 8], soft=True)
    assert network.applies(compiled) is None
    ours, theirs = _both(compiled)
    assert ours.status == theirs.status == "optimal"
    assert float(ours.objective) == pytest.approx(float(theirs.objective))


def test_a_cycle_that_pays_with_no_ceiling_is_unbounded():
    x = lambda n: {"var": n, "index": []}  # noqa: E731
    ir = {"version": 2, "sets": [], "parameters": {},
          "variables": {"a": {"index": [], "domain": "continuous", "lower": 0},
                        "b": {"index": [], "domain": "continuous", "lower": 0}},
          "constraints": [
              {"id": "c_p", "left": {"add": [x("a"), {"mul": [{"const": -1}, x("b")]}]}, "relation": "=", "right": {"const": 0}, "severity": "hard"},
              {"id": "c_q", "left": {"add": [x("b"), {"mul": [{"const": -1}, x("a")]}]}, "relation": "=", "right": {"const": 0}, "severity": "hard"}],
          "objective": {"sense": "maximize", "terms": [{"id": "o", "weight": 1, "expression": x("a")}]}}
    compiled = compile_model(ir, NO_DATA)
    assert network.applies(compiled) is None
    assert network.solve(compiled).solution.status == "unbounded"


def test_an_assignment_turns_one_side_round():
    ir, data = families.assignment("S")
    compiled = compile_model(ir, data)
    rows, flip, *_ = network._shape(compiled)
    assert sum(flip.values()) in (10, len(rows) - 10)  # exactly one side turned


@pytest.mark.parametrize(("change", "why"), [
    (lambda ir: ir["constraints"][0].update(left=families._sum({"mul": [{"const": 2}, {"var": "ship", "index": ["p", "c"]}]},
                                                                 ("c", "customer"))),
     "weighs a decision by more than one"),
    (lambda ir: ir["constraints"].append({"id": "c_total", "left": families._sum({"var": "ship", "index": ["p", "c"]},
                                          ("p", "plant"), ("c", "customer")), "relation": "<=", "right": {"const": 10 ** 6},
                                          "severity": "hard"}),
     "in more than two rules"),
])
def test_what_is_not_a_network_is_left_to_the_solvers(change, why):
    ir, data = families.transport("S")
    change(ir)
    assert why in network.applies(compile_model(ir, data))


def test_rules_that_cannot_be_turned_consistently_are_refused():
    """Three places pairwise joined with the same sign: an odd cycle, not a network."""
    x = lambda n: {"var": n, "index": []}  # noqa: E731
    pairs = {"ab": ("r1", "r2"), "bc": ("r2", "r3"), "ca": ("r3", "r1")}
    rules = {r: [x(v) for v, ends in pairs.items() if r in ends] for r in ("r1", "r2", "r3")}
    ir = {"version": 2, "sets": [], "parameters": {},
          "variables": {v: {"index": [], "domain": "continuous", "lower": 0, "upper": 5} for v in pairs},
          "constraints": [{"id": r, "left": {"add": body}, "relation": "<=", "right": {"const": 4}, "severity": "hard"}
                          for r, body in rules.items()],
          "objective": {"sense": "maximize", "terms": [{"id": "o", "weight": 1, "expression": x("ab")}]}}
    assert "cannot all be read as flow" in network.applies(compile_model(ir, NO_DATA))


def test_a_fractional_number_is_left_to_the_solvers():
    ir, data = families.transport("S")
    data["parameters"]["cost"][0]["value"] = 1.5
    assert "fractional" in network.applies(compile_model(ir, data))


def test_a_run_of_a_network_is_solved_as_one_and_proven(db, empty_queue):  # noqa: F811
    """With `solve.network` at its default, a whole-number network run is answered by min-cost flow, recorded, global."""
    from sqlalchemy import text

    from tests.test_run_events import _run

    seed = next(s for s in range(200) if network.applies(compile_model(_whole(_random_network(s)), NO_DATA)) is None
                and network.solve(compile_model(_whole(_random_network(s)), NO_DATA)).solution.status == "optimal")
    ir = _whole(_random_network(seed))
    run_id = _run(db, ir, "network run")
    row = db.execute(text("SELECT status, optimality, objective, solver_version, params FROM run WHERE id = :r"),
                     {"r": run_id}).mappings().one()
    assert row["status"] == "optimal" and row["optimality"] == "global"
    assert row["solver_version"].startswith("network")
    assert row["params"]["network"] is True and row["params"]["network_run"]["kind"] == "min-cost flow"
    expected = network.solve(compile_model(ir, NO_DATA)).solution.objective
    assert float(row["objective"]) == pytest.approx(float(expected))


def _whole(ir: dict) -> dict:
    for var in ir["variables"].values():
        var["domain"] = "integer"
    return ir


def test_a_continuous_network_run_stays_with_the_lp_solver(db, empty_queue):  # noqa: F811
    """GLOP is nearly as quick on a continuous network and gives shadow prices; the lane leaves it be."""
    from sqlalchemy import text

    from tests.test_run_events import _run

    ir = _random_network(next(s for s in range(200) if network.applies(compile_model(_continuous(_random_network(s)), NO_DATA)) is None
                              and network.solve(compile_model(_continuous(_random_network(s)), NO_DATA)).solution.status == "optimal"))
    run_id = _run(db, _continuous(ir), "continuous network")
    row = db.execute(text("SELECT status, solver_version, params FROM run WHERE id = :r"), {"r": run_id}).mappings().one()
    assert row["status"] == "optimal" and not row["solver_version"].startswith("network")
    assert "network_run" not in row["params"]


def _continuous(ir: dict) -> dict:
    for var in ir["variables"].values():
        var["domain"] = "continuous"
    return ir


def test_a_model_with_no_rule_joining_decisions_is_not_a_network():
    ir = {"version": 2, "sets": [], "parameters": {},
          "variables": {"x": {"index": [], "domain": "binary"}, "y": {"index": [], "domain": "binary"}},
          "constraints": [{"id": "c_x", "left": {"var": "x", "index": []}, "relation": "<=", "right": {"const": 1},
                           "severity": "hard"}],
          "objective": {"sense": "maximize", "terms": [{"id": "o", "weight": 1, "expression": {"var": "x", "index": []}}]}}
    assert "no rule joins two decisions" in network.applies(compile_model(ir, NO_DATA))
