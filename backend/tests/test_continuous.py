"""Linear programming: the class the platform could not express until 0015.

The fixture is a blending problem, which is what an LP is *for*: buy some
quantity of two feeds, each with a cost and a protein content, and meet a
protein requirement as cheaply as possible. Nothing about it is discrete --
you can buy 2.5 kilos -- and the optimum sits at a fraction, which is exactly
the answer the integer-only platform could not give.

Three things are being pinned, and only the first is about arithmetic:

- a continuous model **solves**, and its answer is fractional;
- it is **classified** as LP and routed to the simplex, not to branch and cut
  and not to CP-SAT. A classifier that cannot change which solver runs is
  decoration;
- CP-SAT **refuses** a model it cannot take rather than rounding it. That is
  the failure mode a multi-backend platform exists to prevent: an answer to a
  question nobody asked, indistinguishable from an answer to the one that was.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import text

from app.solve import compile_model, cpsat
from app.solve import lp, milp
from app.solve.backends import CP_SAT, GLOP, MILP, NoBackend, choose
from app.solve.classify import classify
from app.solve.compile import Unsupported
from app.solve.cpsat import NotIntegral
from app.solve.lp import NotContinuous
from app.solve.service import enqueue_run
from app.worker import work_once
from tests.test_v1_problem_run import (  # noqa: F401
    _data,
    _snapshot,
    db,
    make_attribute_def,
    make_domain,
    make_entity,
    make_entity_type,
    make_model_version,
    make_parameter_def,
    make_parameter_value,
    make_problem,
)


@pytest.fixture(autouse=True)
def empty_queue(db):
    db.execute(text("DELETE FROM run"))
    db.commit()
    yield
    db.execute(text("DELETE FROM run"))
    db.commit()


def _blend(db, *, domain_name="blend"):
    """Two feeds, a price and a protein content each, and a protein target.

    barley: 0.5 protein, costs 3;  maize: 0.2 protein, costs 1.
    Need 10 protein, at most 30 kilos of each.

    The cheapest answer is all barley -- 20 kilos at 3 is 60, against maize's
    50 kilos (over its limit) -- and 20 is not where the interesting part is.
    The interesting part is that `buy` is continuous, so the solver is free to
    land between whole numbers, and the protein coefficients are fractions,
    which is what puts the model out of CP-SAT's reach.
    """
    domain = make_domain(db, domain_name)
    feed = make_entity_type(db, domain, "feed", "resource")
    make_attribute_def(db, feed, "protein", "number")
    make_entity(db, feed, "barley", attrs={"protein": 0.5})
    make_entity(db, feed, "maize", attrs={"protein": 0.2})

    cost = make_parameter_def(db, domain, "cost", [feed], default_value=1)
    db.execute(
        text(
            "INSERT INTO parameter_value (parameter_def_id, entity_ids, value)"
            " SELECT :p, ARRAY[e.id], 3 FROM entity e"
            "  WHERE e.entity_type_id = :t AND e.key = 'barley'"
        ),
        {"p": cost, "t": feed},
    )

    ir = {
        "version": 1,
        "sets": ["feed"],
        "parameters": {"cost": {"index": ["feed"]}},
        "variables": {"buy": {"index": ["feed"], "domain": "continuous", "lower": 0, "upper": 30}},
        "constraints": [
            {
                "id": "c_protein",
                "note": "enough protein in the mix",
                "left": {
                    "sum": {
                        "mul": [
                            {"attr": {"of": "f", "name": "protein"}},
                            {"var": "buy", "index": ["f"]},
                        ]
                    },
                    "over": [{"index": "f", "set": "feed"}],
                },
                "relation": ">=",
                "right": {"const": 10},
                "severity": "hard",
            }
        ],
        "objective": {
            "sense": "minimize",
            "terms": [
                {
                    "id": "o_cost",
                    "weight": 1,
                    "expression": {
                        "sum": {
                            "mul": [
                                {"par": "cost", "index": ["f"]},
                                {"var": "buy", "index": ["f"]},
                            ]
                        },
                        "over": [{"index": "f", "set": "feed"}],
                    },
                }
            ],
        },
    }
    problem = make_problem(db, domain)
    return make_model_version(db, problem, ir)


def _ir_and_data(db, version: int):
    ir = db.execute(
        text("SELECT ir FROM model_version WHERE id = :v"), {"v": version}
    ).scalar_one()
    return ir, _data(db, _snapshot(db, version))


# -- it solves, and the answer is fractional --------------------------------


def test_a_continuous_model_solves_and_its_answer_is_not_rounded(db):
    version = _blend(db)
    ir, data = _ir_and_data(db, version)

    result = lp.solve(compile_model(ir, data), time_limit=10.0)

    assert result.status == "optimal"
    # 50 kilos of maize would meet the protein target but breaks the 30-kilo
    # limit, so the mix uses both: 30 maize (6 protein) and 8 barley (4).
    bought = {key[1][0]: value for key, value in result.assignments.items()}
    assert bought["maize"] == pytest.approx(30.0)
    assert bought["barley"] == pytest.approx(8.0)
    assert result.objective == pytest.approx(54.0)


def test_the_two_linear_backends_agree_on_a_continuous_optimum(db):
    """Different searches -- simplex and branch-and-cut over the same
    relaxation -- must reach the same number, or one of them is wrong."""
    version = _blend(db)
    ir, data = _ir_and_data(db, version)
    compiled = compile_model(ir, data)

    from_glop = lp.solve(compiled, time_limit=10.0)
    from_milp = milp.solve(compiled, time_limit=10.0)

    assert from_glop.objective == pytest.approx(from_milp.objective)


def test_a_fraction_survives_the_whole_round_trip(db):
    """Typed as 0.5, stored as numeric, frozen into the snapshot, read back
    and compiled. Any step that went through a float carelessly would turn it
    into 0.5000000000000001 or round it to 0."""
    version = _blend(db)
    _, data = _ir_and_data(db, version)

    protein = {row["id"]: row["protein"] for row in data["sets"]["feed"]}

    assert Decimal(str(protein["barley"])) == Decimal("0.5")
    assert Decimal(str(protein["maize"])) == Decimal("0.2")


def test_an_integer_parameter_is_still_frozen_as_an_integer(db):
    """`trim_scale` in the snapshot. Without it `numeric(15, 6)` writes 3 as
    3.000000, every dataset a model already has would hash differently, and
    nothing about the model would have changed."""
    version = _blend(db)
    _, data = _ir_and_data(db, version)

    stored = data["parameters"]["cost"][0]["value"]
    assert stored == 3
    assert isinstance(stored, int)
    assert data["parameter_defaults"]["cost"] == 1


# -- it is classified, and the classification changes what runs -------------


def test_a_continuous_model_is_classified_LP_and_needs_a_continuous_backend(db):
    version = _blend(db)
    ir, data = _ir_and_data(db, version)

    found = classify(ir, data)

    assert found.model_class == "LP"
    assert "continuous" in found.needs
    assert "integral" not in found.needs
    assert "fractional-data" in found.needs


def test_the_classifier_names_the_number_that_made_the_model_fractional(db):
    """"It has fractional data" sends someone looking through all of it."""
    version = _blend(db)
    ir, data = _ir_and_data(db, version)

    found = classify(ir, data)

    assert any("protein" in reason for reason in found.reasons)


def test_an_LP_goes_to_the_simplex_and_not_to_branch_and_cut(db):
    """The point of having three backends. Branch-and-cut solves an LP by
    solving the relaxation and then finding nothing to branch on; glop just
    solves it."""
    version = _blend(db)
    ir, data = _ir_and_data(db, version)

    backend, why = choose(classify(ir, data))

    assert backend is GLOP
    assert "highest-ranked" in why


def test_an_integral_model_with_a_fractional_parameter_leaves_cp_sat(db):
    """The subtle case, and the one that justifies `fractional-data` being
    separate from the model class. Every variable is binary -- CP-SAT's home
    ground -- but a coefficient is 0.5, and rounding it would answer a
    different question."""
    ir = {
        "version": 1,
        "sets": [],
        "parameters": {},
        "variables": {"x": {"index": [], "domain": "binary"}},
        "constraints": [
            {
                "id": "c_half",
                "left": {"mul": [{"const": 0.5}, {"var": "x", "index": []}]},
                "relation": "<=",
                "right": {"const": 1},
                "severity": "hard",
            }
        ],
    }

    found = classify(ir)

    assert found.model_class == "IP"
    assert "fractional-data" in found.needs
    backend, _ = choose(found)
    assert backend is MILP


def test_a_mixed_model_is_MILP_and_only_one_backend_takes_it(db):
    ir = {
        "version": 1,
        "sets": [],
        "parameters": {},
        "variables": {
            "open": {"index": [], "domain": "binary"},
            "flow": {"index": [], "domain": "continuous", "lower": 0, "upper": 10},
        },
        "constraints": [],
    }

    found = classify(ir)

    assert found.model_class == "MILP"
    assert found.needs >= {"integral", "continuous"}
    backend, why = choose(found)
    assert backend is MILP
    assert "MILP" in why


# -- and what each backend refuses ------------------------------------------


def test_cp_sat_refuses_a_continuous_model_rather_than_rounding_it(db):
    """The whole justification for the capability mechanism. A rounded answer
    is indistinguishable from a correct one to whoever reads it."""
    version = _blend(db)
    ir, data = _ir_and_data(db, version)

    with pytest.raises(NotIntegral) as excinfo:
        cpsat.solve(compile_model(ir, data), time_limit=5.0)

    assert "continuous" in str(excinfo.value)


def test_cp_sat_refuses_a_fractional_coefficient_in_an_otherwise_integral_model():
    from app.solve.compile import Compiled, Constraint, Linear, Variable

    key = ("x", ())
    compiled = Compiled(
        variables={key: Variable(key, "binary", Decimal(0), Decimal(1))},
        constraints=[
            Constraint("c", {}, Linear({key: Decimal("0.5")}), "<=", Linear(const=Decimal(1)))
        ],
        objective=Linear(),
        sense="minimize",
        var_index_sets={"x": []},
    )

    with pytest.raises(NotIntegral) as excinfo:
        cpsat.solve(compiled, time_limit=5.0)

    assert "0.5" in str(excinfo.value)


def test_glop_refuses_a_discrete_model_rather_than_solving_the_relaxation(db):
    """Three quarters of a nurse on Tuesday is not an answer, and a solver
    that returned one without saying so would be worse than none."""
    from app.solve.compile import Compiled, Constraint, Linear, Variable

    key = ("x", ())
    compiled = Compiled(
        variables={key: Variable(key, "binary", Decimal(0), Decimal(1))},
        constraints=[
            Constraint("c", {}, Linear({key: Decimal(2)}), "<=", Linear(const=Decimal(1)))
        ],
        objective=Linear(),
        sense="minimize",
        var_index_sets={"x": []},
    )

    with pytest.raises(NotContinuous) as excinfo:
        lp.solve(compiled, time_limit=5.0)

    assert "discrete" in str(excinfo.value)


def test_asking_for_cp_sat_on_a_continuous_model_is_refused_not_substituted(db):
    version = _blend(db)
    ir, data = _ir_and_data(db, version)

    with pytest.raises(NoBackend) as excinfo:
        choose(classify(ir, data), "cp-sat")

    assert "cannot take a LP model" in str(excinfo.value)


# -- through a run ----------------------------------------------------------


def test_a_continuous_run_records_the_simplex_and_a_fractional_objective(db):
    version = _blend(db)
    problem = db.execute(
        text("SELECT problem_id FROM model_version WHERE id = :v"), {"v": version}
    ).scalar_one()
    scenario = db.execute(
        text(
            "INSERT INTO scenario (problem_id, model_version_id, name)"
            " VALUES (:p, :v, 'base') RETURNING id"
        ),
        {"p": problem, "v": version},
    ).scalar_one()
    db.commit()

    run_id = enqueue_run(db, scenario, time_limit=20.0)
    work_once(db)

    row = db.execute(
        text("SELECT status, solver, solver_version, objective, params FROM run WHERE id = :r"),
        {"r": run_id},
    ).mappings().one()
    assert row["status"] == "optimal"
    assert row["solver"] == "glop"
    assert row["solver_version"].startswith("glop")
    assert row["params"]["classified_as"] == "LP"
    assert row["objective"] == Decimal("54.000000")
