"""Answer-shaping stage (OAAS P2): roster and amounts without going through service."""

from __future__ import annotations

from decimal import Decimal

from app.solve import answers
from app.solve.compile import Compiled, Linear, Variable
from app.solve.result import Solution


def _var(name, domain, lower=0, upper=1, index=()):
    key = (name, tuple(index))
    return key, Variable(key, domain, Decimal(lower), Decimal(upper))


def test_assignments_skip_compiler_auxiliaries_and_zeros():
    compiled = Compiled(
        variables=dict([_var("open", "binary", index=["a"]), _var("open", "binary", index=["b"])]),
        constraints=[],
        objective=Linear(),
        sense="minimize",
        var_index_sets={"open": ["site"]},
    )
    result = Solution(
        status="optimal",
        optimal=True,
        objective=1,
        assignments={
            ("open", ("a",)): 1,
            ("open", ("b",)): 0,
            ("__slack", ("c_once",)): 0.5,
        },
        solver="test",
        wall_seconds=0.01,
    )
    assert answers.assignments(compiled, result) == {"open": [["a"]]}


def test_amounts_report_continuous_not_binary():
    compiled = Compiled(
        variables=dict(
            [
                _var("kg", "continuous", 0, 100, index=["maize"]),
                _var("open", "binary", index=["a"]),
            ]
        ),
        constraints=[],
        objective=Linear(),
        sense="minimize",
        var_index_sets={"kg": ["feed"], "open": ["site"]},
    )
    result = Solution(
        status="optimal",
        optimal=True,
        objective=1,
        assignments={("kg", ("maize",)): 12.5, ("open", ("a",)): 1},
        solver="test",
        wall_seconds=0.01,
    )
    assert answers.amounts(compiled, result) == {
        "kg": [{"index": ["maize"], "value": 12.5}],
    }
