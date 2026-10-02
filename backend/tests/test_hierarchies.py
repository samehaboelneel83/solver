"""GET /api/v1/entities/{id}/trees: a record's place in every relationship that nests its kind
inside itself -- a hierarchy (parent is `from`) and a self-referencing reference attribute (parent
is what it names) -- with the parents it may not take, and loops the database lets through."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from tests.test_api_relationships import (  # noqa: F401
    _entity, _rel_id, _rel_type_id, auth_headers, domain_id, ensure_admin_seeded, hierarchy_type_id, types,
)

client = TestClient(app)


def _trees(entity_id, headers):
    got = client.get(f"/api/v1/entities/{entity_id}/trees", headers=headers)
    assert got.status_code == 200, got.text
    return {t["name"]: t for t in got.json()["trees"]}


def test_a_hierarchy_gives_ancestors_descendants_and_the_parents_that_would_loop(auth_headers, types, hierarchy_type_id):  # noqa: F811
    unit = types["unit"]
    ids = {k: _entity(client, auth_headers, unit, k) for k in ("north", "cairo", "giza", "depot1", "elsewhere")}
    for parent, child in (("north", "cairo"), ("north", "giza"), ("cairo", "depot1")):
        _rel_id(client, auth_headers, hierarchy_type_id, ids[parent], ids[child])

    tree = _trees(ids["cairo"], auth_headers)["reports_to"]
    assert tree["is_hierarchy"] is True and tree["via_attribute"] is None
    assert [(a["key"], a["depth"]) for a in tree["ancestors"]] == [("north", 1)]
    assert [(d["key"], d["parent_id"], d["depth"]) for d in tree["descendants"]] == [("depot1", ids["cairo"], 1)]
    assert set(tree["blocked"]) == {"cairo", "depot1"}
    assert tree["loop"] is False and tree["truncated"] is False

    top = _trees(ids["north"], auth_headers)["reports_to"]
    assert top["ancestors"] == []
    assert [(d["key"], d["depth"]) for d in top["descendants"]] == [("cairo", 1), ("giza", 1), ("depot1", 2)]


def test_a_self_reference_attribute_is_a_tree_read_the_other_way_and_its_loops_are_found(auth_headers, types):  # noqa: F811
    employee = types["employee"]
    made = client.post(f"/api/v1/entity-types/{employee}/attributes",
                       json={"name": "manager", "data_type": "reference", "target_type_id": employee}, headers=auth_headers)
    assert made.status_code == 201, made.text
    boss = _entity(client, auth_headers, employee, "boss")
    lead = _entity(client, auth_headers, employee, "lead", attrs={"manager": "boss"})
    _entity(client, auth_headers, employee, "dev", attrs={"manager": "lead"})

    (tree,) = _trees(lead, auth_headers).values()  # the attribute's mirror relationship, whatever its name
    assert tree["via_attribute"] == "manager"
    assert [a["key"] for a in tree["ancestors"]] == ["boss"]
    assert [d["key"] for d in tree["descendants"]] == ["dev"]
    assert tree["loop"] is False

    # The database refuses a loop through the reference (migration 0098): the boss cannot report
    # to the dev, and the refusal names the field.
    refused = client.patch(f"/api/v1/entities/{boss}", json={"attrs": {"manager": "dev"}}, headers=auth_headers)
    assert refused.status_code == 422, refused.text
    (item,) = refused.json()["detail"]
    assert item["kind"] == "cycle" and item["loc"][-1] == "manager" and '"dev" would make a loop' in item["msg"]
    assert client.patch(f"/api/v1/entities/{boss}", json={"attrs": {"manager": "boss"}}, headers=auth_headers).status_code == 422


def test_an_ordinary_self_relationship_may_loop_and_the_tree_says_so(auth_headers, domain_id, types):  # noqa: F811
    unit = types["unit"]
    supplies = _rel_type_id(client, auth_headers, domain_id, name="supplies", from_type_id=unit, to_type_id=unit)
    a, b, c = (_entity(client, auth_headers, unit, k) for k in ("a", "b", "c"))
    for x, y in ((a, b), (b, c), (c, a)):
        _rel_id(client, auth_headers, supplies, x, y)
    tree = _trees(b, auth_headers)["supplies"]
    assert tree["loop"] is True and tree["via_attribute"] is None


def test_a_record_of_an_unrelated_kind_has_no_trees(auth_headers, types, hierarchy_type_id):  # noqa: F811
    lone = _entity(client, auth_headers, types["employee"], "alone")
    assert _trees(lone, auth_headers) == {}
    assert client.get("/api/v1/entities/999999999/trees", headers=auth_headers).status_code == 404


def test_the_records_naming_this_one_say_whether_a_delete_is_refused_or_clears_them(auth_headers, types):  # noqa: F811
    employee, unit = types["employee"], types["unit"]
    for name, required in (("home", True), ("visits", False)):
        made = client.post(f"/api/v1/entity-types/{employee}/attributes",
                           json={"name": name, "data_type": "reference", "target_type_id": unit, "required": required},
                           headers=auth_headers)
        assert made.status_code == 201, made.text
    north = _entity(client, auth_headers, unit, "north")
    south = _entity(client, auth_headers, unit, "south")
    _entity(client, auth_headers, employee, "ali", attrs={"home": "north", "visits": "south"})
    _entity(client, auth_headers, employee, "mona", attrs={"home": "south", "visits": "south"})

    got = client.get(f"/api/v1/entities/{south}/referrers", headers=auth_headers).json()
    assert got["blocks_delete"] is True
    assert [(f["attribute"], f["required"], f["count"], [r["key"] for r in f["records"]]) for f in got["fields"]] == [
        ("home", True, 1, ["mona"]), ("visits", False, 2, ["ali", "mona"])]
    assert client.get(f"/api/v1/entities/{north}/referrers", headers=auth_headers).json()["fields"][0]["records"][0]["key"] == "ali"
    alone = _entity(client, auth_headers, unit, "east")
    assert client.get(f"/api/v1/entities/{alone}/referrers", headers=auth_headers).json() == {
        "entity_id": alone, "fields": [], "blocks_delete": False}
