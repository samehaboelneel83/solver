"""Ruling 42 -- a save built on a superseded read is refused, not applied.

The defect this closes, end to end: two clients open the same entity; the
second PATCHes two attributes; the first changes only the Label and saves;
the second client's two attributes are gone, with no warning anywhere.

The obvious fix -- send only the fields the user touched -- is wrong and is
not what is implemented. Tasks 11/12 deliberately send the **whole**
attribute set so that a key left behind by a deleted `attribute_def`
disappears on the next save (`EntityRecord.test.tsx` pins that), and a
narrower payload would silently undo it. So the payload stays whole and the
*staleness* is detected instead: `updated_at` on `entity`, `entity_type`,
`relationship_type`, `relationship` and `parameter_value` (migrations
0010, 0021, 0022), maintained by a trigger so that every writer moves it
-- the API, the seed, a migration, `psql` -- and `app/api/concurrency.py`
refuses a write whose `updated_at` is not the stored one.

What each block pins
--------------------
- **the column and its trigger**: present on all five tables, moved by an
  ORM write and by raw SQL, not moved by an UPDATE that changes nothing,
  and moved twice within one transaction (which `now()` would not do).
- **the refusal**: 409, string `detail`, carrying the phrase the browser
  matches on; and the row is *unchanged* afterwards -- a refusal that had
  already written is worse than no refusal at all.
- **the concurrent scenario itself**, replayed over HTTP for each form:
  read, another client writes, first client saves the payload it loaded,
  refused.
- **the escape hatch**: omitting `updated_at` keeps the pre-0010
  behaviour, which is what every other caller (the graph's node rename,
  the seed, `curl`) relies on.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.concurrency import STALE_PREFIX
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.main import app
from app.seed import seed_admin

TABLES = ("entity", "entity_type", "relationship_type", "relationship")
# `parameter_value` is the fifth: the grid writes named cells, and two
# clients typing the same cell is the same silent overwrite 0010 closed
# for a whole row. It is not in TABLES because the omit-hatch parametrize
# PATCHes by `id`, and this table's key is `(parameter_def_id, entity_ids)`.
CELL_TABLE = "parameter_value"
FORM_TABLES = TABLES + (CELL_TABLE,)


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
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def domain_id(auth_headers):
    client = TestClient(app)
    response = client.post(
        "/api/domain/",
        json={"name": f"conc-test-{uuid.uuid4().hex[:8]}"},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    created = response.json()["id"]
    try:
        yield created
    finally:
        client.delete(f"/api/domain/{created}", headers=auth_headers)


@pytest.fixture
def entity_type_id(auth_headers, domain_id):
    """An `employee` type with two optional attributes, so the scenario can
    have one client edit a column and another edit the attributes."""
    client = TestClient(app)
    response = client.post(
        "/api/v1/entity-types",
        json={"domain_id": domain_id, "name": "employee", "role": "agent"},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    type_id = response.json()["id"]
    for name in ("grade", "note"):
        created = client.post(
            f"/api/v1/entity-types/{type_id}/attributes",
            json={"name": name, "data_type": "integer" if name == "grade" else "text"},
            headers=auth_headers,
        )
        assert created.status_code == 201, created.text
    return type_id


@pytest.fixture
def entity(auth_headers, entity_type_id):
    client = TestClient(app)
    response = client.post(
        "/api/v1/entities",
        json={
            "entity_type_id": entity_type_id,
            "key": "ahmed",
            "label": "Ahmed",
            "attrs": {"grade": 3, "note": "original"},
        },
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def relationship_type(auth_headers, domain_id, entity_type_id):
    client = TestClient(app)
    response = client.post(
        "/api/v1/relationship-types",
        json={
            "domain_id": domain_id,
            "name": "reports_to",
            "from_type_id": entity_type_id,
            "to_type_id": entity_type_id,
            "cardinality": "one_to_many",
        },
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def other_entity(auth_headers, entity_type_id):
    client = TestClient(app)
    response = client.post(
        "/api/v1/entities",
        json={"entity_type_id": entity_type_id, "key": "bilal", "label": "Bilal", "attrs": {}},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def relationship(auth_headers, relationship_type, entity, other_entity):
    client = TestClient(app)
    response = client.post(
        "/api/v1/relationships",
        json={
            "relationship_type_id": relationship_type["id"],
            "from_entity_id": entity["id"],
            "to_entity_id": other_entity["id"],
            "attrs": {"weight": 1},
        },
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _assert_stale_conflict(response) -> str:
    """A refusal is a 409 with a **string** `detail` carrying the phrase the
    browser keys on -- not a 422 (no field in the payload is wrong) and not
    an object body (Ruling 19 leaves the platform exactly two shapes)."""
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert isinstance(detail, str), response.text
    assert STALE_PREFIX in detail, detail
    return detail


@pytest.fixture
def parameter(auth_headers, domain_id, entity_type_id):
    """A one-index grid so a cell is addressed by a single entity."""
    client = TestClient(app)
    response = client.post(
        "/api/v1/parameters",
        json={
            "domain_id": domain_id,
            "name": "headcount",
            "index_type_ids": [entity_type_id],
            "default_value": 0,
        },
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def stored_cell(auth_headers, parameter, entity):
    """One stored cell, returned as the values payload so the test can
    send back the `updated_at` the GET (and the PUT response) carries."""
    client = TestClient(app)
    response = client.put(
        f"/api/v1/parameters/{parameter['id']}/values",
        json={"cells": [{"entity_ids": [entity["id"]], "value": 5}]},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    cells = response.json()["cells"]
    assert len(cells) == 1, response.text
    return {"parameter_id": parameter["id"], "cell": cells[0]}


# --- the column and its trigger --------------------------------------------


def test_every_form_backed_table_has_updated_at():
    db = SessionLocal()
    try:
        for table in FORM_TABLES:
            row = db.execute(
                text(
                    "SELECT data_type, is_nullable FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = :t "
                    "AND column_name = 'updated_at'"
                ),
                {"t": table},
            ).first()
            assert row is not None, f"{table}.updated_at is missing"
            assert row[0] == "timestamp with time zone", (table, row[0])
            assert row[1] == "NO", (table, row[1])
    finally:
        db.close()


def test_a_trigger_maintains_it_so_every_writer_is_covered():
    """Not a router concern: the seed writes through the ORM and migrations
    write raw SQL, so the column has to move for a statement no application
    code ever sees."""
    db = SessionLocal()
    try:
        for table in FORM_TABLES:
            row = db.execute(
                text(
                    "SELECT tgname, pg_get_triggerdef(oid) FROM pg_trigger "
                    "WHERE tgrelid = cast(:t AS regclass) AND NOT tgisinternal "
                    "AND tgname = :name"
                ),
                {"t": table, "name": f"{table}_set_updated_at"},
            ).first()
            assert row is not None, f"{table} has no set_updated_at trigger"
            definition = row[1]
            assert "BEFORE INSERT OR UPDATE" in definition, definition
            assert "FOR EACH ROW" in definition, definition
    finally:
        db.close()


def test_raw_sql_moves_it_too(auth_headers, entity):
    """The point of the trigger, stated as a test: a writer that never goes
    near `app/api` still moves the timestamp."""
    db = SessionLocal()
    try:
        before = db.execute(
            text("SELECT updated_at FROM entity WHERE id = :id"), {"id": entity["id"]}
        ).scalar_one()
        db.execute(
            text("UPDATE entity SET label = 'by raw sql' WHERE id = :id"), {"id": entity["id"]}
        )
        db.commit()
        after = db.execute(
            text("SELECT updated_at FROM entity WHERE id = :id"), {"id": entity["id"]}
        ).scalar_one()
        assert after > before
    finally:
        db.close()


def test_an_update_that_changes_nothing_does_not_move_it(auth_headers, entity):
    """Otherwise a no-op write would make every other open form stale for
    no reason."""
    db = SessionLocal()
    try:
        before = db.execute(
            text("SELECT updated_at FROM entity WHERE id = :id"), {"id": entity["id"]}
        ).scalar_one()
        db.execute(
            text("UPDATE entity SET label = label WHERE id = :id"), {"id": entity["id"]}
        )
        db.commit()
        after = db.execute(
            text("SELECT updated_at FROM entity WHERE id = :id"), {"id": entity["id"]}
        ).scalar_one()
        assert after == before
    finally:
        db.close()


def test_two_updates_in_one_transaction_get_two_timestamps(entity):
    """`clock_timestamp()`, not `now()`: `now()` is transaction start time,
    so a row modified twice in one transaction would come out claiming it
    had been modified once."""
    db = SessionLocal()
    try:
        db.execute(text("UPDATE entity SET label = 'a' WHERE id = :id"), {"id": entity["id"]})
        first = db.execute(
            text("SELECT updated_at FROM entity WHERE id = :id"), {"id": entity["id"]}
        ).scalar_one()
        db.execute(text("UPDATE entity SET label = 'b' WHERE id = :id"), {"id": entity["id"]})
        second = db.execute(
            text("SELECT updated_at FROM entity WHERE id = :id"), {"id": entity["id"]}
        ).scalar_one()
        assert second > first
        db.rollback()
    finally:
        db.close()


# --- the read routes carry it ----------------------------------------------


def test_the_entity_read_routes_carry_updated_at(auth_headers, entity, entity_type_id):
    client = TestClient(app)
    one = client.get(f"/api/v1/entities/{entity['id']}", headers=auth_headers)
    assert one.status_code == 200, one.text
    assert one.json()["updated_at"] == entity["updated_at"]

    listed = client.get(
        f"/api/v1/entities?entity_type_id={entity_type_id}", headers=auth_headers
    )
    assert listed.status_code == 200, listed.text
    assert all("updated_at" in item for item in listed.json()["items"])


def test_the_entity_type_read_routes_carry_updated_at(auth_headers, domain_id, entity_type_id):
    client = TestClient(app)
    one = client.get(f"/api/v1/entity-types/{entity_type_id}", headers=auth_headers)
    assert one.status_code == 200, one.text
    assert isinstance(one.json()["updated_at"], str)

    listed = client.get(f"/api/v1/entity-types?domain_id={domain_id}", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    assert all("updated_at" in item for item in listed.json()["items"])


def test_the_relationship_type_read_routes_carry_updated_at(
    auth_headers, domain_id, relationship_type
):
    client = TestClient(app)
    one = client.get(
        f"/api/v1/relationship-types/{relationship_type['id']}", headers=auth_headers
    )
    assert one.status_code == 200, one.text
    assert one.json()["updated_at"] == relationship_type["updated_at"]

    listed = client.get(
        f"/api/v1/relationship-types?domain_id={domain_id}", headers=auth_headers
    )
    assert listed.status_code == 200, listed.text
    assert all("updated_at" in item for item in listed.json()["items"])


def test_the_relationship_read_routes_carry_updated_at(auth_headers, relationship):
    client = TestClient(app)
    one = client.get(f"/api/v1/relationships/{relationship['id']}", headers=auth_headers)
    assert one.status_code == 200, one.text
    assert one.json()["updated_at"] == relationship["updated_at"]
    listed = client.get(
        f"/api/v1/relationships?relationship_type_id={relationship['relationship_type_id']}",
        headers=auth_headers,
    )
    assert listed.status_code == 200, listed.text
    assert all("updated_at" in item for item in listed.json()["items"])


# --- the scenario, over HTTP -----------------------------------------------


def test_the_reported_scenario_is_refused(auth_headers, entity):
    """The exact sequence the review demonstrated.

    Client A opens the entity. Client B changes two attributes. Client A
    changes only the Label and saves -- sending the whole attribute set it
    loaded, which is what Tasks 11/12 require it to send.
    """
    client = TestClient(app)
    a_loaded = entity

    b = client.patch(
        f"/api/v1/entities/{entity['id']}",
        json={"attrs": {"grade": 9, "note": "changed by B"}},
        headers=auth_headers,
    )
    assert b.status_code == 200, b.text

    a_save = client.patch(
        f"/api/v1/entities/{entity['id']}",
        json={
            "key": a_loaded["key"],
            "label": "Ahmed (edited by A)",
            "sort_order": a_loaded["sort_order"],
            "active": a_loaded["active"],
            "attrs": a_loaded["attrs"],
            "updated_at": a_loaded["updated_at"],
        },
        headers=auth_headers,
    )
    detail = _assert_stale_conflict(a_save)
    assert "entity" in detail

    # B's work survived and A's did not land: a refusal that had already
    # written half the payload would be worse than the defect.
    current = client.get(f"/api/v1/entities/{entity['id']}", headers=auth_headers).json()
    assert current["attrs"] == {"grade": 9, "note": "changed by B"}
    assert current["label"] == "Ahmed"


def test_the_same_save_succeeds_once_it_is_rebuilt_on_the_current_read(auth_headers, entity):
    """The refusal is recoverable, which is the whole point of offering a
    reload: re-read, keep what the user typed, send again."""
    client = TestClient(app)
    client.patch(
        f"/api/v1/entities/{entity['id']}",
        json={"attrs": {"grade": 9, "note": "changed by B"}},
        headers=auth_headers,
    )
    fresh = client.get(f"/api/v1/entities/{entity['id']}", headers=auth_headers).json()
    retry = client.patch(
        f"/api/v1/entities/{entity['id']}",
        json={
            "label": "Ahmed (edited by A)",
            "attrs": fresh["attrs"],
            "updated_at": fresh["updated_at"],
        },
        headers=auth_headers,
    )
    assert retry.status_code == 200, retry.text
    assert retry.json()["label"] == "Ahmed (edited by A)"
    # B's attributes are still there: the retry carried them because the
    # reload merged them in, not because the payload was narrowed.
    assert retry.json()["attrs"] == {"grade": 9, "note": "changed by B"}
    # And the response's own timestamp has moved, so the form can save
    # again without a second reload.
    assert retry.json()["updated_at"] != fresh["updated_at"]


def test_an_unchanged_updated_at_is_accepted(auth_headers, entity):
    client = TestClient(app)
    response = client.patch(
        f"/api/v1/entities/{entity['id']}",
        json={"label": "no conflict", "updated_at": entity["updated_at"]},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["label"] == "no conflict"


def test_updated_at_is_not_writable(auth_headers, entity):
    """The client sends it to be *compared*, never to be stored -- the
    trigger is the only writer. A payload that carried it into `setattr`
    would let a client freeze its own row's timestamp and defeat the check
    for everyone else."""
    client = TestClient(app)
    response = client.patch(
        f"/api/v1/entities/{entity['id']}",
        json={"label": "x", "updated_at": entity["updated_at"]},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["updated_at"] != entity["updated_at"]


def test_a_stale_entity_type_save_is_refused(auth_headers, entity_type_id):
    client = TestClient(app)
    loaded = client.get(f"/api/v1/entity-types/{entity_type_id}", headers=auth_headers).json()
    other = client.patch(
        f"/api/v1/entity-types/{entity_type_id}",
        json={"colour": "#123456"},
        headers=auth_headers,
    )
    assert other.status_code == 200, other.text

    refused = client.patch(
        f"/api/v1/entity-types/{entity_type_id}",
        json={"name": "renamed", "role": loaded["role"], "updated_at": loaded["updated_at"]},
        headers=auth_headers,
    )
    detail = _assert_stale_conflict(refused)
    assert "entity type" in detail
    current = client.get(f"/api/v1/entity-types/{entity_type_id}", headers=auth_headers).json()
    assert current["name"] == "employee"
    assert current["colour"] == "#123456"


def test_a_stale_relationship_type_save_is_refused(auth_headers, relationship_type):
    client = TestClient(app)
    loaded = relationship_type
    other = client.patch(
        f"/api/v1/relationship-types/{relationship_type['id']}",
        json={"colour": "#654321"},
        headers=auth_headers,
    )
    assert other.status_code == 200, other.text

    refused = client.patch(
        f"/api/v1/relationship-types/{relationship_type['id']}",
        json={"name": "renamed", "updated_at": loaded["updated_at"]},
        headers=auth_headers,
    )
    detail = _assert_stale_conflict(refused)
    assert "relationship type" in detail
    current = client.get(
        f"/api/v1/relationship-types/{relationship_type['id']}", headers=auth_headers
    ).json()
    assert current["name"] == "reports_to"


def test_a_stale_relationship_save_is_refused(auth_headers, relationship):
    """The graph panel writes the whole attrs object. Two clients opening
    the same edge is the same defect 0010 closed for entities."""
    client = TestClient(app)
    loaded = relationship
    other = client.patch(
        f"/api/v1/relationships/{relationship['id']}",
        json={"attrs": {"weight": 9}},
        headers=auth_headers,
    )
    assert other.status_code == 200, other.text

    refused = client.patch(
        f"/api/v1/relationships/{relationship['id']}",
        json={"attrs": loaded["attrs"], "updated_at": loaded["updated_at"]},
        headers=auth_headers,
    )
    detail = _assert_stale_conflict(refused)
    assert "relationship" in detail
    current = client.get(
        f"/api/v1/relationships/{relationship['id']}", headers=auth_headers
    ).json()
    assert current["attrs"] == {"weight": 9}


def test_the_parameter_values_read_carries_updated_at_on_stored_cells(
    auth_headers, stored_cell
):
    client = TestClient(app)
    response = client.get(
        f"/api/v1/parameters/{stored_cell['parameter_id']}/values",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    cells = response.json()["cells"]
    assert len(cells) == 1
    assert isinstance(cells[0]["updated_at"], str)
    assert cells[0]["updated_at"] == stored_cell["cell"]["updated_at"]
    assert cells[0]["value"] == 5


def test_a_stale_parameter_cell_save_is_refused(auth_headers, stored_cell):
    """The grid sends only dirty cells, so two people editing different
    cells do not collide. Two people typing the same cell still can, and
    that is the overwrite this check refuses."""
    client = TestClient(app)
    loaded = stored_cell["cell"]
    path = f"/api/v1/parameters/{stored_cell['parameter_id']}/values"
    other = client.put(
        path,
        json={"cells": [{"entity_ids": loaded["entity_ids"], "value": 9}]},
        headers=auth_headers,
    )
    assert other.status_code == 200, other.text

    refused = client.put(
        path,
        json={
            "cells": [
                {
                    "entity_ids": loaded["entity_ids"],
                    "value": 7,
                    "updated_at": loaded["updated_at"],
                }
            ]
        },
        headers=auth_headers,
    )
    detail = _assert_stale_conflict(refused)
    assert "parameter cell" in detail
    current = client.get(path, headers=auth_headers).json()
    assert current["cells"][0]["value"] == 9


def test_a_stale_cell_does_not_write_the_other_cells_in_the_same_put(
    auth_headers, stored_cell, other_entity
):
    """The PUT is already atomic for a 422; a 409 has to be the same,
    otherwise the client that lost the race still changed a different
    cell it happened to send in the same request."""
    client = TestClient(app)
    loaded = stored_cell["cell"]
    path = f"/api/v1/parameters/{stored_cell['parameter_id']}/values"
    other = client.put(
        path,
        json={"cells": [{"entity_ids": loaded["entity_ids"], "value": 9}]},
        headers=auth_headers,
    )
    assert other.status_code == 200, other.text

    refused = client.put(
        path,
        json={
            "cells": [
                {
                    "entity_ids": loaded["entity_ids"],
                    "value": 7,
                    "updated_at": loaded["updated_at"],
                },
                {"entity_ids": [other_entity["id"]], "value": 3},
            ]
        },
        headers=auth_headers,
    )
    _assert_stale_conflict(refused)
    current = client.get(path, headers=auth_headers).json()
    assert [cell["value"] for cell in current["cells"]] == [9]


def test_resetting_a_cell_that_someone_else_already_cleared_is_refused(
    auth_headers, stored_cell, parameter
):
    """Sparse storage deletes a cell set to the default. Client A still
    holds the timestamp of a row that B has already removed."""
    client = TestClient(app)
    loaded = stored_cell["cell"]
    path = f"/api/v1/parameters/{stored_cell['parameter_id']}/values"
    cleared = client.put(
        path,
        json={"cells": [{"entity_ids": loaded["entity_ids"], "value": parameter["default_value"]}]},
        headers=auth_headers,
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["cells"] == []

    refused = client.put(
        path,
        json={
            "cells": [
                {
                    "entity_ids": loaded["entity_ids"],
                    "value": 7,
                    "updated_at": loaded["updated_at"],
                }
            ]
        },
        headers=auth_headers,
    )
    _assert_stale_conflict(refused)
    current = client.get(path, headers=auth_headers).json()
    assert current["cells"] == []


def test_omitting_updated_at_on_a_parameter_cell_keeps_last_save_wins(
    auth_headers, stored_cell
):
    client = TestClient(app)
    loaded = stored_cell["cell"]
    path = f"/api/v1/parameters/{stored_cell['parameter_id']}/values"
    other = client.put(
        path,
        json={"cells": [{"entity_ids": loaded["entity_ids"], "value": 9}]},
        headers=auth_headers,
    )
    assert other.status_code == 200, other.text
    response = client.put(
        path,
        json={"cells": [{"entity_ids": loaded["entity_ids"], "value": 7}]},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["cells"][0]["value"] == 7


def test_editing_an_attribute_definition_does_not_make_the_type_stale(
    auth_headers, entity_type_id
):
    """`updated_at` is the type's OWN row. An attribute definition has its
    own routes and its own single-field writes, so touching one must not
    invalidate a type form that is open beside it -- otherwise the editor
    would refuse itself."""
    client = TestClient(app)
    loaded = client.get(f"/api/v1/entity-types/{entity_type_id}", headers=auth_headers).json()
    attribute_id = loaded["attributes"][0]["id"]
    changed = client.patch(
        f"/api/v1/attributes/{attribute_id}", json={"unit": "points"}, headers=auth_headers
    )
    assert changed.status_code == 200, changed.text

    saved = client.patch(
        f"/api/v1/entity-types/{entity_type_id}",
        json={"role": "resource", "updated_at": loaded["updated_at"]},
        headers=auth_headers,
    )
    assert saved.status_code == 200, saved.text


# --- the escape hatch ------------------------------------------------------


@pytest.mark.parametrize("table", TABLES)
def test_omitting_updated_at_keeps_the_pre_0010_behaviour(
    auth_headers, entity, entity_type_id, relationship_type, relationship, table
):
    """Every caller that predates the column keeps working: the graph's
    node rename, `scripts/graph_smoke_check.py`, the seed, `curl`.
    Opting in is what the forms that can lose a concurrent edit do."""
    client = TestClient(app)
    path, payload = {
        "entity": (f"/api/v1/entities/{entity['id']}", {"label": "no check"}),
        "entity_type": (f"/api/v1/entity-types/{entity_type_id}", {"colour": "#abcdef"}),
        "relationship_type": (
            f"/api/v1/relationship-types/{relationship_type['id']}",
            {"colour": "#fedcba"},
        ),
        "relationship": (
            f"/api/v1/relationships/{relationship['id']}",
            {"attrs": {"weight": 2}},
        ),
    }[table]
    # Something else writes the row first, so the read the caller never
    # took would have been stale if it had taken one.
    db = SessionLocal()
    try:
        row_id = {
            "entity": entity["id"],
            "entity_type": entity_type_id,
            "relationship_type": relationship_type["id"],
            "relationship": relationship["id"],
        }[table]
        db.execute(
            text(f"UPDATE {table} SET updated_at = updated_at - interval '1 second' WHERE id = :id"),
            {"id": row_id},
        )
        db.commit()
    finally:
        db.close()

    response = client.patch(path, json=payload, headers=auth_headers)
    assert response.status_code == 200, response.text


def test_an_explicit_null_updated_at_is_no_check_not_a_refusal(auth_headers, entity):
    """`exclude_unset` cannot tell "absent" from "null" once a client sends
    the key with a null in it, and a form that has not loaded a timestamp
    yet (a freshly created record) is the realistic source of one."""
    client = TestClient(app)
    response = client.patch(
        f"/api/v1/entities/{entity['id']}",
        json={"label": "explicit null", "updated_at": None},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text


def test_a_malformed_updated_at_is_a_422_naming_the_field(auth_headers, entity):
    client = TestClient(app)
    response = client.patch(
        f"/api/v1/entities/{entity['id']}",
        json={"label": "x", "updated_at": "not a timestamp"},
        headers=auth_headers,
    )
    assert response.status_code == 422, response.text
    locs = [[str(p) for p in entry["loc"]] for entry in response.json()["detail"]]
    assert ["body", "updated_at"] in locs, locs


def test_a_stale_save_against_a_missing_row_is_still_a_404(auth_headers, entity):
    """The row is resolved before the comparison, so a deleted record says
    so rather than blaming a conflict."""
    client = TestClient(app)
    assert (
        client.delete(f"/api/v1/entities/{entity['id']}", headers=auth_headers).status_code == 204
    )
    response = client.patch(
        f"/api/v1/entities/{entity['id']}",
        json={"label": "x", "updated_at": entity["updated_at"]},
        headers=auth_headers,
    )
    assert response.status_code == 404, response.text
