"""The big-M rewrite of a conditional rule (app.solve.reformulate), row by row.

Each M below is worked by hand from the declared bounds: the most the rule's
expression can exceed its bound over the box -- the tightest M that is still
correct.
"""

from __future__ import annotations

from decimal import Decimal

from app.solve.compile import Compiled, Constraint, Linear, Variable
from app.solve.reformulate import bigm, unbounded_in

S = ("s", ())


def _var(name, lo, hi, domain="integer", default_upper=False):
    key = (name, ())
    return key, Variable(key, domain, Decimal(lo), Decimal(hi), default_upper)


def _model(variables, left: dict, relation: str, rhs, is_=1):
    keys = dict([_var("s", 0, 1, "binary"), *variables])
    rule = Constraint(
        "r", {}, Linear(coeffs={(n, ()): Decimal(a) for n, a in left.items()}), relation,
        Linear(const=Decimal(rhs)), when=(S, is_),
    )
    return Compiled(variables=keys, constraints=[rule], objective=Linear(), sense="minimize", var_index_sets={})


def _rows(compiled):
    rewritten, record = bigm(compiled)
    return [
        ({k[0]: float(v) for k, v in c.left.coeffs.items()}, c.relation, float(c.right.const))
        for c in rewritten.constraints
    ], record


def test_a_closed_site_ships_nothing():
    """x <= 0 while s is 0, x in [0, 10]: M = 10 - 0, so x - 10 s <= 0."""
    rows, record = _rows(_model([_var("x", 0, 10)], {"x": 1}, "<=", 0, is_=0))
    assert rows == [({"x": 1.0, "s": -10.0}, "<=", 0.0)]
    assert record == [{"rule": "r", "kind": "big-m", "rows": 1, "largest_m": 10.0}]


def test_a_cap_switched_on():
    """2x + 3y <= 12 while s, x and y in [0, 4]: the most 2x + 3y can be is 20,
    so M = 8, and 2x + 3y + 8 s <= 20."""
    rows, _ = _rows(_model([_var("x", 0, 4), _var("y", 0, 4)], {"x": 2, "y": 3}, "<=", 12))
    assert rows == [({"x": 2.0, "y": 3.0, "s": 8.0}, "<=", 20.0)]


def test_a_floor_switched_on():
    """x + y >= 5 while s, x and y in [0, 3]: the least is 0, M = 5, x + y - 5 s >= 0."""
    rows, _ = _rows(_model([_var("x", 0, 3), _var("y", 0, 3)], {"x": 1, "y": 1}, ">=", 5))
    assert rows == [({"x": 1.0, "y": 1.0, "s": -5.0}, ">=", 0.0)]


def test_an_equality_is_both_halves_each_with_its_own_m():
    """x = 2 while s, x in [0, 3]: above, M = 1 (x + s <= 3); below, M = 2 (x - 2 s >= 0)."""
    rows, record = _rows(_model([_var("x", 0, 3)], {"x": 1}, "=", 2))
    assert rows == [({"x": 1.0, "s": 1.0}, "<=", 3.0), ({"x": 1.0, "s": -2.0}, ">=", 0.0)]
    assert record[0]["rows"] == 2 and record[0]["largest_m"] == 2.0


def test_a_rule_the_bounds_already_keep_needs_no_row():
    """x <= 5 while s, x in [0, 3]: M would be -2 -- it can never be broken."""
    rows, _ = _rows(_model([_var("x", 0, 3)], {"x": 1}, "<=", 5))
    assert rows == []


def test_a_rule_that_can_never_hold_forbids_its_switch():
    """0 >= 1 while s: s may never be 1 (s <= 0); while s is 0: s >= 1."""
    rows, _ = _rows(_model([], {}, ">=", 1))
    assert rows == [({"s": 1.0}, "<=", 0.0)]
    rows, _ = _rows(_model([], {}, ">=", 1, is_=0))
    assert rows == [({"s": 1.0}, ">=", 1.0)]


def test_a_guard_ceiling_is_found_and_named():
    compiled = _model([_var("x", 0, 1_000_000, default_upper=True)], {"x": 1}, "<=", 0)
    assert unbounded_in(compiled) == ("r", "x")
