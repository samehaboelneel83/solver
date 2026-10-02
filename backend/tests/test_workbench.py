"""The data workbench's tree, read from the model: region > (region) > depot > truck, plus employees
whose home depot is optional, and a demand value per depot."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.test_api_relationships import _entity, auth_headers, domain_id, ensure_admin_seeded  # noqa: F401

client = TestClient(app)


def _kind(headers, domain, name, fields=()):
    made = client.post("/api/v1/entity-types", json={"domain_id": domain, "name": name, "role": "location"}, headers=headers)
    assert made.status_code == 201, made.text
    kind = made.json()["id"]
    for field in fields:
        field = {**field, "target_type_id": kind} if field.get("target_type_id") == "self" else field
        got = client.post(f"/api/v1/entity-types/{kind}/attributes", json=field, headers=headers)
        assert got.status_code == 201, got.text
    return kind


@pytest.fixture
def world(auth_headers, domain_id):  # noqa: F811
    region = _kind(auth_headers, domain_id, "region", [{"name": "parent", "data_type": "reference", "target_type_id": "self"}])
    depot = _kind(auth_headers, domain_id, "depot", [{"name": "region", "data_type": "reference", "target_type_id": region, "required": True}])
    truck = _kind(auth_headers, domain_id, "truck", [{"name": "depot", "data_type": "reference", "target_type_id": depot, "required": True}])
    staff = _kind(auth_headers, domain_id, "staff", [{"name": "home", "data_type": "reference", "target_type_id": depot}])
    ids = {"egypt": _entity(client, auth_headers, region, "egypt"),
           "cairo": _entity(client, auth_headers, region, "cairo", attrs={"parent": "egypt"}),
           "giza": _entity(client, auth_headers, region, "giza", attrs={"parent": "egypt"})}
    ids["D1"] = _entity(client, auth_headers, depot, "D1", attrs={"region": "cairo"})
    ids["D2"] = _entity(client, auth_headers, depot, "D2", attrs={"region": "cairo"})
    for t, d in (("T1", "D1"), ("T2", "D1"), ("T3", "D2")):
        ids[t] = _entity(client, auth_headers, truck, t, attrs={"depot": d})
    ids["ali"] = _entity(client, auth_headers, staff, "ali", attrs={"home": "D1"})
    ids["mona"] = _entity(client, auth_headers, staff, "mona")
    demand = client.post("/api/v1/parameters", json={"domain_id": domain_id, "name": "demand", "index_type_ids": [depot],
                                                     "default_value": 0}, headers=auth_headers).json()["id"]
    client.put(f"/api/v1/parameters/{demand}/values", json={"cells": [{"entity_ids": [ids["D1"]], "value": 40}]}, headers=auth_headers)
    return {"domain": domain_id, "kinds": {"region": region, "depot": depot, "truck": truck, "staff": staff}, "ids": ids,
            "demand": demand}


def _get(path, headers, **params):
    got = client.get(path, params=params, headers=headers)
    assert got.status_code == 200, got.text
    return got.json()


def test_the_roots_are_the_kinds_that_nest_under_no_other(auth_headers, world):  # noqa: F811
    s = _get(f"/api/v1/domains/{world['domain']}/workbench/schema", auth_headers)
    assert s["roots"] == [world["kinds"]["region"]]
    by_field = {e["field"]: e for e in s["edges"]}
    assert by_field["depot"]["child_kind"] == world["kinds"]["truck"] and by_field["depot"]["parent_kind"] == world["kinds"]["depot"]
    assert by_field["home"]["required"] is False


def test_the_tree_from_the_top_down_with_counts(auth_headers, world):  # noqa: F811
    d, k, ids = world["domain"], world["kinds"], world["ids"]
    top = _get(f"/api/v1/domains/{d}/workbench/children", auth_headers, group=f"root:{k['region']}")
    assert [(r["key"], r["children"]) for r in top["items"]] == [("egypt", 2)]

    groups = {g["kind"]: g for g in _get(f"/api/v1/domains/{d}/workbench/groups", auth_headers, parent=ids["cairo"])["groups"]}
    assert (groups["region"]["count"], groups["depot"]["count"]) == (0, 2)
    depots = _get(f"/api/v1/domains/{d}/workbench/children", auth_headers, group=groups["depot"]["group"], parent=ids["cairo"])
    assert [(r["key"], r["children"]) for r in depots["items"]] == [("D1", 3), ("D2", 1)]  # D1: two trucks and ali

    # A staff member with no home depot is not placed: listed at the top under their kind.
    unplaced = _get(f"/api/v1/domains/{d}/workbench/children", auth_headers, group=f"root:{k['staff']}")
    assert [r["key"] for r in unplaced["items"]] == ["mona"]
    filtered = _get(f"/api/v1/domains/{d}/workbench/children", auth_headers, group=groups["depot"]["group"], parent=ids["cairo"], q="2")
    assert [r["key"] for r in filtered["items"]] == ["D2"]


def test_search_finds_any_kind_with_the_path_above_it(auth_headers, world):  # noqa: F811
    d = world["domain"]
    (hit,) = _get(f"/api/v1/domains/{d}/workbench/search", auth_headers, q="T3")["items"]
    assert hit["kind"] == "truck"
    assert [p["key"] for p in hit["path"]] == ["egypt", "cairo", "D2"]
    assert hit["path"][-1]["child_group"].startswith("ref:")


def test_values_for_one_record_and_problems_for_the_tree(auth_headers, world):  # noqa: F811
    ids = world["ids"]
    (demand,) = _get(f"/api/v1/entities/{ids['D1']}/values", auth_headers)["parameters"]
    assert demand["name"] == "demand" and demand["single"] is True and [c["value"] for c in demand["cells"]] == [40.0]
    assert _get(f"/api/v1/entities/{ids['D2']}/values", auth_headers)["parameters"][0]["cells"] == []

    # A staff member whose home depot is switched off: a warning the tree marks on that record.
    closed = _entity(client, auth_headers, world["kinds"]["depot"], "D9", attrs={"region": "giza"}, active=False)
    zaki = _entity(client, auth_headers, world["kinds"]["staff"], "zaki", attrs={"home": "D9"})
    answer = _get(f"/api/v1/domains/{world['domain']}/workbench/problems", auth_headers)
    assert [(i["key"], i["kind"], i["codes"]) for i in answer["items"]] == [("zaki", "staff", ["inactive_target"])]
    problems = answer["records"]
    assert problems.get(str(zaki)) == ["inactive_target"]
    assert str(ids["T1"]) not in problems and str(ids["mona"]) not in problems  # an empty optional field is only a note
    assert closed


def test_a_record_s_place_is_the_list_its_siblings_are_in(auth_headers, world):  # noqa: F811
    d, ids, k = world["domain"], world["ids"], world["kinds"]
    placed = _get(f"/api/v1/domains/{d}/workbench/place", auth_headers, entity=ids["T3"])
    assert placed["parent"]["key"] == "D2" and placed["group"].startswith("ref:")
    assert [p["key"] for p in placed["path"]] == ["egypt", "cairo", "D2"]
    top = _get(f"/api/v1/domains/{d}/workbench/place", auth_headers, entity=ids["mona"])
    assert top["parent"] is None and top["group"] == f"root:{k['staff']}"


def test_bad_groups_are_refused(auth_headers, world):  # noqa: F811
    d = world["domain"]
    assert client.get(f"/api/v1/domains/{d}/workbench/children", params={"group": "nope"}, headers=auth_headers).status_code == 422
    assert client.get(f"/api/v1/domains/{d}/workbench/children", params={"group": "ref:999999"}, headers=auth_headers).status_code == 404
    assert client.get("/api/v1/domains/999999999/workbench/schema", headers=auth_headers).status_code == 404
