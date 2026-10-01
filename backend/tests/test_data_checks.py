"""GET /api/v1/domains/{id}/data-checks: loops, depth, records outside the tree, and reference
fields that point at switched-off records or are left empty."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.data_checks import depths, loops
from app.main import app
from tests.test_api_relationships import (  # noqa: F401
    _entity, _rel_id, auth_headers, domain_id, ensure_admin_seeded, hierarchy_type_id, types,
)

client = TestClient(app)


def _checks(domain, headers, **params):
    got = client.get(f"/api/v1/domains/{domain}/data-checks", params=params, headers=headers)
    assert got.status_code == 200, got.text
    return got.json()["findings"]


def test_loops_are_found_however_long_and_a_tree_has_none():
    assert loops([(1, 2), (2, 3), (3, 1), (3, 4)]) == [[1, 2, 3]]
    assert loops([(5, 5)]) == [[5]]
    assert loops([(1, 2), (1, 3), (2, 4)]) == []
    chain = [(i, i + 1) for i in range(20_000)] + [(20_000, 0)]
    assert len(loops(chain)[0]) == 20_001  # no recursion limit on a long chain
    assert depths({2: [1], 3: [2], 4: [1]}, {1, 2, 3, 4}) == {1: 0, 2: 1, 4: 1, 3: 2}


def test_a_hierarchy_too_deep_and_records_left_outside_it(auth_headers, domain_id, types, hierarchy_type_id):  # noqa: F811
    unit = types["unit"]
    chain = [_entity(client, auth_headers, unit, f"u{i}") for i in range(5)]
    for parent, child in zip(chain, chain[1:]):
        _rel_id(client, auth_headers, hierarchy_type_id, parent, child)
    _entity(client, auth_headers, unit, "stray")

    found = {f["code"]: f for f in _checks(domain_id, auth_headers, max_depth=2)}
    assert set(found) == {"too_deep", "outside_tree"}
    assert [r["key"] for r in found["too_deep"]["records"]] == ["u3", "u4"]
    assert found["too_deep"]["severity"] == "warning" and "deepest is 4" in found["too_deep"]["says"]
    assert [r["key"] for r in found["outside_tree"]["records"]] == ["stray"]
    assert {f["code"] for f in _checks(domain_id, auth_headers, max_depth=10)} == {"outside_tree"}


def test_reference_loops_switched_off_targets_and_empty_references(auth_headers, domain_id, types):  # noqa: F811
    employee = types["employee"]
    made = client.post(f"/api/v1/entity-types/{employee}/attributes",
                       json={"name": "manager", "data_type": "reference", "target_type_id": employee}, headers=auth_headers)
    assert made.status_code == 201, made.text
    a = _entity(client, auth_headers, employee, "a")
    _entity(client, auth_headers, employee, "b", attrs={"manager": "a"})
    _entity(client, auth_headers, employee, "c")
    _entity(client, auth_headers, employee, "gone", active=False)
    _entity(client, auth_headers, employee, "d", attrs={"manager": "gone"})
    assert client.patch(f"/api/v1/entities/{a}", json={"attrs": {"manager": "b"}}, headers=auth_headers).status_code == 200

    findings = _checks(domain_id, auth_headers)
    assert [f["severity"] for f in findings] == sorted((f["severity"] for f in findings),
                                                       key=["error", "warning", "info"].index)
    found = {f["code"]: f for f in findings}
    assert [r["key"] for r in found["loop"]["records"]] == ["a", "b"] and found["loop"]["attribute"] == "manager"
    assert [r["key"] for r in found["inactive_target"]["records"]] == ["d"]
    assert [r["key"] for r in found["empty_reference"]["records"]] == ["c"]


def test_an_unknown_domain_is_404(auth_headers):  # noqa: F811
    assert client.get("/api/v1/domains/999999999/data-checks", headers=auth_headers).status_code == 404
