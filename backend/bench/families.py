"""Seeded generators: one model family per template, at four sizes.

Each generator returns `(ir, data)` -- an IR the contract accepts and a
dataset in the shape a frozen snapshot has -- so an instance goes through the
same `compile -> classify -> choose -> solve` path a run does. Nothing here
touches the database: the benchmark measures the solve, not the snapshot.

The same `(family, size, instance)` always generates the same model, so a
result can be reproduced and two techniques compared on identical input.

Families, and the class each exercises:

- `rota` -- the weekly rota (IP): cover demand per day and shift, one shift
  a day each, a weekly shift cap per person, fewest shifts worked.
- `facility` -- capacitated facility location (MILP): open facilities (yes
  or no) and ship quantities (continuous) to meet demand at least cost.
- `feed_blend` -- the feed-blend template (LP), with more feeds and
  nutrients.
- `load_balance` -- the load-balance template (convex QP): share hours as
  evenly as capacities allow.
- `rota_rates` -- the rota with money and hours in them (IP, fractional
  data): 7.5-hour shifts under a weekly hour cap, and hourly rates to the
  cent. Every decision is yes or no; only the numbers are fractional.
- `knapsack` -- a multi-dimensional knapsack (IP, fractional data): pick
  items with weights to one decimal place under several capacities, for the
  most value to the cent.

The last two are what `solve.cpsat_scaling` is about (migration 0039):
whole-number models that only reach CP-SAT once their rules are scaled.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Callable

SIZES = ("S", "M", "L", "XL")


@dataclass(frozen=True)
class Instance:
    family: str
    size: str
    instance: int
    ir: dict[str, Any]
    data: dict[str, Any]

    @property
    def name(self) -> str:
        return f"{self.family}-{self.size}-{self.instance}"


def _sum(body: dict, *over: tuple[str, str]) -> dict:
    return {"sum": body, "over": [{"index": i, "set": s} for i, s in over]}


def _var(name: str, *index: str) -> dict:
    return {"var": name, "index": list(index)}


def _par(name: str, *index: str) -> dict:
    return {"par": name, "index": list(index)}


def _mul(a: dict, b: dict) -> dict:
    return {"mul": [a, b]}


def _data(sets: dict[str, list[dict]], parameters: dict[str, list[dict]] | None = None) -> dict:
    return {"sets": sets, "parameters": parameters or {}, "parameter_defaults": {}, "relationships": {}}


# -- rota (IP) ----------------------------------------------------------------------

_ROTA = {"S": (10, 7), "M": (30, 7), "L": (80, 14), "XL": (200, 28)}


def rota(size: str, instance: int) -> tuple[dict, dict]:
    people, days = _ROTA[size]
    rnd = random.Random(f"rota-{size}-{instance}")
    shifts = ["early", "late", "night"]
    # Demand sized so the model is feasible with room to choose: about half
    # the people are needed on a given day across the three shifts.
    demand = [
        {"day": f"d{d}", "shift": s, "value": rnd.randint(1, max(1, people // 6))}
        for d in range(days)
        for s in shifts
    ]
    ir = {
        "version": 1,
        "sets": ["person", "day", "shift"],
        "parameters": {"demand": {"index": ["day", "shift"]}},
        "variables": {"assign": {"index": ["person", "day", "shift"], "domain": "binary"}},
        "constraints": [
            {
                "id": "c_cover",
                "forall": [{"index": "d", "set": "day"}, {"index": "s", "set": "shift"}],
                "left": _sum(_var("assign", "p", "d", "s"), ("p", "person")),
                "relation": ">=",
                "right": _par("demand", "d", "s"),
                "severity": "hard",
            },
            {
                "id": "c_one_a_day",
                "forall": [{"index": "p", "set": "person"}, {"index": "d", "set": "day"}],
                "left": _sum(_var("assign", "p", "d", "s"), ("s", "shift")),
                "relation": "<=",
                "right": {"const": 1},
                "severity": "hard",
            },
            {
                "id": "c_cap",
                "forall": [{"index": "p", "set": "person"}],
                "left": _sum(_var("assign", "p", "d", "s"), ("d", "day"), ("s", "shift")),
                "relation": "<=",
                "right": {"attr": {"of": "p", "name": "max_shifts"}},
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
                        _mul({"attr": {"of": "p", "name": "cost"}}, _var("assign", "p", "d", "s")),
                        ("p", "person"),
                        ("d", "day"),
                        ("s", "shift"),
                    ),
                }
            ],
        },
    }
    data = _data(
        {
            "person": [
                {"id": f"p{i}", "max_shifts": rnd.randint(days // 2, days), "cost": rnd.randint(8, 20)}
                for i in range(people)
            ],
            "day": [{"id": f"d{d}"} for d in range(days)],
            "shift": [{"id": s} for s in shifts],
        },
        {"demand": demand},
    )
    return ir, data


# -- facility location (MILP) ----------------------------------------------------

_FACILITY = {"S": (5, 20), "M": (15, 80), "L": (40, 300), "XL": (80, 1000)}


def facility(size: str, instance: int) -> tuple[dict, dict]:
    sites, customers = _FACILITY[size]
    rnd = random.Random(f"facility-{size}-{instance}")
    demand = {f"c{j}": rnd.randint(5, 35) for j in range(customers)}
    total = sum(demand.values())
    ir = {
        "version": 1,
        "sets": ["site", "customer"],
        "parameters": {"ship_cost": {"index": ["site", "customer"]}},
        "variables": {
            "open": {"index": ["site"], "domain": "binary"},
            "ship": {"index": ["site", "customer"], "domain": "continuous", "lower": 0, "upper": 1},
        },
        "constraints": [
            {
                "id": "c_served",
                "forall": [{"index": "c", "set": "customer"}],
                "left": _sum(_var("ship", "f", "c"), ("f", "site")),
                "relation": "=",
                "right": {"const": 1},
                "severity": "hard",
            },
            {
                "id": "c_only_open",
                "forall": [{"index": "f", "set": "site"}, {"index": "c", "set": "customer"}],
                "left": _var("ship", "f", "c"),
                "relation": "<=",
                "right": _var("open", "f"),
                "severity": "hard",
            },
            {
                "id": "c_capacity",
                "forall": [{"index": "f", "set": "site"}],
                "left": _sum(
                    _mul({"attr": {"of": "c", "name": "demand"}}, _var("ship", "f", "c")), ("c", "customer")
                ),
                "relation": "<=",
                "right": _mul({"attr": {"of": "f", "name": "capacity"}}, _var("open", "f")),
                "severity": "hard",
            },
        ],
        "objective": {
            "sense": "minimize",
            "terms": [
                {
                    "id": "o_fixed",
                    "weight": 1,
                    "expression": _sum(
                        _mul({"attr": {"of": "f", "name": "fixed"}}, _var("open", "f")), ("f", "site")
                    ),
                },
                {
                    "id": "o_ship",
                    "weight": 1,
                    "expression": _sum(
                        _mul(_par("ship_cost", "f", "c"), _var("ship", "f", "c")), ("f", "site"), ("c", "customer")
                    ),
                },
            ],
        },
    }
    data = _data(
        {
            # Capacities add up to about twice the demand: several sites must
            # open, and which ones is the decision.
            "site": [
                {"id": f"f{i}", "capacity": rnd.randint(total * 2 // sites, total * 3 // sites), "fixed": rnd.randint(500, 2000)}
                for i in range(sites)
            ],
            "customer": [{"id": key, "demand": value} for key, value in demand.items()],
        },
        {
            "ship_cost": [
                {"site": f"f{i}", "customer": f"c{j}", "value": rnd.randint(10, 200)}
                for i in range(sites)
                for j in range(customers)
            ]
        },
    )
    return ir, data


# -- feed blend (LP) ----------------------------------------------------------------

_BLEND = {"S": (6, 3), "M": (50, 10), "L": (400, 30), "XL": (2000, 60)}


def feed_blend(size: str, instance: int) -> tuple[dict, dict]:
    feeds, nutrients = _BLEND[size]
    rnd = random.Random(f"feed_blend-{size}-{instance}")
    content = {
        (f, n): round(rnd.uniform(0.0, 0.5), 3) for f in range(feeds) for n in range(nutrients)
    }
    # A requirement at 60% of what the average feed would give: met by some
    # blends, not by all.
    need = {n: round(sum(content[(f, n)] for f in range(feeds)) / feeds * 100 * 0.6, 2) for n in range(nutrients)}
    ir = {
        "version": 1,
        "sets": ["feed", "nutrient"],
        "parameters": {
            "cost": {"index": ["feed"]},
            "content": {"index": ["feed", "nutrient"]},
            "need": {"index": ["nutrient"]},
        },
        "variables": {"use": {"index": ["feed"], "domain": "continuous", "lower": 0, "upper": 100}},
        "constraints": [
            {
                "id": "c_batch",
                "left": _sum(_var("use", "f"), ("f", "feed")),
                "relation": "=",
                "right": {"const": 100},
                "severity": "hard",
            },
            {
                "id": "c_need",
                "forall": [{"index": "n", "set": "nutrient"}],
                "left": _sum(_mul(_par("content", "f", "n"), _var("use", "f")), ("f", "feed")),
                "relation": ">=",
                "right": _par("need", "n"),
                "severity": "hard",
            },
        ],
        "objective": {
            "sense": "minimize",
            "terms": [
                {"id": "o_cost", "weight": 1, "expression": _sum(_mul(_par("cost", "f"), _var("use", "f")), ("f", "feed"))}
            ],
        },
    }
    data = _data(
        {"feed": [{"id": f"f{f}"} for f in range(feeds)], "nutrient": [{"id": f"n{n}"} for n in range(nutrients)]},
        {
            "cost": [{"feed": f"f{f}", "value": round(rnd.uniform(0.1, 1.0), 3)} for f in range(feeds)],
            "content": [
                {"feed": f"f{f}", "nutrient": f"n{n}", "value": content[(f, n)]}
                for f in range(feeds)
                for n in range(nutrients)
            ],
            "need": [{"nutrient": f"n{n}", "value": need[n]} for n in range(nutrients)],
        },
    )
    return ir, data


# -- load balance (convex QP) ---------------------------------------------------------

_BALANCE = {"S": 10, "M": 100, "L": 1000, "XL": 5000}


def load_balance(size: str, instance: int) -> tuple[dict, dict]:
    people = _BALANCE[size]
    rnd = random.Random(f"load_balance-{size}-{instance}")
    capacity = [rnd.randint(10, 60) for _ in range(people)]
    total = sum(capacity) * 6 // 10
    ir = {
        "version": 1,
        "sets": ["person"],
        "parameters": {},
        "variables": {"hours": {"index": ["person"], "domain": "continuous", "lower": 0, "upper": 60}},
        "constraints": [
            {
                "id": "c_total",
                "left": _sum(_var("hours", "p"), ("p", "person")),
                "relation": "=",
                "right": {"const": total},
                "severity": "hard",
            },
            {
                "id": "c_capacity",
                "forall": [{"index": "p", "set": "person"}],
                "left": _var("hours", "p"),
                "relation": "<=",
                "right": {"attr": {"of": "p", "name": "capacity"}},
                "severity": "hard",
            },
        ],
        "objective": {
            "sense": "minimize",
            "terms": [
                {
                    "id": "o_even",
                    "weight": 1,
                    "expression": _sum(_mul(_var("hours", "p"), _var("hours", "p")), ("p", "person")),
                }
            ],
        },
    }
    data = _data({"person": [{"id": f"p{i}", "capacity": c} for i, c in enumerate(capacity)]})
    return ir, data


# -- rota_rates (IP, fractional data) ------------------------------------------------


def rota_rates(size: str, instance: int) -> tuple[dict, dict]:
    ir, data = rota(size, instance)
    rnd = random.Random(f"rota_rates-{size}-{instance}")
    days = len(data["sets"]["day"])
    for person in data["sets"]["person"]:
        # Rates to the cent; weekly hours a whole number, 7.5 a shift.
        person["cost"] = rnd.randint(1200, 2600) / 100
        person["max_hours"] = int(person.pop("max_shifts") * 7.5) + rnd.randint(0, 3)
    cap = next(c for c in ir["constraints"] if c["id"] == "c_cap")
    cap["left"] = _mul({"const": 7.5}, cap["left"])
    cap["right"] = {"attr": {"of": "p", "name": "max_hours"}}
    assert days > 0
    return ir, data


# -- knapsack (IP, fractional data) ---------------------------------------------------

_KNAPSACK = {"S": (20, 2), "M": (60, 4), "L": (150, 8), "XL": (400, 12)}


def knapsack(size: str, instance: int) -> tuple[dict, dict]:
    items, dims = _KNAPSACK[size]
    rnd = random.Random(f"knapsack-{size}-{instance}")
    weight = [
        {"item": f"i{i}", "dim": f"d{d}", "value": rnd.randint(10, 300) / 10}
        for i in range(items)
        for d in range(dims)
    ]
    per_dim: dict[str, float] = {}
    for w in weight:
        per_dim[w["dim"]] = per_dim.get(w["dim"], 0) + w["value"]
    ir = {
        "version": 1,
        "sets": ["item", "dim"],
        "parameters": {"weight": {"index": ["item", "dim"]}},
        "variables": {"take": {"index": ["item"], "domain": "binary"}},
        "constraints": [
            {
                "id": "c_capacity",
                "forall": [{"index": "d", "set": "dim"}],
                "left": _sum(_mul(_par("weight", "i", "d"), _var("take", "i")), ("i", "item")),
                "relation": "<=",
                "right": {"attr": {"of": "d", "name": "capacity"}},
                "severity": "hard",
            }
        ],
        "objective": {
            "sense": "maximize",
            "terms": [
                {
                    "id": "o_value",
                    "weight": 1,
                    "expression": _sum(
                        _mul({"attr": {"of": "i", "name": "value"}}, _var("take", "i")), ("i", "item")
                    ),
                }
            ],
        },
    }
    data = _data(
        {
            "item": [{"id": f"i{i}", "value": rnd.randint(100, 5000) / 100} for i in range(items)],
            # About half of everything fits in each dimension.
            "dim": [{"id": d, "capacity": int(total // 2)} for d, total in sorted(per_dim.items())],
        },
        {"weight": weight},
    )
    return ir, data


FAMILIES: dict[str, Callable[[str, int], tuple[dict, dict]]] = {
    "rota": rota,
    "facility": facility,
    "feed_blend": feed_blend,
    "load_balance": load_balance,
    "rota_rates": rota_rates,
    "knapsack": knapsack,
}


def generate(family: str, size: str, instance: int = 0) -> Instance:
    if family not in FAMILIES:
        raise KeyError(f"no family {family!r}; there are {', '.join(FAMILIES)}")
    if size not in SIZES:
        raise KeyError(f"no size {size!r}; there are {', '.join(SIZES)}")
    ir, data = FAMILIES[family](size, instance)
    return Instance(family, size, instance, ir, data)
