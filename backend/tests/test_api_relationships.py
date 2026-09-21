"""Relationship types, relationships, and the v1 graph read
(`app/api/relationships.py`, `app/api/graph.py`, `app/graph/service.py`).

Three things are pinned here.

**1. The relationship_type CHECKs, answered as 422.**  `relationship_type`
carries no trigger -- its rules are plain table CHECKs, which arrive with
`DETAIL = None` and which `translate_db_error` therefore maps to a *409*
(Ruling 16, established on Task 5's two tables).  The brief requires 422
for the two hierarchy rules, so the router shadows them, exactly as
`entity_types.py` shadows the `enum_values` pairing CHECK.  These tests
assert the **422** and which field is blamed, so a regression to the 409
path cannot pass.

**2. The relationship_validate trigger, answered as 422 with `kind`.**
`relationship` *does* carry a trigger, emitting `type_mismatch`,
`cardinality` and `cycle` -- and unlike `entity_validate`, its `field` is
the relationship type's **name**, not a column name.  Every trigger test
asserts `kind` *and* the blamed field, because a test that checked only
`422` would not tell a trigger refusal from a Pydantic one.

**3. Amendment (c) at the API level.**  Re-pointing an existing hierarchy
edge to a legal new parent must return 200.  The topology in
`test_repointing_a_hierarchy_edge_to_a_legal_parent_is_accepted` is chosen
so that the recursive term of the cycle walk genuinely executes and meets
the *pre-update* version of the row being updated -- see that test's
docstring.  A two-node re-point would pass against a function that only
excludes the row in the anchor term, and so would pin nothing.

Test hygiene: every row is created through a real HTTP POST, which the app
commits inside the request, so a test-side rollback cannot undo it.
Everything hangs off one `domain` row, which the `domain_id` fixture
deletes in a `finally`; `ON DELETE CASCADE` takes the entity types,
entities, relationship types and relationships with it.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.main import app
from app.models.v1_domain import RelationshipType
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
    every entity_type / entity / relationship_type / relationship a test
    hung off it, so nothing this file creates survives its own test."""
    client = TestClient(app)
    response = client.post(
        "/api/domain/",
        json={"name": f"rel-test-{uuid.uuid4().hex[:8]}"},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    created_id = response.json()["id"]
    try:
        yield created_id
    finally:
        client.delete(f"/api/domain/{created_id}", headers=auth_headers)


@pytest.fixture
def types(auth_headers, domain_id):
    """Two entity types: `unit` (org) and `employee` (agent). A hierarchy
    needs from_type = to_type, so `unit` carries the trees; `employee`
    exists so a type mismatch is expressible."""
    client = TestClient(app)
    made = {}
    for name, role in (("unit", "org"), ("employee", "agent")):
        response = client.post(
            "/api/v1/entity-types",
            json={"domain_id": domain_id, "name": name, "role": role},
            headers=auth_headers,
        )
        assert response.status_code == 201, response.text
        made[name] = response.json()["id"]
    return made


# --- helpers ---------------------------------------------------------------


def _validation_errors(response) -> list[dict]:
    """Assert `response` is a 422 answered by the **request layer**.

    Since Ruling 19 a trigger's 422 has the same list envelope, so the
    envelope alone no longer says who answered; the absence of `kind`
    does, because only `translate_db_error` adds it.
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


def _trigger_error(response) -> dict:
    """Assert `response` is `translate_db_error`'s 422 and return it
    normalised to `{message, field, kind}`.

    Task 3 emitted an **object** `detail`; Ruling 19 (Obligation A of task
    7) normalised every 422 on this platform onto FastAPI's **list** shape
    -- one entry per failure, `loc == ["body", <field>]`, the human message
    in `msg`, and the trigger's machine discriminator carried as a sibling
    `kind` key.  The shape assertions below are the pin: a test that
    checked only the status number would pass under either body, and so
    would pin neither.
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
    return {"message": entry["msg"], "field": loc[1] if len(loc) > 1 else None, "kind": entry["kind"]}


def _conflict(response) -> str:
    assert response.status_code == 409, response.text
    detail = response.json().get("detail")
    assert isinstance(detail, str), f"expected a string detail, got {detail!r}"
    return detail


def _make_rel_type(client, auth_headers, domain_id, **payload):
    body = {"domain_id": domain_id, **payload}
    return client.post("/api/v1/relationship-types", json=body, headers=auth_headers)


def _rel_type_id(client, auth_headers, domain_id, **payload) -> int:
    response = _make_rel_type(client, auth_headers, domain_id, **payload)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _entity(client, auth_headers, entity_type_id, key, **extra) -> int:
    response = client.post(
        "/api/v1/entities",
        json={"entity_type_id": entity_type_id, "key": key, **extra},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _make_rel(client, auth_headers, rel_type_id, from_id, to_id, **extra):
    return client.post(
        "/api/v1/relationships",
        json={
            "relationship_type_id": rel_type_id,
            "from_entity_id": from_id,
            "to_entity_id": to_id,
            **extra,
        },
        headers=auth_headers,
    )


def _rel_id(client, auth_headers, rel_type_id, from_id, to_id, **extra) -> int:
    response = _make_rel(client, auth_headers, rel_type_id, from_id, to_id, **extra)
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.fixture
def hierarchy_type_id(auth_headers, domain_id, types):
    client = TestClient(app)
    return _rel_type_id(
        client,
        auth_headers,
        domain_id,
        name="reports_to",
        from_type_id=types["unit"],
        to_type_id=types["unit"],
        cardinality="one_to_many",
        is_hierarchy=True,
    )


# --- relationship_type: the two hierarchy CHECKs, as 422 -------------------


def test_create_relationship_type_defaults(auth_headers, domain_id, types):
    client = TestClient(app)
    response = _make_rel_type(
        client,
        auth_headers,
        domain_id,
        name="works_in",
        from_type_id=types["employee"],
        to_type_id=types["unit"],
    )
    assert response.status_code == 201, response.text
    body = response.json()
    # Both mirror the column server defaults, so the payload may omit them.
    assert body["cardinality"] == "many_to_many"
    assert body["is_hierarchy"] is False
    assert body["domain_id"] == domain_id


def test_hierarchy_with_differing_from_and_to_types_is_422(auth_headers, domain_id, types):
    """`CHECK (NOT is_hierarchy OR (from_type_id = to_type_id AND ...))`.
    A hierarchy nests a type inside itself; two different types cannot."""
    client = TestClient(app)
    response = _make_rel_type(
        client,
        auth_headers,
        domain_id,
        name="reports_to",
        from_type_id=types["unit"],
        to_type_id=types["employee"],
        cardinality="one_to_many",
        is_hierarchy=True,
    )
    entry = _assert_blames_field(_validation_errors(response), "to_type_id")
    assert "hierarch" in entry["msg"].lower(), entry


def test_hierarchy_with_wrong_cardinality_is_422(auth_headers, domain_id, types):
    """The other half of the same CHECK: a hierarchy is one_to_many, so
    that each child has at most one parent."""
    client = TestClient(app)
    response = _make_rel_type(
        client,
        auth_headers,
        domain_id,
        name="reports_to",
        from_type_id=types["unit"],
        to_type_id=types["unit"],
        cardinality="many_to_many",
        is_hierarchy=True,
    )
    entry = _assert_blames_field(_validation_errors(response), "cardinality")
    assert "one_to_many" in entry["msg"], entry


def test_hierarchy_with_matching_types_and_one_to_many_is_created(auth_headers, domain_id, types):
    client = TestClient(app)
    response = _make_rel_type(
        client,
        auth_headers,
        domain_id,
        name="reports_to",
        from_type_id=types["unit"],
        to_type_id=types["unit"],
        cardinality="one_to_many",
        is_hierarchy=True,
    )
    assert response.status_code == 201, response.text
    assert response.json()["is_hierarchy"] is True


def test_patch_to_hierarchy_judges_the_merged_row(auth_headers, domain_id, types):
    """The CHECK is on the row, not the payload. A PATCH naming only
    `is_hierarchy` still has to be judged against the *stored*
    cardinality -- the same reasoning `entity_types.py` records for the
    enum_values pairing."""
    client = TestClient(app)
    rel_type_id = _rel_type_id(
        client,
        auth_headers,
        domain_id,
        name="reports_to",
        from_type_id=types["unit"],
        to_type_id=types["unit"],
        cardinality="many_to_many",
    )
    response = client.patch(
        f"/api/v1/relationship-types/{rel_type_id}",
        json={"is_hierarchy": True},
        headers=auth_headers,
    )
    _assert_blames_field(_validation_errors(response), "cardinality")


def test_patch_cardinality_away_from_one_to_many_on_a_hierarchy_is_422(
    auth_headers, hierarchy_type_id
):
    client = TestClient(app)
    response = client.patch(
        f"/api/v1/relationship-types/{hierarchy_type_id}",
        json={"cardinality": "many_to_many"},
        headers=auth_headers,
    )
    _assert_blames_field(_validation_errors(response), "cardinality")


def test_patch_that_fixes_both_halves_at_once_is_accepted(auth_headers, domain_id, types):
    client = TestClient(app)
    rel_type_id = _rel_type_id(
        client,
        auth_headers,
        domain_id,
        name="reports_to",
        from_type_id=types["unit"],
        to_type_id=types["unit"],
        cardinality="many_to_many",
    )
    response = client.patch(
        f"/api/v1/relationship-types/{rel_type_id}",
        json={"is_hierarchy": True, "cardinality": "one_to_many"},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["is_hierarchy"] is True


@pytest.mark.parametrize("name", ["Reports_To", "1reports", "reports-to", "reports_to\n", ""])
def test_relationship_type_name_must_match_the_ddl_pattern(auth_headers, domain_id, types, name):
    """`CHECK (name ~ '^[a-z][a-z0-9_]*$')`. `"reports_to\\n"` is the case
    Python's `$` would wrongly accept and Postgres's would not -- Task 5
    hit it on `entity_type.name` and the same helper guards it here."""
    client = TestClient(app)
    response = _make_rel_type(
        client,
        auth_headers,
        domain_id,
        name=name,
        from_type_id=types["unit"],
        to_type_id=types["unit"],
    )
    _assert_blames_field(_validation_errors(response), "name")


def test_unknown_cardinality_is_422_not_409(auth_headers, domain_id, types):
    """`cardinality` is a text column with a CHECK, not an enum, so an
    unknown label would otherwise reach the database and come back a 409."""
    client = TestClient(app)
    response = _make_rel_type(
        client,
        auth_headers,
        domain_id,
        name="works_in",
        from_type_id=types["employee"],
        to_type_id=types["unit"],
        cardinality="one_to_zero",
    )
    _assert_blames_field(_validation_errors(response), "cardinality")


def test_duplicate_relationship_type_name_in_one_domain_is_409(auth_headers, domain_id, types):
    client = TestClient(app)
    _rel_type_id(
        client,
        auth_headers,
        domain_id,
        name="works_in",
        from_type_id=types["employee"],
        to_type_id=types["unit"],
    )
    response = _make_rel_type(
        client,
        auth_headers,
        domain_id,
        name="works_in",
        from_type_id=types["employee"],
        to_type_id=types["unit"],
    )
    _conflict(response)


def test_unknown_domain_id_is_409(auth_headers, types):
    client = TestClient(app)
    response = _make_rel_type(
        client,
        auth_headers,
        2_000_000_001,
        name="works_in",
        from_type_id=types["employee"],
        to_type_id=types["unit"],
    )
    _conflict(response)


# --- relationship_type: read, list, delete --------------------------------


def test_list_relationship_types_is_scoped_and_ordered(auth_headers, domain_id, types):
    client = TestClient(app)
    for name in ("works_in", "a_covers", "manages"):
        _rel_type_id(
            client,
            auth_headers,
            domain_id,
            name=name,
            from_type_id=types["employee"],
            to_type_id=types["unit"],
        )
    response = client.get(
        "/api/v1/relationship-types", params={"domain_id": domain_id}, headers=auth_headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 3
    assert [item["name"] for item in body["items"]] == ["a_covers", "manages", "works_in"]


def test_get_relationship_type_404(auth_headers):
    client = TestClient(app)
    response = client.get("/api/v1/relationship-types/2000000002", headers=auth_headers)
    assert response.status_code == 404


def test_delete_relationship_type_removes_its_relationships(
    auth_headers, types, hierarchy_type_id
):
    client = TestClient(app)
    a = _entity(client, auth_headers, types["unit"], "a")
    b = _entity(client, auth_headers, types["unit"], "b")
    rel_id = _rel_id(client, auth_headers, hierarchy_type_id, a, b)

    assert (
        client.delete(
            f"/api/v1/relationship-types/{hierarchy_type_id}", headers=auth_headers
        ).status_code
        == 204
    )
    assert client.get(f"/api/v1/relationships/{rel_id}", headers=auth_headers).status_code == 404


def test_relationship_routes_require_authentication():
    client = TestClient(app)
    assert client.get("/api/v1/relationship-types").status_code == 401
    assert client.get("/api/v1/relationships").status_code == 401
    assert client.get("/api/v1/graph", params={"domain_id": 1}).status_code == 401


# --- relationship: the trigger's three kinds ------------------------------


def test_type_mismatch_is_422_naming_the_relationship_type(auth_headers, domain_id, types):
    """kind 1 of 3. Unlike `entity_validate`, `relationship_validate`'s
    `field` is the relationship type's **name**, not a column."""
    client = TestClient(app)
    rel_type_id = _rel_type_id(
        client,
        auth_headers,
        domain_id,
        name="works_in",
        from_type_id=types["employee"],
        to_type_id=types["unit"],
    )
    wrong = _entity(client, auth_headers, types["unit"], "hq")
    unit = _entity(client, auth_headers, types["unit"], "ops")
    detail = _trigger_error(_make_rel(client, auth_headers, rel_type_id, wrong, unit))
    assert detail["kind"] == "type_mismatch"
    assert detail["field"] == "works_in"
    assert "works_in" in detail["message"], detail


def test_one_to_many_target_already_has_a_source_is_422(auth_headers, types, hierarchy_type_id):
    """kind 2 of 3, first arm: one_to_many means each *target* has at most
    one source, which is what gives a hierarchy a single parent per node."""
    client = TestClient(app)
    a = _entity(client, auth_headers, types["unit"], "a")
    b = _entity(client, auth_headers, types["unit"], "b")
    c = _entity(client, auth_headers, types["unit"], "c")
    _rel_id(client, auth_headers, hierarchy_type_id, a, c)
    detail = _trigger_error(_make_rel(client, auth_headers, hierarchy_type_id, b, c))
    assert detail["kind"] == "cardinality"
    assert detail["field"] == "reports_to"


def test_many_to_one_source_already_has_a_target_is_422(auth_headers, domain_id, types):
    """kind 2 of 3, second arm -- the mirror-image branch of the trigger.
    Without this the first arm alone would pass against a function missing
    the second entirely."""
    client = TestClient(app)
    rel_type_id = _rel_type_id(
        client,
        auth_headers,
        domain_id,
        name="works_in",
        from_type_id=types["employee"],
        to_type_id=types["unit"],
        cardinality="many_to_one",
    )
    employee = _entity(client, auth_headers, types["employee"], "ahmed")
    u1 = _entity(client, auth_headers, types["unit"], "u1")
    u2 = _entity(client, auth_headers, types["unit"], "u2")
    _rel_id(client, auth_headers, rel_type_id, employee, u1)
    detail = _trigger_error(_make_rel(client, auth_headers, rel_type_id, employee, u2))
    assert detail["kind"] == "cardinality"
    assert detail["field"] == "works_in"


def test_one_to_one_rejects_a_second_edge_in_either_direction(auth_headers, domain_id, types):
    client = TestClient(app)
    rel_type_id = _rel_type_id(
        client,
        auth_headers,
        domain_id,
        name="heads",
        from_type_id=types["employee"],
        to_type_id=types["unit"],
        cardinality="one_to_one",
    )
    e1 = _entity(client, auth_headers, types["employee"], "e1")
    e2 = _entity(client, auth_headers, types["employee"], "e2")
    u1 = _entity(client, auth_headers, types["unit"], "u1")
    u2 = _entity(client, auth_headers, types["unit"], "u2")
    _rel_id(client, auth_headers, rel_type_id, e1, u1)

    # same target, different source -- the one_to_many arm
    detail = _trigger_error(_make_rel(client, auth_headers, rel_type_id, e2, u1))
    assert detail["kind"] == "cardinality"
    # same source, different target -- the many_to_one arm
    detail = _trigger_error(_make_rel(client, auth_headers, rel_type_id, e1, u2))
    assert detail["kind"] == "cardinality"


def test_self_loop_on_a_hierarchy_is_a_cycle_422(auth_headers, types, hierarchy_type_id):
    """kind 3 of 3, first case: NEW.from = NEW.to, caught by the trigger's
    equality test before the recursive walk runs at all."""
    client = TestClient(app)
    a = _entity(client, auth_headers, types["unit"], "a")
    detail = _trigger_error(_make_rel(client, auth_headers, hierarchy_type_id, a, a))
    assert detail["kind"] == "cycle"
    assert detail["field"] == "reports_to"


def test_closing_a_four_node_chain_is_a_cycle_422(auth_headers, types, hierarchy_type_id):
    """kind 3 of 3, second case -- the one that needs the recursive walk.

    The chain is deliberately four nodes deep: closing a *two*-node loop
    (a->b then b->a) is caught by the anchor term alone, so it would pass
    against a "cycle check" that never recurses.  Here `d -> a` is only
    reachable from `a` after three recursive steps.
    """
    client = TestClient(app)
    a = _entity(client, auth_headers, types["unit"], "a")
    b = _entity(client, auth_headers, types["unit"], "b")
    c = _entity(client, auth_headers, types["unit"], "c")
    d = _entity(client, auth_headers, types["unit"], "d")
    _rel_id(client, auth_headers, hierarchy_type_id, a, b)
    _rel_id(client, auth_headers, hierarchy_type_id, b, c)
    _rel_id(client, auth_headers, hierarchy_type_id, c, d)

    detail = _trigger_error(_make_rel(client, auth_headers, hierarchy_type_id, d, a))
    assert detail["kind"] == "cycle"
    assert detail["field"] == "reports_to"


def test_a_non_hierarchy_type_does_not_forbid_cycles(auth_headers, domain_id, types):
    """The cycle rule is guarded by `rt.is_hierarchy`. A plain
    many_to_many relationship is allowed to be circular, so this pins that
    the guard is read rather than ignored."""
    client = TestClient(app)
    rel_type_id = _rel_type_id(
        client,
        auth_headers,
        domain_id,
        name="covers",
        from_type_id=types["unit"],
        to_type_id=types["unit"],
    )
    a = _entity(client, auth_headers, types["unit"], "a")
    b = _entity(client, auth_headers, types["unit"], "b")
    _rel_id(client, auth_headers, rel_type_id, a, b)
    assert _make_rel(client, auth_headers, rel_type_id, b, a).status_code == 201
    # ... including a self-loop, which only the hierarchy branch forbids.
    assert _make_rel(client, auth_headers, rel_type_id, a, a).status_code == 201


def test_repointing_a_hierarchy_edge_to_a_legal_parent_is_accepted(
    auth_headers, types, hierarchy_type_id
):
    """Amendment (c), at the API level.

    Topology matters here.  Start with the chain `b -> c -> p -> q` and
    re-point the last edge (`p -> q`) to `q -> b`, producing
    `q -> b -> c -> p`.  Validating that update walks down from
    `NEW.to = b`:

    * the **anchor** term finds `b -> c`, a row that is *not* the one
      under update, so the anchor's `id IS DISTINCT FROM NEW.id` exclusion
      is a no-op there and the walk genuinely continues;
    * the **recursive** term then reaches `p`, where the only outgoing
      edge is the pre-update `p -> q` version of the row being changed.

    Without amendment (c)'s exclusion in the *recursive* term, that edge
    yields `q`, which is `NEW.from`, and the update is wrongly rejected as
    a cycle.  A shallower re-point never reaches the recursive term and so
    would pass against the un-amended function.
    """
    client = TestClient(app)
    b = _entity(client, auth_headers, types["unit"], "b")
    c = _entity(client, auth_headers, types["unit"], "c")
    p = _entity(client, auth_headers, types["unit"], "p")
    q = _entity(client, auth_headers, types["unit"], "q")
    _rel_id(client, auth_headers, hierarchy_type_id, b, c)
    _rel_id(client, auth_headers, hierarchy_type_id, c, p)
    moved = _rel_id(client, auth_headers, hierarchy_type_id, p, q)

    response = client.patch(
        f"/api/v1/relationships/{moved}",
        json={"from_entity_id": q, "to_entity_id": b},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["from_entity_id"] == q
    assert response.json()["to_entity_id"] == b

    # Pin the resulting tree rather than merely "no exception": read the
    # parents back off the graph endpoint.
    graph = client.get(
        "/api/v1/graph",
        params={"domain_id": _domain_of(client, auth_headers, types["unit"]), "hierarchy_type_id": hierarchy_type_id},
        headers=auth_headers,
    ).json()
    parent = {node["id"]: node["parent"] for node in graph["nodes"]}
    assert parent[str(b)] == str(q)
    assert parent[str(c)] == str(b)
    assert parent[str(p)] == str(c)
    assert parent[str(q)] is None


def test_repointing_an_edge_beneath_its_own_old_child_is_accepted(
    auth_headers, types, hierarchy_type_id
):
    """Amendment (c), the *anchor* half -- the complement of the test above.

    Start with `x -> y -> z` and re-point the first edge (`x -> y`) to
    `z -> x`, producing `y -> z -> x`: `x` moves from the top of the chain
    to the bottom, under what used to be its grandchild.  Validating that
    update walks down from `NEW.to = x`, and the only edge leaving `x` is
    the pre-update `x -> y` version of the very row being updated.

    * With the anchor term's exclusion, the walk is empty and the update
      is accepted.
    * Without it, the anchor yields `y`, the recursive term then yields
      `z`, which is `NEW.from`, and the update is wrongly rejected.

    Added because mutation testing showed the test above cannot see this
    half: there the walk starts at a node whose outgoing edge is a
    *different* row, so dropping the anchor's exclusion changed nothing and
    the mutant survived.  Between them the two tests kill each exclusion
    independently.
    """
    client = TestClient(app)
    x = _entity(client, auth_headers, types["unit"], "x")
    y = _entity(client, auth_headers, types["unit"], "y")
    z = _entity(client, auth_headers, types["unit"], "z")
    moved = _rel_id(client, auth_headers, hierarchy_type_id, x, y)
    _rel_id(client, auth_headers, hierarchy_type_id, y, z)

    response = client.patch(
        f"/api/v1/relationships/{moved}",
        json={"from_entity_id": z, "to_entity_id": x},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text

    graph = client.get(
        "/api/v1/graph",
        params={
            "domain_id": _domain_of(client, auth_headers, types["unit"]),
            "hierarchy_type_id": hierarchy_type_id,
        },
        headers=auth_headers,
    ).json()
    parent = {node["id"]: node["parent"] for node in graph["nodes"]}
    assert parent == {str(y): None, str(z): str(y), str(x): str(z)}


def test_repointing_into_a_descendant_is_still_a_cycle_422(
    auth_headers, types, hierarchy_type_id
):
    """The other side of amendment (c): excluding the row under update
    must not disable the cycle rule for updates.

    The edge moved must be one that is *not* on the path it would close.
    `a -> b -> c -> d`, plus a side edge `a -> e`; moving the side edge to
    `d -> a` makes `a` its own great-great-grandparent, and the walk from
    `NEW.to = a` needs three recursive steps to find `d`.

    (The first draft of this test moved `a -> b` itself to `d -> a` and
    expected a cycle. The database accepted it, correctly: moving that edge
    removes the only link from `a` down to `d`, leaving the legal chain
    `b -> c -> d -> a`. Recorded because it is exactly the kind of
    wrong-premise test that would have "caught" a broken amendment.)
    """
    client = TestClient(app)
    a = _entity(client, auth_headers, types["unit"], "a")
    b = _entity(client, auth_headers, types["unit"], "b")
    c = _entity(client, auth_headers, types["unit"], "c")
    d = _entity(client, auth_headers, types["unit"], "d")
    e = _entity(client, auth_headers, types["unit"], "e")
    _rel_id(client, auth_headers, hierarchy_type_id, a, b)
    _rel_id(client, auth_headers, hierarchy_type_id, b, c)
    _rel_id(client, auth_headers, hierarchy_type_id, c, d)
    moved = _rel_id(client, auth_headers, hierarchy_type_id, a, e)

    response = client.patch(
        f"/api/v1/relationships/{moved}",
        json={"from_entity_id": d, "to_entity_id": a},
        headers=auth_headers,
    )
    detail = _trigger_error(response)
    assert detail["kind"] == "cycle"


def _domain_of(client, auth_headers, entity_type_id) -> int:
    return client.get(
        f"/api/v1/entity-types/{entity_type_id}", headers=auth_headers
    ).json()["domain_id"]


# --- relationship: ordinary CRUD ------------------------------------------


def test_duplicate_relationship_is_409(auth_headers, domain_id, types):
    """`UNIQUE (relationship_type_id, from_entity_id, to_entity_id)`.

    The type has to be many_to_many for this to be reachable at all: under
    any narrower cardinality the `relationship_validate` trigger refuses
    the second edge first, with a 422, because it runs BEFORE INSERT and
    the UNIQUE index is only consulted afterwards.  (That is worth pinning
    -- the first draft of this test used the hierarchy type and asserted
    409, and got the trigger's 422 instead.)
    """
    client = TestClient(app)
    covers = _rel_type_id(
        client,
        auth_headers,
        domain_id,
        name="covers",
        from_type_id=types["unit"],
        to_type_id=types["unit"],
    )
    a = _entity(client, auth_headers, types["unit"], "a")
    b = _entity(client, auth_headers, types["unit"], "b")
    _rel_id(client, auth_headers, covers, a, b)
    _conflict(_make_rel(client, auth_headers, covers, a, b))


def test_unknown_entity_id_is_409(auth_headers, types, hierarchy_type_id):
    client = TestClient(app)
    a = _entity(client, auth_headers, types["unit"], "a")
    _conflict(_make_rel(client, auth_headers, hierarchy_type_id, a, 2_000_000_003))


def test_valid_to_before_valid_from_is_422(auth_headers, types, hierarchy_type_id):
    """`CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >=
    valid_from)` -- another DETAIL-less CHECK, shadowed so it answers 422
    like every other bad field rather than a 409 naming a constraint."""
    client = TestClient(app)
    a = _entity(client, auth_headers, types["unit"], "a")
    b = _entity(client, auth_headers, types["unit"], "b")
    response = _make_rel(
        client,
        auth_headers,
        hierarchy_type_id,
        a,
        b,
        valid_from="2026-02-01",
        valid_to="2026-01-01",
    )
    _assert_blames_field(_validation_errors(response), "valid_to")


def test_patching_only_valid_to_is_judged_against_the_stored_valid_from(
    auth_headers, types, hierarchy_type_id
):
    client = TestClient(app)
    a = _entity(client, auth_headers, types["unit"], "a")
    b = _entity(client, auth_headers, types["unit"], "b")
    rel_id = _rel_id(client, auth_headers, hierarchy_type_id, a, b, valid_from="2026-02-01")
    response = client.patch(
        f"/api/v1/relationships/{rel_id}", json={"valid_to": "2026-01-01"}, headers=auth_headers
    )
    _assert_blames_field(_validation_errors(response), "valid_to")


def test_list_relationships_filters_by_type_and_endpoint(auth_headers, domain_id, types):
    client = TestClient(app)
    hierarchy = _rel_type_id(
        client,
        auth_headers,
        domain_id,
        name="reports_to",
        from_type_id=types["unit"],
        to_type_id=types["unit"],
        cardinality="one_to_many",
        is_hierarchy=True,
    )
    other = _rel_type_id(
        client,
        auth_headers,
        domain_id,
        name="covers",
        from_type_id=types["unit"],
        to_type_id=types["unit"],
    )
    a = _entity(client, auth_headers, types["unit"], "a")
    b = _entity(client, auth_headers, types["unit"], "b")
    c = _entity(client, auth_headers, types["unit"], "c")
    _rel_id(client, auth_headers, hierarchy, a, b)
    _rel_id(client, auth_headers, hierarchy, a, c)
    _rel_id(client, auth_headers, other, b, c)

    by_type = client.get(
        "/api/v1/relationships",
        params={"relationship_type_id": hierarchy},
        headers=auth_headers,
    ).json()
    assert by_type["total"] == 2

    by_source = client.get(
        "/api/v1/relationships", params={"from_entity_id": b}, headers=auth_headers
    ).json()
    assert by_source["total"] == 1
    assert by_source["items"][0]["relationship_type_id"] == other

    by_target = client.get(
        "/api/v1/relationships", params={"to_entity_id": c}, headers=auth_headers
    ).json()
    assert by_target["total"] == 2


def test_relationship_attrs_round_trip(auth_headers, types, hierarchy_type_id):
    client = TestClient(app)
    a = _entity(client, auth_headers, types["unit"], "a")
    b = _entity(client, auth_headers, types["unit"], "b")
    rel_id = _rel_id(client, auth_headers, hierarchy_type_id, a, b, attrs={"weight": 3})
    body = client.get(f"/api/v1/relationships/{rel_id}", headers=auth_headers).json()
    assert body["attrs"] == {"weight": 3}
    patched = client.patch(
        f"/api/v1/relationships/{rel_id}", json={"attrs": {}}, headers=auth_headers
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["attrs"] == {}


def test_delete_relationship(auth_headers, types, hierarchy_type_id):
    client = TestClient(app)
    a = _entity(client, auth_headers, types["unit"], "a")
    b = _entity(client, auth_headers, types["unit"], "b")
    rel_id = _rel_id(client, auth_headers, hierarchy_type_id, a, b)
    assert client.delete(f"/api/v1/relationships/{rel_id}", headers=auth_headers).status_code == 204
    assert client.get(f"/api/v1/relationships/{rel_id}", headers=auth_headers).status_code == 404


# --- the v1 graph read -----------------------------------------------------
#
# `GET /api/v1/graph` answers the wire contract in `app/graph/schemas.py`,
# which `frontend/src/types/graph.ts` mirrors and which task 7 is required
# to leave unchanged.  Several of its fields have no v1 column behind them
# (`code`, `is_abstract`, `is_directed`, and `hierarchies[]` as a whole),
# so the mapping is a decision, not a translation -- and a wrong decision
# renders wrong labels without failing anything.  The tests below pin every
# one of those fields to the source it is derived from, so the mapping is
# readable from the tests and not only from the report.


@pytest.fixture
def other_domain_id(auth_headers):
    client = TestClient(app)
    response = client.post(
        "/api/domain/",
        json={"name": f"rel-other-{uuid.uuid4().hex[:8]}"},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    created_id = response.json()["id"]
    try:
        yield created_id
    finally:
        client.delete(f"/api/domain/{created_id}", headers=auth_headers)


def _graph(client, auth_headers, domain_id, hierarchy_type_id=None) -> dict:
    params = {"domain_id": domain_id}
    if hierarchy_type_id is not None:
        params["hierarchy_type_id"] = hierarchy_type_id
    response = client.get("/api/v1/graph", params=params, headers=auth_headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_graph_parent_comes_from_the_hierarchy_type(
    auth_headers, domain_id, types, hierarchy_type_id
):
    client = TestClient(app)
    a = _entity(client, auth_headers, types["unit"], "a")
    b = _entity(client, auth_headers, types["unit"], "b")
    c = _entity(client, auth_headers, types["unit"], "c")
    _rel_id(client, auth_headers, hierarchy_type_id, a, b)
    _rel_id(client, auth_headers, hierarchy_type_id, b, c)

    graph = _graph(client, auth_headers, domain_id, hierarchy_type_id)
    parent = {node["id"]: node["parent"] for node in graph["nodes"]}
    # from_entity is the PARENT of to_entity (the DDL's own reading).
    assert parent[str(a)] is None
    assert parent[str(b)] == str(a)
    assert parent[str(c)] == str(b)


def test_graph_without_a_hierarchy_type_id_nests_nothing(
    auth_headers, domain_id, types, hierarchy_type_id
):
    client = TestClient(app)
    a = _entity(client, auth_headers, types["unit"], "a")
    b = _entity(client, auth_headers, types["unit"], "b")
    _rel_id(client, auth_headers, hierarchy_type_id, a, b)

    graph = _graph(client, auth_headers, domain_id)
    assert {node["parent"] for node in graph["nodes"]} == {None}
    # ... while the edge itself is still returned.
    assert len(graph["edges"]) == 1


def test_graph_non_hierarchy_edges_never_set_a_parent(
    auth_headers, domain_id, types, hierarchy_type_id
):
    """The brief's "nothing from non-hierarchy types".  A `covers` edge
    between two units must not nest them even when a hierarchy type is
    selected -- nesting is filtered to the selected type's rows."""
    client = TestClient(app)
    covers = _rel_type_id(
        client,
        auth_headers,
        domain_id,
        name="covers",
        from_type_id=types["unit"],
        to_type_id=types["unit"],
    )
    a = _entity(client, auth_headers, types["unit"], "a")
    b = _entity(client, auth_headers, types["unit"], "b")
    _rel_id(client, auth_headers, covers, a, b)

    graph = _graph(client, auth_headers, domain_id, hierarchy_type_id)
    assert {node["parent"] for node in graph["nodes"]} == {None}
    assert [edge["type"] for edge in graph["edges"]] == ["covers"]


def test_graph_two_hierarchy_types_do_not_bleed_into_each_other(
    auth_headers, domain_id, types, hierarchy_type_id
):
    """Two hierarchies over the same nodes; selecting one must show only
    that one's nesting.  Without the relationship-type filter both tests
    above would still pass while this one fails."""
    client = TestClient(app)
    second = _rel_type_id(
        client,
        auth_headers,
        domain_id,
        name="located_in",
        from_type_id=types["unit"],
        to_type_id=types["unit"],
        cardinality="one_to_many",
        is_hierarchy=True,
    )
    a = _entity(client, auth_headers, types["unit"], "a")
    b = _entity(client, auth_headers, types["unit"], "b")
    c = _entity(client, auth_headers, types["unit"], "c")
    _rel_id(client, auth_headers, hierarchy_type_id, a, b)
    _rel_id(client, auth_headers, second, c, b)

    first_graph = _graph(client, auth_headers, domain_id, hierarchy_type_id)
    assert {n["id"]: n["parent"] for n in first_graph["nodes"]}[str(b)] == str(a)
    second_graph = _graph(client, auth_headers, domain_id, second)
    assert {n["id"]: n["parent"] for n in second_graph["nodes"]}[str(b)] == str(c)


def test_graph_hierarchies_lists_only_hierarchy_relationship_types(
    auth_headers, domain_id, types, hierarchy_type_id
):
    """v1 has no `hierarchy` table: a hierarchy *is* a relationship type
    with `is_hierarchy = true`, and that is what `hierarchies[]` carries.
    The ids are therefore relationship_type ids, which is exactly what
    `hierarchy_type_id` takes back."""
    client = TestClient(app)
    _rel_type_id(
        client,
        auth_headers,
        domain_id,
        name="covers",
        from_type_id=types["unit"],
        to_type_id=types["unit"],
    )
    graph = _graph(client, auth_headers, domain_id)
    assert [h["id"] for h in graph["hierarchies"]] == [str(hierarchy_type_id)]
    assert graph["hierarchies"][0]["code"] == "reports_to"
    assert graph["hierarchies"][0]["name"] == "reports_to"
    # ... and every hierarchy is also an ordinary relationship type.
    assert "reports_to" in [rt["code"] for rt in graph["relationship_types"]]


def test_graph_entity_type_options_carry_the_v1_name_as_both_code_and_name(
    auth_headers, domain_id, types
):
    """v1 `entity_type` has `name` and `role` -- no `code`, no
    `is_abstract`.  `code` is the machine identifier, which in v1 is
    `name`, and `GraphNode.type` is set from the same column so the two
    join.  `is_abstract` has no v1 source at all and is hardcoded False."""
    client = TestClient(app)
    graph = _graph(client, auth_headers, domain_id)
    by_code = {et["code"]: et for et in graph["entity_types"]}
    assert set(by_code) == {"unit", "employee"}
    assert by_code["unit"]["id"] == str(types["unit"])
    assert by_code["unit"]["name"] == "unit"
    assert by_code["unit"]["is_abstract"] is False
    assert by_code["employee"]["is_abstract"] is False


def test_graph_relationship_type_options_mapping(auth_headers, domain_id, types):
    """`code`/`name` both from v1 `name`; `is_directed` has no v1 column
    and is hardcoded True, because every v1 relationship is directed
    (`from_entity_id -> to_entity_id`, which the hierarchy and cardinality
    rules both read).  `source_entity_type`/`target_entity_type` are the
    referenced entity types' names -- NOT NULL in v1, so never the "any"
    that v0's nullable columns could mean."""
    client = TestClient(app)
    _rel_type_id(
        client,
        auth_headers,
        domain_id,
        name="works_in",
        from_type_id=types["employee"],
        to_type_id=types["unit"],
    )
    graph = _graph(client, auth_headers, domain_id)
    option = next(rt for rt in graph["relationship_types"] if rt["code"] == "works_in")
    assert option["name"] == "works_in"
    assert option["is_directed"] is True
    assert option["source_entity_type"] == "employee"
    assert option["target_entity_type"] == "unit"


def test_graph_attribute_definition_options_mapping(auth_headers, domain_id, types):
    """`code`/`name` both from v1 `attribute_def.name`; `data_type` is
    passed through verbatim, so it carries v1's `attr_type` labels
    (`integer`, `text`, ...), not v0's (`string`, `datetime`, ...)."""
    client = TestClient(app)
    created = client.post(
        "/api/v1/entity-types/%d/attributes" % types["unit"],
        json={"name": "headcount", "data_type": "integer"},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    graph = _graph(client, auth_headers, domain_id)
    assert len(graph["attribute_definitions"]) == 1
    option = graph["attribute_definitions"][0]
    assert option["id"] == str(created.json()["id"])
    assert option["entity_type_id"] == str(types["unit"])
    assert option["code"] == "headcount"
    assert option["name"] == "headcount"
    assert option["data_type"] == "integer"


def test_graph_node_fields(auth_headers, domain_id, types):
    """`type` is the entity type's v1 `name` (the same string that appears
    as `entity_types[].code`); `label` prefers `entity.label` and falls
    back to `entity.key`; `attributes` is `entity.attrs` verbatim, with no
    built-in columns folded in -- in v1 `attrs` already *is* the complete
    declared attribute set, and injecting `key`/`active` would shadow an
    attribute a user is entitled to declare under those names."""
    client = TestClient(app)
    client.post(
        "/api/v1/entity-types/%d/attributes" % types["unit"],
        json={"name": "headcount", "data_type": "integer"},
        headers=auth_headers,
    )
    labelled = _entity(
        client, auth_headers, types["unit"], "hq", label="Head Office", attrs={"headcount": 12}
    )
    bare = _entity(client, auth_headers, types["unit"], "ops")

    graph = _graph(client, auth_headers, domain_id)
    node = {n["id"]: n for n in graph["nodes"]}
    assert node[str(labelled)]["type"] == "unit"
    assert node[str(labelled)]["label"] == "Head Office"
    assert node[str(labelled)]["attributes"] == {"headcount": 12}
    assert node[str(bare)]["label"] == "ops"
    assert node[str(bare)]["attributes"] == {}


def test_graph_edge_fields(auth_headers, domain_id, types, hierarchy_type_id):
    """`type` and `label` are both the relationship type's v1 `name`; v1
    has neither a `code` nor a display name.  `attributes` is the
    relationship's own `attrs`."""
    client = TestClient(app)
    a = _entity(client, auth_headers, types["unit"], "a")
    b = _entity(client, auth_headers, types["unit"], "b")
    rel_id = _rel_id(client, auth_headers, hierarchy_type_id, a, b, attrs={"weight": 2})

    graph = _graph(client, auth_headers, domain_id)
    assert len(graph["edges"]) == 1
    edge = graph["edges"][0]
    assert edge["id"] == str(rel_id)
    assert edge["source"] == str(a)
    assert edge["target"] == str(b)
    assert edge["type"] == "reports_to"
    assert edge["label"] == "reports_to"
    assert edge["attributes"] == {"weight": 2}


def test_graph_nodes_are_ordered_by_sort_order_before_key(auth_headers, domain_id, types):
    """The keys deliberately disagree with the sort order: sorted by `key`
    alone the answer is [alpha, mike, zulu], and by `sort_order` first it
    is [zulu, alpha, mike].  A fixture whose two orderings agreed would
    pass against either implementation -- the blind spot mutation testing
    found on task 6."""
    client = TestClient(app)
    _entity(client, auth_headers, types["unit"], "zulu", sort_order=0)
    _entity(client, auth_headers, types["unit"], "alpha", sort_order=5)
    _entity(client, auth_headers, types["unit"], "mike", sort_order=9)
    graph = _graph(client, auth_headers, domain_id)
    assert [n["label"] for n in graph["nodes"]] == ["zulu", "alpha", "mike"]


def test_graph_is_scoped_to_one_domain(auth_headers, domain_id, types, other_domain_id):
    client = TestClient(app)
    mine = _entity(client, auth_headers, types["unit"], "mine")
    other_type = client.post(
        "/api/v1/entity-types",
        json={"domain_id": other_domain_id, "name": "unit", "role": "org"},
        headers=auth_headers,
    ).json()["id"]
    theirs = _entity(client, auth_headers, other_type, "theirs")
    client.post(
        "/api/v1/relationship-types",
        json={
            "domain_id": other_domain_id,
            "name": "covers",
            "from_type_id": other_type,
            "to_type_id": other_type,
        },
        headers=auth_headers,
    )

    graph = _graph(client, auth_headers, domain_id)
    assert [n["id"] for n in graph["nodes"]] == [str(mine)]
    assert str(theirs) not in [n["id"] for n in graph["nodes"]]
    assert "covers" not in [rt["code"] for rt in graph["relationship_types"]]


def test_graph_of_an_unknown_domain_is_empty_not_an_error(auth_headers):
    client = TestClient(app)
    graph = _graph(client, auth_headers, 2_000_000_004)
    assert graph == {
        "nodes": [],
        "edges": [],
        "entity_types": [],
        "relationship_types": [],
        "hierarchies": [],
        "attribute_definitions": [],
    }


def test_graph_hierarchy_type_id_naming_a_non_hierarchy_type_is_404(
    auth_headers, domain_id, types
):
    client = TestClient(app)
    covers = _rel_type_id(
        client,
        auth_headers,
        domain_id,
        name="covers",
        from_type_id=types["unit"],
        to_type_id=types["unit"],
    )
    response = client.get(
        "/api/v1/graph",
        params={"domain_id": domain_id, "hierarchy_type_id": covers},
        headers=auth_headers,
    )
    assert response.status_code == 404, response.text


def test_graph_hierarchy_type_id_from_another_domain_is_404(
    auth_headers, domain_id, other_domain_id, types
):
    client = TestClient(app)
    other_type = client.post(
        "/api/v1/entity-types",
        json={"domain_id": other_domain_id, "name": "unit", "role": "org"},
        headers=auth_headers,
    ).json()["id"]
    foreign = _rel_type_id(
        client,
        auth_headers,
        other_domain_id,
        name="reports_to",
        from_type_id=other_type,
        to_type_id=other_type,
        cardinality="one_to_many",
        is_hierarchy=True,
    )
    response = client.get(
        "/api/v1/graph",
        params={"domain_id": domain_id, "hierarchy_type_id": foreign},
        headers=auth_headers,
    )
    assert response.status_code == 404, response.text


def test_graph_refuses_a_domain_over_the_node_cap(
    auth_headers, domain_id, types, monkeypatch
):
    """GET /graph used to return the whole domain unbounded. Counted
    before the rows are loaded; the cap is lowered here so the test does
    not insert ten thousand entities."""
    monkeypatch.setattr("app.graph.service.GRAPH_MAX_NODES", 2)
    client = TestClient(app)
    _entity(client, auth_headers, types["unit"], "a")
    _entity(client, auth_headers, types["unit"], "b")
    ok = client.get("/api/v1/graph", params={"domain_id": domain_id}, headers=auth_headers)
    assert ok.status_code == 200, ok.text
    assert len(ok.json()["nodes"]) == 2

    _entity(client, auth_headers, types["unit"], "c")
    response = client.get(
        "/api/v1/graph", params={"domain_id": domain_id}, headers=auth_headers
    )
    assert response.status_code == 422, response.text
    detail = response.json().get("detail")
    assert isinstance(detail, list) and detail, detail
    entry = detail[0]
    assert [str(p) for p in entry["loc"]] == ["query", "domain_id"]
    assert "3" in entry["msg"] and "2" in entry["msg"]
    assert "kind" not in entry


def test_a_relationship_type_straddling_domains_is_refused_so_no_graph_can_see_one(
    auth_headers, domain_id, types, other_domain_id
):
    """Until migration 0009, `relationship_type.from_type_id`/`to_type_id`
    were plain FKs to `entity_type` with no same-domain constraint, so a
    relationship type in this domain could join entity types of another.
    Its rows would have been edges between nodes this domain's graph does
    not contain, which Cytoscape cannot draw -- this test used to create
    exactly that and assert `get_domain_graph`'s endpoint filter dropped
    the edge (added after mutation testing showed the filter unguarded).

    0009's rule 3 makes the row impossible: composite FKs
    `(from_type_id, domain_id)` / `(to_type_id, domain_id)` ->
    `entity_type (id, domain_id)`. The router does not shadow them, so the
    refusal is `translate_db_error`'s 409 with a string detail. The graph's
    endpoint filter is left in place as defence in depth, but no data can
    reach it any more (see the task 14a report)."""
    client = TestClient(app)
    mine = _entity(client, auth_headers, types["unit"], "mine")
    foreign_type = client.post(
        "/api/v1/entity-types",
        json={"domain_id": other_domain_id, "name": "unit", "role": "org"},
        headers=auth_headers,
    ).json()["id"]
    response = _make_rel_type(
        client,
        auth_headers,
        domain_id,
        name="covers",
        from_type_id=foreign_type,
        to_type_id=foreign_type,
    )
    assert response.status_code == 409, response.text
    assert isinstance(response.json()["detail"], str), response.text

    graph = _graph(client, auth_headers, domain_id)
    assert [n["id"] for n in graph["nodes"]] == [str(mine)]
    assert "covers" not in [rt["code"] for rt in graph["relationship_types"]]
    assert graph["edges"] == []


# --- colour on relationship_type, and colour in the graph payload ----------
#
# Task 14b. The same shadowed CHECK as `entity_type.colour`, and the same
# decision (normalise case rather than refuse it); see
# `test_api_entity_types.py` for the reasoning, which is not repeated here.
#
# The graph half is the part Task 7 deliberately held: `EntityTypeOption`
# and `RelationshipTypeOption` gain `colour`, because the canvas cannot
# draw a type's colour from a payload that does not carry it. Every other
# field of the contract stays exactly as Task 7 mapped it, which the
# existing tests above still pin.


def _stored_rel_colour(relationship_type_id: int) -> str | None:
    db = SessionLocal()
    try:
        return db.get(RelationshipType, relationship_type_id).colour
    finally:
        db.close()


def test_create_relationship_type_without_a_colour_leaves_it_null(
    auth_headers, domain_id, types
):
    client = TestClient(app)
    response = _make_rel_type(
        client,
        auth_headers,
        domain_id,
        name="works_for",
        from_type_id=types["employee"],
        to_type_id=types["unit"],
    )
    assert response.status_code == 201, response.text
    assert response.json()["colour"] is None
    assert _stored_rel_colour(response.json()["id"]) is None


def test_create_relationship_type_accepts_and_normalises_a_colour(
    auth_headers, domain_id, types
):
    client = TestClient(app)
    response = _make_rel_type(
        client,
        auth_headers,
        domain_id,
        name="works_for",
        from_type_id=types["employee"],
        to_type_id=types["unit"],
        colour="#2CA02C",
    )
    assert response.status_code == 201, response.text
    assert response.json()["colour"] == "#2ca02c"
    assert _stored_rel_colour(response.json()["id"]) == "#2ca02c"


@pytest.mark.parametrize(
    "colour", ["2ca02c", "#2ca", "#zzzzzz", "#2ca02c2c", "#2ca02c\n", "", "green"]
)
def test_create_relationship_type_rejects_a_malformed_colour(
    auth_headers, domain_id, types, colour
):
    client = TestClient(app)
    response = _make_rel_type(
        client,
        auth_headers,
        domain_id,
        name="works_for",
        from_type_id=types["employee"],
        to_type_id=types["unit"],
        colour=colour,
    )
    _assert_blames_field(_validation_errors(response), "colour")


def test_update_relationship_type_sets_and_clears_colour(auth_headers, domain_id, types):
    client = TestClient(app)
    rel_type_id = _rel_type_id(
        client,
        auth_headers,
        domain_id,
        name="works_for",
        from_type_id=types["employee"],
        to_type_id=types["unit"],
    )
    set_response = client.patch(
        f"/api/v1/relationship-types/{rel_type_id}",
        json={"colour": "#D62728"},
        headers=auth_headers,
    )
    assert set_response.status_code == 200, set_response.text
    assert set_response.json()["colour"] == "#d62728"
    assert _stored_rel_colour(rel_type_id) == "#d62728"

    renamed = client.patch(
        f"/api/v1/relationship-types/{rel_type_id}",
        json={"name": "employed_by"},
        headers=auth_headers,
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["colour"] == "#d62728"

    cleared = client.patch(
        f"/api/v1/relationship-types/{rel_type_id}", json={"colour": None}, headers=auth_headers
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["colour"] is None
    assert _stored_rel_colour(rel_type_id) is None


def test_update_relationship_type_rejects_a_malformed_colour(auth_headers, domain_id, types):
    client = TestClient(app)
    rel_type_id = _rel_type_id(
        client,
        auth_headers,
        domain_id,
        name="works_for",
        from_type_id=types["employee"],
        to_type_id=types["unit"],
        colour="#2ca02c",
    )
    response = client.patch(
        f"/api/v1/relationship-types/{rel_type_id}", json={"colour": "#nope"}, headers=auth_headers
    )
    _assert_blames_field(_validation_errors(response), "colour")
    assert _stored_rel_colour(rel_type_id) == "#2ca02c"


def test_list_relationship_types_carries_colour(auth_headers, domain_id, types):
    client = TestClient(app)
    _rel_type_id(
        client,
        auth_headers,
        domain_id,
        name="works_for",
        from_type_id=types["employee"],
        to_type_id=types["unit"],
        colour="#2ca02c",
    )
    _rel_type_id(
        client,
        auth_headers,
        domain_id,
        name="covers",
        from_type_id=types["unit"],
        to_type_id=types["unit"],
    )
    listed = client.get(
        f"/api/v1/relationship-types?domain_id={domain_id}", headers=auth_headers
    )
    assert listed.status_code == 200, listed.text
    assert {row["name"]: row["colour"] for row in listed.json()["items"]} == {
        "works_for": "#2ca02c",
        "covers": None,
    }


def test_database_check_still_rejects_an_uppercase_relationship_colour(
    auth_headers, domain_id, types
):
    db = SessionLocal()
    try:
        db.add(
            RelationshipType(
                domain_id=domain_id,
                name="works_for",
                from_type_id=types["employee"],
                to_type_id=types["unit"],
                colour="#2CA02C",
            )
        )
        with pytest.raises(IntegrityError) as excinfo:
            db.flush()
        assert excinfo.value.orig.pgcode == "23514", excinfo.value.orig.pgcode
    finally:
        db.rollback()
        db.close()


def test_graph_type_options_carry_colour(auth_headers, domain_id, types):
    """The wire change this task makes, pinned on both option lists and in
    both directions: a set colour arrives, an unset one arrives as null
    (not as an invented default -- the fallback is the canvas's job, and
    inventing one here would make "no colour chosen" unexpressible)."""
    client = TestClient(app)
    client.patch(
        f"/api/v1/entity-types/{types['unit']}", json={"colour": "#1f77b4"}, headers=auth_headers
    )
    _rel_type_id(
        client,
        auth_headers,
        domain_id,
        name="works_for",
        from_type_id=types["employee"],
        to_type_id=types["unit"],
        colour="#2ca02c",
    )
    _rel_type_id(
        client,
        auth_headers,
        domain_id,
        name="covers",
        from_type_id=types["unit"],
        to_type_id=types["unit"],
    )

    graph = _graph(client, auth_headers, domain_id)
    assert {row["name"]: row["colour"] for row in graph["entity_types"]} == {
        "unit": "#1f77b4",
        "employee": None,
    }
    assert {row["name"]: row["colour"] for row in graph["relationship_types"]} == {
        "works_for": "#2ca02c",
        "covers": None,
    }
    # Task 7's mapping is unchanged around it.
    unit = next(row for row in graph["entity_types"] if row["name"] == "unit")
    assert unit["code"] == "unit" and unit["is_abstract"] is False
