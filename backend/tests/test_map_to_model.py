"""From a map file to data a model reads, inside the app (improvement plan, phases 1 and 2).

The user test had to compute drive times, "within 15 minutes", "near a hospital" and
"which district" outside the app and type them back in. This walks the same road
through the API, on a small made-up town with nothing flood-specific about it:
layers -> records with shapes -> spatial measures -> parameters and links.
"""
from __future__ import annotations

import io
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.db import SessionLocal
from app.main import app
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401

WGS84 = {"kind": "epsg", "code": 4326}


def _f(layer, geometry, **props):
    return {"type": "Feature", "properties": {"layer": layer, **props}, "geometry": geometry}


def _pt(lon, lat):
    return {"type": "Point", "coordinates": [lon, lat]}


def _box(w, s, e, n):
    return {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}


TOWN = {"type": "FeatureCollection", "features": [
    _f("ZONES", _box(30.00, 31.20, 30.02, 31.22), name="North"),
    _f("ZONES", _box(30.02, 31.20, 30.04, 31.22), name="South"),
    _f("DEPOTS", _pt(30.001, 31.201), name="D1", capacity=4),
    _f("DEPOTS", _pt(30.039, 31.201), name="D2", capacity=6),
    _f("SITES", _pt(30.005, 31.205), name="S1", risk=3),
    _f("SITES", _pt(30.030, 31.205), name="S2", risk=9),
    _f("SITES", _pt(30.035, 31.215), name="S3", risk=5),
    _f("CLINICS", _pt(30.0302, 31.2052), name="C1"),
    # One straight road along 31.201 at 60 km/h, then up the east side at 20 km/h.
    _f("ROADS", {"type": "LineString", "coordinates": [[30.0, 31.201], [30.02, 31.201], [30.04, 31.201]]}, speed=60,
       speed_am=30),
    _f("ROADS", {"type": "LineString", "coordinates": [[30.04, 31.201], [30.04, 31.215]]}, speed=20, speed_am=10),
]}


@pytest.fixture
def town(tenants, db):  # noqa: F811
    http, t = TestClient(app), tenants
    up = http.post("/api/v1/gis/uploads", files={"file": ("town.geojson", io.BytesIO(json.dumps(TOWN).encode()))},
                   data={"domain_id": str(t["domain_a"])}, headers=t["a"])
    assert up.status_code == 201, up.text
    ds = http.post("/api/v1/gis/datasets", json={"upload_id": up.json()["upload_id"], "domain_id": t["domain_a"],
                                                  "name": "Town", "placement": WGS84}, headers=t["a"])
    assert ds.status_code == 201, ds.text
    yield http, t, ds.json()
    with SessionLocal() as session:
        session.execute(text("DELETE FROM gis_dataset"))
        session.execute(text("DELETE FROM gis_upload"))
        session.commit()


def _make(http, t, ds, layer, **edit):
    plan = http.post(f"/api/v1/gis/datasets/{ds['id']}/records/propose", json={"layers": [layer]}, headers=t["a"])
    assert plan.status_code == 200, plan.text
    body = {**plan.json(), **edit}
    made = http.post(f"/api/v1/gis/datasets/{ds['id']}/records", json={"layers": [layer], "plan": body}, headers=t["a"])
    assert made.status_code == 201, made.text
    return plan.json(), made.json()


def test_layers_become_records_with_shapes_fields_and_measures(town, db):  # noqa: F811
    http, t, ds = town
    plan, made = _make(http, t, ds, "DEPOTS")
    assert plan["name"] == "depot" and plan["key"] == "name"
    # The key is listed too, left out (benchmark, October 2026: a changed key kept the old one as a field).
    assert {f["name"]: f["data_type"] for f in plan["fields"] if not f["skip"]} == {"capacity": "integer"}
    assert made["made"] == 2 and made["updated"] == 0
    rows = dict(db.execute(text("SELECT e.key, e.attrs FROM entity e WHERE e.entity_type_id = :t"),
                           {"t": made["entity_type_id"]}).all())
    assert rows["D2"]["capacity"] == 6 and rows["D2"]["shape"] == _pt(30.039, 31.201)
    _, zones = _make(http, t, ds, "ZONES")
    area = db.execute(text("SELECT (attrs->>'area_m2')::float FROM entity WHERE entity_type_id = :t AND key = 'North'"),
                      {"t": zones["entity_type_id"]}).scalar_one()
    assert 3_500_000 < area < 4_500_000  # about 1.9 km x 2.2 km
    # Again: nothing new, the existing records refreshed by key.
    _, again = _make(http, t, ds, "DEPOTS")
    assert again["made"] == 0 and again["updated"] == 2
    # Another organization cannot read the layers.
    assert http.post(f"/api/v1/gis/datasets/{ds['id']}/records/propose", json={"layers": ["DEPOTS"]},
                     headers=t["b"]).status_code == 404


def test_shapes_attach_to_records_that_came_from_a_spreadsheet(town, db):  # noqa: F811
    http, t, ds = town
    kind = http.post("/api/v1/entity-types", json={"domain_id": t["domain_a"], "name": "site"}, headers=t["a"]).json()
    for key in ("S1", "S2", "S9"):
        assert http.post("/api/v1/entities", json={"entity_type_id": kind["id"], "key": key}, headers=t["a"]).status_code == 201
    got = http.post(f"/api/v1/gis/datasets/{ds['id']}/records/attach",
                    json={"layers": ["SITES"], "type": "site", "match": "name"}, headers=t["a"])
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["attached"] == 2 and body["records_without_shape"] == ["S9"] and body["unmatched_features"] == ["S3"]


def test_spatial_measures_are_written_as_data_a_model_reads(town, db):  # noqa: F811
    http, t, ds = town
    _, depots = _make(http, t, ds, "DEPOTS")
    _, sites = _make(http, t, ds, "SITES")
    _, zones = _make(http, t, ds, "ZONES")
    _, clinics = _make(http, t, ds, "CLINICS")
    d = t["domain_a"]

    def post(path, body):
        got = http.post(f"/api/v1/domains/{d}/{path}", json=body, headers=t["a"])
        assert got.status_code == 201, got.text
        return got.json()

    inside = post("spatial/inside", {"name": "zone_of", "from_type_id": sites["entity_type_id"], "to_type_id": zones["entity_type_id"]})
    pairs = dict(db.execute(text("SELECT a.key, b.key FROM relationship r JOIN entity a ON a.id = r.from_entity_id"
                                 " JOIN entity b ON b.id = r.to_entity_id WHERE r.relationship_type_id = :r"),
                            {"r": inside["relationship_type_id"]}).all())
    assert pairs == {"S1": "North", "S2": "South", "S3": "South"}

    count = post("spatial/count", {"name": "clinics_300m", "from_type_id": sites["entity_type_id"],
                                   "to_type_id": clinics["entity_type_id"], "max_m": 300})
    assert count["with_any"] == 1
    near = dict(db.execute(text("SELECT key, (attrs->>'clinics_300m')::int FROM entity WHERE entity_type_id = :t"),
                           {"t": sites["entity_type_id"]}).all())
    assert near == {"S1": 0, "S2": 1, "S3": 0}

    nearest = post("spatial/nearest", {"name": "closest_depot", "from_type_id": sites["entity_type_id"],
                                       "to_type_id": depots["entity_type_id"], "k": 1})
    assert nearest["links"] == 3

    touching = post("spatial/touching", {"name": "next_to", "type_id": zones["entity_type_id"]})
    assert touching["links"] == 2

    # "Within 4 minutes along my own roads", as a 0/1 parameter a rule multiplies by.
    reach = post("within", {"name": "reach", "from_type_id": depots["entity_type_id"], "to_type_id": sites["entity_type_id"],
                            "metric": "network_time", "max_min": 4, "output": "parameter",
                            "network": {"dataset_id": ds["id"], "layer": "ROADS", "speed_field": "speed", "default_kmh": 30}})
    ones = {(a, b) for a, b in db.execute(text(
        "SELECT a.key, b.key FROM parameter_value pv JOIN entity a ON a.id = pv.entity_ids[1]"
        " JOIN entity b ON b.id = pv.entity_ids[2] WHERE pv.parameter_def_id = :p AND pv.value = 1"),
        {"p": reach["parameter_id"]}).all()}
    assert ("D1", "S1") in ones and ("D2", "S2") in ones and ("D1", "S3") not in ones
    assert reach["source"]["metric"].startswith("along layer 'ROADS'")

    minutes = post("distances", {"name": "drive_min", "from_type_id": depots["entity_type_id"],
                                 "to_type_id": sites["entity_type_id"], "metric": "network_time", "unit": "min",
                                 "network": {"dataset_id": ds["id"], "layer": "ROADS", "speed_field": "speed"}})
    assert minutes["pairs"] == 6


def test_a_spreadsheet_with_longitude_and_latitude_makes_places(tenants, db):  # noqa: F811
    http, t = TestClient(app), tenants
    csv_file = "yard_id,lon,lat,max_trucks\nY1,29.90,31.18,6\nY2,29.94,31.18,12\n"
    files = {"file": ("yards.csv", io.BytesIO(csv_file.encode()), "text/csv")}
    proposal = http.post(f"/api/v1/domains/{t['domain_a']}/spreadsheet/propose", files=files, headers=t["a"])
    assert proposal.status_code == 200, proposal.text
    kind = proposal.json()["kinds"][0]
    assert kind["location"] == {"name": "location", "lon": "lon", "lat": "lat", "wkt": None, "skip": False}
    made = http.post(f"/api/v1/domains/{t['domain_a']}/spreadsheet/import",
                     files={"file": ("yards.csv", io.BytesIO(csv_file.encode()), "text/csv")},
                     data={"proposal": json.dumps(proposal.json())}, headers=t["a"])
    assert made.status_code == 200, made.text
    shape = db.execute(text("SELECT e.attrs->'location' FROM entity e JOIN entity_type k ON k.id = e.entity_type_id"
                            " WHERE k.domain_id = :d AND k.name = 'yard' AND e.key = 'Y2'"), {"d": t["domain_a"]}).scalar_one()
    assert shape == {"type": "Point", "coordinates": [29.94, 31.18]}


def test_roads_cross_zones_and_stand_in_for_road_tiles(town, db):  # noqa: F811
    """Benchmark, October 2026: which zones a road passes through, and road distances with no
    road tiles set -- the workspace's own roads are used, and the source says so."""
    http, t, ds = town
    _, roads = _make(http, t, ds, "ROADS")
    _, zones = _make(http, t, ds, "ZONES")
    _, depots = _make(http, t, ds, "DEPOTS")
    _, sites = _make(http, t, ds, "SITES")
    d = t["domain_a"]
    got = http.post(f"/api/v1/domains/{d}/spatial/crosses", json={"name": "passes_through", "from_type_id": roads["entity_type_id"],
                                                                 "to_type_id": zones["entity_type_id"]}, headers=t["a"])
    assert got.status_code == 201, got.text
    crossed = sorted((b, m) for b, m in db.execute(text(
        "SELECT b.key, (r.attrs->>'metres')::float FROM relationship r"
        " JOIN entity b ON b.id = r.to_entity_id WHERE r.relationship_type_id = :r"), {"r": got.json()["relationship_type_id"]}).all())
    # The long road runs ~1.9 km through each zone; the short one ~1.6 km up the south's outer edge.
    assert [b for b, _ in crossed] == ["North", "South", "South"]
    assert 1800 < crossed[0][1] < 2000 and sorted(round(m, -2) for _, m in crossed[1:]) == [1600.0, 1900.0]
    refused = http.post(f"/api/v1/domains/{d}/spatial/crosses", json={"name": "x", "from_type_id": zones["entity_type_id"],
                                                                     "to_type_id": zones["entity_type_id"]}, headers=t["a"])
    assert refused.status_code == 422 and "line" in refused.text

    road = http.post(f"/api/v1/domains/{d}/distances", json={"name": "road_m", "from_type_id": depots["entity_type_id"],
                                                             "to_type_id": sites["entity_type_id"], "metric": "road"}, headers=t["a"])
    assert road.status_code == 201, road.text
    assert road.json()["source"]["metric"].startswith("along layer 'ROADS'")
    assert "no road tiles are set" in road.json()["source"]["note"]


def test_travel_times_by_period_read_each_period_s_speeds_or_scale_them(town, db):  # noqa: F811
    """Benchmark re-test, October 2026: road speeds differ by period (the morning peak)."""
    http, t, ds = town
    _, depots = _make(http, t, ds, "DEPOTS")
    _, sites = _make(http, t, ds, "SITES")
    d = t["domain_a"]
    slot = http.post("/api/v1/entity-types", json={"domain_id": d, "name": "slot"}, headers=t["a"]).json()
    for name, data_type in (("speeds", "text"), ("factor", "number")):
        got = http.post(f"/api/v1/entity-types/{slot['id']}/attributes", json={"name": name, "data_type": data_type}, headers=t["a"])
        assert got.status_code == 201, got.text
    for key, speeds, factor in (("am", "speed_am", 0.5), ("night", "speed", 1)):
        got = http.post("/api/v1/entities", json={"entity_type_id": slot["id"], "key": key, "attrs": {"speeds": speeds, "factor": factor}},
                        headers=t["a"])
        assert got.status_code == 201, got.text
    network = {"dataset_id": ds["id"], "layer": "ROADS", "speed_field": "speed"}
    ask = {"from_type_id": depots["entity_type_id"], "to_type_id": sites["entity_type_id"], "metric": "network_time", "unit": "min",
           "network": network}

    def minutes(name, by):
        got = http.post(f"/api/v1/domains/{d}/distances", json={"name": name, **ask, "by_period": {"type_id": slot["id"], **by}},
                        headers=t["a"])
        assert got.status_code == 201, got.text
        rows = db.execute(text(
            "SELECT a.key, b.key, p.key, pv.value FROM parameter_value pv JOIN parameter_def pd ON pd.id = pv.parameter_def_id"
            " JOIN entity a ON a.id = pv.entity_ids[1] JOIN entity b ON b.id = pv.entity_ids[2] JOIN entity p ON p.id = pv.entity_ids[3]"
            " WHERE pd.name = :n"), {"n": name}).all()
        return got.json(), {(a, b, p): float(v) for a, b, p, v in rows}

    report, by_speeds = minutes("drive_by_slot", {"speed_field_from": "speeds"})
    assert report["pairs"] == 12 and report["source"]["by_period"] == {"kind": "slot", "speed_field_from": "speeds", "periods": 2}

    def plain(name, speed_field):
        got = http.post(f"/api/v1/domains/{d}/distances", json={"name": name, **ask, "network": {**network, "speed_field": speed_field}},
                        headers=t["a"])
        assert got.status_code == 201, got.text
        return {(a, b): float(v) for a, b, v in db.execute(text(
            "SELECT a.key, b.key, pv.value FROM parameter_value pv JOIN parameter_def pd ON pd.id = pv.parameter_def_id"
            " JOIN entity a ON a.id = pv.entity_ids[1] JOIN entity b ON b.id = pv.entity_ids[2] WHERE pd.name = :n"), {"n": name}).all()}

    # Each period reads the roads at its own speeds: the morning as a plain measure at speed_am, the night at speed.
    # (The short way from a place to the nearest road is at the default speed in every period.)
    am, night = plain("drive_am", "speed_am"), plain("drive_night", "speed")
    assert {(a, b): v for (a, b, p), v in by_speeds.items() if p == "am"} == am
    assert {(a, b): v for (a, b, p), v in by_speeds.items() if p == "night"} == night
    assert all(am[k] > night[k] for k in am if night[k] > 0)
    # A factor scales the whole time: half the speed, twice the minutes.
    _, by_factor = minutes("drive_by_factor", {"factor_from": "factor"})
    assert {(a, b): v for (a, b, p), v in by_factor.items() if p == "am"} == pytest.approx({k: 2 * v for k, v in night.items()}, abs=0.11)
    # Within reach by period is a 0/1 parameter over [from, to, period].
    reach = http.post(f"/api/v1/domains/{d}/within", json={"name": "reach_by_slot", **{k: v for k, v in ask.items() if k != "unit"},
                                                           "max_min": 4, "output": "parameter",
                                                           "by_period": {"type_id": slot["id"], "factor_from": "factor"}}, headers=t["a"])
    assert reach.status_code == 201, reach.text
    within = {k for k, v in by_factor.items() if v <= 4}
    assert reach.json()["edges"] == len(within) and 0 < len(within) < 12
    refused = http.post(f"/api/v1/domains/{d}/within", json={"name": "reach_links", **{k: v for k, v in ask.items() if k != "unit"},
                                                             "max_min": 4, "by_period": {"type_id": slot["id"], "factor_from": "factor"}},
                        headers=t["a"])
    assert refused.status_code == 422 and "output parameter" in refused.text


def test_travel_times_read_a_speed_kept_on_the_road_records(town, db):  # noqa: F811
    """Benchmark round 4: a speed computed on the road records (weather) was ignored, every road at the
    default 30 km/h, and a field of no name at all gave the same times without a word."""
    http, t, ds = town
    _, depots = _make(http, t, ds, "DEPOTS")
    _, sites = _make(http, t, ds, "SITES")
    _, roads = _make(http, t, ds, "ROADS")
    d = t["domain_a"]
    got = http.post(f"/api/v1/entity-types/{roads['entity_type_id']}/attributes", json={"name": "storm_kmh", "data_type": "number"},
                    headers=t["a"])
    assert got.status_code == 201, got.text
    db.execute(text("UPDATE entity SET attrs = attrs || jsonb_build_object('storm_kmh', (attrs->>'speed_am')::float / 2)"
                    " WHERE entity_type_id = :t"), {"t": roads["entity_type_id"]})
    db.commit()
    ask = {"from_type_id": depots["entity_type_id"], "to_type_id": sites["entity_type_id"], "metric": "network_time", "unit": "min"}

    def minutes(name, speed_field):
        got = http.post(f"/api/v1/domains/{d}/distances", json={"name": name, **ask,
                        "network": {"dataset_id": ds["id"], "layer": "ROADS", "speed_field": speed_field}}, headers=t["a"])
        return got

    calm = minutes("calm_min", "speed_am")
    storm = minutes("storm_min", "storm_kmh")
    assert calm.status_code == 201 and storm.status_code == 201, storm.text
    assert storm.json()["source"]["fields_from_records"] == {"storm_kmh": "road"}
    values = {name: dict(db.execute(text(
        "SELECT pv.entity_ids::text, pv.value FROM parameter_value pv JOIN parameter_def pd ON pd.id = pv.parameter_def_id"
        " WHERE pd.name = :n"), {"n": name}).all()) for name in ("calm_min", "storm_min")}
    assert all(float(values["storm_min"][k]) > float(v) for k, v in values["calm_min"].items() if float(v) > 0.5)
    wrong = minutes("nowhere_min", "no_such_speed")
    assert wrong.status_code == 422 and "no_such_speed" in wrong.text


def test_a_cost_follows_the_roads_per_km_and_with_tolls(town, db):  # noqa: F811
    """Benchmark round 5: transport cost per pallet-km and tolls in the road table could not be summed
    along each path; one flat rate was used."""
    http, t, ds = town
    _, depots = _make(http, t, ds, "DEPOTS")
    _, sites = _make(http, t, ds, "SITES")
    d = t["domain_a"]
    ask = {"from_type_id": depots["entity_type_id"], "to_type_id": sites["entity_type_id"]}

    def made(name, metric, unit, network):
        got = http.post(f"/api/v1/domains/{d}/distances", json={"name": name, **ask, "metric": metric, "unit": unit,
                        "network": {"dataset_id": ds["id"], "layer": "ROADS", **network}}, headers=t["a"])
        assert got.status_code == 201, got.text
        return {k: float(v) for k, v in db.execute(text(
            "SELECT pv.entity_ids::text, pv.value FROM parameter_value pv JOIN parameter_def pd ON pd.id = pv.parameter_def_id"
            " WHERE pd.name = :n"), {"n": name}).all()}, got.json()["source"]

    km, _ = made("road_km", "network", "km", {})
    per_km, _ = made("cost_flat", "network_cost", "cost", {"default_cost_per_km": 2.0})
    # At 2 a km everywhere, the cheapest path is the shortest: twice its kilometres.
    assert all(abs(per_km[k] - 2 * v) <= 0.02 * max(1.0, 2 * v) for k, v in km.items())
    tolled, source = made("cost_tolled", "network_cost", "cost", {"default_cost_per_km": 2.0, "toll_field": "speed_am"})
    assert source["toll_by"] == "speed_am"
    assert all(tolled[k] >= per_km[k] - 1e-6 for k in per_km) and any(tolled[k] > per_km[k] + 1 for k in per_km)
