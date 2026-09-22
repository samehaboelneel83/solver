"""GLOP and the MILP wrapper load their model as one proto (D7).

Hand-checked models, solved through the adapters, so what is pinned is what
a run gets: the answers, the duals, a rule with no variables left, and the
contract's strict relations on integers.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.solve import lp, milp
from app.solve.compile import Compiled, Constraint, Linear, Variable


def _model(variables, constraints, objective, sense="minimize") -> Compiled:
    return Compiled(
        variables={
            (name, ()): Variable(key=(name, ()), domain=domain, lower=Decimal(lo), upper=Decimal(hi))
            for name, domain, lo, hi in variables
        },
        constraints=[
            Constraint(
                id=cid, index={},
                left=Linear(coeffs={(n, ()): Decimal(c) for n, c in left.items()}),
                relation=relation, right=Linear(const=Decimal(rhs)),
            )
            for cid, left, relation, rhs in constraints
        ],
        objective=Linear(coeffs={(n, ()): Decimal(c) for n, c in objective.items()}),
        sense=sense,
        var_index_sets={},
    )


# min x + y  s.t.  x + 2y >= 4,  3x + y >= 6,  0 <= x, y <= 10.
# Vertices: (0, 6) -> 6, (4, 0) -> 4, and where both rows bind:
# x = 8/5 = 1.6, y = 6/5 = 1.2 -> 2.8, the optimum. Duals there, from
# u + 3v = 1 and 2u + v = 1: u = 0.4, v = 0.2.
CORNER = dict(
    variables=[("x", "continuous", 0, 10), ("y", "continuous", 0, 10)],
    constraints=[("a", {"x": 1, "y": 2}, ">=", 4), ("b", {"x": 3, "y": 1}, ">=", 6)],
    objective={"x": 1, "y": 1},
)


def test_glop_solves_the_hand_worked_lp_with_its_duals():
    result = lp.solve(_model(**CORNER))
    assert result.status == "optimal"
    assert float(result.objective) == pytest.approx(2.8)
    assert float(result.assignments[("x", ())]) == pytest.approx(1.6)
    assert float(result.assignments[("y", ())]) == pytest.approx(1.2)
    assert float(result.duals["a"]) == pytest.approx(0.4)
    assert float(result.duals["b"]) == pytest.approx(0.2)


def test_the_milp_wrapper_agrees_on_the_same_lp():
    result = milp.solve(_model(**CORNER))
    assert result.status == "optimal"
    assert float(result.objective) == pytest.approx(2.8)


@pytest.mark.parametrize("adapter", [lp, milp])
def test_a_rule_with_no_variables_left_still_counts(adapter):
    """`0 >= 1`: the row is empty but its bounds make the model infeasible.
    Dropping empty rows is the bug HiGHS's array build once had."""
    model = _model(
        variables=[("x", "continuous", 0, 10)],
        constraints=[("never", {}, ">=", 1)],
        objective={"x": 1},
    )
    assert adapter.solve(model).status == "infeasible"


def test_strict_relations_hold_on_integers():
    """max x, x integer in [0, 10], x < 4: `< 4` is `<= 3`, so 3."""
    model = _model(
        variables=[("x", "integer", 0, 10)],
        constraints=[("below", {"x": 1}, "<", 4)],
        objective={"x": 1},
        sense="maximize",
    )
    result = milp.solve(model)
    assert result.status == "optimal"
    assert result.objective == 3


def test_every_build_gives_the_same_answer_on_the_benchmark_model():
    from bench.build_speed import measure, synthetic_lp

    found = measure(synthetic_lp(rows=50, cols=100, per_row=20), "GLOP", repeat=1)
    answers = [r["objective"] for r in found.values()]
    assert all(a == pytest.approx(answers[0]) for a in answers)
