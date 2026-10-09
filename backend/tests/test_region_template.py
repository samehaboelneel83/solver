"""The region_partitioning template solves: 4 zones x 2 sub-zones over a hex grid, every piece connected (GIS 8)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app.regions import REGION_PARTITIONING, SUBZONES, ZONES, ZONE_SLACK, layout
from app.showcase import ensure_showcase_templates
from app.worker import work_once
from tests.test_connected import _connected
from tests.test_quadratic import empty_queue  # noqa: F401
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


def _cells(db, domain_id: int) -> int:
    return db.execute(
        text("SELECT count(*) FROM entity e JOIN entity_type t ON t.id = e.entity_type_id"
             " WHERE t.domain_id = :d AND t.name = 'cell'"), {"d": domain_id}
    ).scalar_one()


def test_the_template_solves_with_every_zone_and_sub_zone_connected(tenants, db, empty_queue):  # noqa: F811
    client = TestClient(app)
    template_id = ensure_showcase_templates(db)[REGION_PARTITIONING]
    applied = client.post(f"/api/v1/templates/{template_id}/apply", json={"domain_name": "regions"}, headers=tenants["a"])
    assert applied.status_code == 201, applied.text
    applied = applied.json()
    built = layout()
    assert _cells(db, applied["domain_id"]) == len(built["cells"]) == 90

    # Applied again to the same domain: the seed's names are left alone, and so is its grid.
    again = client.post(f"/api/v1/templates/{template_id}/apply", json={"domain_id": applied["domain_id"], "name": "again"},
                        headers=tenants["a"])
    assert again.status_code == 201, again.text
    assert _cells(db, applied["domain_id"]) == 90

    # 120 s, not 60: alone it answers in about 50 s, and under a full test run's load it ran out of time
    # (a failure that said nothing about the template).
    run = client.post(f"/api/v1/scenarios/{applied['scenario_id']}/runs", json={"time_limit_s": 120}, headers=tenants["a"])
    assert run.status_code in (200, 201, 202), run.text
    run_id = run.json()["id"]
    for _ in range(5):
        if db.execute(text("SELECT status FROM run WHERE id = :r"), {"r": run_id}).scalar_one() not in ("queued", "running"):
            break
        work_once(db)
    solved = client.get(f"/api/v1/runs/{run_id}", headers=tenants["a"]).json()
    assert solved["status"] in ("optimal", "feasible"), (solved["status"], solved.get("error"))

    features = client.get(f"/api/v1/runs/{run_id}/map", headers=tenants["a"]).json()["features"]
    edges = [{"from": e.a, "to": e.b} for e in built["edges"]]
    assert {f["properties"]["group"] for f in features} == set(ZONES)
    assert {f["properties"]["subgroup"] for f in features} == set(SUBZONES)
    for key in ("group", "subgroup"):
        for value in {f["properties"][key] for f in features}:
            members = [f["properties"]["key"] for f in features if f["properties"][key] == value]
            assert _connected(members, edges), (key, value)
    # A sub-zone lies inside the zone it belongs to.
    assert all(f["properties"]["subgroup"].startswith(f["properties"]["group"]) for f in features)
    # And each zone holds its share of the people.
    share = built["total"] / len(ZONES)
    zones = client.get(f"/api/v1/runs/{run_id}/map?dissolve=true", headers=tenants["a"]).json()["features"]
    by_zone: dict[str, float] = {}
    for zone in zones:
        by_zone[zone["properties"]["group"]] = by_zone.get(zone["properties"]["group"], 0) + zone["properties"]["population"]
    assert all(share * (1 - ZONE_SLACK) - 1 <= people <= share * (1 + ZONE_SLACK) + 1 for people in by_zone.values()), by_zone
