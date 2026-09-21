"""Migration 0011: `snapshot_dataset()` freezes the domain's relationships.

Step 1 of the traversal work (`docs/plans/2026-09-20-traversal-decision.md`):
the edges are emitted and **nothing can reference them yet**. So these tests
pin the *shape* of what is frozen, which is what step 2's term algebra and the
model editor will both be designed against.

The rules worth pinning, and why each one can be got wrong:

- keys are entity `key`s, the vocabulary `sets` already uses -- ids would be
  unresolvable against a document that names entities by key;
- `valid_from`/`valid_to` travel when set and `attrs` when non-empty, because
  an edge frozen without its validity dates commits the platform to ignoring
  them;
- both endpoints must be `active`, because `sets` excludes inactive entities
  and an edge naming one would reference a key present in no set;
- every relationship type of the *domain* appears, and no other domain's.
"""

import json
import re
from pathlib import Path

from sqlalchemy import text

from tests.test_v1_problem_run import (  # noqa: F401  (db fixture)
    _data,
    _snapshot,
    db,
    make_domain,
    make_entity,
    make_entity_type,
    make_model_version,
    make_problem,
)

def _ir(*relationships: str) -> dict:
    """A model that declares the edge types it walks.

    Since 0016 the declaration is what `snapshot_dataset()` freezes against,
    exactly as `sets` is -- so a test about the *shape* of a frozen edge has
    to name the type, or nothing is frozen to have a shape. 0011's own tests
    passed no declaration because there was none to pass; the narrowing is
    covered on its own in `test_snapshot_declared_relationships.py`.
    """
    return {
        "sets": [],
        "relationships": list(relationships),
        "parameters": {},
        "variables": {},
        "constraints": [],
        "objective": {},
    }


def _make_relationship_type(
    db,
    domain_id: int,
    name: str,
    from_type: int,
    to_type: int,
    cardinality: str = "many_to_many",
    is_hierarchy: bool = False,
) -> int:
    return db.execute(
        text(
            "INSERT INTO relationship_type"
            " (domain_id, name, from_type_id, to_type_id, cardinality, is_hierarchy)"
            " VALUES (:d, :n, :f, :t, :c, :h) RETURNING id"
        ),
        {"d": domain_id, "n": name, "f": from_type, "t": to_type, "c": cardinality, "h": is_hierarchy},
    ).scalar_one()


def _make_relationship(db, rel_type: int, frm: int, to: int, **extra) -> int:
    cols = {"relationship_type_id": rel_type, "from_entity_id": frm, "to_entity_id": to}
    cols.update(extra)
    names = ", ".join(cols)
    binds = ", ".join(f":{k}" for k in cols)
    params = {k: (json.dumps(v) if k == "attrs" else v) for k, v in cols.items()}
    return db.execute(
        text(f"INSERT INTO relationship ({names}) VALUES ({binds}) RETURNING id"), params
    ).scalar_one()


def _fixture(db, *declares: str):
    """Two unit entities and two employees, a self-referencing hierarchy and a
    cross-type relationship -- the two shapes that read differently."""
    domain = make_domain(db, "trav")
    unit = make_entity_type(db, domain, "unit", "org")
    employee = make_entity_type(db, domain, "employee", "agent")

    hq = make_entity(db, unit, "hq")
    depot = make_entity(db, unit, "depot")
    ahmed = make_entity(db, employee, "ahmed")
    sara = make_entity(db, employee, "sara")

    reports_to = _make_relationship_type(
        db, domain, "reports_to", unit, unit, "one_to_many", is_hierarchy=True
    )
    works_in = _make_relationship_type(db, domain, "works_in", employee, unit, "many_to_one")

    _make_relationship(db, reports_to, hq, depot)
    _make_relationship(db, works_in, ahmed, depot)

    problem = make_problem(db, domain)
    version = make_model_version(db, problem, _ir(*(declares or ("reports_to", "works_in"))))
    return {
        "problem": problem,
        "domain": domain,
        "unit": unit,
        "employee": employee,
        "entities": {"hq": hq, "depot": depot, "ahmed": ahmed, "sara": sara},
        "types": {"reports_to": reports_to, "works_in": works_in},
        "version": version,
    }


def _relationships(db, version: int) -> dict:
    return _data(db, _snapshot(db, version))["relationships"]


def test_edges_are_frozen_by_type_name_and_named_by_entity_key(db):
    f = _fixture(db)

    rels = _relationships(db, f["version"])

    assert set(rels) == {"reports_to", "works_in"}
    assert rels["reports_to"] == [{"from": "hq", "to": "depot"}]
    assert rels["works_in"] == [{"from": "ahmed", "to": "depot"}]


def test_a_declared_type_with_no_edges_is_an_empty_list_not_a_missing_key(db):
    """A consumer that has to branch on "absent or empty" will get it wrong
    once; `sets` and `parameters` already emit `[]` for the same reason."""
    f = _fixture(db)
    _make_relationship_type(db, f["domain"], "mentors", f["employee"], f["employee"])
    version = make_model_version(db, f["problem"], _ir("mentors"))

    rels = _relationships(db, version)

    assert rels["mentors"] == []


def test_validity_dates_and_attrs_travel_only_when_they_are_set(db):
    """The whole point of freezing an edge with its dates: a reporting line
    that starts in March is a different fact from one that always held."""
    f = _fixture(db)
    _make_relationship(
        db,
        f["types"]["works_in"],
        f["entities"]["sara"],
        f["entities"]["hq"],
        valid_from="2026-03-01",
        valid_to="2026-09-30",
        attrs={"fte": 0.5},
    )

    rels = _relationships(db, f["version"])
    dated = [r for r in rels["works_in"] if r["from"] == "sara"][0]
    plain = [r for r in rels["works_in"] if r["from"] == "ahmed"][0]

    assert dated == {
        "from": "sara",
        "to": "hq",
        "valid_from": "2026-03-01",
        "valid_to": "2026-09-30",
        "attrs": {"fte": 0.5},
    }
    # The undated edge carries no empty scaffolding -- absent, not null.
    assert plain == {"from": "ahmed", "to": "depot"}


def test_an_edge_is_dropped_when_either_endpoint_is_inactive(db):
    """`sets` excludes inactive entities, so an edge naming one would point at
    a key that appears in no set. Asserted from both ends, because a query
    that filters only the `from` side passes a one-sided test."""
    f = _fixture(db)
    sara, hq, depot = f["entities"]["sara"], f["entities"]["hq"], f["entities"]["depot"]
    _make_relationship(db, f["types"]["works_in"], sara, hq)

    db.execute(text("UPDATE entity SET active = false WHERE id = :e"), {"e": sara})
    assert [r["from"] for r in _relationships(db, f["version"])["works_in"]] == ["ahmed"]

    db.execute(text("UPDATE entity SET active = true WHERE id = :e"), {"e": sara})
    db.execute(text("UPDATE entity SET active = false WHERE id = :e"), {"e": depot})
    remaining = _relationships(db, f["version"])
    assert remaining["works_in"] == [{"from": "sara", "to": "hq"}]
    assert remaining["reports_to"] == []


def test_another_domains_relationship_types_do_not_leak(db):
    """The parameters loop had this bug class checked in Task 8; the edges
    loop is scoped the same way and needs the same guard. A same-named type
    in a second domain is the case that catches an unscoped query."""
    f = _fixture(db)
    other = make_domain(db, "other")
    other_unit = make_entity_type(db, other, "unit", "org")
    a = make_entity(db, other_unit, "hq")
    b = make_entity(db, other_unit, "depot")
    other_type = _make_relationship_type(
        db, other, "reports_to", other_unit, other_unit, "one_to_many", is_hierarchy=True
    )
    _make_relationship(db, other_type, a, b)

    rels = _relationships(db, f["version"])

    assert rels["reports_to"] == [{"from": "hq", "to": "depot"}]
    assert len(rels["reports_to"]) == 1


def test_the_frozen_document_is_stable_so_identical_snapshots_are_shared(db):
    """`dataset` dedupes on `data_hash`, so the edge list must have a
    deterministic order -- an unordered `jsonb_agg` would mint a new dataset
    row per call and break that."""
    f = _fixture(db)
    _make_relationship(db, f["types"]["works_in"], f["entities"]["sara"], f["entities"]["hq"])

    first = _snapshot(db, f["version"])
    second = _snapshot(db, f["version"])

    assert first == second


def test_0011_carries_0009s_statement_byte_for_byte(db):
    """`downgrade()` restores 0009's function from a copy. If the copy drifts,
    the downgrade silently installs something 0009 never installed -- so the
    copy is re-extracted from 0009's own file and compared."""
    versions = Path(__file__).resolve().parents[1] / "alembic" / "versions"
    pattern = r'_SNAPSHOT_DATASET_0009 = """\n(.*?)"""\n'
    in_0009 = re.search(pattern, (versions / "0009_snapshot_defaults_integrity_colour.py").read_text(encoding="utf-8"), re.S)
    in_0011 = re.search(pattern, (versions / "0011_snapshot_relationships.py").read_text(encoding="utf-8"), re.S)

    assert in_0009 and in_0011
    assert in_0011.group(1) == in_0009.group(1)
