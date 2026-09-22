"""Quadratic rules: a product of two decisions in a constraint.

A quadratic rule can make the set of allowed answers nonconvex -- `x * y <= 4`
over positive x and y admits (10, 0.4) and (0.4, 10) but not the point
between them -- and then a local search can stop at a corner that is not the
best one. So only the backends that prove a global optimum whatever the
shape are offered one: CP-SAT when every decision is whole (it holds each
product exactly) and SCIP otherwise (spatial branch-and-bound). HiGHS, GLOP
and the pywraplp MILP wrapper never see one.

The worked examples, each small enough to check by hand:

- the disc: maximise 3x + 4y with x^2 + y^2 <= 25. The best point is (3, 4),
  for 25 -- a convex QCQP;
- the hyperbola: maximise x + y over [0, 10]^2 with x * y <= 4. The best is a
  corner, (10, 0.4) or (0.4, 10), for 10.4; the symmetric point (2, 2) a
  local search likes is the WORST point on that curve;
- whole numbers: minimise x + y with x * y >= 12 over 0..10. 3 x 4 is the
  smallest pair, for 7;
- mixed: the hyperbola, with a yes/no `open` that the rule needs for any
  area and that costs 1. Shut gives x * y <= 0, so (10, 0) for 10; open gives
  10.4 - 1 = 9.4. The best is 10, shut.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.solve import compile_model, scip
from app.solve.backends import CP_SAT, GLOP, HIGHS, MILP, SCIP, NoBackend, choose
from app.solve.classify import classify
from app.solve.compile import slack_of
from tests.test_quadratic import _run, empty_queue  # noqa: F401
from tests.test_v1_problem_run import (  # noqa: F401
    _data,
    _snapshot,
    db,
    make_domain,
    make_model_version,
    make_problem,
)

X = {"var": "x", "index": []}
Y = {"var": "y", "index": []}
OPEN = {"var": "open", "index": []}


def _mul(a, b):
    return {"mul": [a, b]}


def _c(value):
    return {"const": value}


def _ir(domain: str, rule: dict, objective: list[dict], sense: str, extra: dict | None = None) -> dict:
    variables = {
        "x": {"index": [], "domain": domain, "lower": 0, "upper": 10},
        "y": {"index": [], "domain": domain, "lower": 0, "upper": 10},
        **(extra or {}),
    }
    return {
        "version": 1,
        "sets": [],
        "parameters": {},
        "variables": variables,
        "constraints": [{"severity": "hard", **rule}],
        "objective": {
            "sense": sense,
            "terms": [{"id": f"o{i}", "weight": 1, "expression": e} for i, e in enumerate(objective)],
        },
    }


DISC = _ir(
    "continuous",
    {"id": "c_disc", "left": {"add": [_mul(X, X), _mul(Y, Y)]}, "relation": "<=", "right": _c(25)},
    [_mul(_c(3), X), _mul(_c(4), Y)],
    "maximize",
)
HYPERBOLA = _ir(
    "continuous",
    {"id": "c_hyperbola", "left": _mul(X, Y), "relation": "<=", "right": _c(4)},
    [X, Y],
    "maximize",
)
WHOLE = _ir(
    "integer",
    {"id": "c_area", "left": _mul(X, Y), "relation": ">=", "right": _c(12)},
    [X, Y],
    "minimize",
)
MIXED = _ir(
    "continuous",
    {"id": "c_hyperbola", "left": _mul(X, Y), "relation": "<=", "right": _mul(_c(4), OPEN)},
    [X, Y, _mul(_c(-1), OPEN)],
    "maximize",
    extra={"open": {"index": [], "domain": "binary"}},
)


def _version(db, ir: dict, name: str) -> int:
    return make_model_version(db, make_problem(db, make_domain(db, name)), ir)


def _compiled(db, ir: dict, name: str):
    version = _version(db, ir, name)
    return compile_model(ir, _data(db, _snapshot(db, version)))


# -- classes and who takes them -----------------------------------------------


@pytest.mark.parametrize(
    "ir, model_class, backend",
    [(DISC, "QCQP", SCIP), (HYPERBOLA, "QCQP", SCIP), (WHOLE, "MIQCQP", CP_SAT), (MIXED, "MIQCQP", SCIP)],
    ids=["disc", "hyperbola", "whole", "mixed"],
)
def test_a_quadratic_rule_is_classified_and_routed(ir, model_class, backend):
    found = classify(ir)
    assert found.model_class == model_class
    assert "quadratic-constraints" in found.needs
    assert any("so the model has quadratic rules" in reason for reason in found.reasons)
    assert choose(found)[0] is backend


def test_no_solver_that_needs_convexity_or_linearity_declares_quadratic_rules():
    for backend in (GLOP, HIGHS, MILP):
        assert "quadratic-constraints" not in backend.provides


def test_without_scip_a_continuous_quadratic_rule_is_refused_and_says_why(monkeypatch):
    monkeypatch.setattr(scip, "_available", False)
    with pytest.raises(NoBackend, match="A rule multiplies decisions together"):
        choose(classify(HYPERBOLA))
    # ...while the whole-number one still goes to CP-SAT.
    assert choose(classify(WHOLE))[0] is CP_SAT


# -- compiling ------------------------------------------------------------------


def test_a_rule_keeps_its_products_on_the_left(db):
    compiled = _compiled(db, DISC, "qcqp-compile")
    (rule,) = compiled.constraints
    x, y = ("x", ()), ("y", ())
    assert rule.quadratic == {(x, x): Decimal(1), (y, y): Decimal(1)}
    assert rule.left.coeffs == {}


def test_a_product_on_the_right_moves_left_with_its_sign_flipped(db):
    ir = _ir(
        "continuous",
        {"id": "c", "left": _c(4), "relation": ">=", "right": _mul(X, Y)},
        [X],
        "maximize",
    )
    (rule,) = _compiled(db, ir, "qcqp-right").constraints
    assert rule.quadratic == {(("x", ()), ("y", ())): Decimal(-1)}


def test_slack_counts_the_products(db):
    (rule,) = _compiled(db, HYPERBOLA, "qcqp-slack").constraints
    # x * y = 2 * 1.5 = 3, against a ceiling of 4.
    assert slack_of(rule, {("x", ()): Decimal(2), ("y", ()): Decimal("1.5")}) == Decimal(1)


def test_a_soft_quadratic_equality_keeps_its_products_on_both_halves(db):
    ir = _ir(
        "continuous",
        {"id": "c", "left": _mul(X, Y), "relation": "=", "right": _c(4), "severity": "soft", "weight": 2},
        [X],
        "maximize",
    )
    halves = _compiled(db, ir, "qcqp-soft").constraints
    assert [c.relation for c in halves] == [">=", "<="]
    assert all(c.quadratic == {(("x", ()), ("y", ())): Decimal(1)} for c in halves)


# -- the answers ----------------------------------------------------------------


def test_the_disc_peaks_at_three_four(db):
    solution = scip.solve(_compiled(db, DISC, "qcqp-disc"), time_limit=20)
    assert solution.status == "optimal"
    assert abs(Decimal(str(solution.objective)) - 25) < Decimal("0.0001")


def test_the_hyperbola_is_won_at_a_corner_not_the_middle(db):
    solution = scip.solve(_compiled(db, HYPERBOLA, "qcqp-hyperbola"), time_limit=20)
    assert solution.status == "optimal"
    assert abs(Decimal(str(solution.objective)) - Decimal("10.4")) < Decimal("0.0001")
    assert max(solution.assignments.values()) == 10


def test_whole_numbers_through_a_run_go_to_cp_sat(db):
    row = _run(db, _version(db, WHOLE, "qcqp-whole"))
    assert row["status"] == "optimal", row["error"]
    assert row["solver"] == "cp-sat"
    assert row["optimality"] == "global"
    assert row["objective"] == 7


def test_the_mixed_model_through_a_run_goes_to_scip_and_stays_shut(db):
    row = _run(db, _version(db, MIXED, "qcqp-mixed"))
    assert row["status"] == "optimal", row["error"]
    assert row["solver"] == "scip"
    assert row["optimality"] == "global"
    assert abs(row["objective"] - Decimal("10")) < Decimal("0.0001")


def test_a_continuous_quadratic_rule_through_a_run_is_global(db):
    row = _run(db, _version(db, HYPERBOLA, "qcqp-run"))
    assert row["status"] == "optimal", row["error"]
    assert row["solver"] == "scip"
    assert row["optimality"] == "global"
    assert abs(row["objective"] - Decimal("10.4")) < Decimal("0.0001")
