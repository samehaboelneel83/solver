"""Epic engine, E-3: Benders decomposition over HiGHS.

Capacitated facility location is the textbook case: which sites to open is
the master, how much each open site ships to each customer is the continuous
subproblem. Too little open capacity leaves the subproblem with no answer, so
the same models exercise both kinds of cut. Every answer is checked against
HiGHS's own branch and cut on the whole model.
"""

from __future__ import annotations

import random

import pytest

from app.solve import compile_model
from app.solve.backends import BENDERS, HIGHS, by_name, choose, is_automatic
from app.solve.benders import refuse
from app.solve.classify import classify
from app.solve.service import solve_compiled

pytestmark = pytest.mark.skipif(not HIGHS.is_available(), reason="highspy is not installed in this image")


def _v(name):
    return {"var": name, "index": []}


def _term(coeff, name):
    return {"mul": [{"const": coeff}, _v(name)]}


def _facility(seed: int, sites: int = 5, customers: int = 8, sense: str = "minimize", tight: bool = False):
    rng = random.Random(seed)
    fixed = [rng.randint(40, 120) for _ in range(sites)]
    capacity = [rng.randint(15, 40) for _ in range(sites)]
    demand = [rng.randint(3, 12) for _ in range(customers)]
    if tight:
        # Only most sites together can serve everyone: many proposals leave demand unmet.
        scale = sum(demand) / (0.8 * sum(capacity))
        capacity = [int(c * scale) + 1 for c in capacity]
    cost = [[round(rng.uniform(1, 9), 2) for _ in range(customers)] for _ in range(sites)]
    variables = {f"open{i}": {"index": [], "domain": "binary"} for i in range(sites)}
    variables.update({f"ship{i}_{j}": {"index": [], "domain": "continuous", "lower": 0, "upper": 1000}
                      for i in range(sites) for j in range(customers)})
    constraints = []
    for j in range(customers):
        constraints.append({"id": f"c_demand{j}", "severity": "hard", "relation": "=",
                            "left": {"add": [_v(f"ship{i}_{j}") for i in range(sites)]}, "right": {"const": demand[j]}})
    for i in range(sites):
        constraints.append({"id": f"c_capacity{i}", "severity": "hard", "relation": "<=",
                            "left": {"add": [_v(f"ship{i}_{j}") for j in range(customers)]},
                            "right": _term(capacity[i], f"open{i}")})
    total = [_term(fixed[i], f"open{i}") for i in range(sites)]
    total += [_term(cost[i][j], f"ship{i}_{j}") for i in range(sites) for j in range(customers)]
    goal = {"add": total} if sense == "minimize" else {"mul": [{"const": -1}, {"add": total}]}
    return {
        "version": 2, "sets": [], "parameters": {}, "variables": variables, "constraints": constraints,
        "objective": {"sense": sense, "terms": [{"id": "o_cost", "weight": 1, "expression": goal}]},
    }


def _both(ir, time_limit=30):
    compiled = compile_model(ir, {})
    ours, _ = solve_compiled(by_name("benders"), compiled, time_limit=time_limit, seed=1)
    theirs, _ = solve_compiled(HIGHS, compiled, time_limit=time_limit, seed=1)
    return ours, theirs


@pytest.mark.parametrize("seed", range(6))
def test_it_proves_the_same_optimum_as_branch_and_cut(seed):
    ours, theirs = _both(_facility(seed))
    assert theirs.status == "optimal"
    assert ours.status == "optimal", ours.solver
    assert float(ours.objective) == pytest.approx(float(theirs.objective), rel=1e-6)
    assert float(ours.best_bound) == pytest.approx(float(ours.objective), rel=1e-6)
    assert "optimality" in ours.solver and ours.solver.startswith("benders")


@pytest.mark.parametrize("seed", range(4))
def test_tight_capacity_needs_feasibility_cuts_and_still_proves_the_optimum(seed):
    ours, theirs = _both(_facility(seed, tight=True))
    assert ours.status == theirs.status == "optimal"
    assert float(ours.objective) == pytest.approx(float(theirs.objective), rel=1e-6)
    cuts = int(ours.solver.split(" and ")[1].split(" feasibility")[0])
    assert cuts >= 1, ours.solver


def test_its_answer_keeps_every_rule():
    ir = _facility(3, tight=True)
    compiled = compile_model(ir, {})
    ours, _ = solve_compiled(by_name("benders"), compiled, time_limit=30, seed=1)
    values = {key: float(value) for key, value in ours.assignments.items()}
    for c in compiled.constraints:
        left, right = float(c.left.evaluated_at(values)), float(c.right.evaluated_at(values))
        assert {"=": abs(left - right) <= 1e-6, "<=": left <= right + 1e-6, ">=": left >= right - 1e-6}[c.relation], c.id
    assert all(values[(f"open{i}", ())] in (0.0, 1.0) for i in range(5))


def test_a_maximised_goal_is_the_same_problem_turned_over():
    ours, theirs = _both(_facility(2, sense="maximize"))
    assert ours.status == "optimal"
    assert float(ours.objective) == pytest.approx(float(theirs.objective), rel=1e-6)
    assert float(ours.objective) < 0


def test_a_model_with_no_answer_is_infeasible():
    ir = _facility(1)
    ir["constraints"].append({"id": "c_none", "severity": "hard", "relation": "<=",
                              "left": {"add": [_v(f"open{i}") for i in range(5)]}, "right": {"const": 0}})
    ours, _ = _both(ir)
    assert ours.status == "infeasible"


def test_it_is_chosen_only_by_name():
    found = classify(_facility(0), {})
    assert found.model_class == "MILP"
    chosen, reason = choose(found)
    assert chosen.name != "benders" and "benders" not in reason
    assert not is_automatic(BENDERS)
    assert choose(found, "benders")[0] is BENDERS
    assert BENDERS.proves == "global"


@pytest.mark.parametrize("change, reason", [
    (lambda ir: ir["variables"].update({k: {"index": [], "domain": "binary"} for k in list(ir["variables"])}),
     "no continuous decisions"),
    (lambda ir: ir["variables"].update({f"open{i}": {"index": [], "domain": "continuous", "lower": 0, "upper": 1}
                                        for i in range(5)}), "no whole-number decisions"),
])
def test_a_model_it_cannot_split_is_refused_with_the_reason(change, reason):
    ir = _facility(0)
    change(ir)
    assert reason in refuse(compile_model(ir, {}))


def _rounds(result) -> int:
    return int(result.solver.split(": ")[1].split(" rounds")[0])


def test_pareto_cuts_prove_the_same_optimum_in_no_more_rounds():
    fewer = 0
    for seed in range(6):
        compiled = compile_model(_facility(seed), {})
        plain, _ = solve_compiled(by_name("benders"), compiled, time_limit=30, seed=1)
        strong, _ = solve_compiled(by_name("benders"), compiled, time_limit=30, seed=1,
                                   solver_params={"pareto_cuts": "on"})
        assert strong.status == "optimal" and float(strong.objective) == pytest.approx(float(plain.objective), rel=1e-9)
        assert "from the core point" in strong.solver and "core point" not in plain.solver
        assert _rounds(strong) <= _rounds(plain), (seed, plain.solver, strong.solver)
        fewer += _rounds(strong) < _rounds(plain)
    # Measured on these six: seeds 3 and 5 need two rounds fewer.
    assert fewer >= 1


def test_pareto_cuts_are_a_whitelisted_option_off_by_default():
    from app.solve.params import ENABLED, check

    assert check("benders", {"pareto_cuts": "on"}) == {"pareto_cuts": "on"}
    assert "benders" not in ENABLED
    with pytest.raises(ValueError):
        check("benders", {"pareto_cuts": "yes"})
