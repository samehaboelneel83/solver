"""Parameter definitions and the sparse value grid (`app/api/parameters.py`),
plus how `snapshot_dataset()` resolves a sparse grid (migration 0009) and
keeps both ends of a self-indexed parameter (migration 0025).

What is pinned here, and why each is shaped the way it is:

**1. Who answers which 422.**  `parameter_def` has no trigger -- its rules
are plain CHECKs, which `translate_db_error` would map to a *409*
(Ruling 16) -- so the router answers them, and those 422s carry no `kind`.
`parameter_value` *does* have a trigger (`parameter_value_validate`,
migration 0006), whose 422 carries `kind="parameter_index"`.  Every error
test asserts the presence or absence of `kind`, because a test that checked
only the status would not tell the two layers apart.

**2. Strict integers.**  `parameter_value.value` and
`parameter_def.default_value` are `int` columns.  Postgres *rounds* a
numeric into an int column (`5.5` -> `6`), so a lax validator that let a
float through would not merely be refused later -- it would be silently
stored as a different number.  `"5"`, `5.5`, `5.0` and `true` are all
refused by the request layer; the tests prove "before the database" by
putting a valid cell *first* in the same batch and asserting it was not
stored either (a handler that ran would have written it).

**3. Sparse storage.**  A cell equal to `default_value` is deleted, not
stored -- asserted against the table directly, not only via the GET.

**4. Stable order.**  The fixture's entities are deliberately created so
that insertion order, id order, key order and `sort_order` all disagree
with the order the grid promises (see `grid`).  An order that merely
happened to match insertion would pass a weaker fixture and pin nothing.

**5. Self-indexed parameters.**  `distance[day, day]` is accepted by the
router and by raw SQL. A snapshot of it keys cells `"0"`/`"1"`, so
`(mon, tue)` and `(tue, mon)` both survive.

**6. Obligation B, resolved.**  `test_snapshot_resolves_a_cell_reset_to_the_default`
was Task 8's KNOWN GAP test; since migration 0009 (Ruling 28) the snapshot
carries `parameter_defaults`, and the test asserts the resolved behaviour.

Test hygiene: rows made through HTTP are committed by the app, so a
test-side rollback cannot undo them.  Everything hangs off one `domain`
row which the `domain_id` fixture deletes in a `finally`; `ON DELETE
CASCADE` takes the entity types, entities, parameter defs and values with
it.  Raw-SQL tests use the `db` fixture, which only ever rolls back.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.api.parameters import _get_parameter
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.main import app
from app.seed import seed_admin

# The widest value `numeric(15, 6)` holds, and the finest. Nine integer
# digits and six decimal places (migration 0015).
NUMERIC_MAX = 10**9 - 1
TOO_PRECISE = 1.0000005


@pytest.fixture(autouse=True)
def ensure_admin_seeded():
    db = SessionLocal()
    seed_admin(db)
    db.close()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_headers(client):
    settings = get_settings()
    response = client.post(
        "/api/auth/login",
        data={"username": settings.admin_username, "password": settings.admin_password},
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def domain_id(client, auth_headers):
    """A throwaway domain, deleted in a `finally`. Everything a test makes
    hangs off it and cascades away with it."""
    response = client.post(
        "/api/domain/",
        json={"name": f"param-test-{uuid.uuid4().hex[:8]}"},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    created_id = response.json()["id"]
    try:
        yield created_id
    finally:
        client.delete(f"/api/domain/{created_id}", headers=auth_headers)


@pytest.fixture
def db(domain_id):
    """A raw session that only ever rolls back. Depends on `domain_id` so it
    is torn down *before* the domain is deleted."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def _type(client, auth_headers, domain_id, name, role="other") -> int:
    response = client.post(
        "/api/v1/entity-types",
        json={"domain_id": domain_id, "name": name, "role": role},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _entity(client, auth_headers, entity_type_id, key, sort_order=0) -> int:
    response = client.post(
        "/api/v1/entities",
        json={"entity_type_id": entity_type_id, "key": key, "sort_order": sort_order},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.fixture
def grid(client, auth_headers, domain_id):
    """`day` and `shift`, with entities whose four candidate orders disagree.

    The grid promises: cells ordered by their coordinates left to right,
    each coordinate by the entity's `(sort_order, key)`. Here:

    * **insertion / id order** of days is thu, wed, sat, fri, mon, tue;
    * **key order** is fri, mon, sat, thu, tue, wed;
    * **sort_order** is mon=0, tue=1, wed=2, thu=3, and fri/sat tie at 4 --
      with `sat` inserted first, so only the `key` tiebreaker puts `fri`
      before it.

    Shifts are inserted night, afternoon, morning; key order is afternoon,
    morning, night; sort_order is morning=0, afternoon=1, night=2.
    """
    day = _type(client, auth_headers, domain_id, "day", "time")
    shift = _type(client, auth_headers, domain_id, "shift", "time")
    days = {}
    for key, order in (("thu", 3), ("wed", 2), ("sat", 4), ("fri", 4), ("mon", 0), ("tue", 1)):
        days[key] = _entity(client, auth_headers, day, key, order)
    shifts = {}
    for key, order in (("night", 2), ("afternoon", 1), ("morning", 0)):
        shifts[key] = _entity(client, auth_headers, shift, key, order)
    return {"day": day, "shift": shift, "days": days, "shifts": shifts}


def _make_def(client, auth_headers, domain_id, **payload):
    body = {"domain_id": domain_id, **payload}
    return client.post("/api/v1/parameters", json=body, headers=auth_headers)


def _def_id(client, auth_headers, domain_id, **payload) -> int:
    response = _make_def(client, auth_headers, domain_id, **payload)
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.fixture
def demand(client, auth_headers, domain_id, grid) -> int:
    """demand[day, shift], default 2."""
    return _def_id(
        client,
        auth_headers,
        domain_id,
        name="demand",
        index_type_ids=[grid["day"], grid["shift"]],
        default_value=2,
        unit="people",
    )


def _put(client, auth_headers, parameter_id, cells):
    return client.put(
        f"/api/v1/parameters/{parameter_id}/values",
        json={"cells": cells},
        headers=auth_headers,
    )


def _get_values(client, auth_headers, parameter_id) -> dict:
    response = client.get(f"/api/v1/parameters/{parameter_id}/values", headers=auth_headers)
    assert response.status_code == 200, response.text
    return response.json()


def _plain_cells(payload) -> list[dict]:
    """entity_ids and value only. `updated_at` is asserted present so a
    GET that dropped it cannot hide behind this helper."""
    cells = payload["cells"] if isinstance(payload, dict) else payload
    plain = []
    for cell in cells:
        assert isinstance(cell.get("updated_at"), str), cell
        plain.append({"entity_ids": cell["entity_ids"], "value": cell["value"]})
    return plain


def _stored(db, parameter_id) -> dict[tuple, int]:
    """The table itself, bypassing the router."""
    rows = db.execute(
        text("SELECT entity_ids, value FROM parameter_value WHERE parameter_def_id = :p"),
        {"p": parameter_id},
    ).all()
    return {tuple(ids): value for ids, value in rows}


def _request_layer_errors(response) -> list[dict]:
    """A 422 answered by the router / Pydantic: list-shaped, and no `kind`
    (only `translate_db_error` adds `kind`)."""
    assert response.status_code == 422, response.text
    detail = response.json().get("detail")
    assert isinstance(detail, list) and detail, detail
    for entry in detail:
        assert {"loc", "msg", "type"} <= set(entry), entry
        assert "kind" not in entry, f"the database answered, not the request layer: {entry!r}"
    return detail


def _blamed(detail: list[dict], *loc) -> dict:
    wanted = ["body", *[str(part) for part in loc]]
    matches = [e for e in detail if [str(p) for p in e["loc"]] == wanted]
    assert matches, f"no error at {wanted}; got {[e['loc'] for e in detail]}"
    return matches[0]


def _trigger_error(response) -> dict:
    """`parameter_value_validate`'s 422: one list entry carrying `kind`."""
    assert response.status_code == 422, response.text
    detail = response.json().get("detail")
    assert isinstance(detail, list) and len(detail) == 1, detail
    entry = detail[0]
    assert set(entry) == {"type", "loc", "msg", "kind"}, entry
    assert isinstance(entry["msg"], str) and entry["msg"], entry
    return entry


# --- parameter definitions -------------------------------------------------


def test_routes_require_authentication(client):
    assert client.get("/api/v1/parameters").status_code == 401
    assert client.get("/api/v1/parameters/1/values").status_code == 401
    assert client.put("/api/v1/parameters/1/values", json={"cells": []}).status_code == 401


def test_create_parameter_def(client, auth_headers, domain_id, grid):
    response = _make_def(
        client,
        auth_headers,
        domain_id,
        name="demand",
        index_type_ids=[grid["shift"], grid["day"]],
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body == {
        "id": body["id"],
        "domain_id": domain_id,
        "name": "demand",
        # Index order is meaningful and kept exactly as given, not sorted.
        "index_type_ids": [grid["shift"], grid["day"]],
        "default_value": 0,  # the column default
        "unit": None,
    }


def test_get_list_patch_delete_parameter_def(client, auth_headers, domain_id, grid, demand):
    other = _def_id(
        client, auth_headers, domain_id, name="capacity", index_type_ids=[grid["shift"]]
    )

    listed = client.get(
        "/api/v1/parameters", params={"domain_id": domain_id}, headers=auth_headers
    ).json()
    assert listed["total"] == 2
    assert [item["name"] for item in listed["items"]] == ["capacity", "demand"]

    got = client.get(f"/api/v1/parameters/{demand}", headers=auth_headers).json()
    assert got["default_value"] == 2 and got["unit"] == "people"

    patched = client.patch(
        f"/api/v1/parameters/{demand}",
        json={"default_value": 9, "unit": None},
        headers=auth_headers,
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["default_value"] == 9
    assert patched.json()["unit"] is None

    assert client.delete(f"/api/v1/parameters/{other}", headers=auth_headers).status_code == 204
    assert client.get(f"/api/v1/parameters/{other}", headers=auth_headers).status_code == 404


def test_unknown_parameter_is_404(client, auth_headers):
    for method, path in (
        ("get", "/api/v1/parameters/0"),
        ("patch", "/api/v1/parameters/0"),
        ("delete", "/api/v1/parameters/0"),
        ("get", "/api/v1/parameters/0/values"),
        ("put", "/api/v1/parameters/0/values"),
    ):
        kwargs = {"headers": auth_headers}
        if method in ("patch", "put"):
            kwargs["json"] = {"cells": []} if method == "put" else {"unit": "x"}
        response = getattr(client, method)(path, **kwargs)
        assert response.status_code == 404, (method, path, response.text)


def test_empty_index_type_ids_is_422_not_409(client, auth_headers, domain_id):
    """The DDL's `CHECK (cardinality(index_type_ids) >= 1)` has no DETAIL,
    so left to the database this would be a 409 (Ruling 16)."""
    response = _make_def(client, auth_headers, domain_id, name="demand", index_type_ids=[])
    _blamed(_request_layer_errors(response), "index_type_ids")


def test_self_indexed_parameter_is_accepted(client, auth_headers, domain_id, grid):
    """distance[day, day] is an ordinary parameter. The 0008 CHECK was a
    temporary guard while snapshots keyed cells by type name."""
    response = _make_def(
        client,
        auth_headers,
        domain_id,
        name="distance",
        index_type_ids=[grid["day"], grid["day"]],
    )
    assert response.status_code == 201, response.text
    assert response.json()["index_type_ids"] == [grid["day"], grid["day"]]


def test_patch_to_a_repeated_index_type_is_accepted(client, auth_headers, domain_id, grid):
    parameter = _def_id(
        client, auth_headers, domain_id, name="distance", index_type_ids=[grid["day"]]
    )
    response = client.patch(
        f"/api/v1/parameters/{parameter}",
        json={"index_type_ids": [grid["shift"], grid["shift"]]},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["index_type_ids"] == [grid["shift"], grid["shift"]]


def test_index_type_from_another_domain_or_missing_is_422(client, auth_headers, domain_id, grid):
    foreign_domain = client.post(
        "/api/domain/", json={"name": f"param-other-{uuid.uuid4().hex[:8]}"}, headers=auth_headers
    ).json()["id"]
    try:
        foreign_type = _type(client, auth_headers, foreign_domain, "day")
        for bad in ([grid["day"], foreign_type], [grid["day"], 0]):
            response = _make_def(
                client, auth_headers, domain_id, name="demand", index_type_ids=bad
            )
            _blamed(_request_layer_errors(response), "index_type_ids")
    finally:
        client.delete(f"/api/domain/{foreign_domain}", headers=auth_headers)


@pytest.mark.parametrize("name", ["Demand", "1demand", "demand\n", "de-mand", ""])
def test_invalid_name_is_422(client, auth_headers, domain_id, grid, name):
    response = _make_def(
        client, auth_headers, domain_id, name=name, index_type_ids=[grid["day"]]
    )
    _blamed(_request_layer_errors(response), "name")


def test_duplicate_name_in_a_domain_is_409(client, auth_headers, domain_id, grid, demand):
    response = _make_def(
        client, auth_headers, domain_id, name="demand", index_type_ids=[grid["day"]]
    )
    assert response.status_code == 409, response.text
    assert isinstance(response.json()["detail"], str)


@pytest.mark.parametrize("bad", ["5", True, TOO_PRECISE, NUMERIC_MAX + 1, -(NUMERIC_MAX + 2)])
def test_a_default_the_column_cannot_hold_exactly_is_422(client, auth_headers, domain_id, grid, bad):
    """Decimals are admitted since migration 0015, and the strictness moves
    rather than goes. Postgres *rounds* into `numeric(15, 6)` exactly as it
    rounded into an int, so 1.0000005 would be stored as 1.000001 and nothing
    would say so. `"5"` and `True` are refused on the old footing: a client
    sending either has a type bug."""
    response = _make_def(
        client,
        auth_headers,
        domain_id,
        name="demand",
        index_type_ids=[grid["day"]],
        default_value=bad,
    )
    _blamed(_request_layer_errors(response), "default_value")


@pytest.mark.parametrize("field", ["name", "index_type_ids", "default_value"])
def test_patch_null_for_a_not_null_column_is_422(client, auth_headers, demand, field):
    """Omitting a field means "unchanged"; an explicit null would otherwise
    reach the NOT NULL constraint and come back a 409."""
    response = client.patch(
        f"/api/v1/parameters/{demand}", json={field: None}, headers=auth_headers
    )
    _blamed(_request_layer_errors(response), field)


def test_changing_index_types_is_refused_while_values_are_stored(
    client, auth_headers, grid, demand
):
    """The trigger only judges a `parameter_value` row when *it* is written,
    so re-indexing a parameter under stored cells would leave every one of
    them silently mis-shaped."""
    stored = _put(
        client, auth_headers, demand,
        [{"entity_ids": [grid["days"]["mon"], grid["shifts"]["morning"]], "value": 5}],
    )
    assert stored.status_code == 200, stored.text

    response = client.patch(
        f"/api/v1/parameters/{demand}",
        json={"index_type_ids": [grid["shift"], grid["day"]]},
        headers=auth_headers,
    )
    assert response.status_code == 409, response.text

    # Clearing the grid makes the same change legal.
    cleared = _put(
        client, auth_headers, demand,
        [{"entity_ids": [grid["days"]["mon"], grid["shifts"]["morning"]], "value": 2}],
    )
    assert cleared.status_code == 200, cleared.text
    response = client.patch(
        f"/api/v1/parameters/{demand}",
        json={"index_type_ids": [grid["shift"], grid["day"]]},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["index_type_ids"] == [grid["shift"], grid["day"]]


def test_an_uncommitted_put_blocks_reindex_until_it_commits(demand):
    """PUT holds FOR SHARE on parameter_def; a PATCH that changes the index
    takes FOR UPDATE. Without that lock the PATCH's cell-count can miss an
    uncommitted PUT and leave a cell whose coordinates no longer match.

    The pin is the lock itself: a second session's FOR UPDATE times out
    while the first still holds FOR SHARE, which is the interleaving the
    two ordinary API calls used to be able to hit.
    """
    holder = SessionLocal()
    waiter = SessionLocal()
    try:
        _get_parameter(holder, demand, lock="share")
        waiter.execute(text("SET LOCAL lock_timeout = '250ms'"))
        with pytest.raises(OperationalError) as exc:
            _get_parameter(waiter, demand, lock="update")
        assert exc.value.orig.pgcode == "55P03"
    finally:
        holder.rollback()
        holder.close()
        waiter.rollback()
        waiter.close()


def test_get_does_not_take_the_reindex_lock(client, auth_headers, demand):
    """Readers must not queue behind a writer: GET is AccessShareLock,
    which is compatible with the FOR UPDATE PATCH holds."""
    holder = SessionLocal()
    try:
        _get_parameter(holder, demand, lock="update")
        response = client.get(f"/api/v1/parameters/{demand}", headers=auth_headers)
        assert response.status_code == 200, response.text
    finally:
        holder.rollback()
        holder.close()


# --- the value grid --------------------------------------------------------


def test_values_of_an_empty_grid(client, auth_headers, grid, demand):
    assert _get_values(client, auth_headers, demand) == {
        "index_types": [
            {"id": grid["day"], "name": "day"},
            {"id": grid["shift"], "name": "shift"},
        ],
        "cells": [],
        "default_value": 2,
    }


def test_index_types_follow_index_order_not_id_order(client, auth_headers, domain_id, grid):
    """`shift` was created after `day`, so id order would put it second."""
    parameter = _def_id(
        client,
        auth_headers,
        domain_id,
        name="rota",
        index_type_ids=[grid["shift"], grid["day"]],
    )
    assert _get_values(client, auth_headers, parameter)["index_types"] == [
        {"id": grid["shift"], "name": "shift"},
        {"id": grid["day"], "name": "day"},
    ]


def test_put_upserts_cells(client, auth_headers, db, grid, demand):
    mon, tue = grid["days"]["mon"], grid["days"]["tue"]
    morning = grid["shifts"]["morning"]

    first = _put(
        client, auth_headers, demand,
        [{"entity_ids": [mon, morning], "value": 5}, {"entity_ids": [tue, morning], "value": 7}],
    )
    assert first.status_code == 200, first.text
    second = _put(client, auth_headers, demand, [{"entity_ids": [mon, morning], "value": 6}])
    assert second.status_code == 200, second.text

    # A PUT names cells to set; it does not replace the grid.
    assert _stored(db, demand) == {(mon, morning): 6, (tue, morning): 7}
    # The response is the grid as re-read, same as a GET.
    assert second.json() == _get_values(client, auth_headers, demand)


def test_a_cell_equal_to_the_default_is_deleted_not_stored(client, auth_headers, db, grid, demand):
    mon, morning = grid["days"]["mon"], grid["shifts"]["morning"]
    tue = grid["days"]["tue"]

    _put(
        client, auth_headers, demand,
        [{"entity_ids": [mon, morning], "value": 5}, {"entity_ids": [tue, morning], "value": 7}],
    )
    assert (mon, morning) in _stored(db, demand)

    response = _put(client, auth_headers, demand, [{"entity_ids": [mon, morning], "value": 2}])
    assert response.status_code == 200, response.text

    db.rollback()  # new snapshot: see the committed state
    assert _stored(db, demand) == {(tue, morning): 7}
    assert _plain_cells(response.json()) == [{"entity_ids": [tue, morning], "value": 7}]


def test_setting_a_never_stored_cell_to_the_default_stores_nothing(
    client, auth_headers, db, grid, demand
):
    mon, morning = grid["days"]["mon"], grid["shifts"]["morning"]
    response = _put(client, auth_headers, demand, [{"entity_ids": [mon, morning], "value": 2}])
    assert response.status_code == 200, response.text
    assert _stored(db, demand) == {}


def test_cells_come_back_in_grid_order(client, auth_headers, grid, demand):
    """Coordinates left to right, each by the entity's `(sort_order, key)`.

    Every candidate wrong order is distinguishable here (see `grid`):
    insertion order of the PUT, entity-id order, key order, sort_order
    without the key tiebreak, and sorting by the second coordinate first.
    """
    d, s = grid["days"], grid["shifts"]
    submitted = [
        ("sat", "morning", 11),
        ("thu", "night", 12),
        ("fri", "morning", 13),
        ("tue", "night", 14),
        ("mon", "night", 15),
        ("tue", "morning", 16),
        ("wed", "afternoon", 17),
        ("mon", "afternoon", 18),
        ("thu", "morning", 19),
    ]
    response = _put(
        client,
        auth_headers,
        demand,
        [{"entity_ids": [d[day], s[shift]], "value": v} for day, shift, v in submitted],
    )
    assert response.status_code == 200, response.text

    expected = [
        ("mon", "afternoon", 18),
        ("mon", "night", 15),
        ("tue", "morning", 16),
        ("tue", "night", 14),
        ("wed", "afternoon", 17),
        ("thu", "morning", 19),
        ("thu", "night", 12),
        ("fri", "morning", 13),
        ("sat", "morning", 11),
    ]
    want = [{"entity_ids": [d[day], s[shift]], "value": v} for day, shift, v in expected]
    assert _plain_cells(_get_values(client, auth_headers, demand)) == want
    # And again: stable across reads, not just once.
    assert _plain_cells(_get_values(client, auth_headers, demand)) == want


def test_wrong_arity_is_422_parameter_index(client, auth_headers, db, grid, demand):
    mon, morning = grid["days"]["mon"], grid["shifts"]["morning"]
    response = _put(
        client, auth_headers, demand,
        [{"entity_ids": [mon, morning], "value": 5}, {"entity_ids": [mon], "value": 5}],
    )
    entry = _trigger_error(response)
    assert entry["kind"] == "parameter_index"
    # The failing cell is named by its position in the batch, the same
    # `loc` Pydantic gives a bad `cells[1].value`.
    assert entry["loc"] == ["body", "cells", 1, "entity_ids"]
    # Readable: says what was expected, by type name, in index order.
    assert "day, shift" in entry["msg"]
    # The PUT is atomic: the valid first cell was not kept either.
    assert _stored(db, demand) == {}


def test_right_arity_wrong_types_is_422_parameter_index(client, auth_headers, db, grid, demand):
    """Coordinates swapped: two ids of the right types, in the wrong order."""
    mon, morning = grid["days"]["mon"], grid["shifts"]["morning"]
    response = _put(client, auth_headers, demand, [{"entity_ids": [morning, mon], "value": 5}])
    entry = _trigger_error(response)
    assert entry["kind"] == "parameter_index"
    assert entry["loc"] == ["body", "cells", 0, "entity_ids"]
    assert _stored(db, demand) == {}


def test_nonexistent_entity_is_422_parameter_index(client, auth_headers, grid, demand):
    response = _put(
        client, auth_headers, demand, [{"entity_ids": [grid["days"]["mon"], 0], "value": 5}]
    )
    assert _trigger_error(response)["kind"] == "parameter_index"


def test_a_malformed_cell_is_refused_even_when_its_value_is_the_default(
    client, auth_headers, grid, demand
):
    """A default-valued cell is deleted rather than stored, but it is still
    judged: a wrong-arity cell must not be silently accepted just because
    there was nothing to write."""
    response = _put(
        client, auth_headers, demand, [{"entity_ids": [grid["days"]["mon"]], "value": 2}]
    )
    assert _trigger_error(response)["kind"] == "parameter_index"


@pytest.mark.parametrize("bad", ["5", True, None, TOO_PRECISE, NUMERIC_MAX + 1])
def test_a_value_the_column_cannot_hold_exactly_is_422_before_the_database(
    client, auth_headers, db, grid, demand, bad
):
    """A valid cell comes *first*: had the handler run at all, it would have
    been written. That it was not proves the request layer refused the
    batch before any SQL was issued."""
    mon, tue = grid["days"]["mon"], grid["days"]["tue"]
    morning = grid["shifts"]["morning"]
    response = _put(
        client, auth_headers, demand,
        [{"entity_ids": [mon, morning], "value": 5}, {"entity_ids": [tue, morning], "value": bad}],
    )
    _blamed(_request_layer_errors(response), "cells", 1, "value")
    assert _stored(db, demand) == {}


def test_the_same_cell_twice_in_one_put_is_422(client, auth_headers, db, grid, demand):
    mon, morning = grid["days"]["mon"], grid["shifts"]["morning"]
    response = _put(
        client, auth_headers, demand,
        [{"entity_ids": [mon, morning], "value": 5}, {"entity_ids": [mon, morning], "value": 6}],
    )
    _blamed(_request_layer_errors(response), "cells", 1, "entity_ids")
    assert _stored(db, demand) == {}


def test_deleting_an_entity_removes_its_cells(client, auth_headers, grid, demand):
    mon, tue = grid["days"]["mon"], grid["days"]["tue"]
    morning = grid["shifts"]["morning"]
    _put(
        client, auth_headers, demand,
        [{"entity_ids": [mon, morning], "value": 5}, {"entity_ids": [tue, morning], "value": 7}],
    )
    assert client.delete(f"/api/v1/entities/{mon}", headers=auth_headers).status_code == 204
    assert _plain_cells(_get_values(client, auth_headers, demand)) == [
        {"entity_ids": [tue, morning], "value": 7}
    ]


# --- migration 0025: a repeated index type is a real parameter -------------


def test_self_indexed_parameter_is_accepted_by_the_database(db, domain_id, grid):
    """Raw SQL, bypassing the router: the seed and psql never go through
    the 201, so the CHECK that used to refuse this must be gone."""
    parameter = db.execute(
        text(
            "INSERT INTO parameter_def (domain_id, name, index_type_ids) "
            "VALUES (:d, 'distance', :i) RETURNING id"
        ),
        {"d": domain_id, "i": [grid["day"], grid["day"]]},
    ).scalar_one()
    assert parameter


def test_distinct_index_types_are_still_accepted_by_the_database(db, domain_id, grid):
    parameter = db.execute(
        text(
            "INSERT INTO parameter_def (domain_id, name, index_type_ids) "
            "VALUES (:d, 'rota', :i) RETURNING id"
        ),
        {"d": domain_id, "i": [grid["shift"], grid["day"]]},
    ).scalar_one()
    assert parameter


# --- Obligation B, resolved: the snapshot carries the defaults (Ruling 28) --


def _resolve(data: dict, parameter: str, coordinates: dict) -> int:
    """The solver's rule, as Ruling 28 states it: look the cell up; if it is
    absent, use the parameter's default."""
    for row in data["parameters"][parameter]:
        if {k: v for k, v in row.items() if k != "value"} == coordinates:
            return row["value"]
    return data["parameter_defaults"][parameter]


def test_snapshot_resolves_a_cell_reset_to_the_default(client, auth_headers, db, domain_id, grid, demand):
    """Task 8's KNOWN GAP, now closed by migration 0009.

    This router stores the grid **sparsely** -- a cell reset to
    `default_value` is deleted, not stored -- and `snapshot_dataset()`
    emits only stored rows. Until 0009 nothing in the frozen dataset said
    what an absent cell meant, so (mon, morning) below was unrecoverable.
    The user chose (Ruling 28) to keep sparse storage and have the
    snapshot carry `parameter_defaults` beside the unchanged `parameters`.

    A second domain with its own `demand` (default 9, and a stored cell)
    is present, so a snapshot that looked the default up by name alone
    could pick it up.
    """
    mon, tue = grid["days"]["mon"], grid["days"]["tue"]
    morning = grid["shifts"]["morning"]
    assert _put(
        client, auth_headers, demand,
        [{"entity_ids": [mon, morning], "value": 5}, {"entity_ids": [tue, morning], "value": 7}],
    ).status_code == 200
    # Back to the default (2): the row is deleted.
    assert _put(
        client, auth_headers, demand, [{"entity_ids": [mon, morning], "value": 2}]
    ).status_code == 200

    other = db.execute(
        text("INSERT INTO domain (name) VALUES (:n) RETURNING id"),
        {"n": f"param-other-{uuid.uuid4().hex[:8]}"},
    ).scalar_one()
    other_day = db.execute(
        text("INSERT INTO entity_type (domain_id, name) VALUES (:d, 'day') RETURNING id"),
        {"d": other},
    ).scalar_one()
    other_mon = db.execute(
        text("INSERT INTO entity (entity_type_id, key) VALUES (:t, 'mon') RETURNING id"),
        {"t": other_day},
    ).scalar_one()
    other_demand = db.execute(
        text(
            "INSERT INTO parameter_def (domain_id, name, index_type_ids, default_value) "
            "VALUES (:d, 'demand', :i, 9) RETURNING id"
        ),
        {"d": other, "i": [other_day]},
    ).scalar_one()
    db.execute(
        text(
            "INSERT INTO parameter_value (parameter_def_id, entity_ids, value) VALUES (:p, :e, 4)"
        ),
        {"p": other_demand, "e": [other_mon]},
    )

    problem = db.execute(
        text("INSERT INTO problem (domain_id, name) VALUES (:d, 'p') RETURNING id"),
        {"d": domain_id},
    ).scalar_one()
    model_version = db.execute(
        text(
            "INSERT INTO model_version (problem_id, ir) "
            "VALUES (:p, CAST(:ir AS jsonb)) RETURNING id"
        ),
        {"p": problem, "ir": '{"sets": ["day", "shift"], "parameters": {"demand": {}}}'},
    ).scalar_one()
    dataset = db.execute(text("SELECT snapshot_dataset(:mv)"), {"mv": model_version}).scalar_one()
    data = db.execute(text("SELECT data FROM dataset WHERE id = :d"), {"d": dataset}).scalar_one()

    # `parameters` is unchanged in shape: still only the stored row.
    assert data["parameters"] == {"demand": [{"day": "tue", "shift": "morning", "value": 7}]}
    # ... and the default now travels beside it -- this domain's, not 9.
    assert data["parameter_defaults"] == {"demand": 2}
    assert set(data) == {"sets", "parameters", "parameter_defaults", "relationships", "labels"}

    # So every cell resolves: the reset one to its default, the stored one
    # to its value, and one never touched to the default too.
    assert _resolve(data, "demand", {"day": "mon", "shift": "morning"}) == 2
    assert _resolve(data, "demand", {"day": "tue", "shift": "morning"}) == 7
    assert _resolve(data, "demand", {"day": "wed", "shift": "night"}) == 2


def test_snapshot_keeps_both_coordinates_of_a_self_indexed_parameter(
    client, auth_headers, db, domain_id, grid
):
    """A cell (mon, tue) is not the same as (tue, mon). Snapshots used to
    key both coordinates `day`, so the second overwrote the first."""
    distance = _def_id(
        client,
        auth_headers,
        domain_id,
        name="distance",
        index_type_ids=[grid["day"], grid["day"]],
        default_value=0,
    )
    mon, tue = grid["days"]["mon"], grid["days"]["tue"]
    assert (
        _put(
            client,
            auth_headers,
            distance,
            [
                {"entity_ids": [mon, tue], "value": 4},
                {"entity_ids": [tue, mon], "value": 9},
            ],
        ).status_code
        == 200
    )
    problem = db.execute(
        text("INSERT INTO problem (domain_id, name) VALUES (:d, 'p') RETURNING id"),
        {"d": domain_id},
    ).scalar_one()
    model_version = db.execute(
        text(
            "INSERT INTO model_version (problem_id, ir) "
            "VALUES (:p, CAST(:ir AS jsonb)) RETURNING id"
        ),
        {"p": problem, "ir": '{"sets": ["day"], "parameters": {"distance": {}}}'},
    ).scalar_one()
    dataset = db.execute(text("SELECT snapshot_dataset(:mv)"), {"mv": model_version}).scalar_one()
    data = db.execute(text("SELECT data FROM dataset WHERE id = :d"), {"d": dataset}).scalar_one()
    rows = {(row["0"], row["1"]): row["value"] for row in data["parameters"]["distance"]}
    assert rows == {("mon", "tue"): 4, ("tue", "mon"): 9}


def test_put_refuses_more_cells_than_the_cap(client, auth_headers, demand, monkeypatch):
    """A PUT used to accept an unbounded `cells` list. The cap is lowered
    here so the test does not ship ten thousand rows; Pydantic judges
    length before any cell is written."""
    monkeypatch.setattr("app.api.parameters.PARAMETER_VALUES_MAX_CELLS", 2)
    response = _put(
        client,
        auth_headers,
        demand,
        [
            {"entity_ids": [1, 1], "value": 1},
            {"entity_ids": [1, 2], "value": 1},
            {"entity_ids": [1, 3], "value": 1},
        ],
    )
    entry = _blamed(_request_layer_errors(response), "cells")
    assert "2" in entry["msg"]
