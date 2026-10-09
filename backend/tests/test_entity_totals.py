"""Exact counts and totals over records, grouped by a field, without the Assistant (owner, 9 October 2026)."""
from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


def test_records_are_counted_and_added_up_by_group(tenants):  # noqa: F811
    from app.main import app

    client = TestClient(app)
    built = client.post("/api/v1/problems/from-spec", headers=tenants["a"], json={
        "domain_name": f"wards {uuid4().hex[:6]}", "problem_name": "beds", "ir": {
            "version": 2, "sets": ["ward"], "parameters": {}, "variables": {"x": {"index": ["ward"], "domain": "binary"}},
            "constraints": [{"id": "c", "left": {"sum": {"var": "x", "index": ["w"]}, "over": [{"index": "w", "set": "ward"}]},
                             "relation": "<=", "right": {"const": 1}, "severity": "hard"}]},
        "seed": {"entity_types": [{"name": "ward", "role": "location", "attributes": [
            {"name": "site", "data_type": "text"}, {"name": "beds", "data_type": "integer"}]}],
            "entities": [{"type": "ward", "key": k, "attrs": a} for k, a in (
                ("w1", {"site": "North", "beds": 10}), ("w2", {"site": "North", "beds": 14}),
                ("w3", {"site": "South", "beds": 8}))]}})
    assert built.status_code == 200, built.text
    domain = built.json()["domain_id"]
    ward = next(t for t in client.get(f"/api/v1/entity-types?domain_id={domain}", headers=tenants["a"]).json()["items"]
                if t["name"] == "ward")
    url = f"/api/v1/entity-types/{ward['id']}/totals"
    got = client.get(url, params={"by": "site", "sum": "beds"}, headers=tenants["a"]).json()
    assert got["groups"] == [{"group": "North", "rows": 2, "sums": {"beds": 24.0}},
                             {"group": "South", "rows": 1, "sums": {"beds": 8.0}}]
    assert got["total"] == {"rows": 3, "beds": 32.0}
    assert client.get(url, params={"sum": "site"}, headers=tenants["a"]).status_code == 422
    assert client.get(url, params={"by": "nope"}, headers=tenants["a"]).status_code == 422
    assert client.get(url, headers=tenants["b"]).status_code == 404
