"""Number fields made from a date, a text and a linked record (benchmark, October 2026): what a
predictor or a rule can read, made once on the records themselves."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


def test_dates_texts_and_links_become_number_fields(tenants, db):  # noqa: F811
    http, h, domain = TestClient(app), tenants["a"], tenants["domain_a"]

    def post(path, body, ok=(200, 201)):
        got = http.post(path, json=body, headers=h)
        assert got.status_code in ok, got.text
        return got.json()

    road = post("/api/v1/entity-types", {"domain_id": domain, "name": "road", "role": "location"})
    post(f"/api/v1/entity-types/{road['id']}/attributes", {"name": "lanes", "data_type": "integer"})
    obs = post("/api/v1/entity-types", {"domain_id": domain, "name": "obs", "role": "other"})
    for field in ({"name": "day", "data_type": "date"}, {"name": "weather", "data_type": "text"},
                  {"name": "road", "data_type": "reference", "target_type_id": road["id"]}):
        post(f"/api/v1/entity-types/{obs['id']}/attributes", field)
    post("/api/v1/entities", {"entity_type_id": road["id"], "key": "R1", "attrs": {"lanes": 4}})
    post("/api/v1/entities", {"entity_type_id": obs["id"], "key": "o1", "attrs": {"day": "2026-10-02", "weather": "Dust storm", "road": "R1"}})
    post("/api/v1/entities", {"entity_type_id": obs["id"], "key": "o2", "attrs": {"day": "2026-01-05", "weather": "clear"}})

    parts = post(f"/api/v1/entity-types/{obs['id']}/derive", {"op": "date_parts", "field": "day"})
    assert parts["made"] == ["day_weekday", "day_month", "day_day_of_year"] and parts["records"] == 2
    kinds = post(f"/api/v1/entity-types/{obs['id']}/derive", {"op": "categories", "field": "weather"})
    assert kinds["made"] == ["weather_clear", "weather_dust_storm"]
    linked = post(f"/api/v1/entity-types/{obs['id']}/derive", {"op": "from_link", "field": "road", "of": "lanes"})
    assert linked == {"made": ["road_lanes"], "records": 1, "left_empty": 1}

    items = {e["key"]: e["attrs"] for e in http.get("/api/v1/entities", params={"entity_type_id": obs["id"]}, headers=h).json()["items"]}
    assert items["o1"]["day_weekday"] == 4 and items["o1"]["day_month"] == 10  # a Friday in October
    assert items["o1"]["weather_dust_storm"] == 1 and items["o1"]["weather_clear"] == 0
    assert items["o1"]["road_lanes"] == 4 and "road_lanes" not in items["o2"]

    refused = http.post(f"/api/v1/entity-types/{obs['id']}/derive", json={"op": "date_parts", "field": "road"}, headers=h)
    assert refused.status_code == 422
    assert http.post(f"/api/v1/entity-types/{obs['id']}/derive", json={"op": "date_parts", "field": "day"},
                     headers=tenants["b"]).status_code in (403, 404)


def test_a_formula_over_a_record_s_numbers_becomes_a_field(tenants, db):  # noqa: F811
    """Benchmark, October 2026: volume / capacity and length / speed could not be written."""
    http, h, domain = TestClient(app), tenants["a"], tenants["domain_a"]
    road = http.post("/api/v1/entity-types", json={"domain_id": domain, "name": "link", "role": "location"}, headers=h).json()
    for name in ("volume", "capacity", "label_text"):
        http.post(f"/api/v1/entity-types/{road['id']}/attributes",
                  json={"name": name, "data_type": "text" if name == "label_text" else "number"}, headers=h)
    for key, attrs in (("a", {"volume": 900, "capacity": 1200}), ("b", {"volume": 300, "capacity": 0}), ("c", {"volume": 50})):
        http.post("/api/v1/entities", json={"entity_type_id": road["id"], "key": key, "attrs": attrs}, headers=h)
    path = f"/api/v1/entity-types/{road['id']}/derive"
    done = http.post(path, json={"op": "formula", "field": "vc_ratio", "formula": "volume / capacity"}, headers=h)
    assert done.status_code == 200, done.text
    assert done.json()["records"] == 1 and sorted(done.json()["empty"]) == ["b", "c"]  # no division by zero, nothing missing made up
    items = {e["key"]: e["attrs"] for e in http.get("/api/v1/entities", params={"entity_type_id": road["id"]}, headers=h).json()["items"]}
    assert items["a"]["vc_ratio"] == 0.75 and "vc_ratio" not in items["b"]
    for bad in ("volume / label_text", "__import__('os')", "volume ** 2", "volume /"):
        assert http.post(path, json={"op": "formula", "field": "x", "formula": bad}, headers=h).status_code == 422, bad
