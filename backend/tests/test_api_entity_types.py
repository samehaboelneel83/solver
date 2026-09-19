"""Entity types and their attribute definitions -- the first purpose-built
schema v1 router (`app/api/entity_types.py`).

Two response shapes are in play here and these tests pin which one each
failure produces, because asserting `status_code == 422` alone would pass
under either and prove nothing:

- **FastAPI's validation-error shape** -- `{"detail": [{"loc": [...],
  "msg": ..., "type": ...}]}`. Every field this router rejects lands here:
  the `^[a-z][a-z0-9_]*$` names, `name <> 'id'`, the
  `(data_type = 'enum') = (enum_values IS NOT NULL)` pairing, and the two
  enum-typed columns (`role`, `data_type`). See the task 5 report for why
  these are validated in the request layer rather than left to the
  database's CHECKs.
- **A 409 from `translate_db_error`** -- string `detail`, for the two
  UNIQUE constraints (`entity_type(domain_id, name)`,
  `attribute_def(entity_type_id, name)`) and the `domain_id` FK, which
  nothing in the request layer can know about. This is what proves
  `translate_db_error` is actually wired into this router's write paths.

`test_database_check_rejects_invalid_name_on_a_direct_insert` is the third
leg: the CHECKs the request layer now shadows are still real and still
fire for any writer that is not this router (the seed, psql, a future
worker).

Test hygiene: every row is created through a real HTTP POST, which the app
commits inside the request, so a test-side `db.rollback()` cannot undo it.
Everything created here hangs off one `domain` row, which the `domain_id`
fixture deletes in a `finally`; `ON DELETE CASCADE` takes the entity types
and attribute defs with it.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.main import app
from app.models.v1_domain import EntityType
from app.seed import seed_admin


@pytest.fixture(autouse=True)
def ensure_admin_seeded():
    db = SessionLocal()
    seed_admin(db)
    db.close()


@pytest.fixture
def auth_headers():
    settings = get_settings()
    client = TestClient(app)
    response = client.post(
        "/api/auth/login",
        data={"username": settings.admin_username, "password": settings.admin_password},
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def domain_id(auth_headers):
    """A throwaway domain, deleted in a `finally`. Deleting it cascades to
    every entity_type/attribute_def a test hung off it."""
    client = TestClient(app)
    response = client.post(
        "/api/domain/",
        json={"name": f"et-test-{uuid.uuid4().hex[:8]}"},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    created_id = response.json()["id"]
    try:
        yield created_id
    finally:
        client.delete(f"/api/domain/{created_id}", headers=auth_headers)


# --- helpers ---------------------------------------------------------------


def _validation_errors(response) -> list[dict]:
    """Assert `response` is a 422 in FastAPI's validation-error shape and
    return its error list.

    The shape assertion is the point. Since Ruling 19 every 422 on the
    platform is list-shaped; what distinguishes a trigger answer is the
    `kind` key on the item. A test that only checked the status number
    could not tell a request-layer rejection from a database one.
    """
    assert response.status_code == 422, response.text
    body = response.json()
    detail = body.get("detail")
    assert isinstance(detail, list), f"expected a list of validation errors, got {body!r}"
    assert detail, "validation-error list is empty"
    for entry in detail:
        assert isinstance(entry, dict), entry
        assert "loc" in entry and "msg" in entry and "type" in entry, entry
    return detail


def _assert_blames_field(detail: list[dict], field: str) -> dict:
    """Assert some error in `detail` points at `body.<field>`."""
    matches = [
        entry
        for entry in detail
        if [str(part) for part in entry["loc"]][:1] == ["body"]
        and [str(part) for part in entry["loc"]][-1:] == [field]
    ]
    assert matches, f"no error named body.{field}; got {[e['loc'] for e in detail]}"
    return matches[0]


def _make_entity_type(client, auth_headers, domain_id, name, **extra) -> dict:
    payload = {"domain_id": domain_id, "name": name, **extra}
    response = client.post("/api/v1/entity-types", json=payload, headers=auth_headers)
    assert response.status_code == 201, response.text
    return response.json()


def _make_attribute(client, auth_headers, entity_type_id, name, data_type, **extra) -> dict:
    payload = {"name": name, "data_type": data_type, **extra}
    response = client.post(
        f"/api/v1/entity-types/{entity_type_id}/attributes", json=payload, headers=auth_headers
    )
    assert response.status_code == 201, response.text
    return response.json()


# --- entity_type: name CHECK ----------------------------------------------


def test_create_entity_type_rejects_uppercase_name(auth_headers, domain_id):
    """name="Employee" violates `^[a-z][a-z0-9_]*$`, and the refusal names
    the field in FastAPI's validation-error shape."""
    client = TestClient(app)
    response = client.post(
        "/api/v1/entity-types",
        json={"domain_id": domain_id, "name": "Employee"},
        headers=auth_headers,
    )
    detail = _validation_errors(response)
    entry = _assert_blames_field(detail, "name")
    assert "[a-z]" in (entry["msg"] + str(entry.get("ctx", ""))), entry


@pytest.mark.parametrize(
    "bad_name",
    [
        "Employee",  # uppercase
        "1employee",  # leading digit
        "_employee",  # leading underscore
        "employee-type",  # hyphen
        "employee type",  # space
        "",  # empty
        # Trailing newline: Python's re `$` matches before a final newline,
        # Postgres's `~ '...$'` does not. The request layer has to be at
        # least as strict as the CHECK, or this payload sails past it and
        # comes back as a confusing 409 from the database instead.
        "employee\n",
    ],
)
def test_create_entity_type_rejects_every_name_the_check_would(auth_headers, domain_id, bad_name):
    client = TestClient(app)
    response = client.post(
        "/api/v1/entity-types",
        json={"domain_id": domain_id, "name": bad_name},
        headers=auth_headers,
    )
    detail = _validation_errors(response)
    _assert_blames_field(detail, "name")


def test_create_entity_type_rejects_unknown_role(auth_headers, domain_id):
    """`role` is a Postgres enum, not a CHECK: an unknown label would reach
    the driver as 22P02, which translate_db_error re-raises as a 500."""
    client = TestClient(app)
    response = client.post(
        "/api/v1/entity-types",
        json={"domain_id": domain_id, "name": "employee", "role": "wizard"},
        headers=auth_headers,
    )
    detail = _validation_errors(response)
    _assert_blames_field(detail, "role")


# --- entity_type: happy paths ---------------------------------------------


def test_create_entity_type_defaults_role_to_other(auth_headers, domain_id):
    client = TestClient(app)
    created = _make_entity_type(client, auth_headers, domain_id, "employee")
    assert created["role"] == "other"
    assert created["domain_id"] == domain_id
    assert created["name"] == "employee"
    assert isinstance(created["id"], int)
    assert created["attributes"] == []


def test_create_entity_type_accepts_an_explicit_role(auth_headers, domain_id):
    client = TestClient(app)
    created = _make_entity_type(client, auth_headers, domain_id, "shift", role="time")
    assert created["role"] == "time"


def test_entity_type_detail_embeds_its_attribute_defs(auth_headers, domain_id):
    client = TestClient(app)
    entity_type = _make_entity_type(client, auth_headers, domain_id, "employee")
    _make_attribute(client, auth_headers, entity_type["id"], "rank", "integer", unit="level")
    _make_attribute(
        client,
        auth_headers,
        entity_type["id"],
        "skill",
        "enum",
        enum_values=["cook", "waiter"],
        required=True,
    )

    response = client.get(f"/api/v1/entity-types/{entity_type['id']}", headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert [a["name"] for a in body["attributes"]] == ["rank", "skill"]
    rank, skill = body["attributes"]
    assert rank["data_type"] == "integer"
    assert rank["unit"] == "level"
    assert rank["required"] is False
    assert rank["enum_values"] is None
    assert rank["entity_type_id"] == entity_type["id"]
    assert skill["data_type"] == "enum"
    assert skill["enum_values"] == ["cook", "waiter"]
    assert skill["required"] is True


def test_list_entity_types_is_domain_scoped_and_embeds_attributes(auth_headers, domain_id):
    client = TestClient(app)
    employee = _make_entity_type(client, auth_headers, domain_id, "employee")
    _make_entity_type(client, auth_headers, domain_id, "shift", role="time")
    _make_attribute(client, auth_headers, employee["id"], "rank", "integer")

    response = client.get(f"/api/v1/entity-types?domain_id={domain_id}", headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 2
    by_name = {item["name"]: item for item in body["items"]}
    assert set(by_name) == {"employee", "shift"}
    assert [a["name"] for a in by_name["employee"]["attributes"]] == ["rank"]
    assert by_name["shift"]["attributes"] == []


def test_list_entity_types_excludes_other_domains(auth_headers, domain_id):
    client = TestClient(app)
    _make_entity_type(client, auth_headers, domain_id, "employee")
    other = client.post(
        "/api/domain/", json={"name": f"et-other-{uuid.uuid4().hex[:8]}"}, headers=auth_headers
    )
    assert other.status_code == 201, other.text
    other_id = other.json()["id"]
    try:
        _make_entity_type(client, auth_headers, other_id, "machine")
        response = client.get(f"/api/v1/entity-types?domain_id={domain_id}", headers=auth_headers)
        names = [item["name"] for item in response.json()["items"]]
        assert names == ["employee"]
    finally:
        client.delete(f"/api/domain/{other_id}", headers=auth_headers)


def test_patch_entity_type_changes_role_and_name(auth_headers, domain_id):
    client = TestClient(app)
    entity_type = _make_entity_type(client, auth_headers, domain_id, "employee")
    response = client.patch(
        f"/api/v1/entity-types/{entity_type['id']}",
        json={"role": "agent"},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["role"] == "agent"
    assert response.json()["name"] == "employee"

    response = client.patch(
        f"/api/v1/entity-types/{entity_type['id']}",
        json={"name": "worker"},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == "worker"
    assert body["role"] == "agent"


def test_patch_entity_type_rejects_an_invalid_name(auth_headers, domain_id):
    client = TestClient(app)
    entity_type = _make_entity_type(client, auth_headers, domain_id, "employee")
    response = client.patch(
        f"/api/v1/entity-types/{entity_type['id']}",
        json={"name": "Employee"},
        headers=auth_headers,
    )
    _assert_blames_field(_validation_errors(response), "name")


def test_delete_entity_type_takes_its_attributes_with_it(auth_headers, domain_id):
    client = TestClient(app)
    entity_type = _make_entity_type(client, auth_headers, domain_id, "employee")
    attribute = _make_attribute(client, auth_headers, entity_type["id"], "rank", "integer")

    response = client.delete(f"/api/v1/entity-types/{entity_type['id']}", headers=auth_headers)
    assert response.status_code == 204, response.text
    assert (
        client.get(f"/api/v1/entity-types/{entity_type['id']}", headers=auth_headers).status_code
        == 404
    )
    assert (
        client.patch(
            f"/api/v1/attributes/{attribute['id']}", json={"unit": "x"}, headers=auth_headers
        ).status_code
        == 404
    )


def test_missing_entity_type_is_404_on_every_route(auth_headers):
    client = TestClient(app)
    assert client.get("/api/v1/entity-types/999999999", headers=auth_headers).status_code == 404
    assert (
        client.patch(
            "/api/v1/entity-types/999999999", json={"role": "agent"}, headers=auth_headers
        ).status_code
        == 404
    )
    assert client.delete("/api/v1/entity-types/999999999", headers=auth_headers).status_code == 404
    assert (
        client.get("/api/v1/entity-types/999999999/attributes", headers=auth_headers).status_code
        == 404
    )
    assert (
        client.post(
            "/api/v1/entity-types/999999999/attributes",
            json={"name": "rank", "data_type": "integer"},
            headers=auth_headers,
        ).status_code
        == 404
    )
    assert (
        client.patch(
            "/api/v1/attributes/999999999", json={"unit": "x"}, headers=auth_headers
        ).status_code
        == 404
    )
    assert client.delete("/api/v1/attributes/999999999", headers=auth_headers).status_code == 404


def test_entity_type_routes_require_authentication(domain_id):
    client = TestClient(app)
    assert client.get("/api/v1/entity-types").status_code == 401
    assert (
        client.post("/api/v1/entity-types", json={"domain_id": domain_id, "name": "x"}).status_code
        == 401
    )
    assert client.get("/api/v1/entity-types/1/attributes").status_code == 401
    assert client.delete("/api/v1/attributes/1").status_code == 401


# --- attribute_def: CHECKs -------------------------------------------------


def test_enum_attribute_without_enum_values_is_422(auth_headers, domain_id):
    """`CHECK ((data_type = 'enum') = (enum_values IS NOT NULL))`, first half."""
    client = TestClient(app)
    entity_type = _make_entity_type(client, auth_headers, domain_id, "employee")
    response = client.post(
        f"/api/v1/entity-types/{entity_type['id']}/attributes",
        json={"name": "skill", "data_type": "enum"},
        headers=auth_headers,
    )
    entry = _assert_blames_field(_validation_errors(response), "enum_values")
    assert "enum" in entry["msg"].lower(), entry


def test_non_enum_attribute_with_enum_values_is_422(auth_headers, domain_id):
    """`CHECK ((data_type = 'enum') = (enum_values IS NOT NULL))`, other half."""
    client = TestClient(app)
    entity_type = _make_entity_type(client, auth_headers, domain_id, "employee")
    response = client.post(
        f"/api/v1/entity-types/{entity_type['id']}/attributes",
        json={"name": "rank", "data_type": "integer", "enum_values": ["a", "b"]},
        headers=auth_headers,
    )
    entry = _assert_blames_field(_validation_errors(response), "enum_values")
    assert "enum" in entry["msg"].lower(), entry


def test_attribute_named_id_is_422(auth_headers, domain_id):
    """`CHECK (name ~ '^[a-z][a-z0-9_]*$' AND name <> 'id')` -- 'id' matches
    the pattern, so this half of the CHECK needs its own rejection."""
    client = TestClient(app)
    entity_type = _make_entity_type(client, auth_headers, domain_id, "employee")
    response = client.post(
        f"/api/v1/entity-types/{entity_type['id']}/attributes",
        json={"name": "id", "data_type": "integer"},
        headers=auth_headers,
    )
    entry = _assert_blames_field(_validation_errors(response), "name")
    assert "id" in entry["msg"], entry


@pytest.mark.parametrize("bad_name", ["Rank", "1rank", "rank-two", "rank two", "", "rank\n"])
def test_attribute_name_must_match_the_check(auth_headers, domain_id, bad_name):
    client = TestClient(app)
    entity_type = _make_entity_type(client, auth_headers, domain_id, "employee")
    response = client.post(
        f"/api/v1/entity-types/{entity_type['id']}/attributes",
        json={"name": bad_name, "data_type": "integer"},
        headers=auth_headers,
    )
    _assert_blames_field(_validation_errors(response), "name")


def test_attribute_rejects_unknown_data_type(auth_headers, domain_id):
    client = TestClient(app)
    entity_type = _make_entity_type(client, auth_headers, domain_id, "employee")
    response = client.post(
        f"/api/v1/entity-types/{entity_type['id']}/attributes",
        json={"name": "rank", "data_type": "duration"},
        headers=auth_headers,
    )
    _assert_blames_field(_validation_errors(response), "data_type")


def test_patch_attribute_to_enum_without_enum_values_is_422(auth_headers, domain_id):
    """The pairing CHECK applies to the *merged* row, not just the payload:
    a PATCH that names only `data_type` still has to be checked against the
    stored `enum_values`."""
    client = TestClient(app)
    entity_type = _make_entity_type(client, auth_headers, domain_id, "employee")
    attribute = _make_attribute(client, auth_headers, entity_type["id"], "skill", "text")
    response = client.patch(
        f"/api/v1/attributes/{attribute['id']}",
        json={"data_type": "enum"},
        headers=auth_headers,
    )
    entry = _assert_blames_field(_validation_errors(response), "enum_values")
    assert "enum" in entry["msg"].lower(), entry


def test_patch_attribute_dropping_enum_values_from_an_enum_is_422(auth_headers, domain_id):
    client = TestClient(app)
    entity_type = _make_entity_type(client, auth_headers, domain_id, "employee")
    attribute = _make_attribute(
        client, auth_headers, entity_type["id"], "skill", "enum", enum_values=["cook"]
    )
    response = client.patch(
        f"/api/v1/attributes/{attribute['id']}",
        json={"enum_values": None},
        headers=auth_headers,
    )
    _assert_blames_field(_validation_errors(response), "enum_values")


def test_patch_attribute_to_enum_with_enum_values_succeeds(auth_headers, domain_id):
    """The merged-state check must not be a blanket refusal: supplying both
    halves in one PATCH is legal."""
    client = TestClient(app)
    entity_type = _make_entity_type(client, auth_headers, domain_id, "employee")
    attribute = _make_attribute(client, auth_headers, entity_type["id"], "skill", "text")
    response = client.patch(
        f"/api/v1/attributes/{attribute['id']}",
        json={"data_type": "enum", "enum_values": ["cook", "waiter"]},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["data_type"] == "enum"
    assert response.json()["enum_values"] == ["cook", "waiter"]


# --- attribute_def: happy paths and UNIQUE --------------------------------


def test_list_attributes_of_a_type(auth_headers, domain_id):
    client = TestClient(app)
    entity_type = _make_entity_type(client, auth_headers, domain_id, "employee")
    _make_attribute(client, auth_headers, entity_type["id"], "rank", "integer")
    _make_attribute(client, auth_headers, entity_type["id"], "hired_on", "date")

    response = client.get(
        f"/api/v1/entity-types/{entity_type['id']}/attributes", headers=auth_headers
    )
    assert response.status_code == 200, response.text
    assert [a["name"] for a in response.json()] == ["hired_on", "rank"]


def test_attribute_default_value_round_trips(auth_headers, domain_id):
    client = TestClient(app)
    entity_type = _make_entity_type(client, auth_headers, domain_id, "employee")
    attribute = _make_attribute(
        client, auth_headers, entity_type["id"], "rank", "integer", default_value=3
    )
    assert attribute["default_value"] == 3
    assert attribute["required"] is False


def test_delete_attribute(auth_headers, domain_id):
    client = TestClient(app)
    entity_type = _make_entity_type(client, auth_headers, domain_id, "employee")
    attribute = _make_attribute(client, auth_headers, entity_type["id"], "rank", "integer")
    response = client.delete(f"/api/v1/attributes/{attribute['id']}", headers=auth_headers)
    assert response.status_code == 204, response.text
    listing = client.get(
        f"/api/v1/entity-types/{entity_type['id']}/attributes", headers=auth_headers
    )
    assert listing.json() == []


def test_duplicate_attribute_name_returns_409(auth_headers, domain_id):
    """`UNIQUE (entity_type_id, name)`. Nothing in the request layer can know
    this, so it is the database's answer, routed through translate_db_error
    -- which makes this the test that proves the translator is wired into
    this router's write path at all."""
    client = TestClient(app)
    entity_type = _make_entity_type(client, auth_headers, domain_id, "employee")
    _make_attribute(client, auth_headers, entity_type["id"], "rank", "integer")
    response = client.post(
        f"/api/v1/entity-types/{entity_type['id']}/attributes",
        json={"name": "rank", "data_type": "text"},
        headers=auth_headers,
    )
    assert response.status_code == 409, response.text
    assert isinstance(response.json()["detail"], str), response.text


def test_same_attribute_name_in_a_different_type_is_fine(auth_headers, domain_id):
    client = TestClient(app)
    employee = _make_entity_type(client, auth_headers, domain_id, "employee")
    shift = _make_entity_type(client, auth_headers, domain_id, "shift", role="time")
    _make_attribute(client, auth_headers, employee["id"], "rank", "integer")
    _make_attribute(client, auth_headers, shift["id"], "rank", "integer")


def test_duplicate_entity_type_name_in_one_domain_returns_409(auth_headers, domain_id):
    """`UNIQUE (domain_id, name)`, same reasoning as above."""
    client = TestClient(app)
    _make_entity_type(client, auth_headers, domain_id, "employee")
    response = client.post(
        "/api/v1/entity-types",
        json={"domain_id": domain_id, "name": "employee"},
        headers=auth_headers,
    )
    assert response.status_code == 409, response.text
    assert isinstance(response.json()["detail"], str), response.text


def test_entity_type_in_a_missing_domain_returns_409(auth_headers):
    """FK violation, 23503 -> translate_db_error -> 409."""
    client = TestClient(app)
    response = client.post(
        "/api/v1/entity-types",
        json={"domain_id": 999999999, "name": "employee"},
        headers=auth_headers,
    )
    assert response.status_code == 409, response.text
    assert isinstance(response.json()["detail"], str), response.text


# --- the CHECKs the request layer now shadows are still real --------------


def test_database_check_rejects_invalid_name_on_a_direct_insert(domain_id):
    """The request layer validating these fields does not remove the CHECK;
    it only means this router never reaches it. Anything writing outside the
    router -- the seed, a migration, psql, a future worker -- is still
    stopped by the database. Asserted directly rather than assumed, because
    a constraint nothing exercises is exactly the kind that quietly gets
    dropped later.
    """
    db = SessionLocal()
    try:
        db.add(EntityType(domain_id=domain_id, name="Employee"))
        with pytest.raises(IntegrityError) as excinfo:
            db.flush()
        assert excinfo.value.orig.pgcode == "23514", excinfo.value.orig.pgcode
    finally:
        db.rollback()
        db.close()
