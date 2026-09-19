"""Schema v1 DOMAIN triggers, exercised through raw SQL.

These are contract tests for migration `0006_schema_v1_domain`. Task 3's
API layer maps these failures to HTTP 422 by reading SQLSTATE 23514 and
`json.loads`-ing the DETAIL payload, so the `kind` and `field` values
asserted here are an interface, not decoration.

Note on the exception class: SQLSTATE 23514 is `check_violation`, which
lives in SQLSTATE class 23 (integrity_constraint_violation). psycopg2
therefore raises `psycopg2.errors.CheckViolation`, a subclass of
`psycopg2.IntegrityError`, and SQLAlchemy wraps it as
`sqlalchemy.exc.IntegrityError` -- not ProgrammingError. What the API
actually keys on is `pgcode`, which every test below asserts explicitly.
"""

import json

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.db import SessionLocal


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def _detail(exc_info) -> dict:
    """The JSON DETAIL payload the trigger attached to the error."""
    orig = exc_info.value.orig
    assert orig.pgcode == "23514", f"expected check_violation, got {orig.pgcode}"
    return json.loads(orig.diag.message_detail)


# --------------------------------------------------------------------------
# fixtures: each test builds its own domain so the tests are order-independent
# --------------------------------------------------------------------------


def make_domain(db, name: str) -> int:
    return db.execute(
        text("INSERT INTO domain (name) VALUES (:n) RETURNING id"),
        {"n": f"{name}-{_unique()}"},
    ).scalar_one()


_counter = 0


def _unique() -> int:
    global _counter
    _counter += 1
    return _counter


def make_entity_type(db, domain_id: int, name: str, role: str = "other") -> int:
    return db.execute(
        text(
            "INSERT INTO entity_type (domain_id, name, role) "
            "VALUES (:d, :n, CAST(:r AS entity_role)) RETURNING id"
        ),
        {"d": domain_id, "n": name, "r": role},
    ).scalar_one()


def make_attribute_def(
    db,
    entity_type_id: int,
    name: str,
    data_type: str,
    *,
    required: bool = False,
    enum_values: list[str] | None = None,
    default_value: str | None = None,
) -> int:
    return db.execute(
        text(
            "INSERT INTO attribute_def "
            "(entity_type_id, name, data_type, required, enum_values, default_value) "
            "VALUES (:t, :n, CAST(:dt AS attr_type), :req, :ev, CAST(:dv AS jsonb)) RETURNING id"
        ),
        {
            "t": entity_type_id,
            "n": name,
            "dt": data_type,
            "req": required,
            "ev": enum_values,
            "dv": default_value,
        },
    ).scalar_one()


def make_entity(db, entity_type_id: int, key: str, attrs: str = "{}") -> int:
    return db.execute(
        text(
            "INSERT INTO entity (entity_type_id, key, attrs) "
            "VALUES (:t, :k, CAST(:a AS jsonb)) RETURNING id"
        ),
        {"t": entity_type_id, "k": key, "a": attrs},
    ).scalar_one()


def make_relationship_type(
    db,
    domain_id: int,
    name: str,
    from_type_id: int,
    to_type_id: int,
    *,
    cardinality: str = "many_to_many",
    is_hierarchy: bool = False,
) -> int:
    return db.execute(
        text(
            "INSERT INTO relationship_type "
            "(domain_id, name, from_type_id, to_type_id, cardinality, is_hierarchy) "
            "VALUES (:d, :n, :f, :t, :c, :h) RETURNING id"
        ),
        {
            "d": domain_id,
            "n": name,
            "f": from_type_id,
            "t": to_type_id,
            "c": cardinality,
            "h": is_hierarchy,
        },
    ).scalar_one()


def make_relationship(db, rel_type_id: int, from_id: int, to_id: int) -> int:
    return db.execute(
        text(
            "INSERT INTO relationship (relationship_type_id, from_entity_id, to_entity_id) "
            "VALUES (:rt, :f, :t) RETURNING id"
        ),
        {"rt": rel_type_id, "f": from_id, "t": to_id},
    ).scalar_one()


@pytest.fixture
def employee_type(db):
    """An `employee` entity type with a spread of attribute definitions."""
    domain_id = make_domain(db, "trig")
    et = make_entity_type(db, domain_id, "employee", role="agent")
    make_attribute_def(db, et, "age", "integer")
    make_attribute_def(db, et, "rate", "number")
    make_attribute_def(db, et, "active_flag", "boolean")
    make_attribute_def(db, et, "grade", "enum", enum_values=["junior", "senior"])
    make_attribute_def(db, et, "badge", "text", required=True)
    return domain_id, et


# --------------------------------------------------------------------------
# entity_validate
# --------------------------------------------------------------------------


def test_unknown_attribute_rejected(db, employee_type):
    _, et = employee_type
    with pytest.raises(IntegrityError) as exc:
        make_entity(db, et, "a", '{"badge": "b1", "nope": 1}')
    detail = _detail(exc)
    assert detail["kind"] == "unknown_attribute"
    assert detail["field"] == "nope"
    assert detail["record"] == "a"


def test_required_attribute_missing_rejected(db, employee_type):
    _, et = employee_type
    with pytest.raises(IntegrityError) as exc:
        make_entity(db, et, "b", "{}")
    detail = _detail(exc)
    assert detail["kind"] == "required_attribute"
    assert detail["field"] == "badge"


def test_integer_attribute_rejects_a_float(db, employee_type):
    _, et = employee_type
    with pytest.raises(IntegrityError) as exc:
        make_entity(db, et, "c", '{"badge": "b1", "age": 3.5}')
    detail = _detail(exc)
    assert detail["kind"] == "attribute_type"
    assert detail["field"] == "age"
    assert detail["expected"] == "integer"


def test_number_attribute_rejects_a_string(db, employee_type):
    _, et = employee_type
    with pytest.raises(IntegrityError) as exc:
        make_entity(db, et, "d", '{"badge": "b1", "rate": "12"}')
    detail = _detail(exc)
    assert detail["kind"] == "attribute_type"
    assert detail["field"] == "rate"
    assert detail["expected"] == "number"


def test_boolean_attribute_rejects_a_string(db, employee_type):
    _, et = employee_type
    with pytest.raises(IntegrityError) as exc:
        make_entity(db, et, "e", '{"badge": "b1", "active_flag": "yes"}')
    detail = _detail(exc)
    assert detail["kind"] == "attribute_type"
    assert detail["field"] == "active_flag"
    assert detail["expected"] == "boolean"


def test_enum_attribute_rejects_a_value_outside_enum_values(db, employee_type):
    _, et = employee_type
    with pytest.raises(IntegrityError) as exc:
        make_entity(db, et, "f", '{"badge": "b1", "grade": "principal"}')
    detail = _detail(exc)
    assert detail["kind"] == "attribute_type"
    assert detail["field"] == "grade"
    assert detail["expected"] == "enum"


def test_integer_attribute_accepts_a_whole_number(db, employee_type):
    _, et = employee_type
    entity_id = make_entity(db, et, "g", '{"badge": "b1", "age": 40}')
    attrs = db.execute(
        text("SELECT attrs FROM entity WHERE id = :i"), {"i": entity_id}
    ).scalar_one()
    assert attrs["age"] == 40


def test_default_value_is_materialised_when_absent(db):
    """`entity_validate` writes attribute_def.default_value into attrs on
    insert, so the stored row is self-describing. Documented, not changed
    (spec §3): editing a default later does not update existing rows."""
    domain_id = make_domain(db, "defaults")
    et = make_entity_type(db, domain_id, "shift")
    make_attribute_def(db, et, "capacity", "integer", default_value="7")

    entity_id = make_entity(db, et, "morning", "{}")
    attrs = db.execute(
        text("SELECT attrs FROM entity WHERE id = :i"), {"i": entity_id}
    ).scalar_one()
    assert attrs == {"capacity": 7}

    # An explicitly supplied value is not overwritten by the default.
    other_id = make_entity(db, et, "night", '{"capacity": 2}')
    other = db.execute(
        text("SELECT attrs FROM entity WHERE id = :i"), {"i": other_id}
    ).scalar_one()
    assert other == {"capacity": 2}


# --------------------------------------------------------------------------
# relationship_validate
# --------------------------------------------------------------------------


@pytest.fixture
def two_types(db):
    domain_id = make_domain(db, "rel")
    employee = make_entity_type(db, domain_id, "employee", role="agent")
    unit = make_entity_type(db, domain_id, "unit", role="org")
    return domain_id, employee, unit


def test_entity_type_mismatch_rejected(db, two_types):
    domain_id, employee, unit = two_types
    rt = make_relationship_type(db, domain_id, "works_for", employee, unit)
    e1 = make_entity(db, employee, "ahmed")
    e2 = make_entity(db, employee, "sara")

    with pytest.raises(IntegrityError) as exc:
        make_relationship(db, rt, e1, e2)  # to_entity is an employee, not a unit
    detail = _detail(exc)
    assert detail["kind"] == "type_mismatch"
    assert detail["field"] == "works_for"


def test_one_to_many_rejects_a_second_source_for_a_target(db, two_types):
    domain_id, employee, unit = two_types
    rt = make_relationship_type(
        db, domain_id, "manages", unit, employee, cardinality="one_to_many"
    )
    u1 = make_entity(db, unit, "hq")
    u2 = make_entity(db, unit, "branch")
    e1 = make_entity(db, employee, "ahmed")

    make_relationship(db, rt, u1, e1)
    with pytest.raises(IntegrityError) as exc:
        make_relationship(db, rt, u2, e1)
    detail = _detail(exc)
    assert detail["kind"] == "cardinality"
    assert detail["field"] == "manages"


def test_many_to_one_rejects_a_second_target_for_a_source(db, two_types):
    domain_id, employee, unit = two_types
    rt = make_relationship_type(
        db, domain_id, "belongs_to", employee, unit, cardinality="many_to_one"
    )
    e1 = make_entity(db, employee, "ahmed")
    u1 = make_entity(db, unit, "hq")
    u2 = make_entity(db, unit, "branch")

    make_relationship(db, rt, e1, u1)
    with pytest.raises(IntegrityError) as exc:
        make_relationship(db, rt, e1, u2)
    detail = _detail(exc)
    assert detail["kind"] == "cardinality"
    assert detail["field"] == "belongs_to"


def test_one_to_one_rejects_both_directions(db, two_types):
    domain_id, employee, unit = two_types
    rt = make_relationship_type(
        db, domain_id, "heads", employee, unit, cardinality="one_to_one"
    )
    e1 = make_entity(db, employee, "ahmed")
    e2 = make_entity(db, employee, "sara")
    u1 = make_entity(db, unit, "hq")
    u2 = make_entity(db, unit, "branch")

    make_relationship(db, rt, e1, u1)

    # Each failure aborts its transaction, so take a SAVEPOINT around it --
    # both directions are checked against the same surviving e1 -> u1 edge.

    # target u1 already has a source
    with pytest.raises(IntegrityError) as exc:
        with db.begin_nested():
            make_relationship(db, rt, e2, u1)
    assert _detail(exc)["kind"] == "cardinality"

    # source e1 already has a target
    with pytest.raises(IntegrityError) as exc:
        with db.begin_nested():
            make_relationship(db, rt, e1, u2)
    detail = _detail(exc)
    assert detail["kind"] == "cardinality"
    assert detail["field"] == "heads"


@pytest.fixture
def hierarchy(db):
    domain_id = make_domain(db, "hier")
    unit = make_entity_type(db, domain_id, "unit", role="org")
    rt = make_relationship_type(
        db, domain_id, "parent_of", unit, unit, cardinality="one_to_many", is_hierarchy=True
    )
    return domain_id, unit, rt


def test_hierarchy_self_loop_rejected(db, hierarchy):
    _, unit, rt = hierarchy
    a = make_entity(db, unit, "a")
    with pytest.raises(IntegrityError) as exc:
        make_relationship(db, rt, a, a)
    detail = _detail(exc)
    assert detail["kind"] == "cycle"
    assert detail["field"] == "parent_of"


def test_hierarchy_multi_hop_cycle_rejected(db, hierarchy):
    _, unit, rt = hierarchy
    a = make_entity(db, unit, "a")
    b = make_entity(db, unit, "b")
    c = make_entity(db, unit, "c")
    make_relationship(db, rt, a, b)
    make_relationship(db, rt, b, c)

    # c -> a would close a -> b -> c -> a
    with pytest.raises(IntegrityError) as exc:
        make_relationship(db, rt, c, a)
    detail = _detail(exc)
    assert detail["kind"] == "cycle"
    assert detail["field"] == "parent_of"


def test_legal_repoint_of_an_existing_hierarchy_edge_succeeds(db, hierarchy):
    """Amendment (c). The trigger fires on UPDATE while the row's
    pre-update version is still in the table, so without excluding it from
    the recursive walk this legal re-point is rejected as a cycle:
    walking down from the new parent `a` still finds the old edge a -> b,
    then b -> c, and concludes the new child `c` is an ancestor."""
    _, unit, rt = hierarchy
    a = make_entity(db, unit, "a")
    b = make_entity(db, unit, "b")
    c = make_entity(db, unit, "c")
    edge = make_relationship(db, rt, a, b)  # a -> b
    make_relationship(db, rt, b, c)  # b -> c

    # Re-point the a -> b edge to c -> a, leaving the legal chain b -> c -> a.
    db.execute(
        text(
            "UPDATE relationship SET from_entity_id = :f, to_entity_id = :t WHERE id = :i"
        ),
        {"f": c, "t": a, "i": edge},
    )

    row = db.execute(
        text("SELECT from_entity_id, to_entity_id FROM relationship WHERE id = :i"),
        {"i": edge},
    ).one()
    assert row.from_entity_id == c
    assert row.to_entity_id == a


# --------------------------------------------------------------------------
# entity_descendants
# --------------------------------------------------------------------------


def test_entity_descendants_returns_node_and_subtree_with_depths(db, hierarchy):
    _, unit, rt = hierarchy
    a = make_entity(db, unit, "a")
    b = make_entity(db, unit, "b")
    c = make_entity(db, unit, "c")
    d = make_entity(db, unit, "d")
    outside = make_entity(db, unit, "outside")
    make_relationship(db, rt, a, b)
    make_relationship(db, rt, b, c)
    make_relationship(db, rt, a, d)

    rows = db.execute(
        text("SELECT entity_id, depth FROM entity_descendants(:e, :rt)"),
        {"e": a, "rt": rt},
    ).all()
    assert set(rows) == {(a, 0), (b, 1), (d, 1), (c, 2)}
    assert outside not in {row.entity_id for row in rows}

    # A leaf is its own only descendant, at depth 0.
    leaf = db.execute(
        text("SELECT entity_id, depth FROM entity_descendants(:e, :rt)"),
        {"e": c, "rt": rt},
    ).all()
    assert leaf == [(c, 0)]


# --------------------------------------------------------------------------
# parameter_value_validate / parameter_value_cleanup
# --------------------------------------------------------------------------


@pytest.fixture
def demand(db):
    """demand[day, shift] -- a two-dimensional parameter."""
    domain_id = make_domain(db, "param")
    day = make_entity_type(db, domain_id, "day", role="time")
    shift = make_entity_type(db, domain_id, "shift", role="time")
    pd_id = db.execute(
        text(
            "INSERT INTO parameter_def (domain_id, name, index_type_ids) "
            "VALUES (:d, 'demand', :idx) RETURNING id"
        ),
        {"d": domain_id, "idx": [day, shift]},
    ).scalar_one()
    return domain_id, day, shift, pd_id


def _insert_parameter_value(db, pd_id: int, entity_ids: list[int], value: int) -> None:
    db.execute(
        text(
            "INSERT INTO parameter_value (parameter_def_id, entity_ids, value) "
            "VALUES (:p, :e, :v)"
        ),
        {"p": pd_id, "e": entity_ids, "v": value},
    )


def test_parameter_value_accepts_a_correct_index(db, demand):
    _, day, shift, pd_id = demand
    mon = make_entity(db, day, "mon")
    morning = make_entity(db, shift, "morning")

    _insert_parameter_value(db, pd_id, [mon, morning], 3)
    value = db.execute(
        text("SELECT value FROM parameter_value WHERE parameter_def_id = :p"), {"p": pd_id}
    ).scalar_one()
    assert value == 3


def test_parameter_value_rejects_wrong_arity(db, demand):
    _, day, shift, pd_id = demand
    mon = make_entity(db, day, "mon")

    with pytest.raises(IntegrityError) as exc:
        _insert_parameter_value(db, pd_id, [mon], 3)  # one index, two expected
    detail = _detail(exc)
    assert detail["kind"] == "parameter_index"
    assert detail["field"] == "entity_ids"


def test_parameter_value_rejects_wrong_entity_types(db, demand):
    _, day, shift, pd_id = demand
    mon = make_entity(db, day, "mon")
    tue = make_entity(db, day, "tue")

    with pytest.raises(IntegrityError) as exc:
        _insert_parameter_value(db, pd_id, [mon, tue], 3)  # [day, day], not [day, shift]
    detail = _detail(exc)
    assert detail["kind"] == "parameter_index"
    assert detail["field"] == "entity_ids"


def test_deleting_an_entity_removes_its_parameter_values(db, demand):
    _, day, shift, pd_id = demand
    mon = make_entity(db, day, "mon")
    tue = make_entity(db, day, "tue")
    morning = make_entity(db, shift, "morning")
    _insert_parameter_value(db, pd_id, [mon, morning], 3)
    _insert_parameter_value(db, pd_id, [tue, morning], 5)

    db.execute(text("DELETE FROM entity WHERE id = :i"), {"i": mon})

    remaining = db.execute(
        text("SELECT entity_ids FROM parameter_value WHERE parameter_def_id = :p"),
        {"p": pd_id},
    ).scalars().all()
    assert remaining == [[tue, morning]]
