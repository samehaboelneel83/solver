"""Migration 0016: the frozen dataset carries the edges the IR declares.

Step 2 of `docs/plans/2026-09-20-traversal-decision.md`, data half. 0011
froze **every** relationship type of the domain because no term could name
one; now a `via` binding does, so the model declares what it walks and the
snapshot follows the declaration.

What is worth pinning here, and how each could be got wrong:

- an undeclared type is absent entirely, not an empty list -- emitting `[]`
  for it would make the dataset grow with the domain again, which is the
  coupling this migration exists to cut;
- a model that declares nothing carries `{}`, because `relationships` is
  optional and every model written before traversal omits it;
- the dataset stops depending on the domain's shape: adding an unrelated
  relationship type no longer changes the hash of a snapshot of a model that
  does not name it. That is the property, and it is the one a test can state
  directly;
- a declared type the domain does not have is a `RAISE EXCEPTION`, the same
  backstop `sets` has for a domain that loses a type after a version was
  frozen. At submit time the router refuses first, as a 422.
"""

import re
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.test_snapshot_relationships import (
    _ir,
    _make_relationship,
    _make_relationship_type,
)
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


def _world(db):
    """One hierarchy and one cross-type edge, both with a row, so "absent"
    can never be confused with "had nothing to say"."""
    domain = make_domain(db, "declared")
    unit = make_entity_type(db, domain, "unit", "org")
    employee = make_entity_type(db, domain, "employee", "agent")

    hq = make_entity(db, unit, "hq")
    depot = make_entity(db, unit, "depot")
    ahmed = make_entity(db, employee, "ahmed")

    reports_to = _make_relationship_type(
        db, domain, "reports_to", unit, unit, "one_to_many", is_hierarchy=True
    )
    works_in = _make_relationship_type(db, domain, "works_in", employee, unit, "many_to_one")
    _make_relationship(db, reports_to, hq, depot)
    _make_relationship(db, works_in, ahmed, depot)

    return {
        "domain": domain,
        "unit": unit,
        "employee": employee,
        "problem": make_problem(db, domain),
    }


def test_only_the_declared_type_is_frozen(db):
    w = _world(db)
    version = make_model_version(db, w["problem"], _ir("reports_to"))

    rels = _data(db, _snapshot(db, version))["relationships"]

    assert set(rels) == {"reports_to"}
    assert rels["reports_to"] == [{"from": "hq", "to": "depot"}]


def test_an_undeclared_type_is_absent_rather_than_empty(db):
    """`[]` would say "this type exists and has no edges", which is a
    different claim and would put every type of the domain back in the
    document under another name."""
    w = _world(db)
    version = make_model_version(db, w["problem"], _ir("reports_to"))

    rels = _data(db, _snapshot(db, version))["relationships"]

    assert "works_in" not in rels


def test_a_model_that_declares_nothing_carries_no_edges(db):
    """`relationships` is optional, so this is every model written before
    traversal existed -- including the seed's own earlier versions."""
    w = _world(db)
    without_the_key = {
        "sets": [],
        "parameters": {},
        "variables": {},
        "constraints": [],
        "objective": {},
    }
    version = make_model_version(db, w["problem"], without_the_key)

    assert _data(db, _snapshot(db, version))["relationships"] == {}


def test_the_dataset_no_longer_depends_on_the_domains_shape(db):
    """The property the migration is for. Before 0016, adding a relationship
    type to a domain changed the frozen document of every model in it, so a
    hash moved for a reason no model had anything to do with."""
    w = _world(db)
    version = make_model_version(db, w["problem"], _ir("reports_to"))
    before = _snapshot(db, version)

    other = _make_relationship_type(
        db, w["domain"], "mentors", w["employee"], w["employee"]
    )
    _make_relationship(
        db, other, make_entity(db, w["employee"], "sara"), make_entity(db, w["employee"], "amal")
    )

    assert _snapshot(db, version) == before


def test_declaring_a_type_the_domain_does_not_have_is_refused(db):
    """The backstop, not the front door: `relationship_not_in_domain` makes
    this a 422 at submit time, and this fires only for a domain that lost the
    type after a version was frozen. `sets` has exactly this pair."""
    w = _world(db)
    version = make_model_version(db, w["problem"], _ir("reports_to"))
    db.execute(
        text("DELETE FROM relationship_type WHERE domain_id = :d AND name = 'reports_to'"),
        {"d": w["domain"]},
    )

    with pytest.raises(DBAPIError, match='IR relationship "reports_to"'):
        _snapshot(db, version)
    db.rollback()


def test_0016_carries_0015s_statement_byte_for_byte(db):
    """`downgrade()` restores 0015's function from a copy. If the copy drifts,
    the downgrade silently installs something 0015 never installed."""
    versions = Path(__file__).resolve().parents[1] / "alembic" / "versions"
    pattern = r'_SNAPSHOT_DATASET_0015 = """\n(.*?)"""\n'
    in_0015 = re.search(
        pattern, (versions / "0015_decimal_parameters.py").read_text(encoding="utf-8"), re.S
    )
    in_0016 = re.search(
        pattern,
        (versions / "0016_snapshot_declared_relationships.py").read_text(encoding="utf-8"),
        re.S,
    )

    assert in_0015 and in_0016
    assert in_0016.group(1) == in_0015.group(1)
