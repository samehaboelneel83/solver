"""Knapsack-shaped models go to a MIP solver (the general-purpose evaluation, October 2026: a 2,000-item knapsack
took CP-SAT, the rank's pick, 15.7 s; HiGHS solves the family in well under 2 s)."""
from __future__ import annotations

import random

from fastapi.testclient import TestClient

from app.main import app
from app.solve.backends import knapsack_shaped
from tests.test_quadratic import empty_queue  # noqa: F401
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


def _knapsack(n: int, name: str) -> dict:
    rng = random.Random(7)
    items = [{"type": "item", "key": f"i{j}", "attrs": {"w": rng.randint(10, 400), "v": rng.randint(10, 500)}}
             for j in range(n)]
    cap = sum(e["attrs"]["w"] for e in items) // 3
    i = {"index": "i", "set": "item"}
    return {"domain_name": name, "problem_name": name,
            "seed": {"entity_types": [{"name": "item", "attributes": [{"name": "w", "data_type": "integer"},
                                                                      {"name": "v", "data_type": "integer"}]}],
                     "entities": items, "parameters": [{"name": "cap", "index": [], "default_value": cap}]},
            "ir": {"version": 2, "sets": ["item"], "parameters": {"cap": {"index": []}},
                   "variables": {"take": {"index": ["item"], "domain": "binary"}},
                   "constraints": [{"id": "c_cap", "severity": "hard", "relation": "<=",
                                    "left": {"sum": {"mul": [{"attr": {"of": "i", "name": "w"}},
                                                             {"var": "take", "index": ["i"]}]}, "over": [i]},
                                    "right": {"par": "cap", "index": []}}],
                   "objective": {"sense": "maximize", "terms": [{"id": "o", "weight": 1, "expression": {
                       "sum": {"mul": [{"attr": {"of": "i", "name": "v"}}, {"var": "take", "index": ["i"]}]},
                       "over": [i]}}]}}}


def test_the_shape_test():
    base = {"rows_knapsack": 1, "binary": 2000, "coef_max": 400, "objective_degree": 1}
    assert knapsack_shaped(base)
    assert not knapsack_shaped({**base, "binary": 100})
    assert not knapsack_shaped({**base, "rows_scheduling": 3})
    assert not knapsack_shaped({**base, "rows_knapsack": 0})
    assert not knapsack_shaped(None)


def test_a_large_knapsack_is_solved_by_a_mip_solver(tenants, db):
    from app.worker import work_once

    client = TestClient(app)
    built = client.post("/api/v1/problems/from-spec", json=_knapsack(800, "Knapsack shape"), headers=tenants["b"])
    assert built.status_code == 200, built.text
    run = client.post(f"/api/v1/scenarios/{built.json()['scenario_id']}/runs", json={"time_limit_s": 30},
                      headers=tenants["b"]).json()
    for _ in range(5):
        if work_once(db) is None:
            break
    answer = client.get(f"/api/v1/runs/{run['id']}", headers=tenants["b"]).json()
    assert answer["status"] == "optimal", answer
    assert answer["solver"] in ("highs", "scip"), answer["solver"]
    assert "knapsack-shaped" in answer["params"]["why_solver"]
