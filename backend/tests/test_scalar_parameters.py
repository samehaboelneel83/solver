"""One number as a data value (migration 0104, benchmark October 2026): a truck's capacity or a
budget, with no index, read by a model as `name` and changed in one place."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app.solve.service import enqueue_run
from app.worker import work_once
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db, make_model_version, make_problem  # noqa: F401


def test_one_number_is_data_a_model_reads_and_a_change_moves_the_answer(tenants, db):  # noqa: F811
    http, h, domain = TestClient(app), tenants["a"], tenants["domain_a"]
    made = http.post("/api/v1/parameters", json={"domain_id": domain, "name": "budget", "index_type_ids": [], "default_value": 7},
                     headers=h)
    assert made.status_code == 201, made.text
    pid = made.json()["id"]
    cells = http.put(f"/api/v1/parameters/{pid}/values", json={"cells": [{"entity_ids": [], "value": 3}]}, headers=h)
    assert cells.status_code == 422 and "one number" in cells.text

    ir = {"version": 2, "sets": [], "parameters": {"budget": {"index": []}},
          "variables": {"x": {"index": [], "domain": "integer", "lower": 0, "upper": 100}},
          "constraints": [{"id": "c_budget", "left": {"var": "x", "index": []}, "relation": "<=",
                           "right": {"par": "budget", "index": []}, "severity": "hard"}],
          "objective": {"sense": "maximize", "terms": [{"id": "o", "weight": 1, "expression": {"var": "x", "index": []}}]}}
    problem = db.execute(text("INSERT INTO problem (domain_id, name) VALUES (:d, 'scalar') RETURNING id"), {"d": domain}).scalar_one()
    version = make_model_version(db, problem, ir)
    scenario = db.execute(text("INSERT INTO scenario (problem_id, model_version_id, name) VALUES (:p, :v, 'base') RETURNING id"),
                          {"p": problem, "v": version}).scalar_one()
    db.commit()

    def solved() -> float:
        run = enqueue_run(db, scenario, time_limit=10.0)
        for _ in range(5):
            if db.execute(text("SELECT status FROM run WHERE id = :r"), {"r": run}).scalar_one() != "queued":
                break
            work_once(db)
        return float(db.execute(text("SELECT objective FROM run WHERE id = :r"), {"r": run}).scalar_one())

    assert solved() == 7
    assert http.patch(f"/api/v1/parameters/{pid}", json={"default_value": 12}, headers=h).status_code == 200
    assert solved() == 12
