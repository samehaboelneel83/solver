"""Epic UX, U-1: `q` on every large collection -- by name, and by id when the query is a number."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.search import condition
from app.main import app
from app.solve.service import enqueue_run
from tests.test_api_runs import auth_headers, ensure_admin_seeded  # noqa: F401
from tests.test_v1_problem_run import (  # noqa: F401
    db, make_domain, make_entity_type, make_model_version, make_problem,
)

IR = {"version": 1, "sets": [], "parameters": {}, "variables": {}, "constraints": []}


@pytest.fixture
def world(db):  # noqa: F811
    domain = make_domain(db, "search")
    types = {name: make_entity_type(db, domain, name) for name in ("warehouse", "ware_house_2", "truck")}
    problem = make_problem(db, domain)
    versions = [make_model_version(db, problem, IR, note=note) for note in ("first cut", "with overtime", None)]
    scenarios = {name: db.execute(text("INSERT INTO scenario (problem_id, model_version_id, name) VALUES (:p, :v, :n)"
                                       " RETURNING id"), {"p": problem, "v": versions[0], "n": name}).scalar_one()
                 for name in ("winter peak", "summer", "100% load")}
    db.execute(text("INSERT INTO parameter_def (domain_id, name, index_type_ids) VALUES (:d, 'truck_cost', ARRAY[:t]),"
                    " (:d, 'shift_length', ARRAY[:t])"), {"d": domain, "t": types["truck"]})
    db.commit()
    yield {"domain": domain, "types": types, "problem": problem, "versions": versions, "scenarios": scenarios}
    db.execute(text("DELETE FROM domain WHERE id = :d"), {"d": domain})
    db.commit()


def _names(response, key="name"):
    assert response.status_code == 200, response.text
    return sorted(item[key] for item in response.json()["items"])


def test_scenarios_by_name_and_by_id(world, auth_headers):  # noqa: F811
    client, p = TestClient(app), world["problem"]
    assert _names(client.get(f"/api/v1/scenarios?problem_id={p}&q=WINTER", headers=auth_headers)) == ["winter peak"]
    by_id = world["scenarios"]["summer"]
    assert _names(client.get(f"/api/v1/scenarios?problem_id={p}&q={by_id}", headers=auth_headers)) == ["summer"]
    # `%` is a character here, not a wildcard.
    assert _names(client.get(f"/api/v1/scenarios?problem_id={p}&q=%25", headers=auth_headers)) == ["100% load"]
    total = client.get(f"/api/v1/scenarios?problem_id={p}&q=er", headers=auth_headers).json()["total"]
    assert total == 2


def test_entity_types_parameters_and_relationship_types(world, auth_headers):  # noqa: F811
    client, d = TestClient(app), world["domain"]
    # `_` is a character too: only the type whose name has one.
    assert _names(client.get(f"/api/v1/entity-types?domain_id={d}&q=ware_", headers=auth_headers)) == ["ware_house_2"]
    assert _names(client.get(f"/api/v1/entity-types?domain_id={d}&q=ware", headers=auth_headers)) == \
        ["ware_house_2", "warehouse"]
    assert _names(client.get(f"/api/v1/parameters?domain_id={d}&q=truck", headers=auth_headers)) == ["truck_cost"]
    assert client.get(f"/api/v1/relationship-types?domain_id={d}&q=none", headers=auth_headers).json()["total"] == 0


def test_versions_by_note_and_by_number(world, auth_headers):  # noqa: F811
    client, p = TestClient(app), world["problem"]
    found = client.get(f"/api/v1/problems/{p}/versions?q=overtime", headers=auth_headers).json()["items"]
    assert [v["note"] for v in found] == ["with overtime"]
    numbered = client.get(f"/api/v1/problems/{p}/versions?q=3", headers=auth_headers).json()["items"]
    assert [v["version"] for v in numbered] == [3]


def test_runs_by_status_and_by_id(world, db, auth_headers):  # noqa: F811
    scenario = world["scenarios"]["summer"]
    ids = []
    for status, solver in (("optimal", "highs"), ("infeasible", "cp-sat")):
        run_id = enqueue_run(db, scenario, time_limit=1.0, reuse=False)
        db.execute(text("UPDATE run SET status = :st, params = params || jsonb_build_object('chosen_solver', CAST(:s AS text))"
                        " WHERE id = :r"), {"st": status, "s": solver, "r": run_id})
        ids.append(run_id)
    db.commit()
    client = TestClient(app)
    try:
        base = f"/api/v1/runs?scenario_id={scenario}"
        assert [r["id"] for r in client.get(f"{base}&q=infeas", headers=auth_headers).json()["items"]] == [ids[1]]
        assert [r["id"] for r in client.get(f"{base}&q=highs", headers=auth_headers).json()["items"]] == [ids[0]]
        assert [r["id"] for r in client.get(f"{base}&q={ids[0]}", headers=auth_headers).json()["items"]] == [ids[0]]
    finally:
        db.execute(text("DELETE FROM run WHERE scenario_id = :s"), {"s": scenario})
        db.commit()


def test_an_empty_query_searches_nothing():
    assert condition(None) is None and condition("   ") is None
