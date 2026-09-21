"""Migration 0009, parts 2 and 3: the eight domain integrity rules (Ruling 32)
and the `colour` columns (the 2026-09-19 user request (B)).

**Every rule here is proven with raw SQL.** Task 15's seed writes straight
to the database and never passes through a router, and neither does psql,
a migration or a future worker. Several of these rules were already
enforced by a router (Task 8's rules 4 and 6, Task 9's rule 7), so a test
through the API would prove only the router. Each rule gets at least one
refused write and at least one legal write that still succeeds -- a
constraint that refused everything would pass a refusal-only test.

How each rule is enforced, and so what each test asserts:

====  ==========================================  ==============================
rule  mechanism                                   asserted
====  ==========================================  ==============================
1     CHECK attribute_def_enum_values_not_empty   23514 + constraint name
2     CHECK entity_key_not_blank                  23514 + constraint name
3     composite FKs relationship_type_{from,to}   23503 + constraint name
      _type_same_domain_fkey -> entity_type
      (id, domain_id)
4     trigger parameter_def_validate              23514 + JSON DETAIL,
                                                  kind index_type_domain
5     trigger entity_type_guard: 23503 for the    DELETE: 23503 + the
      body-less DELETE, amendment (a) for the     referencing table name;
      UPDATE that moves domain_id                 UPDATE: JSON DETAIL,
                                                  kind index_type_in_use,
                                                  field domain_id
6     trigger parameter_def_validate              23514 + JSON DETAIL,
                                                  kind parameter_reindex
7     composite FK scenario_version_same_problem  23503 + constraint name
      _fkey -> model_version (id, problem_id)
8     CHECK attribute_def_default_value_matches   23514 + constraint name
      _type, via attr_value_matches_type()
colr  CHECK {entity,relationship}_type_colour_hex 23514 + constraint name
====  ==========================================  ==============================

Domain-scope rules (3, 4, 5) are tested with **two** domains and ids that
really exist in the *other* one. An id that merely does not exist would
also be refused by a rule that only checked existence.

Test hygiene: the `db` fixture only ever rolls back, and every refused
write runs inside a SAVEPOINT (`_refused`) so the session stays usable for
the legal write that follows it. The one API test creates its rows through
HTTP and removes them by deleting its domain in a `finally`.
"""

import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.main import app
from app.seed import seed_admin


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _refused(db, sql: str, params: dict | None = None):
    """Run `sql` inside a savepoint, assert the database refused it, roll
    the savepoint back and return the driver's exception (`exc.orig`)."""
    savepoint = db.begin_nested()
    with pytest.raises(DBAPIError) as exc_info:
        db.execute(text(sql), params or {})
    savepoint.rollback()
    return exc_info.value.orig


def _accepted(db, sql: str, params: dict | None = None):
    """Run `sql` inside a savepoint that is *kept*, so later statements see
    its effect; a refusal fails the test with the database's own message."""
    savepoint = db.begin_nested()
    try:
        result = db.execute(text(sql), params or {})
    except DBAPIError as exc:
        savepoint.rollback()
        pytest.fail(f"the database refused a legal write: {exc.orig}")
    savepoint.commit()
    return result


def _check(orig, constraint: str) -> None:
    assert orig.pgcode == "23514", f"expected check_violation, got {orig.pgcode}: {orig}"
    assert orig.diag.constraint_name == constraint, orig.diag.constraint_name


def _foreign_key(orig, constraint: str) -> None:
    assert orig.pgcode == "23503", f"expected foreign_key_violation, got {orig.pgcode}: {orig}"
    assert orig.diag.constraint_name == constraint, orig.diag.constraint_name


def _referenced(orig, referencing_table: str) -> None:
    """A referenced-row refusal: SQLSTATE 23503 naming the table that still
    references the row. `conflict_detail()` reads exactly `diag.table_name`
    to build its 409, so this is the field the API contract turns on."""
    assert orig.pgcode == "23503", f"expected foreign_key_violation, got {orig.pgcode}: {orig}"
    assert orig.diag.table_name == referencing_table, orig.diag.table_name


def _trigger(orig, kind: str, field: str) -> dict:
    """Amendment (a)'s contract: 23514 plus a JSON DETAIL naming kind and
    field, which is what `translate_db_error` turns into a 422."""
    assert orig.pgcode == "23514", f"expected check_violation, got {orig.pgcode}: {orig}"
    detail = json.loads(orig.diag.message_detail)
    assert detail["kind"] == kind, detail
    assert detail["field"] == field, detail
    return detail


def make_domain(db, name: str = "integrity") -> int:
    return db.execute(
        text("INSERT INTO domain (name) VALUES (:n) RETURNING id"),
        {"n": f"{name}-{uuid.uuid4().hex[:8]}"},
    ).scalar_one()


def make_entity_type(db, domain_id: int, name: str) -> int:
    return db.execute(
        text("INSERT INTO entity_type (domain_id, name) VALUES (:d, :n) RETURNING id"),
        {"d": domain_id, "n": name},
    ).scalar_one()


def make_entity(db, entity_type_id: int, key: str) -> int:
    return db.execute(
        text("INSERT INTO entity (entity_type_id, key) VALUES (:t, :k) RETURNING id"),
        {"t": entity_type_id, "k": key},
    ).scalar_one()


def make_parameter_def(db, domain_id: int, name: str, index_type_ids: list[int]) -> int:
    return db.execute(
        text(
            "INSERT INTO parameter_def (domain_id, name, index_type_ids) "
            "VALUES (:d, :n, :i) RETURNING id"
        ),
        {"d": domain_id, "n": name, "i": index_type_ids},
    ).scalar_one()


def make_parameter_value(db, parameter_def_id: int, entity_ids: list[int], value: int) -> None:
    db.execute(
        text(
            "INSERT INTO parameter_value (parameter_def_id, entity_ids, value) "
            "VALUES (:p, :e, :v)"
        ),
        {"p": parameter_def_id, "e": entity_ids, "v": value},
    )


def _count(db, sql: str, params: dict | None = None) -> int:
    return db.execute(text(sql), params or {}).scalar_one()


@pytest.fixture
def two_domains(db):
    """Two domains, each with its own `day` and `shift` types. Every
    domain-scope test uses the *other* domain's real ids, so a rule that
    checked only existence would accept them."""
    mine = make_domain(db, "mine")
    other = make_domain(db, "other")
    return {
        "mine": mine,
        "other": other,
        "day": make_entity_type(db, mine, "day"),
        "shift": make_entity_type(db, mine, "shift"),
        "other_day": make_entity_type(db, other, "day"),
        "other_shift": make_entity_type(db, other, "shift"),
    }


# --------------------------------------------------------------------------
# rule 1: attribute_def.enum_values is non-empty when present
# --------------------------------------------------------------------------

_INSERT_ATTRIBUTE = (
    "INSERT INTO attribute_def (entity_type_id, name, data_type, enum_values, default_value) "
    "VALUES (:t, :n, CAST(:dt AS attr_type), :ev, CAST(:dv AS jsonb)) RETURNING id"
)


def _attribute(t, n, dt, ev=None, dv=None) -> dict:
    return {"t": t, "n": n, "dt": dt, "ev": ev, "dv": dv}


def test_rule1_empty_enum_values_is_refused(db, two_domains):
    orig = _refused(db, _INSERT_ATTRIBUTE, _attribute(two_domains["day"], "grade", "enum", []))
    _check(orig, "attribute_def_enum_values_not_empty")


@pytest.mark.parametrize("values", [[None], ["junior", None]])
def test_rule1_null_enum_member_is_refused(db, two_domains, values):
    """A NULL member makes `entity_validate`'s `v = ANY (enum_values)` NULL
    instead of false for every non-member, and its `IF NOT ok` then lets
    *any* string through -- so a NULL member silently turns the enum off."""
    orig = _refused(
        db, _INSERT_ATTRIBUTE, _attribute(two_domains["day"], "grade", "enum", values)
    )
    _check(orig, "attribute_def_enum_values_not_empty")


def test_rule1_emptying_enum_values_on_update_is_refused(db, two_domains):
    attribute = _accepted(
        db, _INSERT_ATTRIBUTE, _attribute(two_domains["day"], "grade", "enum", ["a"])
    ).scalar_one()
    orig = _refused(
        db, "UPDATE attribute_def SET enum_values = '{}' WHERE id = :a", {"a": attribute}
    )
    _check(orig, "attribute_def_enum_values_not_empty")


def test_rule1_legal_enum_values_are_accepted(db, two_domains):
    one = _accepted(db, _INSERT_ATTRIBUTE, _attribute(two_domains["day"], "grade", "enum", ["a"]))
    many = _accepted(
        db, _INSERT_ATTRIBUTE, _attribute(two_domains["day"], "band", "enum", ["x", "y", "z"])
    )
    # NULL stays legal for every non-enum type (the 0006 pairing CHECK).
    plain = _accepted(db, _INSERT_ATTRIBUTE, _attribute(two_domains["day"], "hours", "integer"))
    assert one.scalar_one() and many.scalar_one() and plain.scalar_one()


# --------------------------------------------------------------------------
# rule 2: entity.key is non-empty and not whitespace-only
# --------------------------------------------------------------------------


@pytest.mark.parametrize("key", ["", " ", "   ", "\t", "\n", " \r\n\t "])
def test_rule2_blank_entity_key_is_refused(db, two_domains, key):
    orig = _refused(
        db,
        "INSERT INTO entity (entity_type_id, key) VALUES (:t, :k)",
        {"t": two_domains["day"], "k": key},
    )
    _check(orig, "entity_key_not_blank")


def test_rule2_blanking_a_key_on_update_is_refused(db, two_domains):
    entity = make_entity(db, two_domains["day"], "mon")
    orig = _refused(db, "UPDATE entity SET key = '  ' WHERE id = :e", {"e": entity})
    _check(orig, "entity_key_not_blank")


@pytest.mark.parametrize("key", ["mon", "x", "0", " padded ", "two words"])
def test_rule2_legal_keys_are_accepted(db, two_domains, key):
    _accepted(
        db,
        "INSERT INTO entity (entity_type_id, key) VALUES (:t, :k)",
        {"t": two_domains["day"], "k": key},
    )


# --------------------------------------------------------------------------
# rule 3: a relationship type's endpoint types belong to its own domain
# --------------------------------------------------------------------------

_INSERT_RELATIONSHIP_TYPE = (
    "INSERT INTO relationship_type (domain_id, name, from_type_id, to_type_id) "
    "VALUES (:d, :n, :f, :t) RETURNING id"
)


@pytest.mark.parametrize(
    ("from_key", "to_key", "constraint"),
    [
        ("other_day", "shift", "relationship_type_from_type_same_domain_fkey"),
        ("day", "other_shift", "relationship_type_to_type_same_domain_fkey"),
    ],
)
def test_rule3_endpoint_type_from_another_domain_is_refused(
    db, two_domains, from_key, to_key, constraint
):
    """Each side on its own: a rule that checked only `from_type_id` (or
    only `to_type_id`) is caught by one of the two cases."""
    orig = _refused(
        db,
        _INSERT_RELATIONSHIP_TYPE,
        {
            "d": two_domains["mine"],
            "n": "covers",
            "f": two_domains[from_key],
            "t": two_domains[to_key],
        },
    )
    _foreign_key(orig, constraint)


def test_rule3_repointing_an_endpoint_to_another_domain_is_refused(db, two_domains):
    rel_type = _accepted(
        db,
        _INSERT_RELATIONSHIP_TYPE,
        {"d": two_domains["mine"], "n": "covers", "f": two_domains["day"], "t": two_domains["shift"]},
    ).scalar_one()
    orig = _refused(
        db,
        "UPDATE relationship_type SET to_type_id = :t WHERE id = :r",
        {"t": two_domains["other_shift"], "r": rel_type},
    )
    _foreign_key(orig, "relationship_type_to_type_same_domain_fkey")


def test_rule3_moving_a_referenced_entity_type_to_another_domain_is_refused(db, two_domains):
    """The other way to break the rule: leave the relationship type alone
    and move the entity type out from under it."""
    _accepted(
        db,
        _INSERT_RELATIONSHIP_TYPE,
        {"d": two_domains["mine"], "n": "covers", "f": two_domains["day"], "t": two_domains["shift"]},
    )
    # Renamed as it moves, so UNIQUE (domain_id, name) is not what refuses it.
    orig = _refused(
        db,
        "UPDATE entity_type SET domain_id = :o, name = 'moved' WHERE id = :t",
        {"o": two_domains["other"], "t": two_domains["shift"]},
    )
    _foreign_key(orig, "relationship_type_to_type_same_domain_fkey")


def test_rule3_same_domain_endpoints_are_accepted(db, two_domains):
    mine = _accepted(
        db,
        _INSERT_RELATIONSHIP_TYPE,
        {"d": two_domains["mine"], "n": "covers", "f": two_domains["day"], "t": two_domains["shift"]},
    ).scalar_one()
    # The other domain's own relationship type over its own types is fine too.
    theirs = _accepted(
        db,
        _INSERT_RELATIONSHIP_TYPE,
        {
            "d": two_domains["other"],
            "n": "covers",
            "f": two_domains["other_day"],
            "t": two_domains["other_shift"],
        },
    ).scalar_one()
    assert mine != theirs


def test_rule3_deleting_an_endpoint_type_still_cascades(db, two_domains):
    """The composite FKs must not change 0006's ON DELETE CASCADE."""
    rel_type = _accepted(
        db,
        _INSERT_RELATIONSHIP_TYPE,
        {"d": two_domains["mine"], "n": "covers", "f": two_domains["day"], "t": two_domains["shift"]},
    ).scalar_one()
    _accepted(db, "DELETE FROM entity_type WHERE id = :t", {"t": two_domains["shift"]})
    assert _count(db, "SELECT count(*) FROM relationship_type WHERE id = :r", {"r": rel_type}) == 0


# --------------------------------------------------------------------------
# rule 4: every parameter_def.index_type_ids id exists, in the parameter's domain
# --------------------------------------------------------------------------

_INSERT_PARAMETER = (
    "INSERT INTO parameter_def (domain_id, name, index_type_ids) VALUES (:d, :n, :i) RETURNING id"
)


@pytest.mark.parametrize(
    "index",
    [
        ["other_day"],  # another domain's real type, alone
        ["day", "other_shift"],  # ... in second position, after a good one
        ["other_day", "shift"],  # ... in first position, before a good one
        ["other_shift", "day", "other_day"],  # two bad: the *first* is reported
    ],
)
def test_rule4_index_type_from_another_domain_is_refused(db, two_domains, index):
    ids = [two_domains[key] for key in index]
    orig = _refused(db, _INSERT_PARAMETER, {"d": two_domains["mine"], "n": "demand", "i": ids})
    detail = _trigger(orig, "index_type_domain", "index_type_ids")
    foreign = next(i for i in ids if i in (two_domains["other_day"], two_domains["other_shift"]))
    assert detail["index_type_id"] == foreign, detail


@pytest.mark.parametrize("missing", [0, -1, 9_000_000_000_000])
def test_rule4_nonexistent_index_type_is_refused(db, two_domains, missing):
    orig = _refused(
        db,
        _INSERT_PARAMETER,
        {"d": two_domains["mine"], "n": "demand", "i": [two_domains["day"], missing]},
    )
    _trigger(orig, "index_type_domain", "index_type_ids")


def test_rule4_null_index_type_is_refused(db, two_domains):
    orig = _refused(
        db,
        "INSERT INTO parameter_def (domain_id, name, index_type_ids) "
        "VALUES (:d, 'demand', ARRAY[:t, NULL]::bigint[])",
        {"d": two_domains["mine"], "t": two_domains["day"]},
    )
    _trigger(orig, "index_type_domain", "index_type_ids")


def test_rule4_reindexing_onto_another_domain_is_refused(db, two_domains):
    parameter = _accepted(
        db, _INSERT_PARAMETER, {"d": two_domains["mine"], "n": "demand", "i": [two_domains["day"]]}
    ).scalar_one()
    orig = _refused(
        db,
        "UPDATE parameter_def SET index_type_ids = :i WHERE id = :p",
        {"i": [two_domains["day"], two_domains["other_shift"]], "p": parameter},
    )
    _trigger(orig, "index_type_domain", "index_type_ids")


def test_rule4_moving_a_parameter_to_another_domain_is_refused(db, two_domains):
    """Changing `domain_id` re-judges the index: `day` is not in `other`."""
    parameter = _accepted(
        db, _INSERT_PARAMETER, {"d": two_domains["mine"], "n": "demand", "i": [two_domains["day"]]}
    ).scalar_one()
    orig = _refused(
        db,
        "UPDATE parameter_def SET domain_id = :o WHERE id = :p",
        {"o": two_domains["other"], "p": parameter},
    )
    _trigger(orig, "index_type_domain", "index_type_ids")


def test_rule4_same_domain_index_types_are_accepted(db, two_domains):
    mine = _accepted(
        db,
        _INSERT_PARAMETER,
        {"d": two_domains["mine"], "n": "demand", "i": [two_domains["day"], two_domains["shift"]]},
    ).scalar_one()
    theirs = _accepted(
        db,
        _INSERT_PARAMETER,
        {
            "d": two_domains["other"],
            "n": "demand",
            "i": [two_domains["other_shift"], two_domains["other_day"]],
        },
    ).scalar_one()
    # And re-indexing within the domain, with no values stored, is fine.
    _accepted(
        db,
        "UPDATE parameter_def SET index_type_ids = :i WHERE id = :p",
        {"i": [two_domains["shift"]], "p": mine},
    )
    assert theirs


# --------------------------------------------------------------------------
# rule 5: an entity type used as an index type cannot be deleted
# --------------------------------------------------------------------------


def test_rule5_deleting_an_index_type_is_refused(db, two_domains):
    """A DELETE has no request body, so this path deliberately does *not*
    use amendment (a): it raises `foreign_key_violation` naming the
    referencing table, the shape a real ON DELETE RESTRICT would produce.
    `translate_db_error` forwards the trigger's sentence (no
    `constraint_name`) rather than conflict_detail()'s generic "still
    referenced by" -- round 3; the first cut returned a 422 blaming
    `index_type_ids`, a field a DELETE cannot carry."""
    parameter = make_parameter_def(
        db, two_domains["mine"], "demand", [two_domains["day"], two_domains["shift"]]
    )
    # Second position only, so a guard that looked at index_type_ids[1]
    # alone would let it through.
    orig = _refused(db, "DELETE FROM entity_type WHERE id = :t", {"t": two_domains["shift"]})
    _referenced(orig, "parameter_def")
    assert orig.diag.message_primary == (
        'entity type "shift" is an index type of parameter demand; '
        "delete or re-index it first"
    ), orig.diag.message_primary
    # Refused, not cascaded: both rows are still there.
    assert _count(db, "SELECT count(*) FROM entity_type WHERE id = :t", {"t": two_domains["shift"]}) == 1
    assert _count(db, "SELECT count(*) FROM parameter_def WHERE id = :p", {"p": parameter}) == 1


def test_rule5_moving_an_index_type_to_another_domain_is_refused(db, two_domains):
    """Otherwise rule 4 could be broken from the entity_type side.

    Unlike the DELETE above, an UPDATE does carry a body, so amendment (a)
    applies -- and the field it blames is the one the statement wrote,
    `domain_id`, not `index_type_ids` (untouched here, and in another
    table's row)."""
    make_parameter_def(db, two_domains["mine"], "demand", [two_domains["day"]])
    orig = _refused(
        db,
        "UPDATE entity_type SET domain_id = :o, name = 'moved' WHERE id = :t",
        {"o": two_domains["other"], "t": two_domains["day"]},
    )
    detail = _trigger(orig, "index_type_in_use", "domain_id")
    assert detail["record"] == "day", detail
    assert detail["parameters"] == ["demand"], detail


def test_rule5_deleting_an_unreferenced_type_is_accepted(db, two_domains):
    """`shift` is not an index of anything -- but `day` is, in the same
    domain, and another domain's parameter uses a type too. A guard that
    refused whenever *any* parameter existed would fail here."""
    make_parameter_def(db, two_domains["mine"], "demand", [two_domains["day"]])
    make_parameter_def(db, two_domains["other"], "demand", [two_domains["other_shift"]])
    _accepted(db, "DELETE FROM entity_type WHERE id = :t", {"t": two_domains["shift"]})
    assert _count(db, "SELECT count(*) FROM entity_type WHERE id = :t", {"t": two_domains["shift"]}) == 0


def test_rule5_deleting_the_parameter_first_frees_the_type(db, two_domains):
    parameter = make_parameter_def(db, two_domains["mine"], "demand", [two_domains["day"]])
    _accepted(db, "DELETE FROM parameter_def WHERE id = :p", {"p": parameter})
    _accepted(db, "DELETE FROM entity_type WHERE id = :t", {"t": two_domains["day"]})


def test_rule5_renaming_an_index_type_is_accepted(db, two_domains):
    make_parameter_def(db, two_domains["mine"], "demand", [two_domains["day"]])
    _accepted(db, "UPDATE entity_type SET name = 'weekday' WHERE id = :t", {"t": two_domains["day"]})


def test_rule5_deleting_the_whole_domain_still_cascades(db, two_domains):
    """The guard must not block ON DELETE CASCADE from `domain`: the
    parameter goes in the same statement, so nothing is left dangling.
    Every test fixture on the platform tears down this way."""
    mine = two_domains["mine"]
    day, shift = two_domains["day"], two_domains["shift"]
    parameter = make_parameter_def(db, mine, "demand", [day, shift])
    mon = make_entity(db, day, "mon")
    morning = make_entity(db, shift, "morning")
    make_parameter_value(db, parameter, [mon, morning], 3)

    _accepted(db, "DELETE FROM domain WHERE id = :d", {"d": mine})

    assert _count(db, "SELECT count(*) FROM entity_type WHERE domain_id = :d", {"d": mine}) == 0
    assert _count(db, "SELECT count(*) FROM parameter_def WHERE id = :p", {"p": parameter}) == 0
    # The other domain is untouched.
    assert _count(
        db, "SELECT count(*) FROM entity_type WHERE domain_id = :d", {"d": two_domains["other"]}
    ) == 2


# --------------------------------------------------------------------------
# rule 6: index_type_ids cannot change while values are stored
# --------------------------------------------------------------------------


@pytest.fixture
def stored(db, two_domains):
    """demand[day, shift] with one stored cell; `empty` has none."""
    day, shift = two_domains["day"], two_domains["shift"]
    demand = make_parameter_def(db, two_domains["mine"], "demand", [day, shift])
    empty = make_parameter_def(db, two_domains["mine"], "empty", [day, shift])
    make_parameter_value(db, demand, [make_entity(db, day, "mon"), make_entity(db, shift, "am")], 5)
    return {"demand": demand, "empty": empty}


@pytest.mark.parametrize("new_index", [["shift", "day"], ["day"], ["shift"]])
def test_rule6_reindexing_with_stored_values_is_refused(db, two_domains, stored, new_index):
    orig = _refused(
        db,
        "UPDATE parameter_def SET index_type_ids = :i WHERE id = :p",
        {"i": [two_domains[k] for k in new_index], "p": stored["demand"]},
    )
    detail = _trigger(orig, "parameter_reindex", "index_type_ids")
    assert detail["record"] == "demand", detail


def test_rule6_reindexing_without_stored_values_is_accepted(db, two_domains, stored):
    """`empty` has no cells -- but `demand`, in the same domain, does. A
    guard that looked for *any* stored value would refuse this."""
    _accepted(
        db,
        "UPDATE parameter_def SET index_type_ids = :i WHERE id = :p",
        {"i": [two_domains["shift"], two_domains["day"]], "p": stored["empty"]},
    )


def test_rule6_other_changes_with_stored_values_are_accepted(db, two_domains, stored):
    _accepted(
        db,
        "UPDATE parameter_def SET default_value = 9, name = 'need', unit = 'people' WHERE id = :p",
        {"p": stored["demand"]},
    )
    # Writing the same index back is not a change.
    _accepted(
        db,
        "UPDATE parameter_def SET index_type_ids = :i WHERE id = :p",
        {"i": [two_domains["day"], two_domains["shift"]], "p": stored["demand"]},
    )


def test_rule6_reindexing_after_the_values_are_cleared_is_accepted(db, two_domains, stored):
    _accepted(db, "DELETE FROM parameter_value WHERE parameter_def_id = :p", {"p": stored["demand"]})
    _accepted(
        db,
        "UPDATE parameter_def SET index_type_ids = :i WHERE id = :p",
        {"i": [two_domains["shift"]], "p": stored["demand"]},
    )


# --------------------------------------------------------------------------
# rule 7: a scenario points at a version of its own problem
# --------------------------------------------------------------------------


@pytest.fixture
def crossed(db, two_domains):
    """Problems A and B, each with a version numbered 1 -- so a rule that
    compared version *numbers* rather than ownership would accept the
    crossed pair."""
    domain = two_domains["mine"]
    ids = {}
    for label in ("a", "b"):
        problem = db.execute(
            text("INSERT INTO problem (domain_id, name) VALUES (:d, :n) RETURNING id"),
            {"d": domain, "n": f"problem-{label}"},
        ).scalar_one()
        version = db.execute(
            text(
                "INSERT INTO model_version (problem_id, ir) VALUES (:p, '{}'::jsonb) "
                "RETURNING id"
            ),
            {"p": problem},
        ).scalar_one()
        ids[label], ids[f"{label}1"] = problem, version
    return ids


_INSERT_SCENARIO = (
    "INSERT INTO scenario (problem_id, model_version_id, name) VALUES (:p, :m, :n) RETURNING id"
)


def test_rule7_scenario_on_another_problems_version_is_refused(db, crossed):
    orig = _refused(db, _INSERT_SCENARIO, {"p": crossed["a"], "m": crossed["b1"], "n": "x"})
    _foreign_key(orig, "scenario_version_same_problem_fkey")


def test_rule7_repointing_a_scenario_to_another_problems_version_is_refused(db, crossed):
    scenario = _accepted(
        db, _INSERT_SCENARIO, {"p": crossed["a"], "m": crossed["a1"], "n": "base"}
    ).scalar_one()
    orig = _refused(
        db,
        "UPDATE scenario SET model_version_id = :m WHERE id = :s",
        {"m": crossed["b1"], "s": scenario},
    )
    _foreign_key(orig, "scenario_version_same_problem_fkey")


def test_rule7_scenario_on_its_own_problems_version_is_accepted(db, crossed):
    for label in ("a", "b"):
        _accepted(
            db,
            _INSERT_SCENARIO,
            {"p": crossed[label], "m": crossed[f"{label}1"], "n": "base"},
        )
    # Deleting a problem still takes its versions and scenarios with it.
    _accepted(db, "DELETE FROM problem WHERE id = :p", {"p": crossed["b"]})
    assert _count(db, "SELECT count(*) FROM scenario WHERE problem_id = :p", {"p": crossed["b"]}) == 0
    assert _count(db, "SELECT count(*) FROM scenario WHERE problem_id = :p", {"p": crossed["a"]}) == 1


# --------------------------------------------------------------------------
# rule 8: attribute_def.default_value matches data_type
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("data_type", "enum_values", "bad"),
    [
        ("integer", None, '"banana"'),
        ("integer", None, "2.5"),  # a rule that only refused strings passes this
        ("integer", None, "true"),
        ("integer", None, '"5"'),
        ("number", None, '"2.5"'),
        ("number", None, "false"),
        ("boolean", None, "0"),
        ("boolean", None, '"true"'),
        ("enum", ["junior", "senior"], '"wizard"'),
        ("enum", ["junior", "senior"], "1"),
        ("text", None, "5"),
        ("text", None, "true"),
        ("date", None, "20260919"),
        ("time", None, "900"),
        ("text", None, "[]"),
        ("text", None, "{}"),
        # jsonb 'null' is not SQL NULL: it is a value of no data_type (Ruling 18).
        ("integer", None, "null"),
        ("text", None, "null"),
    ],
)
def test_rule8_default_that_contradicts_its_type_is_refused(
    db, two_domains, data_type, enum_values, bad
):
    orig = _refused(
        db,
        _INSERT_ATTRIBUTE,
        _attribute(two_domains["day"], "attr", data_type, enum_values, bad),
    )
    _check(orig, "attribute_def_default_value_matches_type")


@pytest.mark.parametrize(
    ("data_type", "enum_values", "good"),
    [
        ("integer", None, "0"),  # falsy, and must not read as "no default"
        ("integer", None, "-7"),
        ("number", None, "0"),
        ("number", None, "2.5"),
        ("boolean", None, "false"),
        ("boolean", None, "true"),
        ("enum", ["junior", "senior"], '"senior"'),
        ("text", None, '""'),
        ("text", None, '"hello"'),
        ("date", None, '"2026-09-19"'),
        ("time", None, '"09:00"'),
        ("integer", None, None),  # SQL NULL: no default at all
        ("enum", ["junior"], None),
    ],
)
def test_rule8_default_that_matches_its_type_is_accepted(
    db, two_domains, data_type, enum_values, good
):
    _accepted(
        db, _INSERT_ATTRIBUTE, _attribute(two_domains["day"], "attr", data_type, enum_values, good)
    )


def test_rule8_dropping_the_defaults_enum_member_is_refused(db, two_domains):
    """The CHECK is re-judged on UPDATE, so the default cannot be orphaned
    by editing `enum_values` (or `data_type`) instead of the default."""
    attribute = _accepted(
        db,
        _INSERT_ATTRIBUTE,
        _attribute(two_domains["day"], "grade", "enum", ["junior", "senior"], '"senior"'),
    ).scalar_one()
    orig = _refused(
        db, "UPDATE attribute_def SET enum_values = '{junior}' WHERE id = :a", {"a": attribute}
    )
    _check(orig, "attribute_def_default_value_matches_type")
    orig = _refused(
        db,
        "UPDATE attribute_def SET data_type = 'integer', enum_values = NULL WHERE id = :a",
        {"a": attribute},
    )
    _check(orig, "attribute_def_default_value_matches_type")


# The candidate values the agreement test runs through every data type.
_CANDIDATES = [
    "0", "5", "-3", "2.0", "2.5", "1e2", "true", "false",
    '"banana"', '"5"', '""', '"senior"', '"2026-09-19"', "[]", "{}",
]


@pytest.mark.parametrize(
    ("data_type", "enum_values"),
    [
        ("integer", None),
        ("number", None),
        ("text", None),
        ("boolean", None),
        ("enum", ["junior", "senior"]),
        ("date", None),
        ("time", None),
    ],
)
def test_rule8_agrees_with_entity_validate(db, two_domains, data_type, enum_values):
    """"A default can never be one an entity write would then reject":
    for every candidate value, the default CHECK and `entity_validate`
    give the same verdict. Judged side by side, so the two rules cannot
    drift apart without this test naming the value they disagree on.

    (jsonb `null` is deliberately excluded: `entity_validate` treats a
    null attr as absent, but a null *default* is refused -- see the rule
    8 refusal cases.)"""
    judge = make_entity_type(db, two_domains["mine"], "judge")
    _accepted(
        db, _INSERT_ATTRIBUTE, _attribute(judge, "attr", data_type, enum_values)
    )  # no default: entity_validate judges only what the entity sends
    disagreements = []
    for n, candidate in enumerate(_CANDIDATES):
        savepoint = db.begin_nested()
        try:
            db.execute(
                text(
                    "INSERT INTO entity (entity_type_id, key, attrs) "
                    "VALUES (:t, :k, jsonb_build_object('attr', CAST(:v AS jsonb)))"
                ),
                {"t": judge, "k": f"e{n}", "v": candidate},
            )
            entity_ok = True
        except DBAPIError:
            entity_ok = False
        savepoint.rollback()

        savepoint = db.begin_nested()
        try:
            db.execute(
                text(_INSERT_ATTRIBUTE),
                _attribute(two_domains["day"], f"d{n}", data_type, enum_values, candidate),
            )
            default_ok = True
        except DBAPIError:
            default_ok = False
        savepoint.rollback()

        if entity_ok != default_ok:
            disagreements.append((candidate, entity_ok, default_ok))
    assert disagreements == [], f"(value, entity_validate, default CHECK): {disagreements}"


# --------------------------------------------------------------------------
# part 3: colour on entity_type and relationship_type
# --------------------------------------------------------------------------


def _colour_writes(two_domains) -> dict[str, tuple[str, dict]]:
    return {
        "entity_type": (
            "INSERT INTO entity_type (domain_id, name, colour) VALUES (:d, 'tinted', :c)",
            {"d": two_domains["mine"]},
        ),
        "relationship_type": (
            "INSERT INTO relationship_type (domain_id, name, from_type_id, to_type_id, colour) "
            "VALUES (:d, 'tinted', :f, :t, :c)",
            {"d": two_domains["mine"], "f": two_domains["day"], "t": two_domains["shift"]},
        ),
    }


@pytest.mark.parametrize("table", ["entity_type", "relationship_type"])
@pytest.mark.parametrize(
    "colour",
    ["#A1B2C3", "#a1B2c3", "#abc", "red", "a1b2c3", "#a1b2c", "#a1b2c3d", "#a1b2cg", "#a1b2c3\n", ""],
)
def test_colour_that_is_not_lowercase_six_digit_hex_is_refused(db, two_domains, table, colour):
    sql, params = _colour_writes(two_domains)[table]
    orig = _refused(db, sql, {**params, "c": colour})
    _check(orig, f"{table}_colour_hex")


@pytest.mark.parametrize("table", ["entity_type", "relationship_type"])
@pytest.mark.parametrize("colour", ["#a1b2c3", "#000000", "#ffffff", None])
def test_colour_lowercase_hex_or_null_is_accepted(db, two_domains, table, colour):
    sql, params = _colour_writes(two_domains)[table]
    _accepted(db, sql, {**params, "c": colour})
    stored = db.execute(
        text(f"SELECT colour FROM {table} WHERE domain_id = :d AND name = 'tinted'"),
        {"d": two_domains["mine"]},
    ).scalar_one()
    assert stored == colour


def test_colour_columns_are_mirrored_in_the_orm(db, two_domains):
    from app.models.v1_domain import EntityType, RelationshipType

    for model in (EntityType, RelationshipType):
        assert "colour" in model.__table__.columns, model
        assert model.__table__.columns["colour"].nullable, model
    db.execute(
        text("UPDATE entity_type SET colour = '#123abc' WHERE id = :t"), {"t": two_domains["day"]}
    )
    assert getattr(db.get(EntityType, two_domains["day"]), "colour", None) == "#123abc"


# --------------------------------------------------------------------------
# a new trigger kind over real HTTP: rule 5 through the entity-type router
# --------------------------------------------------------------------------


def test_deleting_an_index_type_through_the_api_is_a_409_naming_the_table():
    """The routers were not changed, so the entity-type DELETE reaches the
    database. The trigger's refusal must come back through
    `translate_db_error` as a readable 409 -- not a 500, and not the 204
    that left `index_type_ids` dangling before 0009.

    409, not 422, because a DELETE has no body to blame a field in; this
    is the trigger's own sentence, forwarded because a RAISE 23503 has no
    constraint_name -- a genuine foreign key still gets conflict_detail()'s
    "still referenced by"."""
    session = SessionLocal()
    seed_admin(session)
    session.close()
    client = TestClient(app)
    settings = get_settings()
    token = client.post(
        "/api/auth/login",
        data={"username": settings.admin_username, "password": settings.admin_password},
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    domain = client.post(
        "/api/domain/", json={"name": f"integrity-{uuid.uuid4().hex[:8]}"}, headers=headers
    ).json()["id"]
    try:
        day = client.post(
            "/api/v1/entity-types", json={"domain_id": domain, "name": "day"}, headers=headers
        ).json()["id"]
        created = client.post(
            "/api/v1/parameters",
            json={"domain_id": domain, "name": "demand", "index_type_ids": [day]},
            headers=headers,
        )
        assert created.status_code == 201, created.text

        response = client.delete(f"/api/v1/entity-types/{day}", headers=headers)

        assert response.status_code == 409, response.text
        detail = response.json()["detail"]
        assert detail == (
            'entity type "day" is an index type of parameter demand; '
            "delete or re-index it first"
        ), detail
        assert client.get(f"/api/v1/entity-types/{day}", headers=headers).status_code == 200
    finally:
        deleted = client.delete(f"/api/domain/{domain}", headers=headers)
        # The domain cascade must get past the guard, or this test leaks.
        assert deleted.status_code == 204, deleted.text


# --------------------------------------------------------------------------
# part 1 housekeeping: 0009's downgrade restores 0007's function verbatim
# --------------------------------------------------------------------------


def test_downgrade_snapshot_body_is_a_byte_copy_of_0007():
    """`downgrade()` re-runs `_SNAPSHOT_DATASET_0007`. It must be 0007's own
    CREATE FUNCTION statement, byte for byte -- a retyped copy could drift
    and a downgrade would then install a function no migration defines."""
    import importlib.util
    from pathlib import Path

    versions = Path(__file__).resolve().parent.parent / "alembic" / "versions"
    source_0007 = (versions / "0007_schema_v1_problem_run.py").read_text(encoding="utf-8")
    start = source_0007.index("        CREATE FUNCTION snapshot_dataset(")
    end = source_0007.index("END $$;\n", start) + len("END $$;\n")

    spec = importlib.util.spec_from_file_location(
        "migration_0009", versions / "0009_snapshot_defaults_integrity_colour.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module._SNAPSHOT_DATASET_0007 == "\n" + source_0007[start:end]
