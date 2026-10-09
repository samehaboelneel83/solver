"""Column generation (plan of 8 October 2026, 1D): a small master over the columns that matter, every other column
priced from the rule matrix; the bound is the Lagrangian over every column, so an answer is called best only when
it meets it."""
from __future__ import annotations

import random

import pytest

from app.solve.backends import by_name, choose
from app.solve.classify import classify
from app.solve.compile import Unsupported, compile_model
from app.solve.service import solve_compiled
from tests.test_generate import _recipe_model, _room_data


def _run(name, ir, data, seconds=30):
    model = compile_model(ir, data)
    backend = by_name(name) if name else choose(classify(ir, data))[0]
    result, _ = solve_compiled(backend, model, time_limit=seconds, seed=1, should_stop=lambda: False, workers=1,
                               gap_rel=0.0)
    return result


def _cover(n_items=30, n_sets=400, seed=3, integral=True):
    """Weighted set cover: choose sets (columns) covering every item (row) at least once, cheapest first."""
    rng = random.Random(seed)
    items = [{"id": f"i{k}"} for k in range(n_items)]
    sets = [{"id": f"s{k}", "cost": rng.randint(3, 20)} for k in range(n_sets)]
    covers = [{"from": s["id"], "to": f"i{k}"} for s in sets for k in rng.sample(range(n_items), rng.randint(1, min(5, n_items)))]
    ir = {"version": 2, "sets": ["item", "pick"], "relationships": ["covers"], "parameters": {},
          "variables": {"take": {"index": ["pick"], "domain": "binary" if integral else "continuous",
                                 **({} if integral else {"lower": 0, "upper": 1})}},
          "constraints": [{"id": "c_cover", "forall": [{"index": "i", "set": "item"}],
                           "left": {"sum": {"var": "take", "index": ["s"]},
                                    "over": [{"index": "s", "set": "pick", "via": {"rel": "covers", "to": "i"}}]},
                           "relation": ">=", "right": {"const": 1}, "severity": "hard"}],
          "objective": {"sense": "minimize", "terms": [{"id": "o_cost", "weight": 1, "expression": {
              "sum": {"mul": [{"attr": {"of": "s", "name": "cost"}}, {"var": "take", "index": ["s"]}]},
              "over": [{"index": "s", "set": "pick"}]}}]}}
    data = {"sets": {"item": items, "pick": sets}, "parameters": {}, "relationships": {"covers": covers},
            "parameter_defaults": {}}
    return ir, data


def test_a_linear_cover_is_solved_to_the_full_optimum_from_a_few_columns():
    ir, data = _cover(integral=False)
    full = _run("highs", ir, data)
    got = _run("colgen", ir, data)
    assert got.status == "optimal" and got.objective == pytest.approx(full.objective, rel=1e-6)
    assert got.best_bound == pytest.approx(full.objective, rel=1e-6)
    assert "of 400 columns" in got.solver


@pytest.mark.parametrize("seed", [3, 4, 5])
def test_a_whole_number_cover_is_answered_and_its_bound_never_passes_the_best(seed):
    ir, data = _cover(seed=seed)
    best = _run("highs", ir, data)
    assert best.status == "optimal"
    got = _run("colgen", ir, data)
    assert got.status in ("optimal", "feasible") and got.objective >= best.objective - 1e-6
    # A lower bound (minimising): never above the true best, and the answer is called best only when it meets it.
    assert got.best_bound <= best.objective + 1e-6
    assert (got.status == "optimal") == (got.objective - got.best_bound <= 1e-6 * max(1, abs(got.objective)))
    picked = {k[1][0] for k, v in got.assignments.items() if v}
    for item in data["sets"]["item"]:
        assert any(e["to"] == item["id"] and e["from"] in picked for e in data["relationships"]["covers"])


def test_a_model_with_more_rules_than_decisions_is_solved_whole_and_says_so():
    """A candidate layout has a rule per cell and per aisle: a small master would grow towards the whole model (the
    camp at 0.5 m: 54,468 positions, 116,686 rules -- each master solve slower than the last), so the master is the
    whole model from the start; its whole-number optimum is then proven."""
    ir, data = _recipe_model(), _room_data()
    best = _run(None, ir, data)
    got = _run("colgen", ir, data)
    assert got.status == "optimal" and got.objective == best.objective
    assert "the master was the whole model" in got.solver


def test_each_solve_of_one_highs_gets_the_time_left_not_less():
    """HiGHS counts a time limit against all the run time of one solver: the limit set is that time plus what is
    left (Benders gave each round only what was left, so its later rounds stopped early)."""
    from app.solve.benders import _Lp

    class Fake:
        def __init__(self):
            self.options = {}

        def setOptionValue(self, name, value):
            self.options[name] = value

        def getRunTime(self):
            return 40.0

        def solve(self):
            pass

        def getModelStatus(self):
            return None

    lp = _Lp.__new__(_Lp)
    lp.h = Fake()
    import app.solve.highs as highs

    original = highs._status
    highs._status = lambda status: "optimal"
    try:
        lp.run(5.0)
    finally:
        highs._status = original
    assert lp.h.options["time_limit"] == 45.0


def test_rules_no_column_can_meet_are_infeasible():
    ir, data = _cover(n_items=3, n_sets=12)
    data["relationships"]["covers"] = [e for e in data["relationships"]["covers"] if e["to"] != "i0"]
    assert _run("colgen", ir, data).status == "infeasible"


def test_a_model_column_generation_cannot_hold_is_refused_and_it_is_asked_for_by_name():
    from types import SimpleNamespace

    from app.solve import colgen

    assert by_name("colgen").automatic is False
    quadratic = SimpleNamespace(objective_quadratic=True)
    assert "linear goal" in colgen.refuse(quadratic)
    with pytest.raises(Unsupported, match="colgen"):
        colgen.solve(quadratic, time_limit=1)
