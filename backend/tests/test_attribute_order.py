"""Attributes in the order someone chose (migration 0027).

The property that carries the feature is that **every list follows the same
order**: the type's own attribute list, the type as embedded in the entity
types list (which is what the entity form renders fields from), and the graph
payload. An order that one screen honours and another ignores is worse than
alphabetical, because then the two screens disagree and neither is obviously
wrong.

The reorder route takes the **whole list**, and refuses anything that is not
exactly the type's attributes once each. The tests for those refusals are the
ones that keep a half-applied reorder from leaving attributes interleaved in an
order nobody asked for.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.main import app
from app.seed import seed_admin


@pytest.fixture(autouse=True)
def ensure_admin_seeded():
    db = SessionLocal()
    seed_admin(db)
    db.close()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def headers(client):
    settings = get_settings()
    token = client.post(
        "/api/auth/login",
        data={"username": settings.admin_username, "password": settings.admin_password},
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def domain_id(client, headers):
    response = client.post(
        "/api/domain/", json={"name": f"order-{uuid.uuid4().hex[:8]}"}, headers=headers
    )
    assert response.status_code == 201, response.text
    created = response.json()["id"]
    try:
        yield created
    finally:
        client.delete(f"/api/domain/{created}", headers=headers)


def _type(client, headers, domain_id, name="employee") -> int:
    response = client.post(
        "/api/v1/entity-types", json={"domain_id": domain_id, "name": name}, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _attribute(client, headers, type_id, name, **extra) -> dict:
    response = client.post(
        f"/api/v1/entity-types/{type_id}/attributes",
        json={"name": name, "data_type": "integer", **extra},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _names(client, headers, type_id) -> list[str]:
    response = client.get(f"/api/v1/entity-types/{type_id}/attributes", headers=headers)
    assert response.status_code == 200, response.text
    return [a["name"] for a in response.json()]


def _order(client, headers, type_id, ids):
    return client.put(
        f"/api/v1/entity-types/{type_id}/attribute-order",
        json={"attribute_ids": ids},
        headers=headers,
    )


# -- creating ---------------------------------------------------------------


def test_a_new_attribute_goes_to_the_end(client, headers, domain_id):
    """Where the person adding it is looking, not where its name sorts."""
    type_id = _type(client, headers, domain_id)
    for name in ("zeta", "alpha", "mid"):
        _attribute(client, headers, type_id, name)

    assert _names(client, headers, type_id) == ["zeta", "alpha", "mid"]


def test_an_explicit_position_is_kept(client, headers, domain_id):
    type_id = _type(client, headers, domain_id)
    _attribute(client, headers, type_id, "second")
    first = _attribute(client, headers, type_id, "first", sort_order=0)

    assert first["sort_order"] == 0
    assert _names(client, headers, type_id) == ["first", "second"]


def test_a_tie_is_broken_by_name(client, headers, domain_id):
    """No uniqueness on the position, so equal numbers must still list
    predictably rather than in whatever order the planner returns them."""
    type_id = _type(client, headers, domain_id)
    _attribute(client, headers, type_id, "beta", sort_order=5)
    _attribute(client, headers, type_id, "alpha", sort_order=5)

    assert _names(client, headers, type_id) == ["alpha", "beta"]


# -- reordering -------------------------------------------------------------


def test_reordering_renumbers_the_whole_list(client, headers, domain_id):
    type_id = _type(client, headers, domain_id)
    a = _attribute(client, headers, type_id, "a")["id"]
    b = _attribute(client, headers, type_id, "b")["id"]
    c = _attribute(client, headers, type_id, "c")["id"]

    response = _order(client, headers, type_id, [c, a, b])

    assert response.status_code == 200, response.text
    assert [row["name"] for row in response.json()] == ["c", "a", "b"]
    assert [row["sort_order"] for row in response.json()] == [1, 2, 3]
    assert _names(client, headers, type_id) == ["c", "a", "b"]


def test_a_partial_list_is_refused(client, headers, domain_id):
    """The missing attribute would otherwise keep its old number and land
    somewhere among the new ones -- an order nobody chose."""
    type_id = _type(client, headers, domain_id)
    a = _attribute(client, headers, type_id, "a")["id"]
    _attribute(client, headers, type_id, "b")

    response = _order(client, headers, type_id, [a])

    assert response.status_code == 422
    assert "missing" in response.json()["detail"][0]["msg"]
    assert _names(client, headers, type_id) == ["a", "b"]


def test_another_types_attribute_is_refused(client, headers, domain_id):
    """It would move an attribute on a screen nobody is looking at."""
    mine = _type(client, headers, domain_id, "employee")
    theirs = _type(client, headers, domain_id, "shift")
    a = _attribute(client, headers, mine, "a")["id"]
    foreign = _attribute(client, headers, theirs, "starts")["id"]

    response = _order(client, headers, mine, [a, foreign])

    assert response.status_code == 422
    assert "not attributes of this type" in response.json()["detail"][0]["msg"]


def test_a_duplicate_is_refused(client, headers, domain_id):
    type_id = _type(client, headers, domain_id)
    a = _attribute(client, headers, type_id, "a")["id"]
    _attribute(client, headers, type_id, "b")

    response = _order(client, headers, type_id, [a, a])

    assert response.status_code == 422
    assert "more than once" in response.json()["detail"][0]["msg"]


def test_reordering_needs_the_capability(client, headers, domain_id):
    from tests.test_capabilities_enforced import _account

    type_id = _type(client, headers, domain_id)
    a = _attribute(client, headers, type_id, "a")["id"]
    db = SessionLocal()
    try:
        planner = _account(db, "planner")
    finally:
        db.close()

    response = _order(client, headers | planner, type_id, [a])

    assert response.status_code == 403


def test_a_patch_can_move_one_attribute(client, headers, domain_id):
    type_id = _type(client, headers, domain_id)
    _attribute(client, headers, type_id, "a")
    b = _attribute(client, headers, type_id, "b")["id"]

    response = client.patch(f"/api/v1/attributes/{b}", json={"sort_order": 0}, headers=headers)

    assert response.status_code == 200, response.text
    assert _names(client, headers, type_id) == ["b", "a"]


def test_a_patch_may_not_null_the_position(client, headers, domain_id):
    type_id = _type(client, headers, domain_id)
    a = _attribute(client, headers, type_id, "a")["id"]

    response = client.patch(f"/api/v1/attributes/{a}", json={"sort_order": None}, headers=headers)

    assert response.status_code == 422


# -- every list follows it --------------------------------------------------


def test_the_type_as_listed_carries_its_attributes_in_order(client, headers, domain_id):
    """This embedded list is what the entity form renders fields from, so
    the form follows the order without being told about it."""
    type_id = _type(client, headers, domain_id)
    a = _attribute(client, headers, type_id, "a")["id"]
    b = _attribute(client, headers, type_id, "b")["id"]
    _order(client, headers, type_id, [b, a])

    listed = client.get(f"/api/v1/entity-types?domain_id={domain_id}", headers=headers).json()
    detail = client.get(f"/api/v1/entity-types/{type_id}", headers=headers).json()

    embedded = next(t for t in listed["items"] if t["id"] == type_id)["attributes"]
    assert [x["name"] for x in embedded] == ["b", "a"]
    assert [x["name"] for x in detail["attributes"]] == ["b", "a"]


def test_the_graph_panel_follows_it_too(client, headers, domain_id):
    """`attribute_definitions` is what the graph's node panel lists fields
    from. Flat across types, so this type's entries are picked out by id."""
    type_id = _type(client, headers, domain_id)
    a = _attribute(client, headers, type_id, "a")["id"]
    b = _attribute(client, headers, type_id, "b")["id"]
    _order(client, headers, type_id, [b, a])

    graph = client.get(f"/api/v1/graph?domain_id={domain_id}", headers=headers)

    assert graph.status_code == 200, graph.text
    mine = [
        d["code"]
        for d in graph.json()["attribute_definitions"]
        if d["entity_type_id"] == str(type_id)
    ]
    assert mine == ["b", "a"]


# -- relationship types have the same order ---------------------------------


def test_a_relationship_types_attributes_can_be_reordered(client, headers, domain_id):
    a_type = _type(client, headers, domain_id, "employee")
    b_type = _type(client, headers, domain_id, "unit")
    rel = client.post(
        "/api/v1/relationship-types",
        json={"domain_id": domain_id, "name": "works_in", "from_type_id": a_type,
              "to_type_id": b_type},
        headers=headers,
    )
    assert rel.status_code == 201, rel.text
    rel_id = rel.json()["id"]
    made = [
        client.post(
            f"/api/v1/relationship-types/{rel_id}/attributes",
            json={"name": name, "data_type": "integer"},
            headers=headers,
        ).json()["id"]
        for name in ("share", "since")
    ]

    response = client.put(
        f"/api/v1/relationship-types/{rel_id}/attribute-order",
        json={"attribute_ids": list(reversed(made))},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    listed = client.get(f"/api/v1/relationship-types/{rel_id}/attributes", headers=headers).json()
    assert [x["name"] for x in listed] == ["since", "share"]
