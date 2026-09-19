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
    def __init__(self, message_detail=None, message_primary=None):
        self.message_detail = message_detail
        self.message_primary = message_primary


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


def fake_dbapi_error(*, pgcode, message_detail=None, message_primary=None):
    return _FakeDBAPIError(_FakeOrig(pgcode, _FakeDiag(message_detail, message_primary)))


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
    assert http.detail["field"] == "nope"
    assert http.detail["kind"] == "unknown_attribute"
    assert isinstance(http.detail["message"], str) and http.detail["message"]


def test_real_required_attribute_check_violation_becomes_422(db):
    domain_id = make_domain(db, "dberr")
    et = make_entity_type(db, domain_id, "employee")
    make_attribute_def(db, et, "badge", "text", required=True)

    with pytest.raises(IntegrityError) as exc_info:
        make_entity(db, et, "e2", "{}")
    db.rollback()

    http = translate_db_error(exc_info.value, table="entity")

    assert http.status_code == 422
    assert http.detail["field"] == "badge"
    assert http.detail["kind"] == "required_attribute"


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


def test_check_violation_with_no_detail_at_all_falls_back_to_409():
    exc = fake_dbapi_error(pgcode="23514", message_detail=None)
    http = translate_db_error(exc, table="entity")
    assert http.status_code == 409


def test_unhandled_pgcode_is_reraised():
    exc = fake_dbapi_error(pgcode="42601")  # syntax_error -- a ProgrammingError class
    with pytest.raises(_FakeDBAPIError):
        translate_db_error(exc, table="entity")
