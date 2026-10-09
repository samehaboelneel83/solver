"""The metaheuristic lane (queue R14): answers that keep every rule, never called optimal, never the rules' choice."""

from __future__ import annotations

import pytest

from app.solve import compile_model, evolve
from app.solve.backends import CMA_ES, GA, PSO, REGISTRY, by_name, choose
from app.solve.classify import classify
from app.solve.compile import Unsupported
from app.solve.convexity import refine
from app.solve.lp import NotContinuous
from bench.ipopt import NO_DATA, sines

LANE = ("cma-es", "pso", "ga")
#: Searches for whole-number and continuous decisions alike (9 October 2026).
MIXED = ("ga", "sa", "tabu", "de", "aco")


def _knapsack(n: int = 10):
    """Ten yes-or-no items under a capacity of 20; the best set by brute force."""
    weight = {f"i{k}": k + 1 for k in range(n)}
    value = {f"i{k}": (7 * k) % 11 + 1 for k in range(n)}
    x = lambda k: {"var": f"x_{k}", "index": []}  # noqa: E731
    ir = {
        "version": 2, "sets": [], "parameters": {},
        "variables": {f"x_{k}": {"index": [], "domain": "binary"} for k in weight},
        "constraints": [{"id": "c_cap", "left": {"add": [{"mul": [{"const": w}, x(k)]} for k, w in weight.items()]},
                         "relation": "<=", "right": {"const": 20}, "severity": "hard"}],
        "objective": {"sense": "maximize", "terms": [{"id": f"o_{k}", "weight": v, "expression": x(k)} for k, v in value.items()]},
    }
    best = 0
    for mask in range(1 << n):
        items = [k for i, k in enumerate(weight) if mask >> i & 1]
        if sum(weight[k] for k in items) <= 20:
            best = max(best, sum(value[k] for k in items))
    return ir, best


def test_the_ga_answers_a_knapsack_and_claims_nothing():
    ir, best = _knapsack()
    compiled = compile_model(ir, NO_DATA)
    result = by_name("ga").solve(compiled, time_limit=2, workers=1, seed=3)
    assert result.status == "feasible" and not result.optimal and result.best_bound is None
    assert evolve.holds(compiled, result.assignments)
    assert result.objective <= best  # never past the true optimum


@pytest.mark.parametrize("method", LANE)
def test_each_search_keeps_the_rules_on_a_nonconvex_model(method):
    compiled = compile_model(sines(10), NO_DATA)
    result = by_name(method).solve(compiled, time_limit=2, workers=1, seed=1)
    assert result.status == "feasible" and not result.optimal
    assert evolve.holds(compiled, result.assignments)
    assert result.objective == pytest.approx(evolve.objective_at(compiled, result.assignments))
    # SCIP's bound on this model is 16.57 (bench/results/2026-09-24-ipopt.md): no search passes it.
    assert result.objective <= 16.567066938297376 + 1e-6


def test_the_continuous_searches_refuse_whole_numbers():
    ir, _ = _knapsack()
    compiled = compile_model(ir, NO_DATA)
    for method in ("cma-es", "pso"):
        with pytest.raises(NotContinuous, match="whole numbers"):
            evolve.solve(compiled, method=method, time_limit=0.1)


def test_a_decision_with_no_bound_is_refused_by_name():
    ir = sines(3)
    ir["variables"]["x0"] = {"index": [], "domain": "continuous", "lower": 0}
    compiled = compile_model(ir, NO_DATA)
    with pytest.raises(Unsupported, match="'x0' has no finite bound"):
        evolve.solve(compiled, method="ga", time_limit=0.1)


def test_a_conditional_rule_is_refused():
    ir, _ = _knapsack()
    ir["constraints"].append({"id": "c_if", "when": {"var": "x_i0", "index": [], "is": 1}, "left": {"var": "x_i1", "index": []},
                              "relation": "=", "right": {"const": 0}, "severity": "hard"})
    compiled = compile_model(ir, NO_DATA)
    with pytest.raises(Unsupported, match="conditional"):
        evolve.solve(compiled, method="ga", time_limit=0.1)


def test_the_rules_never_choose_a_search():
    """Registered `local`: never the rules' choice, and never in memory, the race or the portfolio (they compare proofs)."""
    for ir in (sines(10), _knapsack()[0]):
        found = refine(classify(ir, NO_DATA), compile_model(ir, NO_DATA))
        assert choose(found)[0].name not in LANE
    assert all(b.proves == "local" for b in (CMA_ES, PSO, GA))
    assert {"cma-es", "pso", "ga"} <= {b.name for b in REGISTRY}
    found = refine(classify(sines(10), NO_DATA), compile_model(sines(10), NO_DATA))
    assert choose(found, "cma-es")[0].name == "cma-es"


def test_the_fallback_answers_where_the_exact_solver_had_nothing():
    """`solve.metaheuristic`: the exact solver's `unknown` replaced by the search's answer, recorded, claiming nothing."""
    from app.solve.backends import CP_SAT
    from app.solve.result import Solution
    from app.solve.service import _metaheuristic_fallback

    ir, best = _knapsack()
    compiled = compile_model(ir, NO_DATA)
    found = refine(classify(ir, NO_DATA), compiled)
    nothing = Solution("unknown", False, None, {}, 1.0, "cp-sat")
    result, backend, record = _metaheuristic_fallback(compiled, found, CP_SAT, nothing, hint=None, time_limit=4,
                                                      seed=1, workers=1, should_stop=lambda: False)
    assert backend.name == "tabu" and result.status == "feasible" and result.objective <= best  # first, one thread
    assert record["used"] and record["kept"] and record["method"] == "tabu" and record["after"] == "cp-sat"


def test_the_fallback_races_the_searches_and_keeps_the_best():
    from app.solve.backends import CP_SAT
    from app.solve.result import Solution
    from app.solve.service import SEARCH_WHOLE, _metaheuristic_fallback

    ir, best = _knapsack()
    compiled = compile_model(ir, NO_DATA)
    found = refine(classify(ir, NO_DATA), compiled)
    nothing = Solution("unknown", False, None, {}, 1.0, "cp-sat")
    result, backend, record = _metaheuristic_fallback(compiled, found, CP_SAT, nothing, hint=None, time_limit=8,
                                                      seed=1, workers=5, should_stop=lambda: False)
    assert record["methods"] == list(SEARCH_WHOLE) and {r["solver"] for r in record["raced"]} == set(SEARCH_WHOLE)
    answered = [r["objective"] for r in record["raced"] if r["objective"] is not None]
    assert result.objective == max(answered) and backend.name == record["method"]
    assert result.status == "feasible" and evolve.holds(compiled, result.assignments) and result.objective <= best


@pytest.mark.parametrize("method", MIXED[1:])
def test_each_new_search_answers_a_knapsack_and_a_nonconvex_model(method):
    ir, best = _knapsack()
    compiled = compile_model(ir, NO_DATA)
    result = by_name(method).solve(compiled, time_limit=2, workers=1, seed=2)
    assert result.status == "feasible" and not result.optimal and result.best_bound is None
    assert evolve.holds(compiled, result.assignments) and result.objective <= best
    assert result.objective >= 0.8 * best  # a search, but a decent one on ten items
    compiled = compile_model(sines(10), NO_DATA)
    result = by_name(method).solve(compiled, time_limit=2, workers=1, seed=1)
    assert result.status == "feasible" and evolve.holds(compiled, result.assignments)
    assert result.objective <= 16.567066938297376 + 1e-6


def test_the_fallback_says_why_it_cannot_search():
    from app.solve.backends import CP_SAT
    from app.solve.result import Solution
    from app.solve.service import _metaheuristic_fallback

    ir, _ = _knapsack()
    ir["constraints"].append({"id": "c_if", "when": {"var": "x_i0", "index": [], "is": 1},
                              "left": {"var": "x_i1", "index": []}, "relation": "=", "right": {"const": 0},
                              "severity": "hard"})
    compiled = compile_model(ir, NO_DATA)
    found = refine(classify(ir, NO_DATA), compiled)
    nothing = Solution("unknown", False, None, {}, 1.0, "cp-sat")
    result, backend, record = _metaheuristic_fallback(compiled, found, CP_SAT, nothing, hint=None, time_limit=4,
                                                      seed=1, workers=1, should_stop=lambda: False)
    assert result is nothing and backend is CP_SAT
    assert record["used"] is False and record["why"]


def test_a_search_uses_one_core():
    """numpy's BLAS spun a thread per core and ran 60 s searches past the sandbox's CPU allowance (R14's bench)."""
    import resource
    import time

    compiled = compile_model(sines(200), NO_DATA)
    before, began = resource.getrusage(resource.RUSAGE_SELF), time.monotonic()
    by_name("cma-es").solve(compiled, time_limit=3, workers=1, seed=1)
    after, wall = resource.getrusage(resource.RUSAGE_SELF), time.monotonic() - began
    cpu = (after.ru_utime + after.ru_stime) - (before.ru_utime + before.ru_stime)
    assert cpu < 2.5 * wall, (cpu, wall)


def _risk_and_return(n: int = 6):
    """Choose amounts (0..10) of n assets within a budget: most return, least risk (a sum of squares) -- a goal
    that multiplies decisions, so no exact front takes it."""
    v = lambda k: {"var": f"a{k}", "index": []}  # noqa: E731
    gain = [3, 5, 2, 7, 4, 6][:n]
    return {
        "version": 2, "sets": [], "parameters": {},
        "variables": {f"a{k}": {"index": [], "domain": "integer", "lower": 0, "upper": 10} for k in range(n)},
        "constraints": [{"id": "c_budget", "severity": "hard", "relation": "<=",
                         "left": {"add": [v(k) for k in range(n)]}, "right": {"const": 20}}],
        "objective": {"sense": "maximize", "terms": [
            {"id": "o_return", "weight": 1, "expression": {"add": [{"mul": [{"const": g}, v(k)]} for k, g in enumerate(gain)]}},
            {"id": "o_risk", "weight": -1, "expression": {"add": [{"mul": [v(k), v(k)]} for k in range(n)]}}]},
    }


def test_nsga2_draws_a_front_where_the_goal_multiplies_decisions():
    from app.solve import pareto

    compiled = compile_model(_risk_and_return(), NO_DATA)
    pareto.admissible(compiled)  # searched: allowed
    import pytest as _pytest

    with _pytest.raises(pareto.NotTwoGoals):
        pareto.admissible(compiled, searched=False)
    points = pareto.front(None, compiled, steps=8, time_limit=4, solve=None)
    assert 3 <= len(points) <= 9
    for p in points:
        assert p.status == "feasible" and evolve.holds(compiled, p.solution.assignments)
        values = p.solution.assignments
        assert p.first == sum(g * values[(f"a{k}", ())] for k, g in enumerate([3, 5, 2, 7, 4, 6]))
        assert p.second == sum(values[(f"a{k}", ())] ** 2 for k in range(6))
    # A front: more return costs more risk, and no point is beaten on both.
    for p in points:
        assert not any(q.first >= p.first and q.second <= p.second and (q.first, q.second) != (p.first, p.second)
                       for q in points)
