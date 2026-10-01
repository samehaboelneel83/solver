"""Camp plans through the API: drawn, checked, imported, solved by the worker's lane and downloaded.

Two organizations (`tests.test_tenancy.tenants`): what A draws B can neither
see nor change.
"""

from __future__ import annotations

import io
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.camp import jobs
from app.core.db import SessionLocal
from app.main import app
from tests.camp_records import clear_camps
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


@pytest.fixture
def client(tenants):  # noqa: F811
    yield TestClient(app), tenants
    with SessionLocal() as session:
        clear_camps(session)


def _create(http, t, start="blank", name="North camp"):
    made = http.post("/api/v1/camps", json={"domain_id": t["domain_a"], "name": name, "start": start}, headers=t["a"])
    assert made.status_code == 201, made.text
    return made.json()


def test_a_blank_camp_is_ready_to_solve_and_belongs_to_its_organization_only(client):
    http, t = client
    camp = _create(http, t)
    assert camp["check"]["ok"], camp["check"]
    assert camp["problem"]["format"] == "camp-problem/1"
    assert camp["check"]["derived"]["area_m2"] == 600.0
    # The door's clear zone, worked out for the editor to draw.
    (zone,) = camp["check"]["derived"]["door_zones"]
    assert zone["door"] == "D1" and zone["area_m2"] == 6.0

    listed = http.get("/api/v1/camps", params={"domain_id": t["domain_a"]}, headers=t["a"]).json()["items"]
    assert [c["name"] for c in listed] == ["North camp"]
    assert http.get(f"/api/v1/camps/{camp['id']}", headers=t["b"]).status_code == 404
    assert http.delete(f"/api/v1/camps/{camp['id']}", headers=t["b"]).status_code == 404
    assert http.get("/api/v1/camps", params={"domain_id": t["domain_a"]}, headers=t["b"]).status_code == 404


def test_the_check_names_the_shape_at_fault(client):
    http, t = client
    camp = _create(http, t)
    problem = camp["problem"]
    bad = {**problem,
           "doors": [{"id": "D1", "a": [14, 3], "b": [16, 3]}, {"id": "D2", "a": [0, 0], "b": [1, 1]}],
           "obstacles": [{"id": "tank", "ring": [[1, 1], [3, 3], [3, 1], [1, 3]]}]}
    out = http.post("/api/v1/camps/check", json={"problem": bad}, headers=t["a"]).json()
    faults = {f["where"]: f["message"] for f in out["faults"]}
    assert not out["ok"]
    assert "not on a horizontal or vertical wall" in faults["door D1"]
    assert "not horizontal or vertical" in faults["door D2"]
    assert "crosses itself" in faults["obstacle tank"]
    junk = http.post("/api/v1/camps/check", json={"problem": {**problem, "colour": "red"}}, headers=t["a"]).json()
    assert junk["faults"][0]["message"] == "unknown field 'colour'"


def test_a_save_keeps_the_drawing_and_refuses_a_stale_version(client):
    http, t = client
    camp = _create(http, t)
    problem = camp["problem"]
    problem["obstacles"] = [{"id": "tank", "ring": [[5, 5], [7, 5], [7, 7], [5, 7]], "kind": "closed"}]
    saved = http.put(f"/api/v1/camps/{camp['id']}", json={"problem": problem, "updated_at": camp["updated_at"],
                                                          "options": {"solver": "heuristic"}}, headers=t["a"])
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["problem"]["obstacles"][0]["id"] == "tank" and body["options"]["solver"] == "heuristic"
    stale = http.put(f"/api/v1/camps/{camp['id']}", json={"name": "Again", "updated_at": camp["updated_at"]},
                     headers=t["a"])
    assert stale.status_code == 409


def test_a_drawing_and_a_workbook_import_into_the_editor(client):
    http, t = client
    camp = _create(http, t, start="small")
    dxf = http.get(f"/api/v1/camps/{camp['id']}/export", params={"format": "dxf"}, headers=t["a"])
    assert dxf.status_code == 200
    got = http.post("/api/v1/camps/import", files={"file": ("site_plan.dxf", io.BytesIO(dxf.content))},
                    headers=t["a"]).json()
    assert got["problem"]["name"] == "site plan"
    assert got["problem"]["boundary"] == camp["problem"]["boundary"]
    assert [d["id"] for d in got["problem"]["doors"]] == [d["id"] for d in camp["problem"]["doors"]]
    assert got["check"]["ok"]

    xlsx = http.get(f"/api/v1/camps/{camp['id']}/export", params={"format": "xlsx"}, headers=t["a"])
    back = http.post("/api/v1/camps/import", files={"file": ("camp.xlsx", io.BytesIO(xlsx.content))},
                     headers=t["a"]).json()
    assert back["problem"]["bed_types"] == camp["problem"]["bed_types"]
    wrong = http.post("/api/v1/camps/import", files={"file": ("plan.pdf", io.BytesIO(b"%PDF"))}, headers=t["a"])
    assert wrong.status_code == 415


def test_a_solve_runs_in_the_worker_lane_and_its_layout_downloads_as_gis(client):
    http, t = client
    camp = _create(http, t, start="small")
    asked = http.post(f"/api/v1/camps/{camp['id']}/solves", json={"solver": "heuristic"}, headers=t["a"])
    assert asked.status_code == 201, asked.text
    solve = asked.json()
    assert solve["status"] == "queued"
    again = http.post(f"/api/v1/camps/{camp['id']}/solves", json={}, headers=t["a"])
    assert again.status_code == 409

    with SessionLocal() as session:
        assert jobs.work_once(session) == solve["id"]

    done = http.get(f"/api/v1/camp-solves/{solve['id']}", headers=t["a"]).json()
    assert done["status"] == "done", done["error"]
    assert done["result"]["valid"] and done["result"]["beds"] >= 25
    layers = {f["properties"]["layer"] for f in done["result"]["output"]["features"]}
    assert {"boundary", "bed", "corridor", "door", "door_zone", "path"} <= layers
    assert any("stage 0" in line for line in done["progress"])

    wgs = http.get(f"/api/v1/camp-solves/{solve['id']}/files/output_wgs84.geojson", headers=t["a"])
    lon, lat = json.loads(wgs.content)["features"][0]["geometry"]["coordinates"][0][0]
    assert abs(lon - 31.60) < 0.01 and abs(lat - 30.10) < 0.01
    viewer = http.get(f"/api/v1/camp-solves/{solve['id']}/files/viewer.html", headers=t["a"])
    assert viewer.status_code == 200 and "/*__DATA__*/null" not in viewer.text
    assert http.get(f"/api/v1/camp-solves/{solve['id']}", headers=t["b"]).status_code == 404
    assert http.get(f"/api/v1/camp-solves/{solve['id']}/files/secrets.txt", headers=t["a"]).status_code == 404


def test_a_queued_solve_can_be_stopped_and_a_broken_camp_is_not_queued(client):
    http, t = client
    camp = _create(http, t)
    solve = http.post(f"/api/v1/camps/{camp['id']}/solves", json={}, headers=t["a"]).json()
    stopped = http.post(f"/api/v1/camp-solves/{solve['id']}/cancel", headers=t["a"]).json()
    assert stopped["status"] == "cancelled"
    with SessionLocal() as session:
        assert jobs.work_once(session) is None

    problem = {**camp["problem"], "doors": []}
    saved = http.put(f"/api/v1/camps/{camp['id']}", json={"problem": problem}, headers=t["a"]).json()
    assert not saved["check"]["ok"]
    refused = http.post(f"/api/v1/camps/{camp['id']}/solves", json={}, headers=t["a"])
    assert refused.status_code == 422 and "door" in refused.text


def test_a_camp_is_records_of_its_domain_that_the_records_pages_edit(client):
    """The camp, its doors, areas, zones and bed types are records with relationships and parameters;
    a change made on the Parameters page is what the camp reads next."""
    http, t = client
    camp = _create(http, t, start="complex", name="Records camp")
    with SessionLocal() as session:
        kinds = dict(session.execute(text(
            "SELECT t.name, count(*) FROM entity e JOIN entity_type t ON t.id = e.entity_type_id"
            " WHERE t.domain_id = :d GROUP BY t.name"), {"d": t["domain_a"]}).all())
        assert kinds["camp"] == 1 and kinds["door"] == 4 and kinds["closed_area"] == 5
        assert kinds["no_beds_area"] == 2 and kinds["bed_zone"] == 1 and kinds["bed_type"] == 2
        links = dict(session.execute(text(
            "SELECT rt.name, count(*) FROM relationship r JOIN relationship_type rt ON rt.id = r.relationship_type_id"
            " WHERE rt.domain_id = :d GROUP BY rt.name"), {"d": t["domain_a"]}).all())
        assert links["door_of"] == 4 and links["camp_uses"] == 2 and links["must_go_in"] == 1
        cap = session.execute(text(
            "SELECT d.id, v.entity_ids FROM parameter_def d JOIN parameter_value v ON v.parameter_def_id = d.id"
            " JOIN entity e ON e.id = v.entity_ids[1] WHERE d.domain_id = :dom AND d.name = 'door_capacity'"
            " AND e.label = 'D2-east'"), {"dom": t["domain_a"]}).one()
    # The door's evacuation capacity, changed on the Parameters page.
    put = http.put(f"/api/v1/parameters/{cap[0]}/values", json={"cells": [{"entity_ids": cap[1], "value": 75}]},
                   headers=t["a"])
    assert put.status_code == 200, put.text
    again = http.get(f"/api/v1/camps/{camp['id']}", headers=t["a"]).json()
    assert next(d for d in again["problem"]["doors"] if d["id"] == "D2-east")["capacity"] == 75
    # What was drawn reads back exactly: walls straight, doors on them.
    assert again["problem"]["boundary"] == camp["problem"]["boundary"]
    assert [(d["a"], d["b"]) for d in again["problem"]["doors"]] == [(d["a"], d["b"]) for d in camp["problem"]["doors"]]
    assert again["check"]["ok"]
    # Removing a closed area in the editor removes its record.
    problem = again["problem"]
    problem["obstacles"] = [o for o in problem["obstacles"] if o["id"] != "trees"]
    http.put(f"/api/v1/camps/{camp['id']}", json={"problem": problem}, headers=t["a"])
    with SessionLocal() as session:
        left = session.execute(text("SELECT count(*) FROM entity e JOIN entity_type t ON t.id = e.entity_type_id"
                                    " WHERE t.domain_id = :d AND t.name = 'closed_area'"), {"d": t["domain_a"]}).scalar_one()
    assert left == 4
    # Deleting the camp deletes its records.
    assert http.delete(f"/api/v1/camps/{camp['id']}", headers=t["a"]).status_code == 204
    with SessionLocal() as session:
        assert session.execute(text("SELECT count(*) FROM entity e JOIN entity_type t ON t.id = e.entity_type_id"
                                    " WHERE t.domain_id = :d AND t.name <> 'bed_type'"), {"d": t["domain_a"]}).scalar_one() == 0


def test_a_camp_turned_on_the_ground_keeps_its_walls_straight(client):
    """A camp on a grid turned 30° from north: stored on the Earth, read back on its own grid."""
    http, t = client
    camp = _create(http, t, start="small")
    problem = {**camp["problem"], "bearing": 30.0}
    saved = http.put(f"/api/v1/camps/{camp['id']}", json={"problem": problem}, headers=t["a"]).json()
    assert saved["problem"]["bearing"] == 30.0
    assert saved["problem"]["boundary"] == camp["problem"]["boundary"] and saved["check"]["ok"]
    with SessionLocal() as session:
        ring = session.execute(text("SELECT attrs -> 'boundary' -> 'coordinates' -> 0 FROM entity WHERE id = :i"),
                               {"i": camp["id"]}).scalar_one()
    # On the Earth the first wall (east along the grid) runs 30° clockwise from east, i.e. towards south-east.
    (lon0, lat0), (lon1, lat1) = ring[0], ring[1]
    assert lon1 > lon0 and lat1 < lat0
