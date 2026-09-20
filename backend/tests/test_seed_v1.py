"""The schema v1 demo seed (`app.seed.seed_workforce_demo`).

The seed is the project's **first non-router writer**: it writes straight
to the tables, below every router-level validation, so migration 0009's
eight integrity rules are the only thing judging it. That makes these
tests double as a check that a realistic dataset can be built without
tripping any of them.

Two behaviours are load-bearing rather than incidental:

* **Ruling 24** -- `parameter_value` cannot be written through the ORM
  (`db.add()` raises `TypeError: unhashable type: 'list'`, because the
  primary key contains an array), so the seed uses Core inserts. A
  regression here would surface as an error, not as bad data.
* **Ruling 25** -- `model_version.version` and `ir_hash` are filled by
  BEFORE INSERT triggers the ORM does not know about. An ORM write reads
  them back as `None`; the seed uses Core with `returning(...)`.
  `test_seeded_model_version_is_numbered_and_hashed` is what catches a
  revert to the ORM, since the row would still be *created* either way.

The snapshot test pins the same document shape Task 2 pinned
(`test_snapshot_shape_is_pinned`), now including Ruling 28's
`parameter_defaults`.

What these tests deliberately do **not** prove is that the seed works
against an empty database: by the time they run, migrations and other
modules have already written here, and a test that emptied every v1 table
to simulate it would break any module- or session-scoped fixture that had
already built a domain. That claim is made instead by running the seed
into a freshly created, freshly migrated `solver_e2e` (Task 15, Step 3).
"""

import pytest
from sqlalchemy import text

from app.core.db import SessionLocal
from app.seed import WORKFORCE_DOMAIN_NAME, seed_workforce_demo


def _delete_demo(db) -> None:
    # `domain` cascades to entity_type, entity, relationship_type,
    # relationship, parameter_def, parameter_value, problem,
    # model_version, scenario and dataset.
    db.execute(text("DELETE FROM domain WHERE name = :n"), {"n": WORKFORCE_DOMAIN_NAME})
    db.commit()


@pytest.fixture(scope="module")
def seeded():
    """Seed once for the whole module, and remove it afterwards.

    The seed commits (it is a seed), so a test-side rollback cannot undo
    it; the explicit delete is what keeps `solver_test` free of leftovers
    within a session, as Ruling 15's per-session rebuild does across them.
    """
    db = SessionLocal()
    try:
        _delete_demo(db)
        yield seed_workforce_demo(db), db
    finally:
        _delete_demo(db)
        db.close()


# --------------------------------------------------------------------------
# structure
# --------------------------------------------------------------------------


def test_seed_creates_one_domain_with_the_four_entity_types(seeded):
    result, db = seeded

    assert result["created"] is True
    name, = db.execute(
        text("SELECT name FROM domain WHERE id = :d"), {"d": result["domain_id"]}
    ).one()
    assert name == WORKFORCE_DOMAIN_NAME

    rows = db.execute(
        text("SELECT name, role FROM entity_type WHERE domain_id = :d ORDER BY name"),
        {"d": result["domain_id"]},
    ).all()
    assert [(r[0], r[1]) for r in rows] == [
        ("day", "time"),
        ("employee", "agent"),
        ("shift", "time"),
        ("unit", "org"),
    ]


def test_seed_covers_every_attr_type(seeded):
    """Spec §6: the attribute definitions exercise every `attr_type`.

    The expected set is read from the *enum in the database* rather than
    written out here, so adding a label to `attr_type` fails this test
    instead of silently leaving the new type unexercised.
    """
    result, db = seeded

    declared = {
        r[0]
        for r in db.execute(
            text(
                "SELECT e.enumlabel FROM pg_enum e"
                " JOIN pg_type t ON t.oid = e.enumtypid WHERE t.typname = 'attr_type'"
            )
        ).all()
    }
    seeded_types = {
        r[0]
        for r in db.execute(
            text(
                "SELECT DISTINCT ad.data_type FROM attribute_def ad"
                " JOIN entity_type et ON et.id = ad.entity_type_id"
                " WHERE et.domain_id = :d"
            ),
            {"d": result["domain_id"]},
        ).all()
    }
    assert seeded_types == declared


def test_seeded_attribute_definitions_are_pinned(seeded):
    """The whole set, literally.

    Coverage of `attr_type` (above) is satisfied by *any* assignment of
    types to attributes -- swapping `starts_at` from `time` to `text`
    leaves it green, because `ends_at` still carries `time`. Pinning the
    definitions is what makes each attribute's own type, its `required`
    flag and its default a fact the seed cannot quietly change.
    """
    result, db = seeded

    rows = db.execute(
        text(
            "SELECT t.name, ad.name, ad.data_type, ad.required, ad.unit,"
            "       ad.enum_values, ad.default_value"
            "  FROM attribute_def ad JOIN entity_type t ON t.id = ad.entity_type_id"
            " WHERE t.domain_id = :d ORDER BY t.name, ad.name"
        ),
        {"d": result["domain_id"]},
    ).all()

    assert [tuple(r) for r in rows] == [
        ("day", "is_weekend", "boolean", False, None, None, False),
        ("employee", "full_name", "text", True, None, None, None),
        ("employee", "grade", "enum", False, None, ["junior", "mid", "senior"], "mid"),
        ("employee", "hired_on", "date", False, None, None, None),
        ("employee", "hourly_rate", "number", False, "EUR/h", None, 20.0),
        ("employee", "hours_per_week", "integer", False, "h/week", None, 40),
        ("employee", "on_call", "boolean", False, None, None, False),
        ("shift", "ends_at", "time", True, None, None, None),
        ("shift", "starts_at", "time", True, None, None, None),
        ("unit", "cost_centre", "text", False, None, None, None),
    ]

    # Ruling 18: "no default" must be SQL NULL, not jsonb 'null'. The
    # comparison above cannot tell them apart -- both read back as None.
    nulls = db.execute(
        text(
            "SELECT count(*) FROM attribute_def ad JOIN entity_type t"
            " ON t.id = ad.entity_type_id"
            " WHERE t.domain_id = :d AND jsonb_typeof(ad.default_value) = 'null'"
        ),
        {"d": result["domain_id"]},
    ).scalar_one()
    assert nulls == 0


def test_seeded_types_all_carry_a_colour(seeded):
    """Task 14b: the types view is only worth looking at if the demo has
    colours, and 0009's CHECK only permits lowercase `#rrggbb`."""
    result, db = seeded

    for table in ("entity_type", "relationship_type"):
        colours = [
            r[0]
            for r in db.execute(
                text(f"SELECT colour FROM {table} WHERE domain_id = :d"),
                {"d": result["domain_id"]},
            ).all()
        ]
        assert colours, f"no rows in {table}"
        assert all(c is not None for c in colours), f"{table}: a NULL colour"
        assert all(len(c) == 7 and c == c.lower() and c[0] == "#" for c in colours)


def test_days_and_shifts_are_ordered_by_sort_order_not_by_key(seeded):
    """`sort_order` is the only thing that puts `friday` after `tuesday`,
    and it is what `snapshot_dataset()` orders by."""
    result, db = seeded

    days = [
        r[0]
        for r in db.execute(
            text(
                "SELECT e.key FROM entity e JOIN entity_type t ON t.id = e.entity_type_id"
                " WHERE t.domain_id = :d AND t.name = 'day' ORDER BY e.sort_order, e.key"
            ),
            {"d": result["domain_id"]},
        ).all()
    ]
    assert days == ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    assert days != sorted(days), "alphabetical order would pass without sort_order"

    shifts = [
        r[0]
        for r in db.execute(
            text(
                "SELECT e.key FROM entity e JOIN entity_type t ON t.id = e.entity_type_id"
                " WHERE t.domain_id = :d AND t.name = 'shift' ORDER BY e.sort_order, e.key"
            ),
            {"d": result["domain_id"]},
        ).all()
    ]
    assert shifts == ["morning", "evening", "night"]
    assert shifts != sorted(shifts)


def test_reports_to_is_a_hierarchy_over_a_real_tree(seeded):
    """Depth is what makes it a tree rather than a star: `entity_descendants()`
    must report more than one level below the root."""
    result, db = seeded

    rel_type_id, is_hierarchy, from_t, to_t, cardinality = db.execute(
        text(
            "SELECT id, is_hierarchy, from_type_id, to_type_id, cardinality"
            " FROM relationship_type WHERE domain_id = :d AND name = 'reports_to'"
        ),
        {"d": result["domain_id"]},
    ).one()
    assert is_hierarchy is True
    assert from_t == to_t
    assert cardinality == "one_to_many"

    root = db.execute(
        text(
            "SELECT e.id FROM entity e JOIN entity_type t ON t.id = e.entity_type_id"
            " WHERE t.domain_id = :d AND t.name = 'unit' AND e.key = 'head_office'"
        ),
        {"d": result["domain_id"]},
    ).scalar_one()

    # The whole tree, pinned by shape rather than by depth alone: asserting
    # only "some node sits at depth 2" is satisfied by a tree with one deep
    # branch and everything else flattened onto the root.
    edges = db.execute(
        text(
            """
            SELECT p.key, c.key
              FROM relationship r
              JOIN relationship_type rt ON rt.id = r.relationship_type_id
              JOIN entity p ON p.id = r.from_entity_id
              JOIN entity c ON c.id = r.to_entity_id
             WHERE rt.id = :r ORDER BY p.key, c.key
            """
        ),
        {"r": rel_type_id},
    ).all()
    assert [(a, b) for a, b in edges] == [
        ("head_office", "north_region"),
        ("head_office", "south_region"),
        ("head_office", "support"),
        ("north_region", "depot_north"),
        ("south_region", "depot_south"),
    ]

    descendants = db.execute(
        text("SELECT entity_id, depth FROM entity_descendants(:e, :r)"),
        {"e": root, "r": rel_type_id},
    ).all()
    assert sorted({d for _, d in descendants}) == [0, 1, 2]
    assert len(descendants) == 6, "every unit hangs off the root"


def test_every_employee_is_connected_by_works_in(seeded):
    result, db = seeded

    employees, connected = db.execute(
        text(
            """
            SELECT
              (SELECT count(*) FROM entity e JOIN entity_type t ON t.id = e.entity_type_id
                WHERE t.domain_id = :d AND t.name = 'employee'),
              (SELECT count(DISTINCT r.from_entity_id) FROM relationship r
                 JOIN relationship_type rt ON rt.id = r.relationship_type_id
                WHERE rt.domain_id = :d AND rt.name = 'works_in')
            """
        ),
        {"d": result["domain_id"]},
    ).one()
    assert employees > 0
    assert connected == employees


def test_demand_is_a_two_index_parameter_with_stored_cells(seeded):
    """Ruling 24: written with Core inserts, because the ORM cannot.

    Every stored cell differs from the default, matching the sparse
    storage the API and the grid enforce -- a stored cell equal to the
    default would be invisible in the UI and redundant in a snapshot.
    """
    result, db = seeded

    index_type_ids, default_value = db.execute(
        text(
            "SELECT index_type_ids, default_value FROM parameter_def"
            " WHERE domain_id = :d AND name = 'demand'"
        ),
        {"d": result["domain_id"]},
    ).one()
    index_names = [
        r[0]
        for r in db.execute(
            text(
                "SELECT t.name FROM unnest(CAST(:ids AS bigint[])) WITH ORDINALITY AS u(id, ord)"
                " JOIN entity_type t ON t.id = u.id ORDER BY u.ord"
            ),
            {"ids": index_type_ids},
        ).all()
    ]
    assert index_names == ["day", "shift"]

    values = [
        r[0]
        for r in db.execute(
            text(
                "SELECT value FROM parameter_value pv JOIN parameter_def pd"
                " ON pd.id = pv.parameter_def_id WHERE pd.domain_id = :d"
            ),
            {"d": result["domain_id"]},
        ).all()
    ]
    assert len(values) >= 6
    assert all(v != default_value for v in values), "a cell equal to the default is not sparse"


def test_seeded_model_version_is_numbered_and_hashed(seeded):
    """Ruling 25, asserted where it can actually fail.

    The database fills `version` and `ir_hash` from BEFORE INSERT triggers
    whichever way the row was written, so reading the *table* back proves
    nothing about the insert path -- an ORM insert passes that check.
    What an ORM insert cannot do is hand those values back to Python: it
    sends explicit NULLs and reads both as `None`. So the seed reports
    them, and this asserts the reported values, which is the only
    formulation a revert to `db.add()` fails.
    """
    result, db = seeded

    assert result["model_version_number"] == 1, "Ruling 25: version not read back"
    assert isinstance(result["ir_hash"], str) and len(result["ir_hash"]) == 64

    version, ir_hash, ir = db.execute(
        text("SELECT version, ir_hash, ir FROM model_version WHERE id = :v"),
        {"v": result["model_version_id"]},
    ).one()
    assert (version, ir_hash) == (result["model_version_number"], result["ir_hash"])
    assert set(ir["sets"]) >= {"employee", "unit", "day", "shift"}
    assert "demand" in ir["parameters"]


def test_seeded_scenario_belongs_to_the_seeded_version(seeded):
    """Rule 7 (0009) makes a mismatch impossible, but the seed still has
    to pick the right version for the scenario to mean anything."""
    result, db = seeded

    problem_id, model_version_id = db.execute(
        text("SELECT problem_id, model_version_id FROM scenario WHERE id = :s"),
        {"s": result["scenario_id"]},
    ).one()
    assert problem_id == result["problem_id"]
    assert model_version_id == result["model_version_id"]


# --------------------------------------------------------------------------
# snapshot_dataset() -- the point of the seed (spec §6)
# --------------------------------------------------------------------------


def test_snapshot_of_the_seeded_version_is_non_empty_and_matches_the_pinned_shape(seeded):
    """`sets`, `parameters` **and** `parameter_defaults` (Ruling 28).

    `snapshot_dataset()` is VOLATILE and inserts, so its id and the row it
    wrote have to be read in two statements (Task 2's deferred minor 5).
    """
    result, db = seeded

    dataset_id = db.execute(
        text("SELECT snapshot_dataset(:v)"), {"v": result["model_version_id"]}
    ).scalar_one()
    data = db.execute(
        text("SELECT data FROM dataset WHERE id = :i"), {"i": dataset_id}
    ).scalar_one()
    db.rollback()

    assert set(data) == {"sets", "parameters", "parameter_defaults", "relationships"}
    assert data["sets"], "sets is empty"
    assert data["parameters"], "parameters is empty"
    assert data["parameter_defaults"], "parameter_defaults is empty"

    assert set(data["sets"]) == {"employee", "unit", "day", "shift"}
    # entity.key surfaces as "id"; attributes are merged flat beside it.
    assert [row["id"] for row in data["sets"]["day"]] == [
        "mon",
        "tue",
        "wed",
        "thu",
        "fri",
        "sat",
        "sun",
    ]
    assert all("key" not in row for row in data["sets"]["employee"])
    first_employee = data["sets"]["employee"][0]
    assert "id" in first_employee
    assert "full_name" in first_employee

    # A parameter row is keyed by its *index types'* names, plus "value".
    row = data["parameters"]["demand"][0]
    assert set(row) == {"day", "shift", "value"}
    assert isinstance(row["value"], int)

    assert data["parameter_defaults"] == {"demand": 1}


def test_snapshot_is_reused_when_nothing_changed(seeded):
    """UNIQUE (problem_id, data_hash): a second snapshot of unchanged data
    returns the same dataset rather than a duplicate."""
    result, db = seeded

    first = db.execute(
        text("SELECT snapshot_dataset(:v)"), {"v": result["model_version_id"]}
    ).scalar_one()
    second = db.execute(
        text("SELECT snapshot_dataset(:v)"), {"v": result["model_version_id"]}
    ).scalar_one()
    db.rollback()

    assert first == second


# --------------------------------------------------------------------------
# running it twice
# --------------------------------------------------------------------------


def test_seeding_twice_is_idempotent(seeded):
    """Second run writes nothing and reports `created=False`, returning
    the ids that already exist.

    Measured as row counts across every table the seed touches, not just
    the domain: a partial re-seed (duplicate entities, a second
    model_version, extra parameter cells) would be invisible to an
    id-only check.
    """
    result, db = seeded

    def counts() -> dict[str, int]:
        return {
            table: db.execute(
                text(sql), {"d": result["domain_id"]}
            ).scalar_one()
            for table, sql in {
                "entity_type": "SELECT count(*) FROM entity_type WHERE domain_id = :d",
                "attribute_def": (
                    "SELECT count(*) FROM attribute_def ad"
                    " JOIN entity_type t ON t.id = ad.entity_type_id WHERE t.domain_id = :d"
                ),
                "entity": (
                    "SELECT count(*) FROM entity e"
                    " JOIN entity_type t ON t.id = e.entity_type_id WHERE t.domain_id = :d"
                ),
                "relationship_type": "SELECT count(*) FROM relationship_type WHERE domain_id = :d",
                "relationship": (
                    "SELECT count(*) FROM relationship r JOIN relationship_type rt"
                    " ON rt.id = r.relationship_type_id WHERE rt.domain_id = :d"
                ),
                "parameter_def": "SELECT count(*) FROM parameter_def WHERE domain_id = :d",
                "parameter_value": (
                    "SELECT count(*) FROM parameter_value pv JOIN parameter_def pd"
                    " ON pd.id = pv.parameter_def_id WHERE pd.domain_id = :d"
                ),
                "problem": "SELECT count(*) FROM problem WHERE domain_id = :d",
                "model_version": (
                    "SELECT count(*) FROM model_version mv JOIN problem p"
                    " ON p.id = mv.problem_id WHERE p.domain_id = :d"
                ),
                "scenario": (
                    "SELECT count(*) FROM scenario s JOIN problem p"
                    " ON p.id = s.problem_id WHERE p.domain_id = :d"
                ),
            }.items()
        }

    before = counts()
    again = seed_workforce_demo(db)
    after = counts()

    assert again["created"] is False
    assert again["domain_id"] == result["domain_id"]
    assert again["model_version_id"] == result["model_version_id"]
    assert after == before
