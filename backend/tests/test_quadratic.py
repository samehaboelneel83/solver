"""Quadratic objectives: the first nonlinear class, and why it comes first.

For a quadratic objective, "is this answer the best of all?" has an exact
answer: the objective is convex exactly when its matrix has no negative
eigenvalue. So the platform can PROVE an optimum is global rather than hope.
The policy these tests pin follows from that:

- a continuous quadratic model goes to HiGHS only when it is proven convex,
  and then its "optimal" is the global optimum;
- an all-integer one goes to CP-SAT, which searches products of whole numbers
  exactly, so it proves the global optimum whatever the curvature;
- anything else -- a continuous model that is not proven convex, or a
  quadratic goal over mixed decisions -- is refused, with the reason, rather
  than solved by something that might stop at an answer that is only best
  nearby and call it optimal.

The worked examples are small enough to check by hand. Spreading 10 units
over items to minimise the sum of squares puts an equal share on each: over
two continuous items that is 5 and 5, for 50; over three integer items the
best whole-number split is 4, 3, 3, for 34. Maximising the same sum of squares
is nonconvex: its best is everything on one item, for 100.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import text

from app.solve import compile_model, cpsat
from app.solve.backends import CP_SAT, GLOP, HIGHS, MILP, NoBackend, choose
from app.solve.classify import classify, with_convexity
from app.solve.convexity import objective_convexity
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


@pytest.fixture
def without_scip(monkeypatch):
    """A build without the global solver (`app.solve.scip`). The refusals
    below are what such a build must still do; `test_scip` pins that a build
    with it solves these models instead."""
    from app.solve import scip

    monkeypatch.setattr(scip, "_available", False)


def _ir(domain: str, sense: str = "minimize") -> dict:
    """Share 10 units over the items; the objective is the sum of squares."""
    return {
        "version": 1,
        "sets": ["item"],
        "parameters": {},
        "variables": {"x": {"index": ["item"], "domain": domain, "lower": 0, "upper": 10}},
        "constraints": [
            {
                "id": "c_total",
                "left": {"sum": {"var": "x", "index": ["i"]}, "over": [{"index": "i", "set": "item"}]},
                "relation": "=",
                "right": {"const": 10},
                "severity": "hard",
            }
        ],
        "objective": {
            "sense": sense,
            "terms": [
                {
                    "id": "o_squares",
                    "weight": 1,
                    "expression": {
                        "sum": {"mul": [{"var": "x", "index": ["i"]}, {"var": "x", "index": ["i"]}]},
                        "over": [{"index": "i", "set": "item"}],
                    },
                }
            ],
        },
    }


def _model(db, items: int, domain: str, sense: str = "minimize"):
    dom = make_domain(db, f"qp-{domain}-{sense}-{items}")
    item = make_entity_type(db, dom, "item", "resource")
    for k in range(items):
        make_entity(db, item, f"i{k}")
    version = make_model_version(db, make_problem(db, dom), _ir(domain, sense))
    ir = db.execute(text("SELECT ir FROM model_version WHERE id = :v"), {"v": version}).scalar_one()
    return version, ir, _data(db, _snapshot(db, version))


# -- compiling --------------------------------------------------------------


def test_a_product_of_two_variables_compiles_to_the_quadratic_part(db):
    _, ir, data = _model(db, 2, "continuous")

    compiled = compile_model(ir, data)

    assert compiled.objective.coeffs == {}
    assert compiled.objective_quadratic == {
        (("x", ("i0",)), ("x", ("i0",))): Decimal(1),
        (("x", ("i1",)), ("x", ("i1",))): Decimal(1),
    }


def test_x_times_y_and_y_times_x_are_one_term():
    """Two orders of one product must add up, or a solver would be handed a
    matrix that is not symmetric in the way it assumes."""
    ir = {
        "version": 1,
        "sets": [],
        "parameters": {},
        "variables": {
            "x": {"index": [], "domain": "continuous", "lower": 0, "upper": 1},
            "y": {"index": [], "domain": "continuous", "lower": 0, "upper": 1},
        },
        "constraints": [],
        "objective": {
            "sense": "minimize",
            "terms": [
                {"id": "o_xy", "weight": 2, "expression": {"mul": [{"var": "x", "index": []}, {"var": "y", "index": []}]}},
                {
                    "id": "o_yx",
                    "weight": 1,
                    "expression": {
                        "mul": [
                            {"add": [{"var": "y", "index": []}, {"const": 1}]},
                            {"var": "x", "index": []},
                        ]
                    },
                },
            ],
        },
    }

    compiled = compile_model(ir, {"sets": {}, "parameters": {}, "parameter_defaults": {}})

    # 2xy + (y + 1)x = 3xy + x
    assert compiled.objective_quadratic == {(("x", ()), ("y", ())): Decimal(3)}
    assert compiled.objective.coeffs == {("x", ()): Decimal(1)}


# -- convexity --------------------------------------------------------------


def test_minimising_a_sum_of_squares_is_convex(db):
    _, ir, data = _model(db, 2, "continuous")
    assert objective_convexity(compile_model(ir, data)).convex is True


def test_maximising_a_sum_of_squares_is_not(db):
    """The same curve, the other way: its best is at a corner, and a local
    search started elsewhere would stop at a worse corner."""
    _, ir, data = _model(db, 2, "continuous", sense="maximize")
    found = objective_convexity(compile_model(ir, data))
    assert found.convex is False
    assert "not concave" in found.reason


def test_a_lone_cross_term_is_not_convex():
    """x*y alone is a saddle: convex along one diagonal, concave along the
    other. Counting squares would miss it; the eigenvalues do not."""
    ir = {
        "version": 1,
        "sets": [],
        "parameters": {},
        "variables": {
            "x": {"index": [], "domain": "continuous", "lower": 0, "upper": 1},
            "y": {"index": [], "domain": "continuous", "lower": 0, "upper": 1},
        },
        "constraints": [],
        "objective": {
            "sense": "minimize",
            "terms": [{"id": "o", "weight": 1, "expression": {"mul": [{"var": "x", "index": []}, {"var": "y", "index": []}]}}],
        },
    }
    compiled = compile_model(ir, {"sets": {}, "parameters": {}, "parameter_defaults": {}})
    assert objective_convexity(compiled).convex is False


# -- classifying and choosing -------------------------------------------------


def test_a_continuous_quadratic_model_is_QP_and_goes_to_highs_when_convex(db):
    _, ir, data = _model(db, 2, "continuous")
    found = classify(ir, data)
    assert found.model_class == "QP"
    assert "quadratic" in found.needs

    convexity = objective_convexity(compile_model(ir, data))
    backend, _ = choose(with_convexity(found, convexity.convex, convexity.reason))
    assert backend is HIGHS


def test_a_nonconvex_continuous_model_is_refused_and_says_why(db, without_scip):
    """The refusal is the feature: a local solver would return an answer and
    call it optimal."""
    _, ir, data = _model(db, 2, "continuous", sense="maximize")
    convexity = objective_convexity(compile_model(ir, data))
    found = with_convexity(classify(ir, data), convexity.convex, convexity.reason)

    with pytest.raises(NoBackend) as excinfo:
        choose(found)

    message = str(excinfo.value)
    assert "not proven convex" in message
    assert "whole number" in message  # and what would make it solvable


def test_an_all_integer_quadratic_model_goes_to_cp_sat_convex_or_not(db):
    _, ir, data = _model(db, 3, "integer", sense="maximize")
    found = classify(ir, data)
    assert found.model_class == "MIQP"
    # Even marked nonconvex, CP-SAT takes it: it searches exactly.
    backend, _ = choose(with_convexity(found, False, "not convex"))
    assert backend is CP_SAT


def test_a_quadratic_goal_over_mixed_decisions_is_refused_and_says_why(without_scip):
    ir = _ir("continuous")
    ir["variables"]["open"] = {"index": [], "domain": "binary"}
    found = classify(ir)
    assert found.model_class == "MIQP"

    with pytest.raises(NoBackend) as excinfo:
        choose(found)

    assert "mixed-integer quadratic solver" in str(excinfo.value)


def test_no_linear_only_solver_is_offered_a_quadratic_model():
    """GLOP and the pywraplp MILP backend would silently drop the quadratic
    part, so they must not declare that they take one."""
    for backend in (GLOP, MILP):
        assert "quadratic" not in backend.provides


# -- solving --------------------------------------------------------------------


def test_highs_finds_the_convex_optimum(db):
    _, ir, data = _model(db, 2, "continuous")
    compiled = compile_model(ir, data)

    result = HIGHS.solve(compiled, time_limit=10.0, workers=1)

    assert result.status == "optimal"
    assert result.objective == pytest.approx(50.0, abs=1e-4)
    assert sorted(result.assignments.values()) == pytest.approx([5.0, 5.0], abs=1e-4)


def test_cp_sat_finds_the_integer_optimum(db):
    _, ir, data = _model(db, 3, "integer")

    result = cpsat.solve(compile_model(ir, data), time_limit=10.0)

    assert result.status == "optimal"
    assert result.objective == 34
    assert sorted(result.assignments.values()) == [3, 3, 4]


def test_cp_sat_finds_the_nonconvex_integer_optimum(db):
    """Maximising puts everything on one item. A local method started from an
    even split would stay there; the exact search does not."""
    _, ir, data = _model(db, 3, "integer", sense="maximize")

    result = cpsat.solve(compile_model(ir, data), time_limit=10.0)

    assert result.status == "optimal"
    assert result.objective == 100
    assert sorted(result.assignments.values()) == [0, 0, 10]


# -- through a run --------------------------------------------------------------


def _run(db, version: int) -> dict:
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
    return dict(
        db.execute(
            text("SELECT status, solver, optimality, objective, error, params FROM run WHERE id = :r"),
            {"r": run_id},
        ).mappings().one()
    )


def test_a_convex_qp_run_is_solved_and_says_its_optimum_is_global(db):
    version, _, _ = _model(db, 2, "continuous")

    row = _run(db, version)

    assert row["status"] == "optimal"
    assert row["solver"] == "highs"
    assert row["optimality"] == "global"
    assert row["objective"] == Decimal("50")


def test_a_nonconvex_qp_run_is_an_error_with_the_reason_not_a_wrong_answer(db, without_scip):
    version, _, _ = _model(db, 2, "continuous", sense="maximize")

    row = _run(db, version)

    assert row["status"] == "error"
    assert row["optimality"] is None
    assert "not proven convex" in row["error"]


# -- the Model editor agrees with the run -------------------------------------


def test_the_editor_names_no_solver_for_a_model_the_run_would_refuse(db, without_scip):
    """`POST /api/v1/classify` is the editor's "which kind of solver will take
    this". It takes the same convexity step a run does, so it cannot promise
    a solver for a nonconvex model that the run then refuses."""
    from fastapi.testclient import TestClient

    from app.core.config import get_settings
    from app.main import app
    from app.seed import seed_admin

    seed_admin(db)
    settings = get_settings()
    client = TestClient(app)
    token = client.post(
        "/api/auth/login",
        data={"username": settings.admin_username, "password": settings.admin_password},
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    convex_version, _, _ = _model(db, 2, "continuous")
    nonconvex_version, _, _ = _model(db, 2, "continuous", sense="maximize")
    db.commit()

    def ask(version: int) -> dict:
        problem, ir = db.execute(
            text("SELECT problem_id, ir FROM model_version WHERE id = :v"), {"v": version}
        ).one()
        response = client.post(
            "/api/v1/classify", json={"ir": ir, "problem_id": problem}, headers=headers
        )
        assert response.status_code == 200, response.text
        return response.json()

    convex = ask(convex_version)
    nonconvex = ask(nonconvex_version)

    assert convex["model_class"] == "QP"
    assert convex["would_solve"] is not None
    assert "nonconvex" in nonconvex["needs"]
    assert nonconvex["would_solve"] is None

    for version in (convex_version, nonconvex_version):
        domain = db.execute(
            text("SELECT p.domain_id FROM model_version v JOIN problem p ON p.id = v.problem_id WHERE v.id = :v"),
            {"v": version},
        ).scalar_one()
        db.execute(text("DELETE FROM domain WHERE id = :d"), {"d": domain})
    db.commit()
