"""A model as a QUBO (app.solve.qubo): the least value of the QUBO is the model's optimum, for any model of
yes/no and bounded whole-number decisions, linear rules and a linear or quadratic goal."""
from __future__ import annotations

import itertools
import json
import random

import pytest

from app.solve import compile_model
from app.solve.backends import by_name
from app.solve.evolve import holds, objective_at
from app.solve.qubo import NotQubo, anneal, export, to_qubo
from app.solve.service import solve_compiled
from tests.test_api_runs import auth_headers, ensure_admin_seeded  # noqa: F401
from tests.test_pareto import OPTIONS, _ir, _scenario, empty_queue  # noqa: F401
from tests.test_v1_problem_run import (  # noqa: F401
    db,
    make_domain,
    make_entity,
    make_entity_type,
    make_model_version,
    make_parameter_def,
    make_parameter_value,
    make_problem,
)

I = [{"index": "i", "set": "item"}]


def _model(*, sense="maximize", weights=(4, 3, 5, 2, 6), values=(7, 4, 9, 3, 8), capacity=11,
           count=None, extra=None, quadratic=False, whole=False) -> tuple[dict, dict]:
    """A knapsack (a `<=` rule, so a slack), optionally exactly `count` items (an `=` rule), a whole-number
    decision `level` in [0, 5] with a value, and a product in the goal."""
    items = [f"i{k}" for k in range(len(weights))]
    goal = {"sum": {"mul": [{"par": "value", "index": ["i"]}, {"var": "take", "index": ["i"]}]}, "over": I}
    rules = [{"id": "c_cap", "left": {"sum": {"mul": [{"par": "weight", "index": ["i"]}, {"var": "take", "index": ["i"]}]},
                                      "over": I}, "relation": "<=", "right": {"const": capacity}, "severity": "hard"}]
    variables = {"take": {"index": ["item"], "domain": "binary"}}
    if count is not None:
        rules.append({"id": "c_count", "left": {"sum": {"var": "take", "index": ["i"]}, "over": I}, "relation": "=",
                      "right": {"const": count}, "severity": "hard"})
    if whole:
        variables["level"] = {"index": [], "domain": "integer", "lower": 0, "upper": 5}
        goal = {"add": [goal, {"mul": [{"const": 2}, {"var": "level", "index": []}]}]}
        # level <= items taken
        rules.append({"id": "c_level", "left": {"var": "level", "index": []}, "relation": "<=",
                      "right": {"sum": {"var": "take", "index": ["i"]}, "over": I}, "severity": "hard"})
    if quadratic:
        # Products of a yes/no and a whole number, and of a whole number with itself.
        variables.setdefault("level", {"index": [], "domain": "integer", "lower": 0, "upper": 5})
        goal = {"add": [goal,
                        {"mul": [{"const": -1}, {"sum": {"mul": [{"var": "take", "index": ["i"]},
                                                                 {"var": "level", "index": []}]}, "over": I}]},
                        {"mul": [{"const": 2}, {"mul": [{"var": "level", "index": []}, {"var": "level", "index": []}]}]}]}
    if extra:
        rules += extra
    ir = {"version": 2, "sets": ["item"],
          "parameters": {"weight": {"index": ["item"]}, "value": {"index": ["item"]}},
          "variables": variables, "constraints": rules,
          "objective": {"sense": sense, "terms": [{"id": "o", "weight": 1, "expression": goal}]}}
    data = {"sets": {"item": [{"id": k} for k in items]},
            "parameters": {"weight": [{"item": k, "value": w} for k, w in zip(items, weights)],
                           "value": [{"item": k, "value": v} for k, v in zip(items, values)]},
            "parameter_defaults": {}, "relationships": {}}
    return ir, data


def _least(q):
    return min(itertools.product((0, 1), repeat=len(q.bits)), key=q.energy)


@pytest.mark.parametrize("shape", [
    {}, {"count": 2}, {"whole": True}, {"quadratic": True}, {"sense": "minimize", "count": 3},
    {"capacity": 7, "count": 2, "whole": True, "quadratic": True},
])
def test_the_least_value_of_the_qubo_is_the_models_optimum(shape):
    ir, data = _model(**shape)
    compiled = compile_model(ir, data)
    exact = solve_compiled(by_name("cp-sat"), compiled, time_limit=10, seed=1)[0]
    assert exact.status == "optimal"
    q = to_qubo(compiled)
    assert len(q.bits) <= 18, q.summary()
    least = _least(q)
    values = q.decode(least)
    assert holds(compiled, values)
    assert objective_at(compiled, values) == exact.objective
    # The QUBO's value there is the goal (turned to a minimum): every square is zero.
    assert q.energy(least) == pytest.approx(q.turn * float(exact.objective))


def test_a_rule_no_answer_can_break_is_left_out():
    ir, data = _model(capacity=100)
    q = to_qubo(compile_model(ir, data))
    assert q.dropped == ["c_cap"] and q.rules == 0


def test_fractional_rules_are_scaled_to_whole_numbers():
    ir, data = _model(weights=(0.4, 0.3, 0.5, 0.2, 0.6), capacity=1.1)
    compiled = compile_model(ir, data)
    exact = solve_compiled(by_name("highs"), compiled, time_limit=10, seed=1)[0]
    values = to_qubo(compiled).decode(_least(to_qubo(compiled)))
    assert holds(compiled, values) and objective_at(compiled, values) == pytest.approx(exact.objective)


@pytest.mark.parametrize("change, reason", [
    (lambda ir: ir["variables"].update({"x": {"index": [], "domain": "continuous", "lower": 0, "upper": 1}}),
     "is continuous"),
    (lambda ir: ir["objective"].update({"mode": "lex", "terms": ir["objective"]["terms"] * 2}), "in order"),
])
def test_what_a_qubo_cannot_hold_is_refused_by_name(change, reason):
    ir, data = _model()
    change(ir)
    if ir["objective"].get("mode") == "lex":
        ir["objective"]["terms"][1] = {**ir["objective"]["terms"][1], "id": "o2"}
    with pytest.raises(NotQubo, match=reason):
        to_qubo(compile_model(ir, data))


def test_the_files_an_annealer_reads():
    ir, data = _model(count=2)
    q = to_qubo(compile_model(ir, data))
    as_json = json.loads(export(q, "json"))
    assert as_json["vartype"] == "BINARY" and as_json["variables"] == q.bits
    assert len(as_json["linear"]) + len(as_json["quadratic"]) == len(q.terms)
    assert as_json["decisions"]["take[i0]"] == {"lower": 0, "bits": [["take[i0]#0", 1]]}
    text = export(q, "qubo")
    header = next(line for line in text.splitlines() if line.startswith("p "))
    _, _, _, n, diagonal, couplers = header.split()
    assert int(n) == len(q.bits) and int(diagonal) + int(couplers) == len(q.terms)
    assert len([line for line in text.splitlines() if line and line[0].isdigit()]) == len(q.terms)


def test_annealing_finds_an_answer_that_keeps_every_rule():
    rnd = random.Random(5)
    weights = tuple(rnd.randint(2, 12) for _ in range(16))
    values = tuple(rnd.randint(1, 15) for _ in range(16))
    ir, data = _model(weights=weights, values=values, capacity=30, count=5)
    compiled = compile_model(ir, data)
    exact = solve_compiled(by_name("cp-sat"), compiled, time_limit=10, seed=1)[0]
    found = anneal(compiled, time_limit=3, seed=1)
    assert found.status == "feasible" and holds(compiled, found.assignments)
    assert found.objective >= 0.9 * exact.objective


def test_qubo_anneal_runs_by_name_only():
    backend = by_name("qubo-anneal")
    assert backend is not None and not backend.automatic and backend.proves == "local"
    ir, data = _model()
    solution = solve_compiled(backend, compile_model(ir, data), time_limit=2, seed=1)[0]
    assert solution.status == "feasible" and solution.objective == 19


def test_a_scenario_downloads_as_a_qubo(db, empty_queue, auth_headers):  # noqa: F811
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    from app.main import app

    domain, scenario = _scenario(db)
    try:
        client = TestClient(app)
        got = client.get(f"/api/v1/scenarios/{scenario}/qubo", headers=auth_headers)
        assert got.status_code == 200, got.text
        assert got.headers["x-qubo-bits"] == "3" and "attachment" in got.headers["content-disposition"]
        assert json.loads(got.text)["vartype"] == "BINARY"
        text_file = client.get(f"/api/v1/scenarios/{scenario}/qubo?format=qubo&penalty=50", headers=auth_headers)
        assert text_file.status_code == 200 and "p qubo 0 3" in text_file.text
        assert text_file.headers["x-qubo-penalty"] == "50"
    finally:
        db.execute(text("DELETE FROM domain WHERE id = :d"), {"d": domain})
        db.commit()


def test_a_model_a_qubo_cannot_hold_says_why(db, empty_queue, auth_headers):  # noqa: F811
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    from app.main import app

    domain, scenario = _scenario(db)
    try:
        ir = _ir()
        ir["variables"]["pick"]["domain"] = "continuous"
        ir["variables"]["pick"]["upper"] = 1
        problem = db.execute(text("SELECT problem_id FROM scenario WHERE id = :s"), {"s": scenario}).scalar_one()
        version = make_model_version(db, problem, ir)
        scenario = db.execute(text("INSERT INTO scenario (problem_id, model_version_id, name) VALUES (:p, :v, 'c')"
                                   " RETURNING id"), {"p": problem, "v": version}).scalar_one()
        db.commit()
        got = TestClient(app).get(f"/api/v1/scenarios/{scenario}/qubo", headers=auth_headers)
        assert got.status_code == 422 and got.json()["detail"]["code"] == "not_a_qubo"
        assert "continuous" in got.json()["detail"]["message"]
    finally:
        db.execute(text("DELETE FROM domain WHERE id = :d"), {"d": domain})
        db.commit()
