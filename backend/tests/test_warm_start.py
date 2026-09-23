"""Warm starts: the nearest earlier answer, offered as a hint (setting `solve.warm_start`).

A hint changes how fast an answer is found, never which answer is proven:
every backend that takes one must reach the same optimum from a good hint,
a bad one, and none. What a stored roster can hint is exact for yes-or-no
decisions and zero for amounts that were not used -- nothing else.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import text

from app.solve import compile_model
from app.solve.backends import by_name
from app.solve.compile import Compiled, Constraint, Linear, Variable
from app.solve.service import claim_next, enqueue_run, execute_run, solve_compiled
from app.solve.warm import hint_from
from tests.test_diagnose import _scenario_for
from tests.test_solve import _feasible, _ir_and_data  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


def _var(name, domain, lower=0, upper=1, index=()):
    key = (name, tuple(index))
    return key, Variable(key, domain, Decimal(lower), Decimal(upper))


def test_a_roster_hints_what_it_can_say_and_nothing_more():
    variables = dict([
        _var("on", "binary", index=["a"]),
        _var("on", "binary", index=["b"]),
        _var("qty", "integer", 0, 9, index=["a"]),
        _var("qty", "integer", 0, 9, index=["b"]),
        _var("floor", "integer", 1, 9),
        _var("new", "binary"),
        _var("__violation", "integer", 0, 9, index=["c_x"]),
    ])
    compiled = Compiled(variables=variables, constraints=[], objective=Linear(), sense="minimize",
                        var_index_sets={})
    roster = {"on": [["a"]], "qty": [["a"]], "floor": [], "__violation": []}

    assert hint_from(compiled, roster) == {
        ("on", ("a",)): 1.0,  # a yes: exact
        ("on", ("b",)): 0.0,  # a no: exact
        ("qty", ("b",)): 0.0,  # an amount not used: zero
        # qty[a] was used, with a value the roster does not keep: no hint.
        # floor cannot be zero now: no hint. new did not exist then: no hint.
    }


def _knapsack() -> Compiled:
    """Pick from four items, weights 5 4 3 2, values 10 7 5 3, capacity 9:
    the first two (5 + 4 = 9) for 17; the next best, 5 + 3 or 4 + 3 + 2,
    reach 15."""
    weights, values = (5, 4, 3, 2), (10, 7, 5, 3)
    keys = [("take", (str(i),)) for i in range(4)]
    return Compiled(
        variables={k: Variable(k, "binary", Decimal(0), Decimal(1)) for k in keys},
        constraints=[Constraint("c_cap", {}, Linear(coeffs={k: Decimal(w) for k, w in zip(keys, weights)}), "<=",
                                Linear(const=Decimal(9)))],
        objective=Linear(coeffs={k: Decimal(v) for k, v in zip(keys, values)}),
        sense="maximize",
        var_index_sets={"take": [["item"]]},
    )


GOOD = {("take", ("0",)): 1.0, ("take", ("1",)): 1.0, ("take", ("2",)): 0.0, ("take", ("3",)): 0.0}
# Over capacity (5 + 4 + 3): a hint that cannot hold must be dropped, not obeyed.
BAD = {("take", ("0",)): 1.0, ("take", ("1",)): 1.0, ("take", ("2",)): 1.0, ("take", ("3",)): 1.0}


@pytest.mark.parametrize("backend_name", ["cp-sat", "highs", "scip"])
@pytest.mark.parametrize("hint", [None, GOOD, BAD], ids=["cold", "good", "bad"])
def test_a_hint_never_changes_the_proven_optimum(backend_name, hint):
    backend = by_name(backend_name)
    if not backend.is_available():
        pytest.skip(f"{backend_name} is not in this build")
    result, _ = solve_compiled(backend, _knapsack(), time_limit=10, seed=1, hint=hint)
    assert (result.status, result.objective) == ("optimal", 17)


def test_cp_sat_is_given_the_hint(monkeypatch):
    from ortools.sat.python import cp_model

    given = []
    original = cp_model.CpModel.add_hint
    monkeypatch.setattr(cp_model.CpModel, "add_hint", lambda self, var, value: (given.append(value), original(self, var, value))[1])
    solve_compiled(by_name("cp-sat"), _knapsack(), time_limit=10, seed=1, hint=GOOD)
    assert sorted(given) == [0, 0, 1, 1]


def test_a_backend_that_takes_no_hint_accepts_one_and_solves_as_before():
    """GLOP and the MILP wrapper take the keyword and ignore it: the same
    answer with a hint as without. GLOP gets the relaxation, whose optimum
    is 17 too: by value per weight the first two items come first (2, 1.75)
    and exactly fill the 9."""
    from dataclasses import replace

    whole = _knapsack()
    relaxed = replace(whole, variables={k: replace(v, domain="continuous") for k, v in whole.variables.items()})
    for name, model, best in (("milp", whole, 17), ("glop", relaxed, 17)):
        backend = by_name(name)
        if not backend.is_available():
            continue
        result = backend.solve(model, time_limit=5, workers=1, hint=GOOD)
        assert result.status == "optimal" and abs(float(result.objective) - best) < 1e-6, (name, result.objective)


# -- through a run -------------------------------------------------------------------


@pytest.fixture
def empty_queue(db):
    db.execute(text("DELETE FROM run"))
    db.commit()
    yield
    db.execute(text("DELETE FROM run"))
    db.commit()


@pytest.mark.parametrize("on", [False, True])
def test_a_run_starts_from_the_last_answer_only_when_the_setting_says_so(db, empty_queue, on):
    version, _ = _feasible(db)
    scenario = _scenario_for(db, version)
    problem = db.execute(text("SELECT problem_id FROM scenario WHERE id = :s"), {"s": scenario}).scalar_one()
    if on:
        db.execute(
            text(
                "INSERT INTO setting (scope, scope_id, key, value)"
                " VALUES ('problem', :p, 'solve.warm_start', CAST('true' AS jsonb))"
            ),
            {"p": problem},
        )
        db.commit()

    first = enqueue_run(db, scenario, time_limit=10.0)
    assert claim_next(db) == first
    execute_run(db, first)
    # Not answered from the cache: this one is solved, from the last answer.
    second = enqueue_run(db, scenario, time_limit=10.0, reuse=False)
    assert claim_next(db) == second
    outcome = execute_run(db, second)

    params = db.execute(text("SELECT params FROM run WHERE id = :r"), {"r": second}).scalar_one()
    assert outcome.status == "optimal"
    assert params["warm_start"] is on
    if on:
        assert params["warm_start_from"] == first and params["warm_start_hinted"] > 0
    else:
        assert "warm_start_from" not in params
