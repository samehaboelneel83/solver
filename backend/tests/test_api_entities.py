"""Entities -- the router where the database, not the request layer,
decides whether a payload is valid (`app/api/entities.py`).

`entity.attrs` is free-form JSONB. Nothing in the request layer knows what
attributes an entity type declares, so `attrs` is validated by the
`entity_validate` trigger (migration 0006), which raises SQLSTATE 23514
with a JSON `DETAIL` carrying `kind`/`field`/`record`. `translate_db_error`
turns that into a **422 in FastAPI's own list shape** -- one entry,
`loc: ["body", <field>]`, the message in `msg`, and the trigger's `kind`
as a sibling key. (Task 3 originally emitted an *object* `detail`
`{"message", "field", "kind"}`; Ruling 19 normalised it onto the list
shape in task 7, so the platform has exactly one 422 body.)

**This file is where that contract is proven over real HTTP.** Task 5 was
expected to do it and could not: neither `entity_type` nor `attribute_def`
has a trigger, so their CHECKs arrive with `DETAIL = None` and come back as
a **409 with a string `detail`** (Ruling 16). `entity` has a trigger, so
both shapes are reachable here -- and this file pins which failure produces
which, because a test that asserted only `status_code == 422` would pass
under either shape and so would pin neither.

`entity_validate` emits exactly three `kind` values --
`unknown_attribute`, `required_attribute`, `attribute_type` (grep the
`RAISE EXCEPTION`s in `0006_schema_v1_domain.py`). There is one test per
kind, each asserting on `detail["kind"]` **and** `detail["field"]`, plus a
fourth for the `enum_values` case. A fifth used to pin a `default_value`
that did not match its own `data_type` failing late, on the entity write
(Task 5's Concern 4); since migration 0009 the database refuses the
definition itself, and the test asserts that instead.

Three response *sources* are in play and `_trigger_error`,
`_validation_errors` and `_conflict` pin one each. The first two now share
a body shape, so what tells them apart is the `kind` key -- present on a
trigger's entry, absent from FastAPI's:

- **422, list `detail` with `kind`** -- `entity_validate`, via
  `translate_db_error`.
- **422, list `detail` without `kind`** -- FastAPI's own body validation,
  for what the request layer can decide alone (`attrs` not being an object
  at all, `sort_order` not being an integer).
- **409, string `detail`** -- `translate_db_error`'s other branch: the
  `UNIQUE (entity_type_id, key)` violation and the `entity_type_id` FK.
  (`entity_key_not_blank` is the CHECK exception: no JSON DETAIL, but
  the constraint name *is* the field, so it is the 422-with-`kind` shape.)

Test hygiene: every row is created through a real HTTP POST, which the app
commits inside the request, so a test-side `db.rollback()` cannot undo it.
Everything hangs off one `domain` row, which the `domain_id` fixture
deletes in a `finally`; `ON DELETE CASCADE` takes the entity types,
attribute defs, entities and parameter defs with it.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

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
    every entity_type/attribute_def/entity/parameter_def a test hung off
    it, so nothing this file creates survives the test that created it."""
    client = TestClient(app)
    response = client.post(
        "/api/domain/",
        json={"name": f"ent-test-{uuid.uuid4().hex[:8]}"},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    created_id = response.json()["id"]
    try:
        yield created_id
    finally:
        client.delete(f"/api/domain/{created_id}", headers=auth_headers)


@pytest.fixture
def entity_type_id(auth_headers, domain_id):
    """An `employee` type with no attributes -- tests add the attribute
    defs they need."""
    client = TestClient(app)
    response = client.post(
        "/api/v1/entity-types",
        json={"domain_id": domain_id, "name": "employee", "role": "agent"},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


# --- helpers ---------------------------------------------------------------


def _trigger_error(response) -> dict:
    """Assert `response` is a database trigger's 422 and return it
    normalised to `{message, field, kind}` for the tests below to read.

    Since Ruling 19 (task 7) the wire shape is FastAPI's list: exactly one
    entry, whose keys are exactly `type`, `loc`, `msg` and `kind`, with
    `loc == ["body", <field>]`. Every one of those is asserted here, not
    merely the status: a test that checked only the number could not tell
    a trigger refusal from a Pydantic one, and would keep passing if
    `translate_db_error` stopped emitting `kind` -- the one machine-readable
    discriminator a client has (task 8 depends on `kind="parameter_index"`).

    The normalised return keeps the eight tests below about *which* kind
    and field, which did not change, rather than about the envelope, which
    did.
    """
    assert response.status_code == 422, response.text
    body = response.json()
    detail = body.get("detail")
    assert isinstance(detail, list), f"expected a list detail, got {body!r}"
    assert len(detail) == 1, f"a trigger blames exactly one thing, got {detail!r}"
    entry = detail[0]
    assert set(entry) == {"type", "loc", "msg", "kind"}, entry
    assert isinstance(entry["msg"], str) and entry["msg"], entry
    loc = [str(part) for part in entry["loc"]]
    assert loc[0] == "body", entry
    assert len(loc) <= 2, entry
    return {
        "message": entry["msg"],
        "field": loc[1] if len(loc) > 1 else None,
        "kind": entry["kind"],
    }


def _validation_errors(response) -> list[dict]:
    """Assert `response` is FastAPI's own 422 -- the request layer's answer.

    Since Ruling 19 a trigger's 422 has the same list envelope, so the
    envelope alone no longer says who answered. The absence of `kind` does:
    only `translate_db_error` adds it.
    """
    assert response.status_code == 422, response.text
    body = response.json()
    detail = body.get("detail")
    assert isinstance(detail, list), f"expected a list of validation errors, got {body!r}"
    assert detail, "validation-error list is empty"
    for entry in detail:
        assert isinstance(entry, dict), entry
        assert "loc" in entry and "msg" in entry and "type" in entry, entry
        assert "kind" not in entry, f"a database trigger answered, not the request layer: {entry!r}"
    return detail


def _assert_blames_field(detail: list[dict], field: str) -> dict:
    matches = [
        entry
        for entry in detail
        if [str(part) for part in entry["loc"]][:1] == ["body"]
        and [str(part) for part in entry["loc"]][-1:] == [field]
    ]
    assert matches, f"no error named body.{field}; got {[e['loc'] for e in detail]}"
    return matches[0]


def _conflict(response) -> str:
    """Assert `response` is a `translate_db_error` 409: a **string**
    detail, which is what distinguishes it from either 422."""
    assert response.status_code == 409, response.text
    detail = response.json().get("detail")
    assert isinstance(detail, str), f"expected a string detail, got {detail!r}"
    return detail


def _make_attribute(client, auth_headers, entity_type_id, name, data_type, **extra) -> dict:
    payload = {"name": name, "data_type": data_type, **extra}
    response = client.post(
        f"/api/v1/entity-types/{entity_type_id}/attributes", json=payload, headers=auth_headers
    )
    assert response.status_code == 201, response.text
    return response.json()


def _make_entity(client, auth_headers, entity_type_id, key, **extra) -> dict:
    payload = {"entity_type_id": entity_type_id, "key": key, **extra}
    response = client.post("/api/v1/entities", json=payload, headers=auth_headers)
    assert response.status_code == 201, response.text
    return response.json()


# --- the trigger 422 contract: one test per `kind` ------------------------


def test_unknown_attribute_is_422_naming_the_attribute(auth_headers, entity_type_id):
    """kind 1 of 3. No `attribute_def` named `nope` exists, so
    `entity_validate`'s first loop refuses the write."""
    client = TestClient(app)
    response = client.post(
        "/api/v1/entities",
        json={"entity_type_id": entity_type_id, "key": "ahmed", "attrs": {"nope": 1}},
        headers=auth_headers,
    )
    detail = _trigger_error(response)
    assert detail["kind"] == "unknown_attribute"
    assert detail["field"] == "nope"
    # The message has to be diagnosable on its own -- a client that renders
    # only `message` must still learn which attribute and which entity.
    assert "nope" in detail["message"] and "ahmed" in detail["message"], detail


def test_required_attribute_missing_is_422_naming_the_attribute(auth_headers, entity_type_id):
    """kind 2 of 3. `rank` is required and has no default, so an entity
    that omits it cannot be written."""
    client = TestClient(app)
    _make_attribute(client, auth_headers, entity_type_id, "rank", "integer", required=True)
    response = client.post(
        "/api/v1/entities",
        json={"entity_type_id": entity_type_id, "key": "ahmed", "attrs": {}},
        headers=auth_headers,
    )
    detail = _trigger_error(response)
    assert detail["kind"] == "required_attribute"
    assert detail["field"] == "rank"
    assert "rank" in detail["message"], detail


def test_required_attribute_explicit_null_is_also_refused(auth_headers, entity_type_id):
    """`entity_validate` treats a JSON `null` the same as an absent key
    (`IF v IS NULL OR v = 'null'`), so sending the field explicitly does
    not satisfy `required`."""
    client = TestClient(app)
    _make_attribute(client, auth_headers, entity_type_id, "rank", "integer", required=True)
    response = client.post(
        "/api/v1/entities",
        json={"entity_type_id": entity_type_id, "key": "ahmed", "attrs": {"rank": None}},
        headers=auth_headers,
    )
    detail = _trigger_error(response)
    assert detail["kind"] == "required_attribute"
    assert detail["field"] == "rank"


def test_attribute_type_mismatch_is_422_naming_the_attribute(auth_headers, entity_type_id):
    """kind 3 of 3. `rank` is an integer; `"high"` is a string."""
    client = TestClient(app)
    _make_attribute(client, auth_headers, entity_type_id, "rank", "integer")
    response = client.post(
        "/api/v1/entities",
        json={"entity_type_id": entity_type_id, "key": "ahmed", "attrs": {"rank": "high"}},
        headers=auth_headers,
    )
    detail = _trigger_error(response)
    assert detail["kind"] == "attribute_type"
    assert detail["field"] == "rank"
    assert "rank" in detail["message"] and "integer" in detail["message"], detail


def test_integer_attribute_refuses_a_fractional_number(auth_headers, entity_type_id):
    """`integer` is `jsonb_typeof(v) = 'number' AND v % 1 = 0`, so 3.5 is a
    type error even though 3.0 is not -- the half of the CASE arm that a
    test using a string for the bad value never reaches."""
    client = TestClient(app)
    _make_attribute(client, auth_headers, entity_type_id, "rank", "integer")
    response = client.post(
        "/api/v1/entities",
        json={"entity_type_id": entity_type_id, "key": "ahmed", "attrs": {"rank": 3.5}},
        headers=auth_headers,
    )
    detail = _trigger_error(response)
    assert detail["kind"] == "attribute_type"
    assert detail["field"] == "rank"


def test_enum_value_outside_enum_values_is_422(auth_headers, entity_type_id):
    """The `enum` arm of the same CASE: a string is not enough, it has to
    be one of `enum_values`. Still `kind = "attribute_type"` -- the trigger
    emits no separate kind for it."""
    client = TestClient(app)
    _make_attribute(
        client,
        auth_headers,
        entity_type_id,
        "grade",
        "enum",
        enum_values=["junior", "senior"],
    )
    response = client.post(
        "/api/v1/entities",
        json={"entity_type_id": entity_type_id, "key": "ahmed", "attrs": {"grade": "wizard"}},
        headers=auth_headers,
    )
    detail = _trigger_error(response)
    assert detail["kind"] == "attribute_type"
    assert detail["field"] == "grade"


def test_default_value_that_contradicts_its_data_type_is_refused_at_definition(
    auth_headers, entity_type_id
):
    """Task 5's Concern 4, and this task's obligation (iii) -- resolved by
    migration 0009's rule 8.

    Until 0009 nothing validated `attribute_def.default_value` against its
    own `data_type`, so an `integer` attribute could be defined with a
    default of `"banana"`. The definition was accepted and the failure came
    much later, from `entity_validate`, for an entity whose payload never
    mentioned the attribute. This test used to pin that late failure.

    Now the CHECK `attribute_def_default_value_matches_type` refuses the
    *definition*. Task 14a recorded that the resulting generic 409 was
    useless for a correctable field error, and Task 14b shadowed the CHECK
    in the entity-type router, so it is now a **422 naming
    `default_value`** (Ruling 16's pattern). Nothing is stored either way:
    the type's next entity is created cleanly.
    """
    client = TestClient(app)
    response = client.post(
        f"/api/v1/entity-types/{entity_type_id}/attributes",
        json={"name": "rank", "data_type": "integer", "default_value": "banana"},
        headers=auth_headers,
    )
    _assert_blames_field(_validation_errors(response), "default_value")
    listed = client.get(
        f"/api/v1/entity-types/{entity_type_id}/attributes", headers=auth_headers
    )
    assert listed.status_code == 200 and listed.json() == [], listed.text

    created = _make_entity(client, auth_headers, entity_type_id, "ahmed", attrs={})
    assert created["attrs"] == {}


def test_patch_attrs_is_validated_by_the_same_trigger(auth_headers, entity_type_id):
    """`entity_validate` is `BEFORE INSERT OR UPDATE`, so PATCH gets the
    identical contract -- worth pinning separately, since a router could
    easily reach the database on create and not on update."""
    client = TestClient(app)
    _make_attribute(client, auth_headers, entity_type_id, "rank", "integer")
    entity = _make_entity(client, auth_headers, entity_type_id, "ahmed", attrs={"rank": 3})

    response = client.patch(
        f"/api/v1/entities/{entity['id']}",
        json={"attrs": {"rank": "high"}},
        headers=auth_headers,
    )
    detail = _trigger_error(response)
    assert detail["kind"] == "attribute_type"
    assert detail["field"] == "rank"

    # And the refused update left the stored row alone.
    stored = client.get(f"/api/v1/entities/{entity['id']}", headers=auth_headers)
    assert stored.json()["attrs"] == {"rank": 3}


# --- the other two shapes, so 422-vs-409 stays a real distinction ----------


def test_duplicate_key_in_one_entity_type_is_409_with_a_string_detail(
    auth_headers, entity_type_id
):
    """`UNIQUE (entity_type_id, key)` is a plain constraint, not a trigger:
    no JSON DETAIL, so `translate_db_error` returns its 409 branch."""
    client = TestClient(app)
    _make_entity(client, auth_headers, entity_type_id, "ahmed")
    response = client.post(
        "/api/v1/entities",
        json={"entity_type_id": entity_type_id, "key": "ahmed"},
        headers=auth_headers,
    )
    _conflict(response)


def test_same_key_under_a_different_entity_type_is_allowed(auth_headers, domain_id):
    """The unique is scoped to the type, so the 409 above is about the
    pair, not the key."""
    client = TestClient(app)
    first = client.post(
        "/api/v1/entity-types",
        json={"domain_id": domain_id, "name": "employee"},
        headers=auth_headers,
    ).json()["id"]
    second = client.post(
        "/api/v1/entity-types",
        json={"domain_id": domain_id, "name": "machine"},
        headers=auth_headers,
    ).json()["id"]
    _make_entity(client, auth_headers, first, "a1")
    _make_entity(client, auth_headers, second, "a1")


def test_unknown_entity_type_id_is_409_with_a_string_detail(auth_headers):
    """The FK violation, the third `translate_db_error` branch reachable
    from this router."""
    client = TestClient(app)
    response = client.post(
        "/api/v1/entities",
        json={"entity_type_id": 2**40, "key": "ahmed"},
        headers=auth_headers,
    )
    _conflict(response)


def test_attrs_that_is_not_an_object_is_a_request_layer_422(auth_headers, entity_type_id):
    """`CHECK (jsonb_typeof(attrs) = 'object')` is a table CHECK with no
    DETAIL, so letting the database answer would give a 409. The request
    layer is typed to be at least as strict, so this is FastAPI's 422
    naming the field instead."""
    client = TestClient(app)
    response = client.post(
        "/api/v1/entities",
        json={"entity_type_id": entity_type_id, "key": "ahmed", "attrs": [1, 2]},
        headers=auth_headers,
    )
    _assert_blames_field(_validation_errors(response), "attrs")


def test_non_integer_sort_order_is_a_request_layer_422(auth_headers, entity_type_id):
    client = TestClient(app)
    response = client.post(
        "/api/v1/entities",
        json={"entity_type_id": entity_type_id, "key": "ahmed", "sort_order": "first"},
        headers=auth_headers,
    )
    _assert_blames_field(_validation_errors(response), "sort_order")


def test_blank_entity_key_is_422_naming_key(auth_headers, entity_type_id):
    """Migration 0009's `entity_key_not_blank` CHECK has no JSON DETAIL,
    so without a named branch it used to collapse into the generic 409.
    The UI already refuses an empty key; the API must name `key` the same
    way a trigger 422 does, not hide it as a conflict."""
    client = TestClient(app)
    response = client.post(
        "/api/v1/entities",
        json={"entity_type_id": entity_type_id, "key": "   "},
        headers=auth_headers,
    )
    error = _trigger_error(response)
    assert error["kind"] == "entity_key_not_blank"
    assert error["field"] == "key"
    assert "key is required" in error["message"]

    created = _make_entity(client, auth_headers, entity_type_id, "ahmed")
    patch = client.patch(
        f"/api/v1/entities/{created['id']}",
        json={"key": "", "updated_at": created["updated_at"]},
        headers=auth_headers,
    )
    patched = _trigger_error(patch)
    assert patched["kind"] == "entity_key_not_blank"
    assert patched["field"] == "key"


# --- happy paths -----------------------------------------------------------


def test_create_entity_applies_column_defaults(auth_headers, entity_type_id):
    client = TestClient(app)
    created = _make_entity(client, auth_headers, entity_type_id, "ahmed")
    assert isinstance(created["id"], int)
    assert created["entity_type_id"] == entity_type_id
    assert created["key"] == "ahmed"
    assert created["label"] is None
    assert created["sort_order"] == 0
    assert created["active"] is True
    assert created["attrs"] == {}


def test_create_entity_materialises_an_optional_default(auth_headers, entity_type_id):
    """Spec §3: `entity_validate` **materialises** defaults into `attrs` on
    write rather than resolving them on read. The response therefore has to
    show the stored row, not the submitted payload -- if the router
    returned its own input, `attrs` would come back `{}` and a later read
    would disagree with the create response."""
    client = TestClient(app)
    _make_attribute(client, auth_headers, entity_type_id, "rank", "integer", default_value=5)
    created = _make_entity(client, auth_headers, entity_type_id, "ahmed", attrs={})
    assert created["attrs"] == {"rank": 5}

    # ... and the same value is what a fresh read returns.
    fetched = client.get(f"/api/v1/entities/{created['id']}", headers=auth_headers)
    assert fetched.json()["attrs"] == {"rank": 5}


def test_an_explicit_value_beats_the_default(auth_headers, entity_type_id):
    client = TestClient(app)
    _make_attribute(client, auth_headers, entity_type_id, "rank", "integer", default_value=5)
    created = _make_entity(client, auth_headers, entity_type_id, "ahmed", attrs={"rank": 9})
    assert created["attrs"] == {"rank": 9}


def test_every_attr_type_round_trips(auth_headers, entity_type_id):
    """One attribute per `attr_type` label, so a future change to the
    trigger's CASE cannot silently start rejecting a whole type."""
    client = TestClient(app)
    _make_attribute(client, auth_headers, entity_type_id, "rank", "integer")
    _make_attribute(client, auth_headers, entity_type_id, "rate", "number")
    _make_attribute(client, auth_headers, entity_type_id, "note", "text")
    _make_attribute(client, auth_headers, entity_type_id, "senior", "boolean")
    _make_attribute(
        client, auth_headers, entity_type_id, "grade", "enum", enum_values=["junior", "senior"]
    )
    _make_attribute(client, auth_headers, entity_type_id, "starts_at", "time")
    _make_attribute(client, auth_headers, entity_type_id, "hired_on", "date")

    attrs = {
        "rank": 3,
        "rate": 12.5,
        "note": "night shift only",
        "senior": True,
        "grade": "senior",
        "starts_at": "08:00",
        "hired_on": "2024-01-31",
    }
    created = _make_entity(client, auth_headers, entity_type_id, "ahmed", attrs=attrs)
    assert created["attrs"] == attrs


def test_patch_updates_only_the_fields_supplied(auth_headers, entity_type_id):
    client = TestClient(app)
    _make_attribute(client, auth_headers, entity_type_id, "rank", "integer")
    entity = _make_entity(
        client, auth_headers, entity_type_id, "ahmed", label="Ahmed", attrs={"rank": 3}
    )
    response = client.patch(
        f"/api/v1/entities/{entity['id']}",
        json={"label": "Ahmed H.", "active": False},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["label"] == "Ahmed H."
    assert updated["active"] is False
    # Untouched by a PATCH that did not name them.
    assert updated["key"] == "ahmed"
    assert updated["attrs"] == {"rank": 3}


def test_patch_attrs_replaces_the_whole_object(auth_headers, entity_type_id):
    """`attrs` is one JSONB column, so a PATCH naming it replaces it rather
    than merging -- pinned because the opposite is an equally plausible
    design and clients need to know which they get."""
    client = TestClient(app)
    _make_attribute(client, auth_headers, entity_type_id, "rank", "integer")
    _make_attribute(client, auth_headers, entity_type_id, "note", "text")
    entity = _make_entity(
        client, auth_headers, entity_type_id, "ahmed", attrs={"rank": 3, "note": "x"}
    )
    response = client.patch(
        f"/api/v1/entities/{entity['id']}", json={"attrs": {"rank": 4}}, headers=auth_headers
    )
    assert response.status_code == 200, response.text
    attrs = response.json()["attrs"]
    assert attrs["rank"] == 4
    # `note` was not carried over from the stored row -- which is the whole
    # claim. Asserted as "no value" rather than "no key" because of the
    # `default_value` defect this file's next test localises: `note`'s
    # definition holds jsonb 'null' rather than SQL NULL, so the trigger
    # materialises a `note: null` key today and will stop once that is
    # fixed. Either way the old "x" is gone.
    assert attrs.get("note") is None, attrs


def test_an_attribute_whose_default_is_sql_null_adds_no_key(auth_headers, entity_type_id):
    """`entity_validate` materialises a default only when
    `attribute_def.default_value IS NOT NULL`, so an attribute with no
    default must leave `attrs` alone.

    This inserts the definition with a genuine SQL NULL, bypassing Task 5's
    router, because the same definition created *through* that router does
    not behave this way: SQLAlchemy's `JSONB` persists Python `None` as
    **jsonb 'null'** unless the column is declared `none_as_null=True`, and
    'null' is not NULL, so the trigger materialises `{"note": null}` into
    every entity of the type. The trigger is correct; the ORM mapping in
    `models/v1_domain.py` is what makes "no default" unexpressible through
    the API. See the task 6 report -- the fix is outside this task's files.

    This assertion stays true once that is fixed, so it is a description of
    the intended contract rather than a pin on today's defect.
    """
    client = TestClient(app)
    db = SessionLocal()
    try:
        db.execute(
            text(
                "INSERT INTO attribute_def (entity_type_id, name, data_type, default_value)"
                " VALUES (:t, 'note', 'text', NULL)"
            ),
            {"t": entity_type_id},
        )
        db.commit()
    finally:
        db.close()

    created = _make_entity(client, auth_headers, entity_type_id, "ahmed", attrs={})
    assert created["attrs"] == {}


def test_an_attribute_created_through_the_api_with_no_default_adds_no_key(
    auth_headers, entity_type_id
):
    """The router builds the row with `**payload.model_dump()`, so
    `default_value` is always *present* and explicitly `None` -- never
    simply absent. `JSONB(none_as_null=True)` on the column is what makes
    that store as SQL NULL instead of jsonb 'null'; without it the trigger
    sees `IS NOT NULL` and materialises `{"note": null}` into every entity
    of the type, and that flows on into snapshot_dataset()'s set rows.

    The sibling test above pins the same contract through raw SQL, which
    passed even while the router was broken. This one covers the path the
    API actually takes, so it fails if the mapping regresses.
    """
    client = TestClient(app)
    _make_attribute(client, auth_headers, entity_type_id, "note", "text")

    created = _make_entity(client, auth_headers, entity_type_id, "ahmed", attrs={})

    assert created["attrs"] == {}, created["attrs"]


def test_delete_entity(auth_headers, entity_type_id):
    client = TestClient(app)
    entity = _make_entity(client, auth_headers, entity_type_id, "ahmed")
    response = client.delete(f"/api/v1/entities/{entity['id']}", headers=auth_headers)
    assert response.status_code == 204, response.text
    assert client.get(f"/api/v1/entities/{entity['id']}", headers=auth_headers).status_code == 404


def test_delete_entity_removes_its_parameter_values(auth_headers, domain_id, entity_type_id):
    """`parameter_value.entity_ids` is a bigint[], and arrays cannot carry
    foreign keys -- so the `parameter_value_cleanup` trigger deletes the
    rows instead of an ON DELETE CASCADE. The API must not block the delete
    trying to protect data the database already handles.

    The parameter rows are written directly (Task 8 owns their API), but
    the delete goes through this router, which is the part under test.
    """
    client = TestClient(app)
    entity = _make_entity(client, auth_headers, entity_type_id, "ahmed")
    other = _make_entity(client, auth_headers, entity_type_id, "sara")

    db = SessionLocal()
    try:
        param_id = db.execute(
            text(
                "INSERT INTO parameter_def (domain_id, name, index_type_ids)"
                " VALUES (:d, 'cost', ARRAY[:t]::bigint[]) RETURNING id"
            ),
            {"d": domain_id, "t": entity_type_id},
        ).scalar_one()
        db.execute(
            text(
                "INSERT INTO parameter_value (parameter_def_id, entity_ids, value)"
                " VALUES (:p, ARRAY[:e]::bigint[], 7), (:p, ARRAY[:o]::bigint[], 9)"
            ),
            {"p": param_id, "e": entity["id"], "o": other["id"]},
        )
        db.commit()
    finally:
        db.close()

    response = client.delete(f"/api/v1/entities/{entity['id']}", headers=auth_headers)
    assert response.status_code == 204, response.text

    db = SessionLocal()
    try:
        remaining = db.execute(
            text("SELECT entity_ids FROM parameter_value WHERE parameter_def_id = :p"),
            {"p": param_id},
        ).scalars().all()
    finally:
        db.close()
    # The deleted entity's row is gone; the other entity's row is untouched.
    assert remaining == [[other["id"]]]


# --- list ------------------------------------------------------------------


def test_list_filters_by_entity_type_id(auth_headers, domain_id):
    client = TestClient(app)
    first = client.post(
        "/api/v1/entity-types",
        json={"domain_id": domain_id, "name": "employee"},
        headers=auth_headers,
    ).json()["id"]
    second = client.post(
        "/api/v1/entity-types",
        json={"domain_id": domain_id, "name": "machine"},
        headers=auth_headers,
    ).json()["id"]
    _make_entity(client, auth_headers, first, "ahmed")
    _make_entity(client, auth_headers, second, "lathe")

    response = client.get(
        "/api/v1/entities", params={"entity_type_id": first}, headers=auth_headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert [row["key"] for row in body["items"]] == ["ahmed"]
    assert body["total"] == 1


def test_list_q_searches_key_and_label(auth_headers, entity_type_id):
    client = TestClient(app)
    _make_entity(client, auth_headers, entity_type_id, "ahmed", label="Night shift")
    _make_entity(client, auth_headers, entity_type_id, "sara", label="Day shift")
    _make_entity(client, auth_headers, entity_type_id, "omar", label=None)

    by_key = client.get(
        "/api/v1/entities",
        params={"entity_type_id": entity_type_id, "q": "hme"},
        headers=auth_headers,
    ).json()
    assert [row["key"] for row in by_key["items"]] == ["ahmed"]

    by_label = client.get(
        "/api/v1/entities",
        params={"entity_type_id": entity_type_id, "q": "day"},
        headers=auth_headers,
    ).json()
    assert [row["key"] for row in by_label["items"]] == ["sara"]

    # Matching neither column matches nothing -- including the row whose
    # label is NULL, which a naive `key ILIKE ... OR label ILIKE ...` gets
    # right only because the OR short-circuits on the key match.
    assert (
        client.get(
            "/api/v1/entities",
            params={"entity_type_id": entity_type_id, "q": "zzz"},
            headers=auth_headers,
        ).json()["total"]
        == 0
    )


def test_list_q_is_case_insensitive(auth_headers, entity_type_id):
    client = TestClient(app)
    _make_entity(client, auth_headers, entity_type_id, "ahmed", label="Night shift")
    body = client.get(
        "/api/v1/entities",
        params={"entity_type_id": entity_type_id, "q": "NIGHT"},
        headers=auth_headers,
    ).json()
    assert [row["key"] for row in body["items"]] == ["ahmed"]


def test_list_orders_by_sort_order_then_key(auth_headers, entity_type_id):
    """`sort_order` is what makes mon..sun come back in week order rather
    than alphabetically, so it has to lead the ORDER BY.

    The keys are chosen so the two orders genuinely disagree: alphabetically
    they are fri, mon, sat, thu, tue, wed. A `mon/tue/wed` fixture would sort
    identically either way and would pass against an ORDER BY that ignored
    `sort_order` entirely -- which is exactly what a mutation of this
    router's ORDER BY proved before the keys were changed.

    `sat` and `sun` share a `sort_order`, which is what exercises the `key`
    tiebreaker rather than leaving it to chance.
    """
    client = TestClient(app)
    for key, order in [
        ("wed", 3),
        ("mon", 1),
        ("sun", 6),
        ("fri", 5),
        ("tue", 2),
        ("sat", 6),
        ("thu", 4),
    ]:
        _make_entity(client, auth_headers, entity_type_id, key, sort_order=order)
    body = client.get(
        "/api/v1/entities", params={"entity_type_id": entity_type_id}, headers=auth_headers
    ).json()
    assert [row["key"] for row in body["items"]] == [
        "mon",
        "tue",
        "wed",
        "thu",
        "fri",
        "sat",  # same sort_order as sun; the key tiebreaker decides
        "sun",
    ]


def test_list_paginates_with_total_counting_every_match(auth_headers, entity_type_id):
    """`sort_order` runs opposite to `key` here for the same reason as the
    test above: a page that happened to be correct under either ordering
    would not pin which one paginates."""
    client = TestClient(app)
    for index in range(5):
        _make_entity(client, auth_headers, entity_type_id, f"e{index}", sort_order=10 - index)

    page = client.get(
        "/api/v1/entities",
        params={"entity_type_id": entity_type_id, "limit": 2, "offset": 2},
        headers=auth_headers,
    ).json()
    assert [row["key"] for row in page["items"]] == ["e2", "e1"]
    # `total` is the size of the whole match, not of the page -- that is
    # what a pager needs to render "3-4 of 5".
    assert page["total"] == 5


# --- 404s ------------------------------------------------------------------


def test_missing_entity_is_404_on_every_route(auth_headers):
    client = TestClient(app)
    missing = 2**40
    assert client.get(f"/api/v1/entities/{missing}", headers=auth_headers).status_code == 404
    assert (
        client.patch(
            f"/api/v1/entities/{missing}", json={"label": "x"}, headers=auth_headers
        ).status_code
        == 404
    )
    assert client.delete(f"/api/v1/entities/{missing}", headers=auth_headers).status_code == 404


def test_entities_require_authentication():
    """Every other route on this platform is behind `get_current_user`; an
    unauthenticated 200 here would be a hole, not a convenience."""
    client = TestClient(app)
    assert client.get("/api/v1/entities").status_code == 401
    assert client.post("/api/v1/entities", json={"entity_type_id": 1, "key": "x"}).status_code == 401


def test_whole_number_keys_list_in_number_order(auth_headers, entity_type_id):
    """Benchmark round 3: incidents listed 1, 10, 100, 101 ... 2."""
    client = TestClient(app)
    for key in ("10", "2", "100", "1", "b", "a"):
        _make_entity(client, auth_headers, entity_type_id, key)
    listed = client.get(f"/api/v1/entities?entity_type_id={entity_type_id}", headers=auth_headers).json()["items"]
    assert [e["key"] for e in listed] == ["1", "2", "10", "100", "a", "b"]
