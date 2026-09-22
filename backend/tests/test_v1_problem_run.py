"""Schema v1 PROBLEM + RUN halves: hashing, immutability, versioning,
``snapshot_dataset()`` and the ``run_overview`` view.

Contract tests for migration ``0007_schema_v1_problem_run``. Everything
here is exercised through raw SQL, because every behaviour under test
lives in a trigger, a function or a view rather than in Python.

Note on the exception class: ``forbid_update()`` and ``snapshot_dataset()``
raise with a bare ``RAISE EXCEPTION``, which is SQLSTATE **P0001**.
psycopg2 maps SQLSTATE class ``P0`` to ``psycopg2.InternalError`` (the
concrete class is ``psycopg2.errors.RaiseException``), and SQLAlchemy wraps
that as ``sqlalchemy.exc.InternalError`` -- *not* ``ProgrammingError``,
which psycopg2 reserves for classes 20/21/3D/3F/42/44. Amendment (a)'s
structured 23514 payloads apply to the DOMAIN validation triggers only, so
there is no JSON DETAIL to read here.
"""

import json

import pytest
from sqlalchemy import text
from sqlalchemy.exc import InternalError

from app.core.db import SessionLocal
from app.models.v1_problem import IMMUTABLE_TABLES


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


_counter = 0


def _unique() -> int:
    """Test-local sequence, so names stay unique inside one pytest process."""
    global _counter
    _counter += 1
    return _counter


def _raised(exc_info) -> str:
    """Assert the error really is a plpgsql RAISE and return its message."""
    orig = exc_info.value.orig
    assert orig.pgcode == "P0001", f"expected raise_exception, got {orig.pgcode}"
    return str(exc_info.value)


# --------------------------------------------------------------------------
# builders -- every test constructs its own domain, so order does not matter
# --------------------------------------------------------------------------


def make_domain(db, name: str = "dom") -> int:
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


def make_attribute_def(db, entity_type_id: int, name: str, data_type: str) -> int:
    return db.execute(
        text(
            "INSERT INTO attribute_def (entity_type_id, name, data_type) "
            "VALUES (:t, :n, CAST(:dt AS attr_type)) RETURNING id"
        ),
        {"t": entity_type_id, "n": name, "dt": data_type},
    ).scalar_one()


def make_entity(
    db,
    entity_type_id: int,
    key: str,
    *,
    sort_order: int = 0,
    active: bool = True,
    attrs: dict | None = None,
    label: str | None = None,
) -> int:
    return db.execute(
        text(
            "INSERT INTO entity (entity_type_id, key, sort_order, active, attrs, label) "
            "VALUES (:t, :k, :s, :a, CAST(:at AS jsonb), :l) RETURNING id"
        ),
        {
            "t": entity_type_id,
            "k": key,
            "s": sort_order,
            "a": active,
            "at": json.dumps(attrs or {}),
            "l": label,
        },
    ).scalar_one()


def make_parameter_def(
    db, domain_id: int, name: str, index_type_ids: list[int], default_value: int = 0
) -> int:
    return db.execute(
        text(
            "INSERT INTO parameter_def (domain_id, name, index_type_ids, default_value) "
            "VALUES (:d, :n, :i, :dv) RETURNING id"
        ),
        {"d": domain_id, "n": name, "i": index_type_ids, "dv": default_value},
    ).scalar_one()


def make_parameter_value(db, parameter_def_id: int, entity_ids: list[int], value: int) -> None:
    db.execute(
        text(
            "INSERT INTO parameter_value (parameter_def_id, entity_ids, value) "
            "VALUES (:p, :e, :v)"
        ),
        {"p": parameter_def_id, "e": entity_ids, "v": value},
    )


def make_problem(db, domain_id: int, name: str = "prob") -> int:
    return db.execute(
        text("INSERT INTO problem (domain_id, name) VALUES (:d, :n) RETURNING id"),
        {"d": domain_id, "n": f"{name}-{_unique()}"},
    ).scalar_one()


def make_model_version(db, problem_id: int, ir: dict, note: str | None = None) -> int:
    """`version` is deliberately not supplied: next_model_version() fills it."""
    return db.execute(
        text(
            "INSERT INTO model_version (problem_id, ir, note) "
            "VALUES (:p, CAST(:ir AS jsonb), :n) RETURNING id"
        ),
        {"p": problem_id, "ir": json.dumps(ir), "n": note},
    ).scalar_one()


def make_scenario(db, problem_id: int, model_version_id: int, name: str = "base") -> int:
    return db.execute(
        text(
            "INSERT INTO scenario (problem_id, model_version_id, name) "
            "VALUES (:p, :m, :n) RETURNING id"
        ),
        {"p": problem_id, "m": model_version_id, "n": f"{name}-{_unique()}"},
    ).scalar_one()


def make_dataset(db, problem_id: int, data: dict) -> int:
    """`data_hash` is deliberately not supplied: set_hash() fills it."""
    return db.execute(
        text("INSERT INTO dataset (problem_id, data) VALUES (:p, CAST(:d AS jsonb)) RETURNING id"),
        {"p": problem_id, "d": json.dumps(data)},
    ).scalar_one()


def make_run(db, scenario_id: int, dataset_id: int, status: str = "queued") -> int:
    return db.execute(
        text(
            "INSERT INTO run (scenario_id, dataset_id, status) "
            "VALUES (:s, :d, CAST(:st AS run_status)) RETURNING id"
        ),
        {"s": scenario_id, "d": dataset_id, "st": status},
    ).scalar_one()


def make_constraint_result(
    db,
    run_id: int,
    constraint_id: str,
    *,
    hard: bool = True,
    satisfied: bool = True,
    total_violation: int = 0,
    penalty_paid: int = 0,
) -> None:
    db.execute(
        text(
            "INSERT INTO constraint_result "
            "(run_id, constraint_id, label, hard, satisfied, total_violation, penalty_paid) "
            "VALUES (:r, :c, :l, :h, :s, :tv, :pp)"
        ),
        {
            "r": run_id,
            "c": constraint_id,
            "l": constraint_id.replace("_", " "),
            "h": hard,
            "s": satisfied,
            "tv": total_violation,
            "pp": penalty_paid,
        },
    )


# --------------------------------------------------------------------------
# migration shape
# --------------------------------------------------------------------------

V1_PROBLEM_RUN_TABLES = {
    "template",
    "problem",
    "model_version",
    "scenario",
    "dataset",
    "run",
    "solution",
    "constraint_result",
}


def test_problem_and_run_tables_exist_in_public(db):
    present = set(
        db.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = ANY(:t)"
            ),
            {"t": sorted(V1_PROBLEM_RUN_TABLES)},
        ).scalars()
    )
    assert present == V1_PROBLEM_RUN_TABLES


def test_surrogate_keys_are_bigint_identity(db):
    """No UUIDs in v1. `solution` and `constraint_result` key off `run_id`
    instead of carrying a surrogate, so they are excluded."""
    identity_tables = sorted(V1_PROBLEM_RUN_TABLES - {"solution", "constraint_result"})
    rows = db.execute(
        text(
            "SELECT table_name, data_type, is_identity, identity_generation "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' AND column_name = 'id' AND table_name = ANY(:t)"
        ),
        {"t": identity_tables},
    ).all()

    assert sorted(r.table_name for r in rows) == identity_tables
    for row in rows:
        assert row.data_type == "bigint", row.table_name
        assert row.is_identity == "YES", row.table_name
        assert row.identity_generation == "ALWAYS", row.table_name


def test_run_status_enum_labels(db):
    labels = (
        db.execute(
            text(
                "SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
                "WHERE t.typname = 'run_status' ORDER BY e.enumsortorder"
            )
        )
        .scalars()
        .all()
    )
    assert labels == [
        "queued",
        "running",
        "optimal",
        "feasible",
        "infeasible",
        "unknown",
        "error",
        "cancelled",
        # 0029 appends it: ALTER TYPE ... ADD VALUE goes on the end.
        "unbounded",
    ]


def test_indexes_functions_and_view_exist(db):
    indexes = set(
        db.execute(
            text(
                "SELECT indexname FROM pg_indexes WHERE indexname IN "
                "('run_scenario_idx', 'run_queue_idx', 'constraint_result_violated_idx')"
            )
        ).scalars()
    )
    functions = set(
        db.execute(
            text(
                "SELECT proname FROM pg_proc WHERE proname IN "
                "('set_hash', 'forbid_update', 'next_model_version', 'snapshot_dataset')"
            )
        ).scalars()
    )
    views = set(
        db.execute(text("SELECT viewname FROM pg_views WHERE viewname = 'run_overview'")).scalars()
    )

    assert indexes == {"run_scenario_idx", "run_queue_idx", "constraint_result_violated_idx"}
    assert functions == {"set_hash", "forbid_update", "next_model_version", "snapshot_dataset"}
    assert views == {"run_overview"}


def test_snapshot_dataset_signature_is_stable(db):
    """Task 9's seed, and any future run submitter, binds against this."""
    signature = db.execute(
        text(
            "SELECT pg_get_function_arguments(oid) || ' -> ' || pg_get_function_result(oid) "
            "FROM pg_proc WHERE proname = 'snapshot_dataset'"
        )
    ).scalar_one()
    assert signature == "p_model_version bigint -> bigint"


def test_next_model_version_takes_the_advisory_lock(db):
    """Amendment (b): the single-argument, bigint form of
    pg_advisory_xact_lock, keyed on problem_id with no lossy int cast."""
    body = db.execute(
        text("SELECT prosrc FROM pg_proc WHERE proname = 'next_model_version'")
    ).scalar_one()
    assert "pg_advisory_xact_lock(NEW.problem_id)" in body


# --------------------------------------------------------------------------
# immutability -- all four RUN-side tables
# --------------------------------------------------------------------------


def test_immutable_tables_constant_matches_the_database(db):
    """Task 4 asserts none of these gets a generic CRUD router, so the
    constant has to track the triggers rather than drift from them."""
    triggered = set(
        db.execute(
            text(
                "SELECT c.relname FROM pg_trigger g "
                "JOIN pg_class c ON c.oid = g.tgrelid "
                "JOIN pg_proc p ON p.oid = g.tgfoid "
                "WHERE p.proname = 'forbid_update' AND NOT g.tgisinternal"
            )
        ).scalars()
    )
    assert triggered == IMMUTABLE_TABLES
    assert IMMUTABLE_TABLES == {"model_version", "dataset", "solution", "constraint_result"}


def test_model_version_is_immutable(db):
    problem = make_problem(db, make_domain(db))
    mv = make_model_version(db, problem, {"sets": []})

    with pytest.raises(InternalError) as exc:
        db.execute(text("UPDATE model_version SET note = 'x' WHERE id = :i"), {"i": mv})

    assert "model_version rows are immutable" in _raised(exc)


def test_dataset_is_immutable(db):
    problem = make_problem(db, make_domain(db))
    ds = make_dataset(db, problem, {"sets": {}, "parameters": {}})

    with pytest.raises(InternalError) as exc:
        db.execute(text("UPDATE dataset SET data = '{}'::jsonb WHERE id = :i"), {"i": ds})

    assert "dataset rows are immutable" in _raised(exc)


def test_solution_is_immutable(db):
    problem = make_problem(db, make_domain(db))
    mv = make_model_version(db, problem, {"sets": []})
    scenario = make_scenario(db, problem, mv)
    ds = make_dataset(db, problem, {"sets": {}, "parameters": {}})
    run = make_run(db, scenario, ds)
    db.execute(
        text("INSERT INTO solution (run_id, assignments) VALUES (:r, CAST(:a AS jsonb))"),
        {"r": run, "a": json.dumps({"assign": [["ahmed", "mon"]]})},
    )

    with pytest.raises(InternalError) as exc:
        db.execute(
            text("UPDATE solution SET assignments = '{}'::jsonb WHERE run_id = :r"), {"r": run}
        )

    assert "solution rows are immutable" in _raised(exc)


def test_constraint_result_is_immutable(db):
    problem = make_problem(db, make_domain(db))
    mv = make_model_version(db, problem, {"sets": []})
    scenario = make_scenario(db, problem, mv)
    ds = make_dataset(db, problem, {"sets": {}, "parameters": {}})
    run = make_run(db, scenario, ds)
    make_constraint_result(db, run, "c_one")

    with pytest.raises(InternalError) as exc:
        db.execute(
            text("UPDATE constraint_result SET satisfied = false WHERE run_id = :r"), {"r": run}
        )

    assert "constraint_result rows are immutable" in _raised(exc)


# --------------------------------------------------------------------------
# versioning
# --------------------------------------------------------------------------


def test_model_version_numbering_starts_at_one_and_increments(db):
    problem = make_problem(db, make_domain(db))
    ids = [make_model_version(db, problem, {"sets": [], "n": n}) for n in range(3)]

    versions = (
        db.execute(
            text("SELECT version FROM model_version WHERE id = ANY(:i) ORDER BY id"),
            {"i": ids},
        )
        .scalars()
        .all()
    )
    assert versions == [1, 2, 3]


def test_two_problems_number_independently(db):
    domain = make_domain(db)
    first = make_problem(db, domain, "a")
    second = make_problem(db, domain, "b")

    make_model_version(db, first, {"sets": [], "n": 1})
    make_model_version(db, first, {"sets": [], "n": 2})
    b1 = make_model_version(db, second, {"sets": [], "n": 1})

    assert (
        db.execute(text("SELECT version FROM model_version WHERE id = :i"), {"i": b1}).scalar_one()
        == 1
    )
    assert (
        db.execute(
            text("SELECT max(version) FROM model_version WHERE problem_id = :p"), {"p": first}
        ).scalar_one()
        == 2
    )


def test_explicit_version_is_respected(db):
    """The trigger only fills a NULL, so an explicit number still wins --
    which is what would let a future importer preserve historical numbering."""
    problem = make_problem(db, make_domain(db))
    mv = db.execute(
        text(
            "INSERT INTO model_version (problem_id, version, ir) "
            "VALUES (:p, 7, '{}'::jsonb) RETURNING id"
        ),
        {"p": problem},
    ).scalar_one()

    assert (
        db.execute(text("SELECT version FROM model_version WHERE id = :i"), {"i": mv}).scalar_one()
        == 7
    )


# --------------------------------------------------------------------------
# hashing
# --------------------------------------------------------------------------


def test_ir_hash_ignores_the_key_order_written(db):
    problem = make_problem(db, make_domain(db))
    first = make_model_version(db, problem, {"sets": ["day"], "objective": {"a": 1, "b": 2}})
    second = make_model_version(db, problem, {"objective": {"b": 2, "a": 1}, "sets": ["day"]})

    hashes = (
        db.execute(
            text("SELECT ir_hash FROM model_version WHERE id = ANY(:i)"), {"i": [first, second]}
        )
        .scalars()
        .all()
    )
    assert len(hashes) == 2
    assert len(set(hashes)) == 1
    assert len(hashes[0]) == 64  # sha256, hex


def test_ir_hash_changes_when_the_ir_changes(db):
    problem = make_problem(db, make_domain(db))
    first = make_model_version(db, problem, {"sets": ["day"]})
    second = make_model_version(db, problem, {"sets": ["shift"]})

    hashes = (
        db.execute(
            text("SELECT ir_hash FROM model_version WHERE id = ANY(:i)"), {"i": [first, second]}
        )
        .scalars()
        .all()
    )
    assert len(set(hashes)) == 2


def test_data_hash_ignores_the_key_order_written(db):
    """UNIQUE (problem_id, data_hash) means the reordered twin cannot even be
    inserted -- the collision *is* the proof that the hashes matched."""
    problem = make_problem(db, make_domain(db))
    first = make_dataset(db, problem, {"sets": {"day": []}, "parameters": {}})
    first_hash = db.execute(
        text("SELECT data_hash FROM dataset WHERE id = :i"), {"i": first}
    ).scalar_one()

    with pytest.raises(Exception) as exc:
        make_dataset(db, problem, {"parameters": {}, "sets": {"day": []}})
    assert "dataset_problem_id_data_hash_key" in str(exc.value)

    db.rollback()
    assert len(first_hash) == 64


# --------------------------------------------------------------------------
# snapshot_dataset()
# --------------------------------------------------------------------------


@pytest.fixture
def snapshot_domain(db):
    """employee(+attrs), day, shift, and demand[day, shift].

    Deliberately small and fully enumerated, because
    `test_snapshot_shape_is_pinned` asserts the whole document literally.

    Two details are load-bearing rather than incidental, and exist so the
    pinned document discriminates on its own instead of leaning on the
    narrower tests below:

    * `aaliya` sorts *first* by key but *last* by `sort_order`, so a
      snapshot that dropped `sort_order` from its ORDER BY would reorder
      the pinned list.
    * `dormant` is inactive, so a snapshot that stopped filtering on
      `active` would add a row to the pinned list.
    """
    domain = make_domain(db, "snap")
    employee = make_entity_type(db, domain, "employee", role="agent")
    day = make_entity_type(db, domain, "day", role="time")
    shift = make_entity_type(db, domain, "shift", role="time")

    make_attribute_def(db, employee, "hours", "integer")
    make_attribute_def(db, employee, "senior", "boolean")

    entities = {
        "ahmed": make_entity(
            db, employee, "ahmed", sort_order=0, attrs={"hours": 40, "senior": True}
        ),
        "bilal": make_entity(
            db, employee, "bilal", sort_order=1, attrs={"hours": 20, "senior": False}
        ),
        "aaliya": make_entity(
            db, employee, "aaliya", sort_order=2, attrs={"hours": 30, "senior": True}
        ),
        "dormant": make_entity(
            db,
            employee,
            "dormant",
            sort_order=3,
            active=False,
            attrs={"hours": 10, "senior": False},
        ),
        "mon": make_entity(db, day, "mon", sort_order=0),
        "tue": make_entity(db, day, "tue", sort_order=1),
        "morning": make_entity(db, shift, "morning", sort_order=0),
        "night": make_entity(db, shift, "night", sort_order=1),
    }

    # default 1, not the column's 0: a snapshot that emitted a constant 0
    # (or coalesced a missing default to 0) must not match by accident.
    demand = make_parameter_def(db, domain, "demand", [day, shift], default_value=1)
    make_parameter_value(db, demand, [entities["mon"], entities["morning"]], 3)
    make_parameter_value(db, demand, [entities["mon"], entities["night"]], 5)
    make_parameter_value(db, demand, [entities["tue"], entities["morning"]], 7)

    problem = make_problem(db, domain, "snap")
    mv = make_model_version(
        db,
        problem,
        {"sets": ["employee", "day", "shift"], "parameters": {"demand": {}}},
    )
    return {
        "domain": domain,
        "problem": problem,
        "model_version": mv,
        "types": {"employee": employee, "day": day, "shift": shift},
        "entities": entities,
        "demand": demand,
    }


def _snapshot(db, model_version: int) -> int:
    return db.execute(text("SELECT snapshot_dataset(:mv)"), {"mv": model_version}).scalar_one()


def _data(db, dataset_id: int) -> dict:
    return db.execute(
        text("SELECT data FROM dataset WHERE id = :d"), {"d": dataset_id}
    ).scalar_one()


def test_snapshot_shape_is_pinned(db, snapshot_domain):
    """The whole document, literally.

    `snapshot_dataset()` has no reader in this repository (spec §8), so
    nothing else in the tree would notice if its shape drifted. Asserting
    equality against a fully enumerated expected document -- rather than
    spot-checking a few keys -- is what makes a future `psp/data.py`
    mismatch a test failure instead of a silent one. Every part of the
    contract is load-bearing here: the two top-level keys, `entity.key`
    surfacing as `"id"`, attributes merged flat into the same object,
    parameter rows keyed by the *index type's* name plus `"value"`, the
    `sort_order`-then-`key` row ordering, and the exclusion of inactive
    entities.
    """
    dataset_id = _snapshot(db, snapshot_domain["model_version"])
    data = _data(db, dataset_id)

    assert data == {
        "sets": {
            "employee": [
                {"id": "ahmed", "hours": 40, "senior": True},
                {"id": "bilal", "hours": 20, "senior": False},
                # sorts first by key, last by sort_order; `dormant` is
                # inactive and therefore absent entirely.
                {"id": "aaliya", "hours": 30, "senior": True},
            ],
            "day": [{"id": "mon"}, {"id": "tue"}],
            "shift": [{"id": "morning"}, {"id": "night"}],
        },
        "parameters": {
            "demand": [
                {"day": "mon", "shift": "morning", "value": 3},
                {"day": "mon", "shift": "night", "value": 5},
                {"day": "tue", "shift": "morning", "value": 7},
            ]
        },
        # Ruling 28 (migration 0009): what an absent cell means.
        "parameter_defaults": {"demand": 1},
        # Migration 0011: the domain's edges, frozen with everything else.
        # This fixture declares no relationship type, so the key is present
        # and empty -- which is itself the pinned fact, because a consumer
        # that has to branch on "absent or empty" will get it wrong once.
        "relationships": {},
        # Migration 0012: display names, beside the set rows rather than
        # inside them. This fixture's entities carry no label, so each set is
        # present and empty -- the same "present, not absent" contract.
        "labels": {"employee": {}, "day": {}, "shift": {}},
    }

    # Spelled out again, so a future reader sees which facts the literal
    # above is pinning, and so a partial drift names itself.
    assert set(data) == {"sets", "parameters", "parameter_defaults", "relationships", "labels"}
    assert data["sets"]["employee"][0]["id"] == "ahmed"  # entity.key -> "id"
    assert "key" not in data["sets"]["employee"][0]
    # A label never reaches the rows the compiler reads (migration 0012).
    assert "label" not in data["sets"]["employee"][0]
    assert data["parameters"]["demand"][0] == {"day": "mon", "shift": "morning", "value": 3}
    assert set(data["parameters"]["demand"][0]) == {"day", "shift", "value"}


def test_snapshot_names_sets_present_in_the_ir_only(db, snapshot_domain):
    """An entity_type the IR does not name is not snapshotted, and a set the
    IR does name but which has no rows still appears, as an empty list."""
    make_entity_type(db, snapshot_domain["domain"], "location", role="location")
    mv = make_model_version(
        db, snapshot_domain["problem"], {"sets": ["day", "location"], "parameters": {}}
    )
    data = _data(db, _snapshot(db, mv))

    assert set(data["sets"]) == {"day", "location"}
    assert data["sets"]["location"] == []
    assert data["parameters"] == {}
    assert data["parameter_defaults"] == {}


def test_snapshot_raises_for_a_set_with_no_entity_type(db, snapshot_domain):
    mv = make_model_version(
        db, snapshot_domain["problem"], {"sets": ["employee", "nonesuch"], "parameters": {}}
    )
    with pytest.raises(InternalError) as exc:
        _snapshot(db, mv)
    assert 'IR set "nonesuch" has no entity_type in this domain' in _raised(exc)


def test_snapshot_raises_for_a_parameter_with_no_parameter_def(db, snapshot_domain):
    mv = make_model_version(
        db, snapshot_domain["problem"], {"sets": [], "parameters": {"nonesuch": {}}}
    )
    with pytest.raises(InternalError) as exc:
        _snapshot(db, mv)
    assert 'IR parameter "nonesuch" has no parameter_def in this domain' in _raised(exc)


def test_snapshot_raises_for_an_unknown_model_version(db):
    with pytest.raises(InternalError) as exc:
        _snapshot(db, -1)
    assert "model_version -1 not found" in _raised(exc)


def test_snapshot_excludes_inactive_entities(db, snapshot_domain):
    db.execute(
        text("UPDATE entity SET active = false WHERE id = :i"),
        {"i": snapshot_domain["entities"]["bilal"]},
    )
    data = _data(db, _snapshot(db, snapshot_domain["model_version"]))

    assert [row["id"] for row in data["sets"]["employee"]] == ["ahmed", "aaliya"]


def test_snapshot_drops_parameter_rows_indexed_by_an_inactive_entity(db, snapshot_domain):
    """HAVING bool_and(e.active): a cell is only as live as its coordinates."""
    db.execute(
        text("UPDATE entity SET active = false WHERE id = :i"),
        {"i": snapshot_domain["entities"]["night"]},
    )
    data = _data(db, _snapshot(db, snapshot_domain["model_version"]))

    assert data["parameters"]["demand"] == [
        {"day": "mon", "shift": "morning", "value": 3},
        {"day": "tue", "shift": "morning", "value": 7},
    ]


def test_snapshot_orders_set_members_by_sort_order_then_key(db, snapshot_domain):
    day = snapshot_domain["types"]["day"]
    # Inserted out of order, and two share a sort_order so `key` breaks the tie.
    make_entity(db, day, "wed", sort_order=2)
    make_entity(db, day, "zeta", sort_order=5)
    make_entity(db, day, "alpha", sort_order=5)

    mv = make_model_version(db, snapshot_domain["problem"], {"sets": ["day"], "parameters": {}})
    data = _data(db, _snapshot(db, mv))

    assert [row["id"] for row in data["sets"]["day"]] == ["mon", "tue", "wed", "alpha", "zeta"]


def test_snapshot_dedup_returns_same_id(db, snapshot_domain):
    first = _snapshot(db, snapshot_domain["model_version"])
    second = _snapshot(db, snapshot_domain["model_version"])
    assert first == second

    count = db.execute(
        text("SELECT count(*) FROM dataset WHERE problem_id = :p"),
        {"p": snapshot_domain["problem"]},
    ).scalar_one()
    assert count == 1


def test_snapshot_dedups_across_model_versions_of_one_problem(db, snapshot_domain):
    """The dataset is keyed by the *data*, not by the IR that asked for it:
    a second model version listing the same sets shares the snapshot."""
    first = _snapshot(db, snapshot_domain["model_version"])
    twin = make_model_version(
        db,
        snapshot_domain["problem"],
        {"sets": ["employee", "day", "shift"], "parameters": {"demand": {}}, "note": "v2"},
    )
    assert _snapshot(db, twin) == first


def test_snapshot_returns_a_new_id_after_the_data_changes(db, snapshot_domain):
    first = _snapshot(db, snapshot_domain["model_version"])
    make_entity(
        db,
        snapshot_domain["types"]["employee"],
        "carla",
        sort_order=4,
        attrs={"hours": 35, "senior": False},
    )
    second = _snapshot(db, snapshot_domain["model_version"])

    assert second != first
    assert [row["id"] for row in _data(db, second)["sets"]["employee"]] == [
        "ahmed",
        "bilal",
        "aaliya",
        "carla",
    ]


def test_snapshot_ignores_another_domains_identically_named_type(db, snapshot_domain):
    """Resolution is scoped to the problem's domain, not global by name."""
    other = make_domain(db, "other")
    other_day = make_entity_type(db, other, "day")
    make_entity(db, other_day, "sat", sort_order=9)

    data = _data(db, _snapshot(db, snapshot_domain["model_version"]))
    assert [row["id"] for row in data["sets"]["day"]] == ["mon", "tue"]


def test_snapshot_ignores_another_domains_identically_named_parameter(db, snapshot_domain):
    """The parameters loop's twin of the test above: `pd.domain_id =
    v_domain` scopes the rows, not only the existence check before them.

    The other domain's `demand` is given *stored values* on purpose. A
    same-named `parameter_def` with no `parameter_value` rows would add
    nothing to the unscoped query either, and the mutant dropping the
    predicate would survive (Task 2's deferred minor; closed in Task 8).
    """
    other = make_domain(db, "other")
    other_day = make_entity_type(db, other, "day")
    other_shift = make_entity_type(db, other, "shift")
    sat = make_entity(db, other_day, "sat")
    late = make_entity(db, other_shift, "late")
    other_demand = make_parameter_def(db, other, "demand", [other_day, other_shift])
    make_parameter_value(db, other_demand, [sat, late], 99)

    data = _data(db, _snapshot(db, snapshot_domain["model_version"]))
    assert data["parameters"]["demand"] == [
        {"day": "mon", "shift": "morning", "value": 3},
        {"day": "mon", "shift": "night", "value": 5},
        {"day": "tue", "shift": "morning", "value": 7},
    ]
    # Ruling 28's defaults are scoped the same way (the other one is 0).
    assert data["parameter_defaults"] == {"demand": 1}


# --------------------------------------------------------------------------
# snapshot_dataset(): parameter defaults (Ruling 28, migration 0009)
# --------------------------------------------------------------------------


def test_snapshot_carries_the_default_of_a_parameter_with_no_stored_cells(db, snapshot_domain):
    """Every cell at its default means no `parameter_value` rows at all --
    the parameter's rows are `[]` and only `parameter_defaults` says what
    any cell is worth."""
    domain = snapshot_domain["domain"]
    types = snapshot_domain["types"]
    make_parameter_def(db, domain, "capacity", [types["day"]], default_value=6)
    mv = make_model_version(
        db,
        snapshot_domain["problem"],
        {"sets": ["day"], "parameters": {"demand": {}, "capacity": {}}},
    )
    data = _data(db, _snapshot(db, mv))

    assert data["parameters"]["capacity"] == []
    assert data["parameter_defaults"] == {"demand": 1, "capacity": 6}


def test_snapshot_defaults_name_only_parameters_the_ir_references(db, snapshot_domain):
    """Exactly the set the `parameters` loop resolves: a parameter_def the
    IR does not name contributes neither rows nor a default."""
    make_parameter_def(
        db, snapshot_domain["domain"], "capacity", [snapshot_domain["types"]["day"]], 6
    )
    data = _data(db, _snapshot(db, snapshot_domain["model_version"]))
    assert set(data["parameters"]) == {"demand"}
    assert data["parameter_defaults"] == {"demand": 1}


def test_snapshot_with_no_parameters_key_has_empty_defaults(db, snapshot_domain):
    mv = make_model_version(db, snapshot_domain["problem"], {"sets": ["day"]})
    data = _data(db, _snapshot(db, mv))
    assert data["parameters"] == {}
    assert data["parameter_defaults"] == {}


def test_snapshot_defaults_are_scoped_to_the_problems_domain(db):
    """Two domains, each with its own `demand` and a different default,
    and each problem snapshotted. Both orders matter: whichever row an
    unscoped lookup happened to pick -- first inserted or last -- one of
    the two assertions sees the other domain's value. Neither parameter
    has stored cells, so nothing but the default distinguishes them."""
    defaults = {}
    for label, default in (("first", 11), ("second", 22)):
        domain = make_domain(db, label)
        day = make_entity_type(db, domain, "day")
        make_parameter_def(db, domain, "demand", [day], default_value=default)
        problem = make_problem(db, domain, label)
        mv = make_model_version(db, problem, {"sets": [], "parameters": {"demand": {}}})
        defaults[label] = _data(db, _snapshot(db, mv))["parameter_defaults"]

    assert defaults == {"first": {"demand": 11}, "second": {"demand": 22}}


def test_snapshots_differing_only_in_a_default_hash_differently(db, snapshot_domain):
    """Ruling 28: the default is part of the data, so changing it is a
    new dataset -- not a dedup hit on the old one."""
    first = _snapshot(db, snapshot_domain["model_version"])
    db.execute(
        text("UPDATE parameter_def SET default_value = 4 WHERE id = :p"),
        {"p": snapshot_domain["demand"]},
    )
    second = _snapshot(db, snapshot_domain["model_version"])

    assert second != first
    hashes = db.execute(
        text("SELECT id, data_hash FROM dataset WHERE id IN (:a, :b)"),
        {"a": first, "b": second},
    ).all()
    assert len({h for _, h in hashes}) == 2
    before, after = _data(db, first), _data(db, second)
    assert before["parameters"] == after["parameters"]  # the cells did not change
    assert before["sets"] == after["sets"]
    assert (before["parameter_defaults"], after["parameter_defaults"]) == (
        {"demand": 1},
        {"demand": 4},
    )


# --------------------------------------------------------------------------
# run_overview
# --------------------------------------------------------------------------


def test_run_overview_counts_violations_and_sums_penalty(db, snapshot_domain):
    problem = snapshot_domain["problem"]
    mv = snapshot_domain["model_version"]
    scenario = make_scenario(db, problem, mv, "peak")
    ds = _snapshot(db, mv)
    run = make_run(db, scenario, ds, status="feasible")
    db.execute(text("UPDATE run SET objective = 42, wall_time_s = 1.5 WHERE id = :r"), {"r": run})

    make_constraint_result(db, run, "c_cover", satisfied=True, penalty_paid=0)
    make_constraint_result(
        db, run, "c_rest", hard=False, satisfied=False, total_violation=2, penalty_paid=10
    )
    make_constraint_result(
        db, run, "c_fair", hard=False, satisfied=False, total_violation=1, penalty_paid=25
    )

    row = db.execute(
        text(
            "SELECT run_id, problem, scenario, model_version, dataset_id, status, "
            "objective, wall_time_s, violated, penalty FROM run_overview WHERE run_id = :r"
        ),
        {"r": run},
    ).one()

    assert row.run_id == run
    assert row.scenario.startswith("peak-")
    assert row.model_version == 1
    assert row.dataset_id == ds
    assert row.status == "feasible"
    assert row.objective == 42
    assert row.wall_time_s == 1.5
    assert row.violated == 2
    assert row.penalty == 35


def test_run_overview_reports_zero_for_a_run_with_no_results(db, snapshot_domain):
    """coalesce, not NULL: a queued run reports 0/0, so a UI can sort on it."""
    problem = snapshot_domain["problem"]
    mv = snapshot_domain["model_version"]
    scenario = make_scenario(db, problem, mv, "empty")
    run = make_run(db, scenario, _snapshot(db, mv))

    row = db.execute(
        text("SELECT violated, penalty, status FROM run_overview WHERE run_id = :r"), {"r": run}
    ).one()
    assert (row.violated, row.penalty, row.status) == (0, 0, "queued")


def test_run_overview_names_the_problem_through_the_scenario(db, snapshot_domain):
    problem = snapshot_domain["problem"]
    name = db.execute(text("SELECT name FROM problem WHERE id = :p"), {"p": problem}).scalar_one()
    scenario = make_scenario(db, problem, snapshot_domain["model_version"], "named")
    run = make_run(db, scenario, _snapshot(db, snapshot_domain["model_version"]))

    assert (
        db.execute(
            text("SELECT problem FROM run_overview WHERE run_id = :r"), {"r": run}
        ).scalar_one()
        == name
    )
