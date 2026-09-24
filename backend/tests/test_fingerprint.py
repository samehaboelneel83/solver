"""The run fingerprint (app.solve.fingerprint): each number worked by hand."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.solve import compile_model
from app.solve.compile import Compiled, Constraint, Linear, Variable
from app.solve.fingerprint import VERSION, fingerprint, row_type
from tests.test_blocks import _knapsacks

NO_DATA = {"sets": {}, "parameters": {}, "parameter_defaults": {}, "relationships": {}}


def test_two_knapsacks_worked_by_hand():
    # take[a1..b3]: six binaries. c_fits is two rows (one per sack), weights
    # 5 4 3 | 2 2 3 under 8 | 4: both knapsacks, 6 non-zeros, all whole.
    fp = fingerprint(compile_model(*_knapsacks()))
    assert fp["version"] == VERSION == 2
    assert (fp["variables"], fp["binary"], fp["integer"], fp["continuous"], fp["auxiliary"]) == (6, 6, 0, 0, 0)
    assert (fp["rows"], fp["nnz"], fp["rows_knapsack"], fp["rows_general"]) == (2, 6, 2, 0)
    assert fp["density"] == pytest.approx(6 / 12)
    assert (fp["coef_min"], fp["coef_max"]) == (2.0, 5.0)
    assert fp["coef_range_log10"] == pytest.approx(0.398, abs=1e-3)  # log10(5/2)
    assert fp["integral_data"] is True and fp["blocks"] == 2
    assert (fp["objective_degree"], fp["objective_terms"], fp["lexicographic"]) == (1, 1, False)
    # No non-binary decision: nothing to bound.
    assert (fp["bounds_declared"], fp["bound_width_median"]) == (1.0, 0.0)


def _model(domain="binary", upper=1, default_upper=False):
    keys = [("x", (str(i),)) for i in range(3)]
    variables = {k: Variable(k, domain, Decimal(0), Decimal(upper), default_upper=default_upper) for k in keys}
    return Compiled(variables=variables, constraints=[], objective=Linear(), sense="minimize", var_index_sets={}), keys


def _row(keys, coeffs, relation, rhs, **extra):
    return Constraint("c", {}, Linear(coeffs={k: Decimal(c) for k, c in zip(keys, coeffs)}), relation,
                      Linear(const=Decimal(rhs)), **extra)


@pytest.mark.parametrize(
    "coeffs, relation, rhs, expected",
    [
        ([1, 1, 1], "=", 1, "partition"),
        ([1, 1, 1], ">=", 1, "cover"),
        ([-1, -1, -1], "<=", -1, "cover"),  # the same rule written negated
        ([1, 1, 1], "<=", 1, "packing"),
        ([1, 1, 1], "<=", 2, "cardinality"),
        ([3, 5, 2], "<=", 7, "knapsack"),
        ([3, -5, 2], "<=", 7, "general"),
        ([1.5, 1, 1], "<=", 2, "general"),
    ],
)
def test_row_types(coeffs, relation, rhs, expected):
    compiled, keys = _model()
    assert row_type(compiled, _row(keys, coeffs, relation, rhs)) == expected


def test_whole_number_rows_are_not_set_rows_and_a_conditional_is_named():
    compiled, keys = _model("integer", 5)
    assert row_type(compiled, _row(keys, [1, 1, 1], "=", 1)) == "general"
    binary, bkeys = _model()
    assert row_type(binary, _row(bkeys[1:], [1, 1], "<=", 1, when=(bkeys[0], 1))) == "conditional"


def test_bound_tightness_counts_only_declared_upper_bounds():
    compiled, keys = _model("integer", 4)
    compiled.variables[keys[2]] = Variable(keys[2], "integer", Decimal(0), Decimal(1_000_000), default_upper=True)
    fp = fingerprint(compiled)
    assert fp["bounds_declared"] == pytest.approx(2 / 3) and fp["bound_width_median"] == 4.0


def test_a_quadratic_goal_with_functions_and_fractional_data():
    ir = {
        "version": 2, "sets": [], "parameters": {},
        "variables": {"x": {"index": [], "domain": "continuous", "lower": 0.5, "upper": 4},
                      "y": {"index": [], "domain": "continuous", "lower": 0, "upper": 4}},
        "constraints": [{"id": "c", "left": {"add": [{"var": "x", "index": []}, {"mul": [{"const": 0.5}, {"var": "y", "index": []}]}]},
                         "relation": "<=", "right": {"const": 3}, "severity": "hard"}],
        "objective": {"sense": "minimize", "terms": [{"id": "o", "weight": 1, "expression": {"add": [
            {"mul": [{"var": "x", "index": []}, {"var": "y", "index": []}]},
            {"fn": "log", "of": {"var": "x", "index": []}}]}}]},
    }
    fp = fingerprint(compile_model(ir, NO_DATA))
    # x, y and the stand-in for log(x).
    assert (fp["variables"], fp["continuous"], fp["auxiliary"], fp["functions"]) == (3, 2, 1, 1)
    assert fp["objective_degree"] == 2 and fp["integral_data"] is False
    assert fp["coef_range_log10"] == pytest.approx(0.301, abs=1e-3)  # log10(1 / 0.5)
    assert fp["bound_width_median"] == 4.0  # widths 3.5 and 4


def test_an_empty_model_has_a_fingerprint_too():
    compiled = Compiled(variables={}, constraints=[], objective=Linear(), sense="minimize", var_index_sets={})
    fp = fingerprint(compiled)
    assert (fp["variables"], fp["rows"], fp["density"], fp["coef_range_log10"], fp["blocks"]) == (0, 0, 0.0, 0.0, 0)
