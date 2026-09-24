"""A geometry attribute: validated on write, stored as given, refused by arithmetic (GIS 1, migration 0049)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app.spatial.geometry import MAX_VERTICES, validate_geometry
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db, make_domain, make_entity_type  # noqa: F401

SQUARE = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}


@pytest.mark.parametrize(
    "value, fault",
    [
        (SQUARE, None),
        ({"type": "Point", "coordinates": [31.2, 30.0]}, None),
        ({"type": "MultiPolygon", "coordinates": [SQUARE["coordinates"]]}, None),
        ({"type": "LineString", "coordinates": [[0, 0], [1, 1]]}, "a geometry is a Point, Polygon or MultiPolygon, not LineString"),
        ({"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0.5]]]},
         "ring 0 is not closed: it starts at [0, 0] and ends at [0, 0.5]"),
        ({"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [0, 0]]]},
         "ring 0 has 3 positions; a ring needs at least 4 (the first repeated last)"),
        ({"type": "Point", "coordinates": [200, 0]}, "position [200, 0] is outside longitude -180..180 or latitude -90..90"),
        ({"type": "Point", "coordinates": ["a", 0]}, "position ['a', 0] is not two numbers"),
        ({"type": "Point", "coordinates": [True, 0]}, "position [True, 0] is not two numbers"),
        ("POLYGON((0 0,1 0,1 1,0 0))", "a geometry is a GeoJSON object, not text"),
    ],
)
def test_each_fault_is_named(value, fault):
    assert validate_geometry(value) == fault


def test_too_many_vertices_is_refused_with_the_count():
    ring = [[i * 1e-6, 0] for i in range(MAX_VERTICES)] + [[0, 1e-3], [0, 0]]
    assert validate_geometry({"type": "Polygon", "coordinates": [ring]}) == (
        f"this geometry has {MAX_VERTICES + 2} positions; the limit is {MAX_VERTICES}"
    )


def test_the_database_accepts_a_geometry_and_refuses_text_for_one(db):  # noqa: F811
    domain = make_domain(db, "geo")
    area = make_entity_type(db, domain, "area", "other")
    db.execute(text("INSERT INTO attribute_def (entity_type_id, name, data_type) VALUES (:t, 'shape', 'geometry')"), {"t": area})
    db.execute(
        text("INSERT INTO entity (entity_type_id, key, attrs) VALUES (:t, 'a', CAST(:g AS jsonb))"),
        {"t": area, "g": '{"shape": {"type": "Point", "coordinates": [31, 30]}}'},
    )
    db.commit()
    with pytest.raises(Exception, match='attribute "shape" must be geometry'):
        db.execute(
            text("INSERT INTO entity (entity_type_id, key, attrs) VALUES (:t, 'b', CAST(:g AS jsonb))"),
            {"t": area, "g": '{"shape": "POINT(31 30)"}'},
        )
    db.rollback()
    db.execute(text("DELETE FROM domain WHERE id = :d"), {"d": domain})
    db.commit()


def test_the_api_names_a_bad_ring_and_keeps_a_good_shape(tenants, db):  # noqa: F811
    client = TestClient(app)
    headers = tenants["a"]
    domain = tenants["domain_a"]
    area = client.post("/api/v1/entity-types", json={"domain_id": domain, "name": "area"}, headers=headers)
    assert area.status_code == 201, area.text
    area_id = area.json()["id"]
    made = client.post(f"/api/v1/entity-types/{area_id}/attributes", json={"name": "shape", "data_type": "geometry"},
                       headers=headers)
    assert made.status_code == 201, made.text
    open_ring = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0.5]]]}
    refused = client.post("/api/v1/entities", json={"entity_type_id": area_id, "key": "a", "attrs": {"shape": open_ring}},
                          headers=headers)
    assert refused.status_code == 422
    detail = refused.json()["detail"][0]
    assert detail["loc"] == ["body", "attrs", "shape"] and "ring 0 is not closed" in detail["msg"]
    kept = client.post("/api/v1/entities", json={"entity_type_id": area_id, "key": "b", "attrs": {"shape": SQUARE}},
                       headers=headers)
    assert kept.status_code == 201 and kept.json()["attrs"]["shape"] == SQUARE
    patched = client.patch(f"/api/v1/entities/{kept.json()['id']}", json={"attrs": {"shape": open_ring}}, headers=headers)
    assert patched.status_code == 422


def test_a_geometry_is_not_a_number_to_the_ir(db):  # noqa: F811
    """Review Focus 5: geometry refused by arithmetic and filters, as text is."""
    from app.ir.validate import validate_ir

    domain = make_domain(db, "geo-ir")
    area = make_entity_type(db, domain, "area", "other")
    db.execute(text("INSERT INTO attribute_def (entity_type_id, name, data_type) VALUES (:t, 'shape', 'geometry')"), {"t": area})
    db.commit()
    x = {"var": "x", "index": ["a"]}
    over = [{"index": "a", "set": "area"}]
    ir = {"version": 2, "sets": ["area"], "parameters": {}, "variables": {"x": {"index": ["area"], "domain": "binary"}},
          "constraints": [], "objective": {"sense": "maximize", "terms": [{"id": "o", "weight": 1, "expression":
              {"sum": {"mul": [{"attr": {"of": "a", "name": "shape"}}, x]}, "over": over}}]}}
    assert validate_ir(db, domain, ir).code == "attribute_not_arithmetic"
    ir["objective"]["terms"][0]["expression"] = {"sum": x, "over": [{**over[0], "where": [{"attr": "shape", "op": "=", "value": "x"}]}]}
    assert validate_ir(db, domain, ir).code == "where_operator_not_offered"
    db.execute(text("DELETE FROM domain WHERE id = :d"), {"d": domain})
    db.commit()
