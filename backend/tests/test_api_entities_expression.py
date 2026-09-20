"""`GET /api/v1/entities?expr=<document>` -- the expression filter.

Three things are proven here, and they are different things:

**1. The compiled SQL selects the right rows.** Every case in
`expression_cross_check.json` is compiled and **executed** against a real
fixture, and the keys that come back are compared with the `expect` written
in that file. A test that only asserted on the generated SQL string would
pass for a query that returns the wrong rows, so none does. The same file
is read by `frontend/src/expressions/crossCheck.test.ts`, which evaluates
the same documents in the browser's evaluator; the two suites therefore
agree with a hand-derived answer rather than with each other.

**2. Nothing the caller sends becomes SQL.** The literals are asserted to
be bound parameters and absent from the statement text, including the
attribute names and the `%`-escaped needle of a `contains`.

**3. A refusal happens before the table is read.** Every request that must
be refused is run with a listener recording every statement the process
executes, and the assertion is that none of them mentions `entity` -- not
that the response was a 422 and nothing broke. `parse_expression` has no
`Session` in scope at all (`test_expressions_refusal.py` asserts that
separately), so for the structural refusals the recorder is a second
witness rather than the only one.

The fixture's `u3.hired` is the string `not-a-date` in a `date` attribute.
That is legal -- `entity_validate` checks only `jsonb_typeof(v) = 'string'`
for date and time -- and it is the row that tells a text comparison from a
`::date` cast, which raises on it.
"""

import json
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.db import SessionLocal, engine
from app.expressions import ExpressionRefusal, compile_expression, parse_expression
from app.main import app
from app.models.v1_domain import (
    AttributeDef,
    Domain,
    Entity,
    EntityType,
    Relationship,
    RelationshipType,
)
from app.seed import seed_admin

FIXTURE = json.loads((Path(__file__).with_name("expression_cross_check.json")).read_text(encoding="utf-8"))


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


class _World:
    """The fixture, as it exists in the database."""

    def __init__(self, entity_types, relationship_types, entities):
        self.entity_types = entity_types
        self.relationship_types = relationship_types
        self.entities = entities
        self.entity_ids = [e.id for e in entities.values()]

    def document(self, template: dict) -> dict:
        """`@unit` / `@covers` replaced with the ids this run actually
        has. Field ids are opaque strings to everything but `fields.py`, so
        the substitution is textual and total."""
        raw = json.dumps(template)
        for name, row in {**self.entity_types, **self.relationship_types}.items():
            raw = raw.replace(f"@{name}:", f"{row.id}:")
        assert "@" not in raw, raw
        return json.loads(raw)


@pytest.fixture(scope="module")
def world():
    """Built once for the whole module and torn down by deleting the
    domain, which cascades to every type, attribute, entity and
    relationship hung off it."""
    db = SessionLocal()
    domain = Domain(name=f"expr-{uuid.uuid4().hex[:8]}")
    db.add(domain)
    db.flush()

    entity_types = {}
    for spec in FIXTURE["entityTypes"]:
        row = EntityType(domain_id=domain.id, name=spec["name"], role=spec["role"])
        db.add(row)
        db.flush()
        entity_types[spec["name"]] = row
        for attribute in spec["attributes"]:
            db.add(
                AttributeDef(
                    entity_type_id=row.id,
                    name=attribute["name"],
                    data_type=attribute["data_type"],
                    required=False,
                    enum_values=attribute.get("enum_values"),
                )
            )
    db.flush()

    relationship_types = {}
    for spec in FIXTURE["relationshipTypes"]:
        row = RelationshipType(
            domain_id=domain.id,
            name=spec["name"],
            from_type_id=entity_types[spec["from"]].id,
            to_type_id=entity_types[spec["to"]].id,
            cardinality=spec["cardinality"],
        )
        db.add(row)
        db.flush()
        relationship_types[spec["name"]] = row

    entities = {}
    for spec in FIXTURE["entities"]:
        row = Entity(
            entity_type_id=entity_types[spec["type"]].id,
            key=spec["key"],
            label=spec["label"],
            sort_order=spec["sort_order"],
            active=spec["active"],
            attrs=spec["attrs"],
        )
        db.add(row)
        db.flush()
        entities[spec["key"]] = row

    for spec in FIXTURE["relationships"]:
        db.add(
            Relationship(
                relationship_type_id=relationship_types[spec["type"]].id,
                from_entity_id=entities[spec["from"]].id,
                to_entity_id=entities[spec["to"]].id,
            )
        )
    db.commit()

    # The trigger stores what it was given; assert the two rows the whole
    # file turns on really are in the shapes the fixture claims.
    stored = {row.key: row.attrs for row in db.query(Entity).filter(Entity.id.in_([e.id for e in entities.values()]))}
    assert "note" in stored["u1"] and stored["u1"]["note"] is None, "u1 must store a JSON null"
    assert "note" not in stored["u2"], "u2 must have no note key at all"
    assert stored["u3"]["hired"] == "not-a-date", "the database really does allow this"

    built = _World(entity_types, relationship_types, entities)
    try:
        yield built
    finally:
        db.delete(db.get(Domain, domain.id))
        db.commit()
        db.close()


def _matching_keys(db, world: _World, document: dict) -> list[str]:
    parsed = parse_expression(json.dumps(document))
    predicate = compile_expression(db, parsed)
    rows = db.execute(
        sa.select(Entity.key).where(Entity.id.in_(world.entity_ids), predicate).order_by(Entity.key)
    ).scalars()
    return list(rows)


# --- 1. the compiled SQL selects the right rows ----------------------------


@pytest.mark.parametrize("case", FIXTURE["cases"], ids=[c["name"] for c in FIXTURE["cases"]])
def test_cross_check_case_selects_the_hand_derived_keys(case, world):
    db = SessionLocal()
    try:
        assert _matching_keys(db, world, world.document(case["document"])) == sorted(case["expect"]), (
            case["why"]
        )
    finally:
        db.close()


def test_the_fixture_covers_every_operator_and_every_function():
    """A cross-check file that quietly stopped exercising `count` or
    `notIn` would still pass every case in it."""
    from app.expressions.catalogue import FUNCTIONS, OPERATORS

    raw = json.dumps(FIXTURE["cases"])
    for operator in OPERATORS:
        assert f'"operator": "{operator}"' in raw, f"no case uses {operator}"
    for name in FUNCTIONS:
        assert f'"fn:{name}:' in raw, f"no case uses {name}()"


# --- 2. nothing the caller sends becomes SQL -------------------------------


def _compiled(db, world: _World, document: dict):
    parsed = parse_expression(json.dumps(document))
    predicate = compile_expression(db, parsed)
    return sa.select(Entity.key).where(predicate).compile(
        dialect=sa.dialects.postgresql.dialect()
    )


def test_every_literal_is_a_bound_parameter_and_not_in_the_statement(world):
    db = SessionLocal()
    try:
        compiled = _compiled(
            db,
            world,
            world.document(
                {
                    "version": 1,
                    "query": {
                        "combinator": "and",
                        "rules": [
                            {"field": "col:key", "operator": "=", "value": "'; DROP TABLE entity; --"},
                            {"field": "attr:@unit:code", "operator": "contains", "value": "100%"},
                            {"field": "attr:@unit:grade", "operator": "in", "value": ["a", "b"]},
                        ],
                    },
                }
            ),
        )
        statement = str(compiled)
        # An `IN` binds an expanding parameter, whose value is the list --
        # still bound, just nested one level.
        params = []
        for value in compiled.params.values():
            params.extend(value) if isinstance(value, list) else params.append(value)
        # The literals are values psycopg2 sends out of band...
        assert "'; DROP TABLE entity; --" in params
        assert "%100\\%%" in params
        assert "a" in params and "b" in params
        # ...and the attribute names are parameters too, not identifiers.
        assert "code" in params and "grade" in params
        # ...and none of them is anywhere in the statement text.
        assert "DROP" not in statement
        assert "'code'" not in statement and "'grade'" not in statement
        assert "100" not in statement
    finally:
        db.close()


def test_the_count_subquery_binds_its_relationship_type_id(world):
    db = SessionLocal()
    try:
        compiled = _compiled(
            db,
            world,
            world.document(
                {
                    "version": 1,
                    "query": {
                        "combinator": "and",
                        "rules": [
                            {"field": "fn:count:rel:@covers:outgoing", "operator": ">=", "value": 2}
                        ],
                    },
                }
            ),
        )
        statement = str(compiled)
        relationship_type_id = world.relationship_types["covers"].id
        assert "SELECT count(*)" in statement
        # A correlated scalar subquery over an ALIAS of `relationship`, with
        # the type id bound rather than written into the comparison.
        assert "FROM relationship AS relationship_1" in statement
        assert "relationship_1.relationship_type_id = %(relationship_type_id_1)s" in statement
        assert f"= {relationship_type_id}" not in statement
        assert relationship_type_id in compiled.params.values()
    finally:
        db.close()


# --- 3. a refusal happens before the table is read -------------------------


class _Recorder:
    """Every statement the process executes while this is open."""

    def __init__(self):
        self.statements: list[str] = []

    def __enter__(self):
        sa.event.listen(engine, "before_cursor_execute", self._record)
        return self

    def __exit__(self, *exc):
        sa.event.remove(engine, "before_cursor_execute", self._record)
        return False

    def _record(self, conn, cursor, statement, parameters, context, executemany):
        self.statements.append(statement)

    @property
    def touched_entity(self) -> list[str]:
        return [s for s in self.statements if "entity" in s.lower() and "attribute_def" not in s.lower()]


ADVERSARIAL = {
    "a field name carrying SQL": {
        "version": 1,
        "query": {
            "combinator": "and",
            "rules": [{"field": 'attr:1:"; drop table entity; --', "operator": "=", "value": 1}],
        },
    },
    "a function name with a comment sequence": {
        "version": 1,
        "query": {
            "combinator": "and",
            "rules": [{"field": "fn:year/*x*/:col:key", "operator": "=", "value": 1}],
        },
    },
    "an object where a scalar is required": {
        "version": 1,
        "query": {"combinator": "and", "rules": [{"field": "col:key", "operator": "=", "value": {"a": 1}}]},
    },
    "version 99": {"version": 99, "query": {"combinator": "and", "rules": []}},
}


@pytest.mark.parametrize("name", sorted(ADVERSARIAL))
def test_an_adversarial_document_is_refused_without_the_entity_table_being_read(name, auth_headers):
    client = TestClient(app)
    with _Recorder() as recorder:
        response = client.get(
            "/api/v1/entities",
            params={"expr": json.dumps(ADVERSARIAL[name])},
            headers=auth_headers,
        )
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert isinstance(detail, list) and len(detail) == 1
    assert detail[0]["loc"][:2] == ["query", "expr"]
    assert detail[0]["msg"]
    # The auth lookup is the only thing that ran.
    assert recorder.touched_entity == [], recorder.statements


def test_a_two_hundred_deep_nest_is_refused_without_the_entity_table_being_read(auth_headers):
    node = root = {"combinator": "and", "rules": []}
    for _ in range(200):
        inner = {"combinator": "and", "rules": []}
        node["rules"].append(inner)
        node = inner
    client = TestClient(app)
    with _Recorder() as recorder:
        response = client.get(
            "/api/v1/entities",
            params={"expr": json.dumps({"version": 1, "query": root})},
            headers=auth_headers,
        )
    assert response.status_code == 422, response.text
    assert "nested" in response.json()["detail"][0]["msg"]
    assert recorder.touched_entity == [], recorder.statements


def test_an_enum_value_outside_enum_values_is_refused_without_the_entity_table_being_read(
    auth_headers, world
):
    """This one genuinely needs the catalogue: only `attribute_def` knows
    what `grade` allows. So the assertion is narrower and exact -- the two
    catalogue lookups ran, and `entity` was still never read."""
    document = world.document(
        {
            "version": 1,
            "query": {
                "combinator": "and",
                "rules": [{"field": "attr:@unit:grade", "operator": "=", "value": "z"}],
            },
        }
    )
    client = TestClient(app)
    with _Recorder() as recorder:
        response = client.get(
            "/api/v1/entities", params={"expr": json.dumps(document)}, headers=auth_headers
        )
    assert response.status_code == 422, response.text
    message = response.json()["detail"][0]["msg"]
    assert '"z" is not one of a, b, c' in message
    assert recorder.touched_entity == [], recorder.statements
    assert any("attribute_def" in s for s in recorder.statements)


def test_an_unknown_attribute_is_refused_naming_it(auth_headers, world):
    document = world.document(
        {
            "version": 1,
            "query": {
                "combinator": "and",
                "rules": [{"field": "attr:@unit:nosuch", "operator": "=", "value": "x"}],
            },
        }
    )
    client = TestClient(app)
    with _Recorder() as recorder:
        response = client.get(
            "/api/v1/entities", params={"expr": json.dumps(document)}, headers=auth_headers
        )
    assert response.status_code == 422, response.text
    assert "nosuch" in response.json()["detail"][0]["msg"]
    assert recorder.touched_entity == []


def test_an_operator_the_data_type_does_not_offer_is_refused(auth_headers, world):
    document = world.document(
        {
            "version": 1,
            "query": {
                "combinator": "and",
                "rules": [{"field": "attr:@unit:live", "operator": ">", "value": True}],
            },
        }
    )
    client = TestClient(app)
    response = client.get(
        "/api/v1/entities", params={"expr": json.dumps(document)}, headers=auth_headers
    )
    assert response.status_code == 422, response.text
    detail = response.json()["detail"][0]
    assert detail["loc"] == ["query", "expr", "query", "rules", 0, "operator"]
    assert "boolean" in detail["msg"]


def test_is_empty_on_a_required_attribute_is_refused(auth_headers):
    """`entity_validate` guarantees a required attribute is present, so
    "is empty" there is dead -- and the client does not offer it."""
    db = SessionLocal()
    domain = Domain(name=f"expr-req-{uuid.uuid4().hex[:8]}")
    db.add(domain)
    db.flush()
    entity_type = EntityType(domain_id=domain.id, name="thing", role="other")
    db.add(entity_type)
    db.flush()
    db.add(AttributeDef(entity_type_id=entity_type.id, name="must", data_type="text", required=True))
    db.commit()
    try:
        document = {
            "version": 1,
            "query": {
                "combinator": "and",
                "rules": [{"field": f"attr:{entity_type.id}:must", "operator": "null", "value": None}],
            },
        }
        client = TestClient(app)
        response = client.get(
            "/api/v1/entities", params={"expr": json.dumps(document)}, headers=auth_headers
        )
        assert response.status_code == 422, response.text
        assert response.json()["detail"][0]["loc"][-1] == "operator"
    finally:
        db.delete(db.get(Domain, domain.id))
        db.commit()
        db.close()


def test_a_refusals_loc_points_at_the_offending_rule(auth_headers, world):
    """Ruling 30: the client keys on `loc`. The second rule of the nested
    group is `query.rules[1].rules[1]`."""
    document = world.document(
        {
            "version": 1,
            "query": {
                "combinator": "and",
                "rules": [
                    {"field": "col:key", "operator": "=", "value": "u1"},
                    {
                        "combinator": "or",
                        "rules": [
                            {"field": "col:key", "operator": "=", "value": "u2"},
                            {"field": "attr:@unit:grade", "operator": "=", "value": "z"},
                        ],
                    },
                ],
            },
        }
    )
    client = TestClient(app)
    response = client.get(
        "/api/v1/entities", params={"expr": json.dumps(document)}, headers=auth_headers
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"][0]["loc"] == [
        "query",
        "expr",
        "query",
        "rules",
        1,
        "rules",
        1,
        "value",
    ]


# --- the route itself -------------------------------------------------------


def _keys(response) -> list[str]:
    assert response.status_code == 200, response.text
    return sorted(item["key"] for item in response.json()["items"])


def test_the_route_filters_by_the_expression(auth_headers, world):
    document = world.document(
        {
            "version": 1,
            "query": {
                "combinator": "and",
                "rules": [{"field": "attr:@unit:cap", "operator": "<", "value": 10}],
            },
        }
    )
    client = TestClient(app)
    response = client.get(
        "/api/v1/entities",
        params={"entity_type_id": world.entity_types["unit"].id, "expr": json.dumps(document)},
        headers=auth_headers,
    )
    assert _keys(response) == ["u1"]
    assert response.json()["total"] == 1


def test_the_expression_narrows_rather_than_widens(auth_headers, world):
    """An expression must not let a caller see rows the route would not
    have returned. `entity_type_id` selects the shifts; the expression is
    about units; the answer is nothing, not the units."""
    document = world.document(
        {
            "version": 1,
            "query": {
                "combinator": "and",
                "rules": [{"field": "attr:@unit:cap", "operator": "<", "value": 1000}],
            },
        }
    )
    client = TestClient(app)
    response = client.get(
        "/api/v1/entities",
        params={"entity_type_id": world.entity_types["shift"].id, "expr": json.dumps(document)},
        headers=auth_headers,
    )
    assert _keys(response) == []
    assert response.json()["total"] == 0


def test_the_expression_composes_with_the_search_box(auth_headers, world):
    document = world.document(
        {
            "version": 1,
            "query": {
                "combinator": "and",
                "rules": [{"field": "col:active", "operator": "=", "value": True}],
            },
        }
    )
    client = TestClient(app)
    response = client.get(
        "/api/v1/entities",
        params={
            "entity_type_id": world.entity_types["unit"].id,
            "q": "u",
            "expr": json.dumps(document),
            "limit": 500,
        },
        headers=auth_headers,
    )
    assert _keys(response) == ["u1", "u2"]


def test_the_total_counts_the_filtered_rows_not_all_of_them(auth_headers, world):
    document = world.document(
        {
            "version": 1,
            "query": {
                "combinator": "and",
                "rules": [{"field": "col:active", "operator": "=", "value": False}],
            },
        }
    )
    client = TestClient(app)
    response = client.get(
        "/api/v1/entities",
        params={"entity_type_id": world.entity_types["unit"].id, "expr": json.dumps(document), "limit": 1},
        headers=auth_headers,
    )
    assert response.json()["total"] == 1


def test_an_empty_expression_changes_nothing(auth_headers, world):
    client = TestClient(app)
    params = {"entity_type_id": world.entity_types["unit"].id, "limit": 500}
    without = client.get("/api/v1/entities", params=params, headers=auth_headers)
    with_empty = client.get(
        "/api/v1/entities",
        params={**params, "expr": json.dumps({"version": 1, "query": {"combinator": "and", "rules": []}})},
        headers=auth_headers,
    )
    assert _keys(with_empty) == _keys(without)


def test_the_route_still_needs_a_token(world):
    client = TestClient(app)
    response = client.get(
        "/api/v1/entities",
        params={"expr": json.dumps({"version": 1, "query": {"combinator": "and", "rules": []}})},
    )
    assert response.status_code == 401


def test_an_unauthenticated_request_is_refused_before_the_expression_is_read():
    """A caller with no token cannot use the compiler as an oracle."""
    client = TestClient(app)
    with _Recorder() as recorder:
        response = client.get("/api/v1/entities", params={"expr": "{"})
    assert response.status_code == 401
    assert recorder.touched_entity == []


def test_ordering_and_paging_still_work_under_an_expression(auth_headers, world):
    document = world.document(
        {"version": 1, "query": {"combinator": "and", "rules": [
            {"field": "col:key", "operator": "beginsWith", "value": "u"}]}}
    )
    client = TestClient(app)
    first = client.get(
        "/api/v1/entities",
        params={"entity_type_id": world.entity_types["unit"].id, "expr": json.dumps(document),
                "limit": 2, "offset": 0},
        headers=auth_headers,
    )
    second = client.get(
        "/api/v1/entities",
        params={"entity_type_id": world.entity_types["unit"].id, "expr": json.dumps(document),
                "limit": 2, "offset": 2},
        headers=auth_headers,
    )
    assert [i["key"] for i in first.json()["items"]] == ["u1", "u2"]
    assert [i["key"] for i in second.json()["items"]] == ["u3"]
    assert first.json()["total"] == 3


def test_a_document_over_the_size_cap_is_refused_by_the_route(auth_headers):
    client = TestClient(app)
    with _Recorder() as recorder:
        response = client.get(
            "/api/v1/entities", params={"expr": "x" * 30000}, headers=auth_headers
        )
    assert response.status_code == 422
    assert recorder.touched_entity == []


def test_a_stored_value_whose_type_disagrees_with_the_declaration_reads_as_no_value(auth_headers):
    """The one shape the shared fixture cannot hold, because the trigger
    refuses to write it: an `attrs` value whose JSON type disagrees with
    the attribute's DECLARED type.

    It is reachable all the same -- change `attribute_def.data_type` and
    the rows that already exist are not revisited (`entity_validate` is
    BEFORE INSERT OR UPDATE on `entity`, not on `attribute_def`; Ruling 29
    is the same blind spot from the other side). The filter must not start
    answering nonsense there, and it must not start answering DIFFERENTLY
    from the browser, whose `compare()` returns null when the two operands
    are not both strings and whose `fold()` gives "" for a non-string.

    So: a comparison finds nothing (the value cannot be read as text), and
    "is empty" is still FALSE, because the attribute HAS a value -- it is
    just not one this rule can compare. Those two are different questions
    and the compiler keeps them apart.
    """
    db = SessionLocal()
    domain = Domain(name=f"expr-drift-{uuid.uuid4().hex[:8]}")
    db.add(domain)
    db.flush()
    entity_type = EntityType(domain_id=domain.id, name="drifted", role="other")
    db.add(entity_type)
    db.flush()
    attribute = AttributeDef(entity_type_id=entity_type.id, name="v", data_type="integer", required=False)
    db.add(attribute)
    db.flush()
    row = Entity(entity_type_id=entity_type.id, key="d1", attrs={"v": 5})
    db.add(row)
    db.commit()
    # The declaration moves; the stored row does not.
    db.execute(
        sa.update(AttributeDef).where(AttributeDef.id == attribute.id).values(data_type="text")
    )
    db.commit()
    assert db.get(Entity, row.id).attrs == {"v": 5}

    def keys(rule):
        parsed = parse_expression(json.dumps({"version": 1, "query": {"combinator": "and", "rules": [rule]}}))
        predicate = compile_expression(db, parsed)
        return list(
            db.execute(sa.select(Entity.key).where(Entity.id == row.id, predicate)).scalars()
        )

    field = f"attr:{entity_type.id}:v"
    try:
        assert keys({"field": field, "operator": "=", "value": "5"}) == []
        assert keys({"field": field, "operator": "contains", "value": "5"}) == []
        assert keys({"field": field, "operator": "null", "value": None}) == []
        assert keys({"field": field, "operator": "notNull", "value": None}) == ["d1"]
    finally:
        db.delete(db.get(Domain, domain.id))
        db.commit()
        db.close()


def test_compile_expression_refuses_rather_than_raising_a_database_error(world):
    """The compiler's own contract, without HTTP in the way: everything it
    cannot answer is an `ExpressionRefusal`, never a DBAPI error leaking
    out as a 500."""
    db = SessionLocal()
    try:
        parsed = parse_expression(
            json.dumps(
                {
                    "version": 1,
                    "query": {
                        "combinator": "and",
                        "rules": [{"field": "attr:999999:nope", "operator": "=", "value": "x"}],
                    },
                }
            )
        )
        with pytest.raises(ExpressionRefusal) as excinfo:
            compile_expression(db, parsed)
        assert excinfo.value.code == "unknown_field"
    finally:
        db.close()
