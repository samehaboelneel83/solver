"""A draft is checked, read back in words and trial-solved from the model editor, as check_spec does for the
Assistant (owner, 9 October 2026)."""
from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401

IR = {"version": 2, "sets": ["crew"], "parameters": {}, "variables": {"use": {"index": ["crew"], "domain": "binary"}},
      "constraints": [{"id": "two", "note": "At most two crews", "left": {"sum": {"var": "use", "index": ["c"]},
                       "over": [{"index": "c", "set": "crew"}]}, "relation": "<=", "right": {"const": 2},
                       "severity": "hard"}],
      "objective": {"sense": "maximize", "terms": [{"id": "size", "weight": 1, "expression": {
          "sum": {"mul": [{"attr": {"of": "c", "name": "size"}}, {"var": "use", "index": ["c"]}]},
          "over": [{"index": "c", "set": "crew"}]}}]}}


def test_a_draft_is_read_back_and_trial_solved(tenants):  # noqa: F811
    from app.main import app

    client = TestClient(app)
    built = client.post("/api/v1/problems/from-spec", headers=tenants["a"], json={
        "domain_name": f"crews {uuid4().hex[:6]}", "problem_name": "crews", "ir": IR, "seed": {
            "entity_types": [{"name": "crew", "role": "resource", "attributes": [{"name": "size", "data_type": "number"}]}],
            "entities": [{"type": "crew", "key": k, "attrs": {"size": s}} for k, s in (("A", 4), ("B", 6), ("C", 3))]}})
    assert built.status_code == 200, built.text
    problem = built.json()["problem_id"]
    url = f"/api/v1/problems/{problem}/draft-check"
    body = client.post(url, headers=tenants["a"], json={"ir": IR, "trial": True}).json()
    assert body["refusal"] is None
    assert any("two" in line for line in body["readback"])
    assert body["trial"]["status"] == "optimal" and body["trial"]["objective"] == 10
    bad = client.post(url, headers=tenants["a"], json={"ir": {**IR, "sets": ["crew", "no_such_kind"]}, "trial": True}).json()
    assert bad["refusal"]["code"] == "set_not_in_domain" and "trial" not in bad
    assert client.post(url, headers=tenants["b"], json={"ir": IR}).status_code == 404
