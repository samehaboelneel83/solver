"""Fractional data made whole exactly, so CP-SAT can take it (migration 0039)."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.solve.classify import Classification
from app.solve.compile import Compiled, Constraint, Linear, Variable
from app.solve.scaling import FRACTIONAL, SCALED, NotScalable, admit, check, decimals, scale
from app.solve.service import claim_next, enqueue_run, execute_run
from tests.test_quadratic import empty_queue  # noqa: F401
from tests.test_v1_problem_run import db, make_domain, make_model_version, make_problem  # noqa: F401

X, Y = ("x", ()), ("y", ())


def test_decimals_counts_places_not_trailing_zeros():
    assert decimals(Decimal("7.5")) == 1
    assert decimals(Decimal("12.75")) == 2
    assert decimals(Decimal("3.50")) == 1
    assert decimals(Decimal("40")) == 0
    assert decimals(Decimal("1E+2")) == 0


def test_a_row_is_scaled_to_whole_numbers_and_its_common_factor_removed():
    """7.5x + 2.25y <= 30: x100 is 750x + 225y <= 3000; the gcd is 75, so
    10x + 3y <= 40, the original multiplied by 4/3."""
    row = scale({X: Decimal("7.5"), Y: Decimal("2.25")}, Decimal(30), {}, {X: Decimal(10), Y: Decimal(10)}, "r")
    assert row.coeffs == {X: 10, Y: 3}
    assert row.rhs == 40
    assert row.factor == Decimal(4) / Decimal(3)


def test_more_than_four_places_is_not_scaled():
    with pytest.raises(NotScalable, match="5 decimal places"):
        scale({X: Decimal("0.12345")}, Decimal(1), {}, {X: Decimal(1)}, "rule 'w'")


def test_a_row_that_would_reach_two_to_the_53_is_not_scaled():
    """0.0001 x <= 1 with x up to 10^13 scales to x <= 10^4 -- fine -- but
    1.0001 x with the same reach is 10001 x, whose activity passes 2^53."""
    reach = {X: Decimal(10) ** 13}
    assert scale({X: Decimal("0.0001")}, Decimal(1), {}, reach, "r").rhs == 10**4
    with pytest.raises(NotScalable, match="past 2\\^53"):
        scale({X: Decimal("1.0001")}, Decimal(1), {}, reach, "r")


def _model(domain: str, coeff: str) -> Compiled:
    return Compiled(
        variables={X: Variable(X, domain, Decimal(0), Decimal(10))},
        constraints=[Constraint("c", {}, Linear({X: Decimal(coeff)}), "<=", Linear(const=Decimal(8)))],
        objective=Linear({X: Decimal(1)}),
        sense="maximize",
        var_index_sets={"x": []},
    )


def test_a_continuous_variable_is_never_scaled():
    with pytest.raises(NotScalable, match="continuous"):
        check(_model("continuous", "1.5"))


def test_admit_swaps_the_need_only_when_the_model_scales():
    found = Classification("IP", ["x is whole"], {"linear", "integral", FRACTIONAL})
    scaled = admit(found, _model("integer", "1.5"))
    assert FRACTIONAL not in scaled.needs and SCALED in scaled.needs
    assert any("whole numbers exactly" in r for r in scaled.reasons)

    kept = admit(found, _model("integer", "1.23456"))
    assert FRACTIONAL in kept.needs and SCALED not in kept.needs
    assert any("not scaled for CP-SAT" in r for r in kept.reasons)

    whole = Classification("IP", [], {"linear", "integral"})
    assert admit(whole, _model("integer", "2")) is whole


# -- through a run -------------------------------------------------------------------

# max x, 1.5 x <= 8, x whole in [0, 10]: x <= 5.33, so 5.
IR = {
    "version": 1,
    "sets": [],
    "parameters": {},
    "variables": {"x": {"index": [], "domain": "integer", "bounds": {"lower": 0, "upper": 10}}},
    "constraints": [
        {
            "id": "c_cap",
            "left": {"mul": [{"const": 1.5}, {"var": "x", "index": []}]},
            "relation": "<=",
            "right": {"const": 8},
            "severity": "hard",
        }
    ],
    "objective": {"sense": "maximize", "terms": [{"id": "o", "weight": 1, "expression": {"var": "x", "index": []}}]},
}


@pytest.mark.parametrize("setting, solver", [(None, "highs"), ("true", "cp-sat")])
def test_the_setting_decides_whether_a_run_goes_to_cp_sat(db, empty_queue, setting, solver):  # noqa: F811
    domain = make_domain(db)
    problem = make_problem(db, domain)
    version = make_model_version(db, problem, IR)
    scenario = db.execute(
        text("INSERT INTO scenario (problem_id, model_version_id, name) VALUES (:p, :v, 's') RETURNING id"),
        {"p": problem, "v": version},
    ).scalar_one()
    if setting is not None:
        db.execute(
            text(
                "INSERT INTO setting (scope, scope_id, key, value)"
                " VALUES ('problem', :p, 'solve.cpsat_scaling', CAST(:v AS jsonb))"
            ),
            {"p": problem, "v": setting},
        )
    db.commit()
    try:
        run_id = enqueue_run(db, scenario, time_limit=10.0)
        assert claim_next(db) == run_id
        outcome = execute_run(db, run_id)
        row = db.execute(
            text("SELECT solver, objective, params FROM run WHERE id = :r"), {"r": run_id}
        ).mappings().one()
        assert outcome.status == "optimal"
        assert row["solver"] == solver
        assert row["objective"] == 5
        assert row["params"]["cpsat_scaling"] is (setting == "true")
    finally:
        db.execute(text("DELETE FROM run"))
        db.execute(text("DELETE FROM domain WHERE id = :d"), {"d": domain})
        db.commit()
