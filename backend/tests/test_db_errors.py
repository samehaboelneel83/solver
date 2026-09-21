"""`translate_db_error` maps structured Postgres trigger errors to HTTP.

Two real SQLSTATEs are exercised against the live database, not fakes:

- **23514** (check_violation) -- raised by the DOMAIN validation triggers
  added in migration `0006_schema_v1_domain` (`entity_validate`,
  `relationship_validate`, `parameter_value_validate`). These carry
  `USING ERRCODE = '23514'` and a JSON `DETAIL` payload (see
  `test_v1_domain_triggers.py` for the payload contract). psycopg2 raises
  `CheckViolation`, a subclass of `IntegrityError`; SQLAlchemy wraps it as
  `sqlalchemy.exc.IntegrityError`.
- **P0001** -- the bare `RAISE EXCEPTION`s left verbatim from the
  authoritative DDL: `forbid_update()` on the four immutable tables
  (migration `0007_schema_v1_problem_run`). These carry a human message but
  no JSON `DETAIL`. psycopg2 maps SQLSTATE class P0 to `InternalError`
  (`psycopg2.errors.RaiseException`); SQLAlchemy wraps it as
  `sqlalchemy.exc.InternalError`.

A real 23505 (unique_violation) is exercised too, via `domain.name UNIQUE`.

Fakes are used only for branches a real error can't reach: a malformed (or
non-dict, or `kind`-less) `DETAIL`, and a pgcode this module doesn't know
about at all (must re-raise, not swallow).
"""

import json
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, InternalError

from app.core.db import SessionLocal
from app.crud.db_errors import translate_db_error


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def _unique() -> str:
    """A run-unique suffix.

    `solver_test` is created once by `conftest.py` and never dropped, so
    anything a test *commits* persists across pytest invocations. A
    process-local counter (0, 1, 2, ... reset every run) is not unique
    against that: it reliably regenerates the same name the next run picks,
    colliding with a row a prior run left behind. uuid4 is unique across
    runs, not just within one.
    """
    return uuid.uuid4().hex[:8]


# --------------------------------------------------------------------------
# fixtures/builders, mirroring test_v1_domain_triggers.py and
# test_v1_problem_run.py just enough to provoke each real trigger
# --------------------------------------------------------------------------


def make_domain(db, name: str) -> int:
    return db.execute(
        text("INSERT INTO domain (name) VALUES (:n) RETURNING id"),
        {"n": f"{name}-{_unique()}"},
    ).scalar_one()


def make_entity_type(db, domain_id: int, name: str, role: str = "other") -> int:
    return db.execute(
        text(
            "INSERT INTO entity_type (domain_id, name, role) "
            "VALUES (:d, :n, CAST(:r AS entity_role)) RETURNING id"
        ),
        {"d": domain_id, "n": name, "r": role},
    ).scalar_one()


def make_attribute_def(db, entity_type_id: int, name: str, data_type: str, *, required: bool = False) -> int:
    return db.execute(
        text(
            "INSERT INTO attribute_def (entity_type_id, name, data_type, required) "
            "VALUES (:t, :n, CAST(:dt AS attr_type), :req) RETURNING id"
        ),
        {"t": entity_type_id, "n": name, "dt": data_type, "req": required},
    ).scalar_one()


def make_entity(db, entity_type_id: int, key: str, attrs: str = "{}") -> int:
    return db.execute(
        text("INSERT INTO entity (entity_type_id, key, attrs) VALUES (:t, :k, CAST(:a AS jsonb)) RETURNING id"),
        {"t": entity_type_id, "k": key, "a": attrs},
    ).scalar_one()


def make_problem(db, domain_id: int, name: str = "prob") -> int:
    return db.execute(
        text("INSERT INTO problem (domain_id, name) VALUES (:d, :n) RETURNING id"),
        {"d": domain_id, "n": f"{name}-{_unique()}"},
    ).scalar_one()


def make_model_version(db, problem_id: int, ir: dict) -> int:
    """`version` and `ir_hash` are deliberately not supplied: they're filled
    by the `next_model_version()` and `set_hash()` triggers respectively."""
    return db.execute(
        text("INSERT INTO model_version (problem_id, ir) VALUES (:p, CAST(:ir AS jsonb)) RETURNING id"),
        {"p": problem_id, "ir": json.dumps(ir)},
    ).scalar_one()


class _FakeDiag:
    def __init__(
        self,
        message_detail=None,
        message_primary=None,
        table_name=None,
        constraint_name=None,
    ):
        self.message_detail = message_detail
        self.message_primary = message_primary
        self.table_name = table_name
        self.constraint_name = constraint_name


class _FakeOrig:
    def __init__(self, pgcode, diag=None):
        self.pgcode = pgcode
        self.diag = diag


class _FakeDBAPIError(Exception):
    """Duck-types sqlalchemy.exc.DBAPIError enough for translate_db_error:
    it only ever reads `.orig.pgcode` and `.orig.diag`, and re-raises `exc`
    itself (not a reconstructed one) on the fallback path."""

    def __init__(self, orig):
        self.orig = orig
        super().__init__(str(orig))


def fake_dbapi_error(
    *,
    pgcode,
    message_detail=None,
    message_primary=None,
    table_name=None,
    constraint_name=None,
):
    return _FakeDBAPIError(
        _FakeOrig(
            pgcode,
            _FakeDiag(message_detail, message_primary, table_name, constraint_name),
        )
    )


# --------------------------------------------------------------------------
# 23514 check_violation, from the real entity_validate trigger
# --------------------------------------------------------------------------


def test_real_unknown_attribute_check_violation_becomes_422(db):
    domain_id = make_domain(db, "dberr")
    et = make_entity_type(db, domain_id, "employee")
    make_attribute_def(db, et, "badge", "text", required=True)

    with pytest.raises(IntegrityError) as exc_info:
        make_entity(db, et, "e1", '{"badge": "b1", "nope": 1}')
    db.rollback()

    http = translate_db_error(exc_info.value, table="entity")

    assert http.status_code == 422
    # Ruling 19: FastAPI's list shape, one entry, `kind` as a sibling key.
    assert isinstance(http.detail, list) and len(http.detail) == 1, http.detail
    entry = http.detail[0]
    assert set(entry) == {"type", "loc", "msg", "kind"}, entry
    assert entry["loc"] == ["body", "nope"]
    assert entry["kind"] == "unknown_attribute"
    assert isinstance(entry["msg"], str) and entry["msg"]


def test_real_required_attribute_check_violation_becomes_422(db):
    domain_id = make_domain(db, "dberr")
    et = make_entity_type(db, domain_id, "employee")
    make_attribute_def(db, et, "badge", "text", required=True)

    with pytest.raises(IntegrityError) as exc_info:
        make_entity(db, et, "e2", "{}")
    db.rollback()

    http = translate_db_error(exc_info.value, table="entity")

    assert http.status_code == 422
    assert isinstance(http.detail, list) and len(http.detail) == 1, http.detail
    assert http.detail[0]["loc"] == ["body", "badge"]
    assert http.detail[0]["kind"] == "required_attribute"


def test_real_parameter_index_violation_becomes_a_list_422_with_kind(db):
    """The kind task 8 depends on, provoked through the real
    `parameter_value_validate` trigger rather than a fake.

    Worth its own test for two reasons. `kind` is the only machine-readable
    discriminator a client gets for a trigger failure, and Ruling 19 moved
    it from a top-level `detail` key onto the list entry -- a place a
    careless reshaping could drop it from. And, contrary to what this
    module's docstring and `errors.ts` used to claim, `parameter_index`
    **does** name a field: the trigger's DETAIL carries `'field',
    'entity_ids'` (migration 0006). So the `loc` is `["body",
    "entity_ids"]`, not a bare `["body"]`.
    """
    domain_id = make_domain(db, "dberr")
    day = make_entity_type(db, domain_id, "day")
    shift = make_entity_type(db, domain_id, "shift")
    mon = make_entity(db, day, "mon")
    pd_id = db.execute(
        text(
            "INSERT INTO parameter_def (domain_id, name, index_type_ids) "
            "VALUES (:d, 'demand', ARRAY[:day, :shift]::bigint[]) RETURNING id"
        ),
        {"d": domain_id, "day": day, "shift": shift},
    ).scalar_one()

    with pytest.raises(IntegrityError) as exc_info:
        db.execute(
            text(
                "INSERT INTO parameter_value (parameter_def_id, entity_ids, value) "
                "VALUES (:p, ARRAY[:e]::bigint[], 3)"
            ),
            {"p": pd_id, "e": mon},
        )
    db.rollback()

    http = translate_db_error(exc_info.value, table="parameter_value")

    assert http.status_code == 422
    assert isinstance(http.detail, list) and len(http.detail) == 1, http.detail
    entry = http.detail[0]
    assert entry["kind"] == "parameter_index"
    assert entry["loc"] == ["body", "entity_ids"]


# --------------------------------------------------------------------------
# P0001, from the real forbid_update trigger
# --------------------------------------------------------------------------


def test_real_immutable_table_raise_exception_becomes_409(db):
    problem = make_problem(db, make_domain(db, "dberr"))
    mv = make_model_version(db, problem, {"sets": []})

    with pytest.raises(InternalError) as exc_info:
        db.execute(text("UPDATE model_version SET note = 'x' WHERE id = :i"), {"i": mv})
    db.rollback()

    http = translate_db_error(exc_info.value, table="model_version")

    assert http.status_code == 409
    assert "model_version rows are immutable" in http.detail


# --------------------------------------------------------------------------
# 23505 unique_violation, from the real domain.name UNIQUE constraint
# --------------------------------------------------------------------------


def test_real_unique_violation_becomes_409(db):
    # No commit: Postgres checks a non-deferred UNIQUE constraint per
    # statement, so the second INSERT raises inside this still-open
    # transaction without either row ever reaching disk (same pattern as
    # the other real-database tests here, which never commit either --
    # only rely on `db.rollback()` in the fixture teardown).
    name = f"dup-{_unique()}"
    db.execute(text("INSERT INTO domain (name) VALUES (:n)"), {"n": name})

    with pytest.raises(IntegrityError) as exc_info:
        db.execute(text("INSERT INTO domain (name) VALUES (:n)"), {"n": name})
    db.rollback()

    http = translate_db_error(exc_info.value, table="domain")

    assert http.status_code == 409


# --------------------------------------------------------------------------
# branches a real error can't reach: malformed DETAIL, unhandled pgcode
# --------------------------------------------------------------------------


def test_check_violation_without_json_detail_falls_back_to_409():
    exc = fake_dbapi_error(pgcode="23514", message_detail="not json")
    http = translate_db_error(exc, table="entity")
    assert http.status_code == 409


def test_check_violation_with_json_but_no_kind_falls_back_to_409():
    exc = fake_dbapi_error(pgcode="23514", message_detail=json.dumps({"field": "x"}))
    http = translate_db_error(exc, table="entity")
    assert http.status_code == 409


def test_trigger_payload_without_a_field_blames_the_body_as_a_whole():
    """No trigger in migrations 0006/0007 omits `field` today -- every one
    of the seven kinds sets it -- so this branch is reachable only by a
    fake. It is pinned anyway because the frontend renders a `loc` of bare
    `["body"]` as the message alone, and a `loc` of `["body", None]` would
    reach the user as the literal text "None: ..."."""
    exc = fake_dbapi_error(
        pgcode="23514",
        message_detail=json.dumps({"kind": "some_future_kind"}),
        message_primary="the row as a whole is invalid",
    )
    http = translate_db_error(exc, table="entity")
    assert http.status_code == 422
    assert http.detail == [
        {
            "type": "value_error",
            "loc": ["body"],
            "msg": "the row as a whole is invalid",
            "kind": "some_future_kind",
        }
    ]


def test_check_violation_with_no_detail_at_all_falls_back_to_409():
    exc = fake_dbapi_error(pgcode="23514", message_detail=None)
    http = translate_db_error(exc, table="entity")
    assert http.status_code == 409


def test_unhandled_pgcode_is_reraised():
    exc = fake_dbapi_error(pgcode="42601")  # syntax_error -- a ProgrammingError class
    with pytest.raises(_FakeDBAPIError):
        translate_db_error(exc, table="entity")


def test_trigger_23503_without_a_constraint_forwards_the_trigger_sentence():
    """entity_type_guard's DELETE: TABLE=parameter_def, no CONSTRAINT.
    conflict_detail would rewrite this to "still referenced by"; the
    trigger names the parameters, which is the half the user can act on."""
    message = (
        'entity type "shift" is an index type of parameter demand; '
        "delete or re-index it first"
    )
    exc = fake_dbapi_error(
        pgcode="23503",
        message_primary=message,
        table_name="parameter_def",
    )
    http = translate_db_error(exc, table="entity_type")
    assert http.status_code == 409
    assert http.detail == message


def test_real_fk_23503_still_uses_conflict_detail():
    """A real foreign key always names its constraint, so it keeps the
    generic "still referenced by" sentence -- that is the platform 409
    for every other referenced-row refusal."""
    exc = fake_dbapi_error(
        pgcode="23503",
        message_primary="insert or update on table \"parameter_def\" violates foreign key constraint",
        table_name="parameter_def",
        constraint_name="parameter_def_domain_id_fkey",
    )
    http = translate_db_error(exc, table="entity_type")
    assert http.status_code == 409
    assert http.detail == "entity_type row is still referenced by parameter_def records"
