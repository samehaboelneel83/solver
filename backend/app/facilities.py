"""The facility_coverage template (queue R16a): which sites to open, and who each serves, from the map.

Eight candidate sites and forty customers placed around central Cairo,
each with a point shape. Nothing about distance is typed in: applying the
template computes `distance[site, customer]` (whole metres, straight line)
and `reaches[site -> customer]` (within 4 km) from the shapes, as
`POST .../distances` and `.../within` do, and records where they came from.
The model:

- every customer is served by exactly one site, and only by an open one;
- a site serves no more demand than its capacity;
- every customer has an open site within reach (4 km) -- coverage;
- least cost: each open site's fixed cost plus, per customer, demand times
  distance in metres (whole numbers, so CP-SAT keeps the model).

Each customer is placed within about 3 km of some site, so coverage can hold.

A model whose rules each read `serve` in at most two rows would be a network
(`app.solve.network`); the capacity and coverage rows are why this one is
not, which is the usual facility-location shape.
"""

from __future__ import annotations

import random
from typing import Any

FACILITY_COVERAGE = "facility_coverage"
REACH_M = 4000
#: A box around central Cairo, about 14 km x 12 km.
_WEST, _SOUTH, _EAST, _NORTH = 31.18, 29.98, 31.325, 30.09


def _places() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rnd = random.Random("facility_coverage")
    point = lambda: {"type": "Point", "coordinates": [round(rnd.uniform(_WEST, _EAST), 5), round(rnd.uniform(_SOUTH, _NORTH), 5)]}  # noqa: E731
    sites = [{"key": f"site_{k + 1}", "label": f"Site {k + 1}",
              "attrs": {"place": point(), "fixed_cost": rnd.randint(40, 90) * 1000, "capacity": rnd.randint(90, 160)}}
             for k in range(8)]
    # Each customer within about 3 km of some site (0.027 degrees of latitude is 3 km), so every one
    # can be covered -- by that site or another, if the cheaper plan closes it.
    customers = []
    for k in range(40):
        near = rnd.choice(sites)["attrs"]["place"]["coordinates"]
        where = [round(near[0] + rnd.uniform(-0.02, 0.02), 5), round(near[1] + rnd.uniform(-0.018, 0.018), 5)]
        customers.append({"key": f"customer_{k + 1}", "label": f"Customer {k + 1}",
                          "attrs": {"place": {"type": "Point", "coordinates": where}, "demand": rnd.randint(5, 25)}})
    return sites, customers


def build_seed() -> dict[str, Any]:
    sites, customers = _places()
    return {
        "entity_types": [
            {"name": "site", "role": "location", "colour": "#dc2626",
             "attributes": [{"name": "place", "data_type": "geometry"}, {"name": "fixed_cost", "data_type": "integer"},
                            {"name": "capacity", "data_type": "integer"}]},
            {"name": "customer", "role": "location", "colour": "#2563eb",
             "attributes": [{"name": "place", "data_type": "geometry"}, {"name": "demand", "data_type": "integer"}]},
        ],
        "entities": [*({"type": "site", **s} for s in sites), *({"type": "customer", **c} for c in customers)],
        # Computed from the shapes when the template is applied (queue R16a).
        "distances": [{"name": "distance", "from": "site", "to": "customer", "unit": "m"}],
        "within": [{"name": "reaches", "from": "site", "to": "customer", "max_m": REACH_M}],
    }


def build_ir() -> dict[str, Any]:
    serve = {"var": "serve", "index": ["s", "c"]}
    opened = {"var": "open", "index": ["s"]}
    each_site = [{"index": "s", "set": "site"}]
    each_customer = [{"index": "c", "set": "customer"}]
    return {
        "version": 2,
        "sets": ["site", "customer"],
        "relationships": ["reaches"],
        "parameters": {"distance": {"index": ["site", "customer"]}},
        "variables": {"open": {"index": ["site"], "domain": "binary"},
                      "serve": {"index": ["site", "customer"], "domain": "binary"}},
        "constraints": [
            {"id": "c_served_once", "note": "every customer is served by exactly one site", "forall": each_customer,
             "left": {"sum": serve, "over": each_site}, "relation": "=", "right": {"const": 1}, "severity": "hard"},
            {"id": "c_only_open", "note": "only an open site serves", "forall": [*each_site, *each_customer],
             "left": serve, "relation": "<=", "right": opened, "severity": "hard"},
            {"id": "c_capacity", "note": "a site serves no more demand than its capacity", "forall": each_site,
             "left": {"sum": {"mul": [{"attr": {"of": "c", "name": "demand"}}, serve]}, "over": each_customer},
             "relation": "<=", "right": {"mul": [{"attr": {"of": "s", "name": "capacity"}}, opened]}, "severity": "hard"},
            {"id": "c_covered", "note": f"every customer has an open site within {REACH_M // 1000} km", "forall": each_customer,
             "left": {"sum": opened, "over": [{"index": "s", "set": "site", "via": {"rel": "reaches", "to": "c"}}]},
             "relation": ">=", "right": {"const": 1}, "severity": "hard"},
        ],
        "objective": {"sense": "minimize", "terms": [
            {"id": "o_fixed", "weight": 1, "expression": {
                "sum": {"mul": [{"attr": {"of": "s", "name": "fixed_cost"}}, opened]}, "over": each_site}},
            {"id": "o_travel", "weight": 1, "expression": {
                "sum": {"mul": [{"mul": [{"attr": {"of": "c", "name": "demand"}}, {"par": "distance", "index": ["s", "c"]}]}, serve]},
                "over": [*each_site, *each_customer]}},
        ]},
    }
