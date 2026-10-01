"""A camp from map data: a CAD drawing imported as GIS layers (nothing camp-specific about
the import), then a camp built from the layers a person points at, laid out and valid."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.camp import jobs
from app.camp.engine import camp_layout  # noqa: F401 -- the engine on the path
from app.core.db import SessionLocal
from app.main import app
from tests.cad_fixtures import E0, N0
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


@pytest.fixture
def client(tenants):  # noqa: F811
    yield TestClient(app), tenants
    with SessionLocal() as session:
        session.execute(text("DELETE FROM camp_plan"))
        session.execute(text("DELETE FROM gis_dataset"))
        session.commit()


def _surveyed_camp(path) -> None:
    """The small example camp as a surveyed drawing in UTM 36N, its door drawn as a gate block."""
    import ezdxf
    from camp_layout.dxf import write_dxf
    from camp_layout.examples import small_camp

    write_dxf(small_camp(), str(path))
    doc = ezdxf.readfile(str(path))
    msp = doc.modelspace()
    for e in list(msp):
        if e.dxf.layer == "DOORS" and e.dxftype() == "LINE":
            (a, b) = e.dxf.start, e.dxf.end
            msp.delete_entity(e)
    gate = doc.blocks.new("GATE")
    gate.add_line((0, 0), (b.x - a.x, 0))
    gate.add_arc((0, 0), b.x - a.x, 0, 90)
    msp.add_blockref("GATE", (a.x, a.y), dxfattribs={"layer": "DOORS"})
    for e in msp:
        e.translate(E0, N0, 0)
    doc.saveas(path)


def test_a_camp_is_built_from_any_imported_drawings_layers(client, tmp_path):
    http, t = client
    _surveyed_camp(tmp_path / "camp.dxf")
    up = http.post("/api/v1/gis/uploads", files={"file": ("camp.dxf", io.BytesIO((tmp_path / "camp.dxf").read_bytes()))},
                   data={"domain_id": str(t["domain_a"])}, headers=t["a"]).json()
    ds = http.post("/api/v1/gis/datasets", json={"upload_id": up["upload_id"], "domain_id": t["domain_a"], "name": "Camp drawing",
                                                  "placement": {"kind": "epsg", "code": 32636}}, headers=t["a"]).json()
    layer = {l["name"]: l["id"] for l in ds["layers"]}
    made = http.post("/api/v1/camps/from-map", json={
        "domain_id": t["domain_a"], "name": "From the map", "dataset_id": ds["id"], "boundary": layer["CAMP_BOUNDARY"],
        "doors": [layer["DOORS"]], "obstacles": [layer["OBSTACLES"]]}, headers=t["a"])
    assert made.status_code == 201, made.text
    camp = made.json()
    p = camp["problem"]
    # The drawing's own grid, from the boundary's corner: the small camp is 14 x 9 m.
    xs = [q[0] for q in p["boundary"]]
    ys = [q[1] for q in p["boundary"]]
    assert (min(xs), min(ys), max(xs), max(ys)) == (0, 0, 14, 9)
    # The gate block (a leaf and its swing arc) is one door, on the south wall.
    (door,) = p["doors"]
    assert door["a"][1] == door["b"][1] == 0 and door["b"][0] - door["a"][0] == pytest.approx(1.5, abs=0.01)
    assert [o["id"] for o in p["obstacles"]] == ["pillar"]
    lon, lat = p["origin_lonlat"]
    assert 31 < lon < 32.5 and 29.5 < lat < 31
    assert camp["check"]["ok"], camp["check"]["faults"]
    # Laid out like any camp.
    solve = http.post(f"/api/v1/camps/{camp['id']}/solves", json={"solver": "heuristic"}, headers=t["a"]).json()
    with SessionLocal() as session:
        jobs.work_once(session)
    done = http.get(f"/api/v1/camp-solves/{solve['id']}", headers=t["a"]).json()
    assert done["status"] == "done" and done["result"]["valid"] and done["result"]["beds"] >= 25
    # Layers of another dataset, or none for the boundary, are refused.
    bad = http.post("/api/v1/camps/from-map", json={"domain_id": t["domain_a"], "name": "x", "dataset_id": ds["id"],
                                                     "boundary": 999999}, headers=t["a"])
    assert bad.status_code == 422
