"""Derived map layers (benchmark round 5): buffers, service areas and places not reached, saved as map data."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from tests.test_distances import DEGREE_M, placed  # noqa: F401
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


def _layers(db, dataset_id):  # noqa: F811
    return {r.name: r.feature_count for r in db.execute(text(
        "SELECT name, feature_count FROM gis_layer WHERE dataset_id = :d"), {"d": dataset_id}).all()}


def test_a_buffer_round_each_record_is_saved_as_map_data(placed, db):  # noqa: F811
    made = placed["post"]("/api/v1/gis/derived-layers", {"domain_id": placed["domain"], "name": "sites 10 km", "how": "buffer",
                                                         "entity_type_id": placed["site"]["id"], "radius_km": 10, "keys": ["s0", "s1"]})
    assert made["made"] == 2 and made["name"] == "sites 10 km"
    assert _layers(db, made["id"]) == {"site within 10 km": 2}
    feats = placed["client"].get(f"/api/v1/gis/datasets/{made['id']}/features", headers=placed["headers"]).json()["features"]
    ring = feats[0]["geometry"]["coordinates"][0]
    xs = [p[0] for p in ring]
    # 10 km either side of the equator point: about 0.09 degrees of longitude.
    assert (max(xs) - min(xs)) * DEGREE_M / 2 == pytest.approx(10_000, rel=0.01)


def test_service_areas_and_the_places_not_reached(placed, db):  # noqa: F811
    post, domain = placed["post"], placed["domain"]
    reach = post(f"/api/v1/domains/{domain}/within", {"name": "reach", "from_type_id": placed["site"]["id"],
                                                      "to_type_id": placed["customer"]["id"], "max_m": 0.6 * DEGREE_M, "output": "parameter"})
    served = post("/api/v1/gis/derived-layers", {"domain_id": domain, "name": "served", "how": "service_area",
                                                 "entity_type_id": placed["site"]["id"], "parameter_id": reach["parameter_id"]})
    assert _layers(db, served["id"]) == {"served by each site": 2}  # s2 reaches nobody
    left = post("/api/v1/gis/derived-layers", {"domain_id": domain, "name": "left out", "how": "not_reached",
                                               "entity_type_id": placed["site"]["id"], "parameter_id": reach["parameter_id"], "keys": ["s0"]})
    assert _layers(db, left["id"]) == {"customer not reached": 2}  # c2 and c3; s0 reaches c0 and c1
    bad = placed["client"].post("/api/v1/gis/derived-layers", json={"domain_id": domain, "name": "x", "how": "buffer",
                                                                    "entity_type_id": placed["site"]["id"]}, headers=placed["headers"])
    assert bad.status_code == 422 and "radius_km" in bad.text
