"""The region_partitioning template (GIS 8, spatial spec §5): districts over a hex grid.

A 10 km x 8 km area near Cairo is covered in 1 km hexes, each carrying the
people who live in it (a fixed, seeded population layer). The model cuts
the area into 4 zones and each zone into 2 sub-zones such that

- every cell is in exactly one zone and one sub-zone, and a sub-zone's
  cells are in its own zone (`belongs_to`, walked as a `via`);
- every zone holds its share of the people within 10%, every sub-zone
  within 15%;
- every zone and every sub-zone is one connected piece (`connected`, at
  both levels);
- the pieces are compact: the goal is the least moment of inertia about
  fixed centres.

**Why a moment of inertia, not the fewest cut edges.** A cut-edge goal needs
a variable per adjacent pair and zone, and a variable here is declared over
whole sets -- cell x cell x zone, half a million for this grid. The
distance of each cell from its zone's centre is data, so the goal is linear
in `assign` and costs nothing extra. On the hex grid's axial coordinates
(q = `col`, r = `row`) four times the squared distance is
(2dq + dr)^2 + 3dr^2: whole numbers, so CP-SAT keeps the model.

**Why 1 km cells, not 500 m.** Measured with 8 threads: at 1 km (90
cells) the nested model is proven optimal by HiGHS in about 7 s and by
CP-SAT in 10-20 s; at 750 m CP-SAT finds nothing feasible in 60 s, and at
500 m (360 cells) nothing in 120 s. A
template is a working example to copy, so it is the size that solves; the
`districting` bench family records where the exact flow stops scaling.

Everything is computed here from the same pure functions the grid endpoint
uses, so the template's constants (the population total, the centres) are
exactly what applying it will build.
"""

from __future__ import annotations

import random
from functools import lru_cache
from typing import Any

from app.spatial.grid import make_grid, sum_points

REGION_PARTITIONING = "region_partitioning"
CELL_SIZE_M = 1000
#: A 10 km x 8 km rectangle near 31.2 E, 30.0 N (about 0.104 x 0.072 degrees).
BOUNDARY = {
    "type": "Polygon",
    "coordinates": [[[31.20, 30.00], [31.304, 30.00], [31.304, 30.072], [31.20, 30.072], [31.20, 30.00]]],
}
ZONES = ("z1", "z2", "z3", "z4")
#: Each zone's two sub-zones: `z1a`, `z1b`, ...
SUBZONES = tuple(f"{z}{half}" for z in ZONES for half in "ab")
#: Where each zone's centre sits, as a fraction of the grid's extent
#: (west to east, south to north): the four quarters.
_ZONE_AT = {"z1": (0.25, 0.25), "z2": (0.75, 0.25), "z3": (0.25, 0.75), "z4": (0.75, 0.75)}
#: A sub-zone's centre: its zone's quarter split west and east.
_SUB_OFFSET = {"a": -0.125, "b": 0.125}
ZONE_SLACK, SUBZONE_SLACK = 0.10, 0.15


def population_points(count: int = 400, seed: int = 7) -> list[dict[str, float]]:
    """A fixed population layer: more people towards the south-west, as a
    real city is uneven, so balance pulls the zones out of their quarters."""
    rnd = random.Random(seed)
    (x0, y0), (x1, y1) = BOUNDARY["coordinates"][0][0], BOUNDARY["coordinates"][0][2]
    points = []
    for _ in range(count):
        fx, fy = rnd.random() ** 1.6, rnd.random() ** 1.3
        points.append({"lon": round(x0 + fx * (x1 - x0), 6), "lat": round(y0 + fy * (y1 - y0), 6),
                       "population": rnd.randint(50, 500)})
    return points


def _x2(q: int, r: int) -> int:
    """Twice the east-west position of an axial hex, in half-widths."""
    return 2 * q + r


@lru_cache(maxsize=1)
def layout() -> dict[str, Any]:
    """The grid the template will build, and what the model's constants are read from."""
    cells, edges, _ = make_grid(BOUNDARY, crs=4326, shape="hex", size_m=CELL_SIZE_M, keep="centre")
    points = population_points()
    sums, _lost = sum_points(cells, [(p["lon"], p["lat"], {"population": p["population"]}) for p in points], 4326)
    xs = [_x2(c.col, c.row) for c in cells]
    rows = [c.row for c in cells]
    (xmin, xmax), (rmin, rmax) = (min(xs), max(xs)), (min(rows), max(rows))

    def nearest(fx: float, fy: float) -> tuple[int, int]:
        """The cell nearest a fraction of the extent, as its (row, col)."""
        tx, tr = xmin + fx * (xmax - xmin), rmin + fy * (rmax - rmin)
        best = min(cells, key=lambda c: (_x2(c.col, c.row) - tx) ** 2 + 3 * (c.row - tr) ** 2)
        return best.row, best.col

    centres = {z: nearest(*at) for z, at in _ZONE_AT.items()}
    for z, (fx, fy) in _ZONE_AT.items():
        for half, dx in _SUB_OFFSET.items():
            centres[f"{z}{half}"] = nearest(fx + dx, fy)
    population = {c.key: sums.get(c.key, {}).get("population", 0.0) for c in cells}
    return {"cells": cells, "edges": edges, "population": population,
            "total": int(sum(population.values())), "centres": centres}


def _attr(of: str, name: str) -> dict[str, Any]:
    return {"attr": {"of": of, "name": name}}


def _inertia(u: str, g: str, var: str, shape: str = "hex") -> dict[str, Any]:
    """assign[u,g] times the squared distance from u to g's centre: on a
    hex grid four times it, (2dq + dr)^2 + 3dr^2; on a square one dc^2 + dr^2."""
    dr = {"add": [_attr(u, "row"), {"mul": [{"const": -1}, _attr(g, "row")]}]}
    if shape == "hex":
        dx = {"add": [{"mul": [{"const": 2}, _attr(u, "col")]}, _attr(u, "row"),
                      {"mul": [{"const": -2}, _attr(g, "col")]}, {"mul": [{"const": -1}, _attr(g, "row")]}]}
        distance = {"add": [{"mul": [dx, dx]}, {"mul": [{"const": 3}, {"mul": [dr, dr]}]}]}
    else:
        dc = {"add": [_attr(u, "col"), {"mul": [{"const": -1}, _attr(g, "col")]}]}
        distance = {"add": [{"mul": [dc, dc]}, {"mul": [dr, dr]}]}
    return {"mul": [distance, {"var": var, "index": [u, g]}]}


def _people(var: str, g: str) -> dict[str, Any]:
    return {"sum": {"mul": [_attr("u", "population"), {"var": var, "index": ["u", g]}]},
            "over": [{"index": "u", "set": "cell"}]}


def _balance(rule: str, var: str, g: str, group_set: str, share: float, slack: float, noun: str) -> list[dict]:
    return [
        {"id": f"{rule}_enough", "note": f"each {noun} holds at least its share of the people, less {slack:.0%}",
         "forall": [{"index": g, "set": group_set}], "left": _people(var, g), "relation": ">=",
         "right": {"const": int(share * (1 - slack))}, "severity": "hard"},
        {"id": f"{rule}_not_too_many", "note": f"and at most its share, plus {slack:.0%}",
         "forall": [{"index": g, "set": group_set}], "left": _people(var, g), "relation": "<=",
         "right": {"const": -(-int(share * (1 + slack) * 1000) // 1000)}, "severity": "hard"},
    ]


def build_ir(zones: int = len(ZONES), subzones: int = len(SUBZONES), total: int | None = None,
             nested: bool = True, shape: str = "hex") -> dict[str, Any]:
    total = layout()["total"] if total is None else total
    one_each = lambda var, g, group_set: {  # noqa: E731
        "id": f"c_one_{group_set}", "note": f"every cell is in exactly one {group_set.replace('subzone', 'sub-zone')}",
        "forall": [{"index": "u", "set": "cell"}],
        "left": {"sum": {"var": var, "index": ["u", g]}, "over": [{"index": g, "set": group_set}]},
        "relation": "=", "right": {"const": 1}, "severity": "hard"}
    connected = lambda rule, var, g, group_set: {  # noqa: E731
        "id": rule, "note": f"every {group_set.replace('subzone', 'sub-zone')} is one connected piece", "severity": "hard",
        "connected": {"assign": {"var": var, "index": ["u", g]}, "units": {"index": "u", "set": "cell"},
                      "groups": {"index": g, "set": group_set}, "via": "adjacent"}}
    constraints = [one_each("assign", "z", "zone"), *_balance("c_zone", "assign", "z", "zone", total / zones, ZONE_SLACK, "zone"),
                   connected("c_zone_connected", "assign", "z", "zone")]
    variables = {"assign": {"index": ["cell", "zone"], "domain": "binary"}}
    terms = [{"id": "o_zones_compact", "weight": 1,
              "expression": {"sum": _inertia("u", "z", "assign", shape),
                             "over": [{"index": "u", "set": "cell"}, {"index": "z", "set": "zone"}]}}]
    sets, relationships = ["cell", "zone"], ["adjacent"]
    if nested:
        sets.append("subzone")
        relationships.append("belongs_to")
        variables["sub"] = {"index": ["cell", "subzone"], "domain": "binary"}
        constraints += [
            one_each("sub", "s", "subzone"),
            {"id": "c_inside_its_zone", "note": "a sub-zone's cells are in the zone it belongs to",
             "forall": [{"index": "u", "set": "cell"}, {"index": "s", "set": "subzone"},
                        {"index": "z", "set": "zone", "via": {"rel": "belongs_to", "from": "s"}}],
             "left": {"var": "sub", "index": ["u", "s"]}, "relation": "<=",
             "right": {"var": "assign", "index": ["u", "z"]}, "severity": "hard"},
            *_balance("c_subzone", "sub", "s", "subzone", total / subzones, SUBZONE_SLACK, "sub-zone"),
            connected("c_subzone_connected", "sub", "s", "subzone"),
        ]
        terms.append({"id": "o_subzones_compact", "weight": 1,
                      "expression": {"sum": _inertia("u", "s", "sub", shape),
                                     "over": [{"index": "u", "set": "cell"}, {"index": "s", "set": "subzone"}]}})
    return {"version": 2, "sets": sets, "relationships": relationships, "parameters": {}, "variables": variables,
            "constraints": constraints, "objective": {"sense": "minimize", "terms": terms}}


def build_seed() -> dict[str, Any]:
    centres = layout()["centres"]
    centre = lambda name: {"row": centres[name][0], "col": centres[name][1]}  # noqa: E731
    return {
        "entity_types": [
            {"name": "area", "role": "location", "colour": "#64748b",
             "attributes": [{"name": "boundary", "data_type": "geometry"}]},
            {"name": "zone", "role": "org", "colour": "#2563eb",
             "attributes": [{"name": "row", "data_type": "integer"}, {"name": "col", "data_type": "integer"}]},
            {"name": "subzone", "role": "org", "colour": "#7c3aed",
             "attributes": [{"name": "row", "data_type": "integer"}, {"name": "col", "data_type": "integer"}]},
        ],
        "relationship_types": [
            {"name": "belongs_to", "from": "subzone", "to": "zone", "cardinality": "many_to_one", "is_hierarchy": False},
        ],
        "entities": [
            {"type": "area", "key": "region", "label": "The region", "attrs": {"boundary": BOUNDARY}},
            *({"type": "zone", "key": z, "label": f"Zone {z[1]}", "attrs": centre(z)} for z in ZONES),
            *({"type": "subzone", "key": s, "label": f"Zone {s[1]}{s[2].upper()}", "attrs": centre(s)} for s in SUBZONES),
        ],
        "relationships": [{"type": "belongs_to", "from": ["subzone", s], "to": ["zone", s[:2]]} for s in SUBZONES],
        # Made after the records: the cells, their adjacency and their people.
        "grids": [{"boundary_entity": ["area", "region"], "shape": "hex", "size_m": CELL_SIZE_M,
                   "entity_type": "cell", "layers": population_points()}],
    }


def sample_dataset(nested: bool = True) -> dict[str, Any]:
    """The dataset applying the template freezes, built in memory: for the
    bench and for checking the model without a database."""
    built = layout()
    centres = built["centres"]
    sets: dict[str, Any] = {
        "cell": [{"id": c.key, "row": c.row, "col": c.col, "population": built["population"][c.key]} for c in built["cells"]],
        "zone": [{"id": z, "row": centres[z][0], "col": centres[z][1]} for z in ZONES],
    }
    relationships = {"adjacent": [{"from": e.a, "to": e.b} for e in built["edges"]]}
    if nested:
        sets["subzone"] = [{"id": s, "row": centres[s][0], "col": centres[s][1]} for s in SUBZONES]
        relationships["belongs_to"] = [{"from": s, "to": s[:2]} for s in SUBZONES]
    return {"sets": sets, "parameters": {}, "parameter_defaults": {}, "relationships": relationships}
