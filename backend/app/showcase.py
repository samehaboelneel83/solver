"""Showcase templates that show the solving the demo rota cannot.

The seeded rota is an integer program: every decision is yes or no, so a
person exploring the product never meets a fractional answer, a linear
program, or a quadratic objective -- the platform's widest capabilities were
its least visible. These are small, real, and checkable by hand, and each
is a template, so applying one builds its own domain and model beside
whatever is already there.

**feed_blend** -- a linear program. Blend 100 kg of feed from three
ingredients at least cost, with at least 20 kg of protein and at most 5 kg of
fibre. The answer is fractional, the model is classified LP, and it goes to
the simplex method.

**load_balance** -- a convex quadratic program. Share 120 hours of work
across four people with different capacities, as evenly as possible:
minimise the sum of squared loads, which penalises one person carrying much
more than another. Even would be 30 each; Chloe can take only 15 and Dev only
30, so Ana and Ben take the remaining 75 between them -- 37.5 each, a sum of
squares of 3937.5. The model is classified QP, proven convex, and its optimum
is reported as the global one.

**workshop** -- scheduling (IR version 2). Three jobs are cut, then welded;
each machine does one job at a time, and a job reaches the welder only once
it is cut. Each operation is an interval, `no_overlap` holds each machine,
and the route (cut feeds weld) is a relationship the rule walks. Shortest
makespan: Johnson's rule orders the jobs B, then A and C (either way), for
9 -- and 9 is also a lower bound, since welding takes 8 and cannot start
before the shortest cut (B's 1) ends. Only CP-SAT holds intervals.

**region_partitioning** -- districts (IR version 2, spatial). A 10 km x 8 km
area in 1 km hexes with a population layer, cut into 4 connected zones of
2 connected sub-zones each, balanced and compact. Built in `app.regions`,
whose docstring says why the goal is a moment of inertia and why the cells
are 1 km.

**cairo_university_lectures** -- OAAS Phase 6 demand-led use case. Four
FCAI sections meet once in a week: day × morning/afternoon × room, with the
instructor fixed on each section. Hard rules stop room and instructor
clashes and keep enrollment inside capacity; the goal prefers mornings.
Built in `app.lectures`; every section can sit in a morning slot, so the
proven objective is 0.

All six are refreshed on every start, as `weekly_rota` is, so a live
database cannot drift from this file.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.v1_problem import Template
from app.facilities import FACILITY_COVERAGE
from app.emergency_coverage import EMERGENCY_COVERAGE
from app.heatwave import HEATWAVE_COOLING
from app.heatwave import build_ir as heatwave_ir
from app.heatwave import build_seed as heatwave_seed
from app.emergency_coverage import build_ir as emergency_ir
from app.emergency_coverage import build_seed as emergency_seed
from app.facilities import build_ir as facility_ir
from app.facilities import build_seed as facility_seed
from app.lectures import CAIRO_UNIVERSITY_LECTURES
from app.lectures import build_ir as lectures_ir
from app.lectures import build_seed as lectures_seed
from app.regions import REGION_PARTITIONING, build_ir, build_seed

FEED_BLEND = "feed_blend"
LOAD_BALANCE = "load_balance"
WORKSHOP = "workshop"


def _sum(body: dict[str, Any], index: str, set_name: str) -> dict[str, Any]:
    return {"sum": body, "over": [{"index": index, "set": set_name}]}


def _var(name: str, index: str) -> dict[str, Any]:
    return {"var": name, "index": [index]}


def _attr(of: str, name: str) -> dict[str, Any]:
    return {"attr": {"of": of, "name": name}}


FEED_BLEND_IR: dict[str, Any] = {
    "version": 1,
    "sets": ["feed"],
    "parameters": {"cost": {"index": ["feed"]}},
    "variables": {
        "use": {"index": ["feed"], "domain": "continuous", "lower": 0, "upper": 100},
    },
    "constraints": [
        {
            "id": "c_batch",
            "note": "the batch is exactly 100 kg",
            "left": _sum(_var("use", "f"), "f", "feed"),
            "relation": "=",
            "right": {"const": 100},
            "severity": "hard",
        },
        {
            "id": "c_protein",
            "note": "at least 20 kg of protein in the batch",
            "left": _sum({"mul": [_attr("f", "protein"), _var("use", "f")]}, "f", "feed"),
            "relation": ">=",
            "right": {"const": 20},
            "severity": "hard",
        },
        {
            "id": "c_fibre",
            "note": "at most 5 kg of fibre in the batch",
            "left": _sum({"mul": [_attr("f", "fibre"), _var("use", "f")]}, "f", "feed"),
            "relation": "<=",
            "right": {"const": 5},
            "severity": "hard",
        },
    ],
    "objective": {
        "sense": "minimize",
        "terms": [
            {
                "id": "o_cost",
                "weight": 1,
                "expression": _sum(
                    {"mul": [{"par": "cost", "index": ["f"]}, _var("use", "f")]}, "f", "feed"
                ),
            }
        ],
    },
}

FEED_BLEND_SEED: dict[str, Any] = {
    "entity_types": [
        {
            "name": "feed",
            "role": "resource",
            "colour": "#ca8a04",
            "attributes": [
                {"name": "protein", "data_type": "number", "unit": "kg/kg", "required": True},
                {"name": "fibre", "data_type": "number", "unit": "kg/kg", "required": True},
            ],
        }
    ],
    "parameters": [{"name": "cost", "index": ["feed"], "default_value": 0, "unit": "EUR/kg"}],
    "entities": [
        {"type": "feed", "key": "maize", "label": "Maize", "attrs": {"protein": 0.09, "fibre": 0.02}},
        {"type": "feed", "key": "soy", "label": "Soybean meal", "attrs": {"protein": 0.44, "fibre": 0.06}},
        {"type": "feed", "key": "bran", "label": "Wheat bran", "attrs": {"protein": 0.16, "fibre": 0.10}},
    ],
    "parameter_values": [
        {"parameter": "cost", "entities": [["feed", "maize"]], "value": 0.30},
        {"parameter": "cost", "entities": [["feed", "soy"]], "value": 0.90},
        {"parameter": "cost", "entities": [["feed", "bran"]], "value": 0.20},
    ],
}

LOAD_BALANCE_IR: dict[str, Any] = {
    "version": 1,
    "sets": ["person"],
    "parameters": {},
    "variables": {
        "hours": {"index": ["person"], "domain": "continuous", "lower": 0, "upper": 60},
    },
    "constraints": [
        {
            "id": "c_total",
            "note": "all 120 hours of work are covered",
            "left": _sum(_var("hours", "p"), "p", "person"),
            "relation": "=",
            "right": {"const": 120},
            "severity": "hard",
        },
        {
            "id": "c_capacity",
            "note": "nobody works past their capacity",
            "forall": [{"index": "p", "set": "person"}],
            "left": _var("hours", "p"),
            "relation": "<=",
            "right": _attr("p", "capacity"),
            "severity": "hard",
        },
    ],
    "objective": {
        "sense": "minimize",
        "terms": [
            {
                "id": "o_evenness",
                "weight": 1,
                # hours[p] * hours[p]: squaring punishes one person carrying
                # much more than another, which is what "even" means here.
                "expression": _sum({"mul": [_var("hours", "p"), _var("hours", "p")]}, "p", "person"),
            }
        ],
    },
}

LOAD_BALANCE_SEED: dict[str, Any] = {
    "entity_types": [
        {
            "name": "person",
            "role": "agent",
            "colour": "#7c3aed",
            "attributes": [
                {"name": "capacity", "data_type": "number", "unit": "h", "required": True},
            ],
        }
    ],
    "entities": [
        {"type": "person", "key": "ana", "label": "Ana", "attrs": {"capacity": 50}},
        {"type": "person", "key": "ben", "label": "Ben", "attrs": {"capacity": 50}},
        {"type": "person", "key": "chloe", "label": "Chloe", "attrs": {"capacity": 15}},
        {"type": "person", "key": "dev", "label": "Dev", "attrs": {"capacity": 30}},
    ],
}

_JM = {"index": ["job", "machine"]}
_OP = {"var": "op", "index": ["j", "m"]}

WORKSHOP_IR: dict[str, Any] = {
    "version": 2,
    "sets": ["job", "machine"],
    "relationships": ["feeds"],
    "parameters": {"duration": {"index": ["job", "machine"]}},
    "variables": {
        "begin": {**_JM, "domain": "integer", "lower": 0, "upper": 40},
        "finish": {**_JM, "domain": "integer", "lower": 0, "upper": 40},
        "makespan": {"index": [], "domain": "integer", "lower": 0, "upper": 40},
        # Each job's turn on each machine: from begin to finish, lasting its
        # duration there.
        "op": {**_JM, "domain": "interval", "start": "begin", "end": "finish", "size": "duration"},
    },
    "constraints": [
        {
            "id": "c_one_at_a_time",
            "note": "each machine works on one job at a time",
            "forall": [{"index": "m", "set": "machine"}],
            "no_overlap": {"interval": _OP, "over": [{"index": "j", "set": "job"}]},
            "severity": "hard",
        },
        {
            "id": "c_route",
            "note": "a job reaches the next machine only once this one is done with it",
            "forall": [
                {"index": "j", "set": "job"},
                {"index": "m", "set": "machine"},
                {"index": "n", "set": "machine", "via": {"rel": "feeds", "from": "m"}},
            ],
            "left": {"var": "finish", "index": ["j", "m"]},
            "relation": "<=",
            "right": {"var": "begin", "index": ["j", "n"]},
            "severity": "hard",
        },
        {
            "id": "c_makespan",
            "note": "the makespan is when the last operation ends",
            "forall": [{"index": "j", "set": "job"}, {"index": "m", "set": "machine"}],
            "left": {"var": "finish", "index": ["j", "m"]},
            "relation": "<=",
            "right": {"var": "makespan", "index": []},
            "severity": "hard",
        },
    ],
    "objective": {
        "sense": "minimize",
        "terms": [{"id": "o_makespan", "weight": 1, "expression": {"var": "makespan", "index": []}}],
    },
}

_DURATIONS = {"a": (3, 2), "b": (1, 4), "c": (2, 2)}  # hours to cut, hours to weld

WORKSHOP_SEED: dict[str, Any] = {
    "entity_types": [
        {"name": "job", "role": "task", "colour": "#0f766e", "attributes": []},
        {"name": "machine", "role": "resource", "colour": "#b45309", "attributes": []},
    ],
    "relationship_types": [
        {"name": "feeds", "from": "machine", "to": "machine", "cardinality": "one_to_one", "is_hierarchy": False},
    ],
    "parameters": [{"name": "duration", "index": ["job", "machine"], "default_value": 0, "unit": "h"}],
    "entities": [
        *({"type": "job", "key": key, "label": f"Job {key.upper()}"} for key in _DURATIONS),
        {"type": "machine", "key": "cut", "label": "Cutter"},
        {"type": "machine", "key": "weld", "label": "Welder"},
    ],
    "relationships": [{"type": "feeds", "from": ["machine", "cut"], "to": ["machine", "weld"]}],
    "parameter_values": [
        {"parameter": "duration", "entities": [["job", job], ["machine", machine]], "value": hours}
        for job, pair in _DURATIONS.items()
        for machine, hours in zip(("cut", "weld"), pair)
    ],
}

SHOWCASE: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {
    FEED_BLEND: (FEED_BLEND_SEED, FEED_BLEND_IR),
    LOAD_BALANCE: (LOAD_BALANCE_SEED, LOAD_BALANCE_IR),
    WORKSHOP: (WORKSHOP_SEED, WORKSHOP_IR),
    REGION_PARTITIONING: (build_seed(), build_ir()),
    FACILITY_COVERAGE: (facility_seed(), facility_ir()),
    CAIRO_UNIVERSITY_LECTURES: (lectures_seed(), lectures_ir()),
    EMERGENCY_COVERAGE: (emergency_seed(), emergency_ir()),
    HEATWAVE_COOLING: (heatwave_seed(), heatwave_ir()),
}


#: A one-line purpose for each template that does not say its own (improvement plan 4.7): the
#: template list shows it, so a newcomer can tell a facility-location model from a blend.
NOTES: dict[str, str] = {
    FEED_BLEND: "Mix ingredients at the lowest cost while meeting nutrient limits: the classic blending "
                "(diet) model -- feed, fuel, fertiliser, concrete.",
    LOAD_BALANCE: "Share work across people or machines as evenly as each one's capacity allows: "
                  "minimise the busiest one's load.",
    WORKSHOP: "Order jobs through machines (cut, then weld) so everything is finished as early as possible: "
              "a job-shop schedule with task durations.",
    REGION_PARTITIONING: "Cut a map into connected zones with balanced populations, each as compact as it can be: "
                         "territories, districts, service areas.",
    FACILITY_COVERAGE: "Choose which sites to open and who each one serves, from the places on the map, at the "
                       "least fixed plus travel cost: depots, clinics, yards, warehouses.",
}


def ensure_showcase_templates(db: Session) -> dict[str, int]:
    """Create or refresh the showcase templates. Idempotent on the name."""
    ids: dict[str, int] = {}
    for name, (seed, ir) in SHOWCASE.items():
        if not seed.get("note") and name in NOTES:
            seed = {**seed, "note": NOTES[name]}
        found = db.execute(select(Template.id).where(Template.name == name)).scalar_one_or_none()
        if found is not None:
            db.execute(
                update(Template)
                .where(Template.id == found)
                .values(domain_seed=seed, default_ir=ir, ir_version=str(ir["version"]))
            )
            ids[name] = found
            continue
        row = Template(name=name, ir_version=str(ir["version"]), domain_seed=seed, default_ir=ir)
        db.add(row)
        db.flush()
        ids[name] = row.id
    db.commit()
    return ids
