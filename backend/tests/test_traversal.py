"""Traversal: the constraint a hierarchy exists for.

Step 2 of `docs/plans/2026-09-20-traversal-decision.md`. That note opens with
three things a planner would say and a table marking each **no**; this file
turns the first of them into a model that solves.

The fixture is that note's own example, reduced to what the question needs:

    head_office
      +-- north_region
            +-- north_depot

with an employee in each of the two lower units. "North Region needs two
people, counting its depots" is then true only if the walk reaches through
`reports_to` and out along `works_in` -- and false, by one, if either walk
stops short.

What is being pinned:

- a walk composes with another walk, which is the case precomputed closures
  (option 2 of the decision note) could not have answered;
- `one`, `any` and `any_or_self` differ, and differ in the way their names
  claim -- a test that only used the hierarchy's leaf would pass for all
  three;
- the edges come from the **frozen dataset**, not the live rows, so changing
  the org chart after a snapshot does not change what that snapshot solves.
  This is the reproducibility guarantee the traversal note said any answer
  had to preserve;
- a cycle terminates. `is_hierarchy` forbids one and a dataset is never
  re-validated, so the compiler cannot assume it.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.solve import compile_model, cpsat
from app.solve.compile import Unsupported
from app.seed import seed_workforce_demo
from app.solve.service import patched
from tests.test_snapshot_relationships import _make_relationship, _make_relationship_type
from tests.test_v1_problem_run import (  # noqa: F401
    _data,
    _snapshot,
    db,
    make_domain,
    make_entity,
    make_entity_type,
    make_model_version,
    make_problem,
)


def _org(db, *, domain_name="trav-solve"):
    """head_office -> north_region -> north_depot, one employee in each of
    the lower two. Three levels, because a two-level tree cannot tell
    `one` from `any`."""
    domain = make_domain(db, domain_name)
    unit = make_entity_type(db, domain, "unit", "org")
    employee = make_entity_type(db, domain, "employee", "agent")

    units = {k: make_entity(db, unit, k) for k in ("head_office", "north_region", "north_depot")}
    people = {k: make_entity(db, employee, k) for k in ("ahmed", "sara")}

    reports_to = _make_relationship_type(
        db, domain, "reports_to", unit, unit, "one_to_many", is_hierarchy=True
    )
    works_in = _make_relationship_type(db, domain, "works_in", employee, unit, "many_to_one")

    _make_relationship(db, reports_to, units["head_office"], units["north_region"])
    _make_relationship(db, reports_to, units["north_region"], units["north_depot"])
    _make_relationship(db, works_in, people["ahmed"], units["north_region"])
    _make_relationship(db, works_in, people["sara"], units["north_depot"])

    return {
        "domain": domain,
        "unit": unit,
        "employee": employee,
        "units": units,
        "people": people,
        "types": {"reports_to": reports_to, "works_in": works_in},
        "problem": make_problem(db, domain),
    }


def _model(depth: str) -> dict:
    """"Every unit is staffed by at least two people, counting the units
    beneath it." Two walks: down the hierarchy, then out to the people."""
    return {
        "version": 1,
        "sets": ["employee", "unit"],
        "relationships": ["reports_to", "works_in"],
        "parameters": {},
        "variables": {"assign": {"index": ["employee"], "domain": "binary"}},
        "constraints": [
            {
                "id": "c_region_cover",
                "forall": [{"index": "u", "set": "unit"}],
                "left": {
                    "sum": {"var": "assign", "index": ["e"]},
                    "over": [
                        {
                            "index": "sub",
                            "set": "unit",
                            "via": {"rel": "reports_to", "from": "u", "depth": depth},
                        },
                        {"index": "e", "set": "employee", "via": {"rel": "works_in", "to": "sub"}},
                    ],
                },
                "relation": ">=",
                "right": {"const": 2},
                "severity": "hard",
            }
        ],
    }


def _compiled(db, org, ir):
    version = make_model_version(db, org["problem"], ir)
    return compile_model(ir, _data(db, _snapshot(db, version)))


def _reached(compiled, unit: str) -> set[str]:
    """Which people the constraint instance for `unit` actually counts."""
    for constraint in compiled.constraints:
        if constraint.index.get("u") == unit:
            return {key[1][0] for key in constraint.left.coeffs}
    return set()


# -- the walk itself --------------------------------------------------------


def test_two_walks_compose_to_reach_people_through_the_hierarchy(db):
    """The question the decision note said option 2 could not answer: it
    crosses a hierarchy *and* a non-hierarchical edge."""
    org = _org(db)

    compiled = _compiled(db, org, _model("any_or_self"))

    # north_region and everything beneath it: ahmed there, sara in the depot.
    assert _reached(compiled, "north_region") == {"ahmed", "sara"}
    # head_office holds nobody itself but sits above both.
    assert _reached(compiled, "head_office") == {"ahmed", "sara"}
    # the leaf reaches only its own.
    assert _reached(compiled, "north_depot") == {"sara"}


@pytest.mark.parametrize(
    "depth,expected",
    [
        # one hop from head_office is north_region, whose employee is ahmed.
        ("one", {"ahmed"}),
        # every unit strictly beneath: north_region and north_depot.
        ("any", {"ahmed", "sara"}),
        # the same, plus head_office itself -- which holds nobody, so the
        # set does not change and the *unit* set is what differs. Pinned
        # below on north_depot, where it does change the people.
        ("any_or_self", {"ahmed", "sara"}),
    ],
)
def test_depth_means_what_its_name_says(db, depth, expected):
    org = _org(db, domain_name=f"trav-depth-{depth}")

    compiled = _compiled(db, org, _model(depth))

    assert _reached(compiled, "head_office") == expected


def test_any_or_self_includes_the_anchor_and_any_does_not(db):
    """The leaf is where the two differ in people rather than in units:
    `north_depot` has no units beneath it, so `any` counts nobody at all."""
    org = _org(db)

    strict = _compiled(db, org, _model("any"))
    reflexive = _compiled(db, org, _model("any_or_self"))

    assert _reached(strict, "north_depot") == set()
    assert _reached(reflexive, "north_depot") == {"sara"}


def test_a_traversal_constraint_solves(db):
    """End to end: the rule holds for the two upper units and cannot hold
    for the leaf, which has one person -- so the model is infeasible, and
    that is the correct answer rather than a compile error."""
    org = _org(db)
    compiled = _compiled(db, org, _model("any_or_self"))

    result = cpsat.solve(compiled, time_limit=10.0)

    assert result.status == "infeasible"


def test_the_rule_holds_once_the_leaf_is_excused(db):
    """The same model with the bound the data can meet. Proves the
    infeasibility above came from the arithmetic and not from an empty
    expansion, which would have been satisfiable rather than infeasible."""
    org = _org(db)
    ir = _model("any_or_self")
    ir["constraints"][0]["right"] = {"const": 1}

    result = cpsat.solve(_compiled(db, org, ir), time_limit=10.0)

    assert result.status == "optimal"


# -- reproducibility --------------------------------------------------------


def test_the_walk_reads_the_frozen_edges_and_not_the_live_ones(db):
    """The guarantee the whole traversal decision turned on. Move an
    employee after the snapshot; the compiled model must not notice."""
    org = _org(db)
    ir = _model("any_or_self")
    version = make_model_version(db, org["problem"], ir)
    frozen = _data(db, _snapshot(db, version))

    db.execute(
        text("DELETE FROM relationship WHERE relationship_type_id = :t"),
        {"t": org["types"]["works_in"]},
    )
    db.commit()

    assert _reached(compile_model(ir, frozen), "north_region") == {"ahmed", "sara"}


def test_a_cycle_terminates_instead_of_hanging_the_worker(db):
    """`is_hierarchy` forbids a cycle and a frozen dataset is never
    re-validated, so the closure cannot assume acyclicity. Written against
    the compiler directly, because the DDL will not let one be stored."""
    org = _org(db)
    ir = _model("any")
    data = {
        "sets": {
            "unit": [{"id": "a"}, {"id": "b"}],
            "employee": [{"id": "ahmed"}],
        },
        "parameters": {},
        "parameter_defaults": {},
        "relationships": {
            "reports_to": [{"from": "a", "to": "b"}, {"from": "b", "to": "a"}],
            "works_in": [{"from": "ahmed", "to": "b"}],
        },
    }

    compiled = compile_model(ir, data)

    assert _reached(compiled, "a") == {"ahmed"}


def test_a_dataset_frozen_before_traversal_is_refused_not_silently_empty(db):
    """An old snapshot carries no edges for a type the model declares.
    Finding nothing reachable would report an answer to a constraint that
    never ran, which is the failure the contract exists to prevent."""
    org = _org(db)
    ir = _model("any")
    stale = {
        "sets": {"unit": [{"id": "a"}], "employee": [{"id": "ahmed"}]},
        "parameters": {},
        "parameter_defaults": {},
        "relationships": {},
    }

    with pytest.raises(Unsupported, match="snapshotted before traversal"):
        compile_model(ir, stale)


# -- the acceptance: the seeded demo says it, and solves ---------------------


@pytest.fixture
def demo(db):
    created = seed_workforce_demo(db)
    db.commit()
    yield created
    db.execute(text("DELETE FROM domain WHERE id = :d"), {"d": created["domain_id"]})
    db.commit()


def _seeded(db, demo):
    ir = db.execute(
        text("SELECT ir FROM model_version WHERE id = :v"), {"v": demo["model_version_id"]}
    ).scalar_one()
    return ir, compile_model(ir, _data(db, _snapshot(db, demo["model_version_id"])))


def test_the_demo_counts_north_regions_depot_towards_its_late_shift(db, demo):
    """The acceptance test for the whole traversal change.

    "North Region needs three people on lates, counting its depots" is the
    first of the three things `docs/plans/2026-09-20-traversal-decision.md`
    lists as inexpressible. It is now a constraint in the shipped demo.

    The assertion that matters is *who* it counts: **nobody works in North
    Region itself**. Ahmed and Bilal are both in North Depot, one level
    down, so a constraint that did not walk would count zero -- and the
    sharpest evidence the walk is real is that it reaches them while
    leaving South Depot's people and Head Office's out.
    """
    _, compiled = _seeded(db, demo)

    instances = [c for c in compiled.constraints if c.id == "c_north_region_lates"]

    # One per day, and the unit and shift filters each pick exactly one.
    assert len(instances) == 7
    monday = next(c for c in instances if c.index["d"] == "mon")
    assert monday.index["r"] == "north_region"
    assert monday.index["late"] == "evening"

    counted = {key[1] for key in monday.left.coeffs if key[0] == "assign"}
    # Reached through north_region -> depot_north -> the people in it.
    assert counted == {("ahmed", "mon", "evening"), ("bilal", "mon", "evening")}


def test_the_seeded_demo_solves_with_the_traversal_in_it(db, demo):
    """Through the scenario, which is the only way this demo has an answer:
    it is over-subscribed on purpose and `relaxed_cover` softens coverage.

    The traversal constraint is soft too, and deliberately short by one, so
    it pays a penalty rather than making the model infeasible -- a hard
    version would have proven the constraint compiles and nothing else.
    """
    scenario = db.execute(
        text("SELECT patch FROM scenario WHERE id = :s"), {"s": demo["scenario_id"]}
    ).scalar_one()
    ir, _ = _seeded(db, demo)
    relaxed = patched(ir, scenario or {})

    result = cpsat.solve(
        compile_model(relaxed, _data(db, _snapshot(db, demo["model_version_id"]))),
        time_limit=30.0,
    )

    assert result.status in ("optimal", "feasible")
    # The rule is in the answer rather than merely in the document: two
    # people are available where three are asked for, so it is broken by
    # exactly one on each of the seven days.
    assert result.assignments
