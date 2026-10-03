"""A record's link field in an index position (benchmark round 5): `rate[of_district[c]]` -- the rate of
the district each cell links to -- written directly, not copied onto the cells first."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.solve import compile_model
from app.solve.backends import by_name
from app.solve.compile import Unsupported
from app.solve.service import solve_compiled
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db, make_problem  # noqa: F401

import pytest

C = "c"
SERVE = {"var": "serve", "index": [C]}
RATE = {"par": "rate", "index": [{"attr": {"of": C, "name": "of_district"}}]}


def _ir(position=None):
    return {"version": 2, "sets": ["cell", "district"], "parameters": {"rate": {"index": ["district"]}},
            "variables": {"serve": {"index": ["cell"], "domain": "continuous", "lower": 0, "upper": 100}},
            "constraints": [{"id": "at_most_rate", "forall": [{"index": C, "set": "cell"}], "severity": "hard",
                             "left": SERVE, "relation": "<=", "right": position or RATE}],
            "objective": {"sense": "maximize", "terms": [{"id": "served", "weight": 1,
                                                          "expression": {"sum": SERVE, "over": [{"index": C, "set": "cell"}]}}]}}


def test_a_cell_reads_the_rate_of_the_district_it_links_to():
    data = {"sets": {"district": [{"id": "D1"}, {"id": "D2"}],
                     "cell": [{"id": "c1", "of_district": "D1"}, {"id": "c2", "of_district": "D2"}, {"id": "c3", "of_district": "D2"}]},
            "parameters": {"rate": [{"district": "D1", "value": 3}, {"district": "D2", "value": 5}]}, "parameter_defaults": {"rate": 0}}
    result, _ = solve_compiled(by_name("highs"), compile_model(_ir(), data), time_limit=10, seed=1)
    assert float(result.objective) == pytest.approx(3 + 5 + 5)
    data["sets"]["cell"].append({"id": "c4"})
    with pytest.raises(Unsupported, match="of_district of c4 links to no record"):
        compile_model(_ir(), data)


def test_the_workspace_checks_the_field_links_to_that_kind(tenants, db):  # noqa: F811
    http, h, domain = TestClient(app), tenants["a"], tenants["domain_a"]

    def post(path, body, ok=(200, 201)):
        got = http.post(path, json=body, headers=h)
        assert got.status_code in ok, got.text
        return got.json()

    district = post("/api/v1/entity-types", {"domain_id": domain, "name": "district", "role": "location"})
    cell = post("/api/v1/entity-types", {"domain_id": domain, "name": "cell", "role": "location"})
    post(f"/api/v1/entity-types/{cell['id']}/attributes", {"name": "of_district", "data_type": "reference", "target_type_id": district["id"]})
    post(f"/api/v1/entity-types/{cell['id']}/attributes", {"name": "people", "data_type": "number"})
    post("/api/v1/parameters", {"domain_id": domain, "name": "rate", "index_type_ids": [district["id"]]})
    problem = make_problem(db, domain)
    db.commit()
    post(f"/api/v1/problems/{problem}/versions", {"ir": _ir()})
    wrong = http.post(f"/api/v1/problems/{problem}/versions", headers=h,
                      json={"ir": _ir({"par": "rate", "index": [{"attr": {"of": C, "name": "people"}}]})})
    assert wrong.status_code == 422 and "has no link field 'people'" in wrong.text
