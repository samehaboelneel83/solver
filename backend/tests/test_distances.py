"""Distances and nearness from the map (queue R16a): computed from shapes, recorded with their source."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from tests.test_quadratic import empty_queue  # noqa: F401
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401

#: One degree of longitude on the equator, in metres (WGS84): the check needs no second library.
DEGREE_M = 111_319.49


def _point(lon, lat):
    return {"type": "Point", "coordinates": [lon, lat]}


@pytest.fixture
def placed(tenants, db):  # noqa: F811
    """Three sites and four customers on the equator, a customer with no shape, and a site as a square."""
    client, headers, domain = TestClient(app), tenants["a"], tenants["domain_a"]

    def post(path, body):
        response = client.post(path, json=body, headers=headers)
        assert response.status_code in (200, 201), response.text
        return response.json()

    site = post("/api/v1/entity-types", {"domain_id": domain, "name": "site", "role": "location"})
    customer = post("/api/v1/entity-types", {"domain_id": domain, "name": "customer", "role": "location"})
    for t in (site, customer):
        post(f"/api/v1/entity-types/{t['id']}/attributes", {"name": "place", "data_type": "geometry"})
    post("/api/v1/entities", {"entity_type_id": site["id"], "key": "s0", "attrs": {"place": _point(0, 0)}})
    post("/api/v1/entities", {"entity_type_id": site["id"], "key": "s1", "attrs": {"place": _point(1, 0)}})
    square = {"type": "Polygon", "coordinates": [[[1.9, -0.1], [2.1, -0.1], [2.1, 0.1], [1.9, 0.1], [1.9, -0.1]]]}
    post("/api/v1/entities", {"entity_type_id": site["id"], "key": "s2", "attrs": {"place": square}})
    for k, lon in enumerate((0.0, 0.5, 1.0, 3.0)):
        post("/api/v1/entities", {"entity_type_id": customer["id"], "key": f"c{k}", "attrs": {"place": _point(lon, 0)}})
    post("/api/v1/entities", {"entity_type_id": customer["id"], "key": "nowhere", "attrs": {}})
    return {"client": client, "headers": headers, "domain": domain, "site": site, "customer": customer, "post": post}


def _values(db, parameter_id):  # noqa: F811
    rows = db.execute(text(
        "SELECT a.key, b.key, pv.value FROM parameter_value pv JOIN entity a ON a.id = pv.entity_ids[1]"
        " JOIN entity b ON b.id = pv.entity_ids[2] WHERE pv.parameter_def_id = :p"), {"p": parameter_id}).all()
    return {(a, b): float(v) for a, b, v in rows}


def test_distances_are_geodesic_metres_with_their_source(placed, db):  # noqa: F811
    report = placed["post"](f"/api/v1/domains/{placed['domain']}/distances",
                            {"name": "distance", "from_type_id": placed["site"]["id"], "to_type_id": placed["customer"]["id"]})
    assert report["pairs"] == 3 * 4 and report["missing"] == ["nowhere"]
    values = _values(db, report["parameter_id"])
    assert values[("s0", "c0")] == 0
    assert values[("s0", "c2")] == pytest.approx(DEGREE_M, abs=1)
    assert values[("s1", "c3")] == pytest.approx(2 * DEGREE_M, abs=1)
    # A shape is measured from a point inside it: the square's is at 2 degrees east.
    assert values[("s2", "c3")] == pytest.approx(DEGREE_M, abs=0.1 * DEGREE_M)
    assert all(v == int(v) for v in values.values())  # whole metres
    source = report["source"]
    assert source["kind"] == "distance" and source["unit"] == "m" and "straight line" in source["metric"]
    assert (source["from"], source["to"], source["missing"]) == ("site", "customer", ["nowhere"])
    row = db.execute(text("SELECT unit, default_value, source FROM parameter_def WHERE id = :p"),
                     {"p": report["parameter_id"]}).one()
    assert row.unit == "m" and float(row.default_value) == 0 and row.source["computed_at"]


def test_nearest_keeps_a_few_and_the_rest_are_far_never_free(placed, db):  # noqa: F811
    report = placed["post"](f"/api/v1/domains/{placed['domain']}/distances",
                            {"name": "near", "from_type_id": placed["site"]["id"], "to_type_id": placed["customer"]["id"],
                             "nearest": 2, "unit": "km"})
    assert report["pairs"] == 3 * 2
    values = _values(db, report["parameter_id"])
    assert set(b for a, b in values if a == "s0") == {"c0", "c1"}
    assert values[("s0", "c1")] == pytest.approx(DEGREE_M / 2000, abs=0.001)
    far = report["source"]["far"]
    default = db.execute(text("SELECT default_value FROM parameter_def WHERE id = :p"), {"p": report["parameter_id"]}).scalar_one()
    assert float(default) == far and far > max(values.values()) * 5


def test_computing_again_replaces_the_values(placed, db):  # noqa: F811
    body = {"name": "distance", "from_type_id": placed["site"]["id"], "to_type_id": placed["customer"]["id"]}
    first = placed["post"](f"/api/v1/domains/{placed['domain']}/distances", body)
    second = placed["post"](f"/api/v1/domains/{placed['domain']}/distances", {**body, "nearest": 1})
    assert second["parameter_id"] == first["parameter_id"] and len(_values(db, second["parameter_id"])) == 3


def test_a_name_over_other_types_is_refused(placed):
    post = placed["post"]
    post(f"/api/v1/domains/{placed['domain']}/distances",
         {"name": "distance", "from_type_id": placed["site"]["id"], "to_type_id": placed["customer"]["id"]})
    response = placed["client"].post(f"/api/v1/domains/{placed['domain']}/distances", headers=placed["headers"],
                                     json={"name": "distance", "from_type_id": placed["customer"]["id"],
                                           "to_type_id": placed["site"]["id"]})
    assert response.status_code == 409 and "other types" in response.text


def test_too_many_pairs_asks_for_nearest(placed, monkeypatch):
    from app.api import distances

    monkeypatch.setattr(distances, "MAX_PAIRS", 5)
    response = placed["client"].post(f"/api/v1/domains/{placed['domain']}/distances", headers=placed["headers"],
                                     json={"name": "d", "from_type_id": placed["site"]["id"],
                                           "to_type_id": placed["customer"]["id"]})
    assert response.status_code == 422 and "nearest" in response.text


def test_within_links_places_closer_than_the_distance(placed, db):  # noqa: F811
    report = placed["post"](f"/api/v1/domains/{placed['domain']}/within",
                            {"name": "reaches", "from_type_id": placed["site"]["id"], "to_type_id": placed["customer"]["id"],
                             "max_m": 0.6 * DEGREE_M})
    edges = db.execute(text(
        "SELECT a.key, b.key FROM relationship r JOIN entity a ON a.id = r.from_entity_id JOIN entity b ON b.id = r.to_entity_id"
        " WHERE r.relationship_type_id = :t"), {"t": report["relationship_type_id"]}).all()
    assert sorted(edges) == [("s0", "c0"), ("s0", "c1"), ("s1", "c1"), ("s1", "c2")]
    assert report["source"]["kind"] == "within" and report["source"]["max_m"] == pytest.approx(0.6 * DEGREE_M)


def test_a_run_says_which_computed_data_it_read(placed, db, empty_queue):  # noqa: F811
    from app.worker import work_once

    post, domain = placed["post"], placed["domain"]
    post(f"/api/v1/domains/{domain}/distances",
         {"name": "distance", "from_type_id": placed["site"]["id"], "to_type_id": placed["customer"]["id"]})
    serve = {"var": "serve", "index": ["s", "c"]}
    ir = {"version": 2, "sets": ["site", "customer"], "parameters": {"distance": {"index": ["site", "customer"]}},
          "variables": {"serve": {"index": ["site", "customer"], "domain": "binary"}},
          "constraints": [{"id": "c_served", "forall": [{"index": "c", "set": "customer"}],
                           "left": {"sum": serve, "over": [{"index": "s", "set": "site"}]}, "relation": "=",
                           "right": {"const": 1}, "severity": "hard"}],
          "objective": {"sense": "minimize", "terms": [{"id": "o_distance", "weight": 1, "expression": {
              "sum": {"mul": [{"par": "distance", "index": ["s", "c"]}, serve]},
              "over": [{"index": "s", "set": "site"}, {"index": "c", "set": "customer"}]}}]}}
    problem = post("/api/problem/", {"domain_id": domain, "name": "nearest site"})
    version = post(f"/api/v1/problems/{problem['id']}/versions", {"ir": ir})
    scenario = post("/api/v1/scenarios", {"problem_id": problem["id"], "model_version_id": version["id"], "name": "base"})
    run_id = post(f"/api/v1/scenarios/{scenario['id']}/runs", {"reuse": False, "time_limit_s": 10})["id"]
    for _ in range(5):
        if db.execute(text("SELECT status FROM run WHERE id = :r"), {"r": run_id}).scalar_one() not in ("queued", "running"):
            break
        work_once(db)
    run = placed["client"].get(f"/api/v1/runs/{run_id}", headers=placed["headers"]).json()
    assert run["status"] == "optimal"
    [computed] = run["params"]["computed_inputs"]
    assert computed["input"] == "parameter" and computed["kind"] == "distance" and computed["name"] == "distance"
    assert computed["unit"] == "m"


def test_road_distances_through_the_endpoint_never_guess_a_missing_road(tenants, db, monkeypatch):  # noqa: F811
    """`metric: road` on tiles built in the test: a road where there is one, the far default where there is none."""
    from app.spatial import roads
    from tests import test_roads as t

    client, headers, domain = TestClient(app), tenants["a"], tenants["domain_a"]

    def post(path, body):
        response = client.post(path, json=body, headers=headers)
        assert response.status_code in (200, 201), response.text
        return response.json()

    depot = post("/api/v1/entity-types", {"domain_id": domain, "name": "depot", "role": "location"})
    shop = post("/api/v1/entity-types", {"domain_id": domain, "name": "shop", "role": "location"})
    for type_ in (depot, shop):
        post(f"/api/v1/entity-types/{type_['id']}/attributes", {"name": "place", "data_type": "geometry"})
    at = lambda px, py: {"type": "Point", "coordinates": list(t.lonlat(px, py))}  # noqa: E731
    post("/api/v1/entities", {"entity_type_id": depot["id"], "key": "d", "attrs": {"place": at(1000, 2000)}})
    post("/api/v1/entities", {"entity_type_id": shop["id"], "key": "on_road", "attrs": {"place": at(2000, 1000)}})
    post("/api/v1/entities", {"entity_type_id": shop["id"], "key": "in_the_desert", "attrs": {"place": at(4000, 4000)}})
    fetch = t.fetch_for([({"class": "primary"}, [(1000, 2000), (3000, 2000)]),
                         ({"class": "primary"}, [(2000, 1000), (2000, 3000)])])
    real_network = roads.network
    monkeypatch.setattr(roads, "vector_source", lambda index, fetch=None: t.TEMPLATE)
    monkeypatch.setattr(roads, "network", lambda places, template, fetch_=None: real_network(places, template, fetch))
    report = post(f"/api/v1/domains/{domain}/distances",
                  {"name": "drive", "from_type_id": depot["id"], "to_type_id": shop["id"], "metric": "road"})
    values = _values(db, report["parameter_id"])
    assert values == {("d", "on_road"): pytest.approx(2 * t._units_to_m(1000), rel=0.01)}
    source = report["source"]
    assert source["metric"].startswith("road") and source["no_road"] == 1 and source["off_road"] == ["in_the_desert"]
    assert source["far"] >= 9.99 * values[("d", "on_road")]  # ten times the longest, before rounding
    timed = post(f"/api/v1/domains/{domain}/distances",
                 {"name": "drive_time", "from_type_id": depot["id"], "to_type_id": shop["id"], "metric": "time", "unit": "s"})
    assert timed["source"]["unit"] == "s" and all(v == int(v) for v in _values(db, timed["parameter_id"]).values())
    refused = client.post(f"/api/v1/domains/{domain}/distances", headers=headers,
                          json={"name": "x", "from_type_id": depot["id"], "to_type_id": shop["id"], "metric": "time", "unit": "m"})
    assert refused.status_code == 422 and "time measure is in s or min" in refused.text
