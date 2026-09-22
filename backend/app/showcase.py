"""Two templates that show the solving the demo rota cannot.

The seeded rota is an integer program: every decision is yes or no, so a
person exploring the product never meets a fractional answer, a linear
program, or a quadratic objective -- the platform's widest capabilities were
its least visible. These two are small, real, and checkable by hand, and each
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

Both are refreshed on every start, as `weekly_rota` is, so a live database
cannot drift from this file.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.v1_problem import Template

FEED_BLEND = "feed_blend"
LOAD_BALANCE = "load_balance"


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

SHOWCASE: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {
    FEED_BLEND: (FEED_BLEND_SEED, FEED_BLEND_IR),
    LOAD_BALANCE: (LOAD_BALANCE_SEED, LOAD_BALANCE_IR),
}


def ensure_showcase_templates(db: Session) -> dict[str, int]:
    """Create or refresh both templates. Idempotent on the name."""
    ids: dict[str, int] = {}
    for name, (seed, ir) in SHOWCASE.items():
        found = db.execute(select(Template.id).where(Template.name == name)).scalar_one_or_none()
        if found is not None:
            db.execute(update(Template).where(Template.id == found).values(domain_seed=seed, default_ir=ir))
            ids[name] = found
            continue
        row = Template(name=name, ir_version="1", domain_seed=seed, default_ir=ir)
        db.add(row)
        db.flush()
        ids[name] = row.id
    db.commit()
    return ids
