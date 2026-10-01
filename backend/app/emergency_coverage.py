"""The emergency_coverage template (improvement plan 5.8): where to keep response units so the places
at risk are covered -- and the critical ones twice -- from the map, with goals in order.

Ten candidate stations and sixty places at risk around Alexandria, each a point. Nothing about reach is
typed in: applying the template links each station to the places within 3 km (`reaches`, as
`POST .../within` does). It teaches the spatial pattern most cover problems share, without knowing
what the units are (ambulances, pump trucks, fire engines, repair crews):

- a place counts as covered only when an open station reaches it;
- a critical place needs two open stations within reach (a backup);
- at most `MAX_OPEN` stations open;
- goals in order: first the most risk covered, then the least running cost.
"""

from __future__ import annotations

import random
from typing import Any

EMERGENCY_COVERAGE = "emergency_coverage"
REACH_M = 3000
MAX_OPEN = 6
_WEST, _SOUTH, _EAST, _NORTH = 29.88, 31.17, 30.10, 31.26


def _places() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rnd = random.Random(EMERGENCY_COVERAGE)
    stations = []
    for k in range(10):
        where = [round(_WEST + (k + 0.5) * (_EAST - _WEST) / 10 + rnd.uniform(-0.004, 0.004), 5),
                 round(rnd.uniform(_SOUTH + 0.02, _NORTH - 0.02), 5)]
        stations.append({"key": f"station_{k + 1}", "label": f"Station {k + 1}",
                         "attrs": {"place": {"type": "Point", "coordinates": where},
                                   "running_cost": rnd.randint(20, 60) * 1000}})
    places = []
    for k in range(60):
        near = rnd.choice(stations)["attrs"]["place"]["coordinates"]
        where = [round(near[0] + rnd.uniform(-0.02, 0.02), 5), round(near[1] + rnd.uniform(-0.017, 0.017), 5)]
        risk = rnd.randint(1, 10)
        places.append({"key": f"place_{k + 1}", "label": f"Place {k + 1}",
                       "attrs": {"place": {"type": "Point", "coordinates": where}, "risk": risk,
                                 "critical": 1 if risk >= 9 else 0}})
    return stations, places


def build_seed() -> dict[str, Any]:
    stations, places = _places()
    return {
        "note": ("Where to keep response units so the places at risk are covered -- the critical ones twice -- "
                 "from points on the map: ambulances, pump trucks, fire engines, repair crews."),
        "entity_types": [
            {"name": "station", "role": "location", "colour": "#dc2626",
             "attributes": [{"name": "place", "data_type": "geometry"}, {"name": "running_cost", "data_type": "integer"}]},
            {"name": "risk_place", "role": "location", "colour": "#2563eb",
             "attributes": [{"name": "place", "data_type": "geometry"}, {"name": "risk", "data_type": "integer"},
                            {"name": "critical", "data_type": "integer"}]},
        ],
        "entities": [*({"type": "station", **s} for s in stations), *({"type": "risk_place", **p} for p in places)],
        "within": [{"name": "reaches", "from": "station", "to": "risk_place", "max_m": REACH_M}],
    }


def build_ir() -> dict[str, Any]:
    opened = {"var": "open", "index": ["s"]}
    covered = {"var": "covered", "index": ["p"]}
    each_place = [{"index": "p", "set": "risk_place"}]
    in_reach = [{"index": "s", "set": "station", "via": {"rel": "reaches", "to": "p"}}]
    return {
        "version": 2,
        "sets": ["station", "risk_place"],
        "relationships": ["reaches"],
        "parameters": {},
        "variables": {"open": {"index": ["station"], "domain": "binary"},
                      "covered": {"index": ["risk_place"], "domain": "binary"}},
        "constraints": [
            {"id": "c_covered_only_in_reach", "note": "a place counts as covered only when an open station reaches it",
             "forall": each_place, "left": covered, "relation": "<=",
             "right": {"sum": opened, "over": in_reach}, "severity": "hard"},
            {"id": "c_critical_backup", "note": "a critical place needs two open stations within reach",
             "forall": each_place, "left": {"sum": opened, "over": in_reach}, "relation": ">=",
             "right": {"mul": [{"const": 2}, {"attr": {"of": "p", "name": "critical"}}]}, "severity": "soft", "weight": 100},
            {"id": "c_budget", "note": f"at most {MAX_OPEN} stations open",
             "left": {"sum": opened, "over": [{"index": "s", "set": "station"}]}, "relation": "<=",
             "right": {"const": MAX_OPEN}, "severity": "hard"},
        ],
        "objective": {"sense": "maximize", "mode": "lex", "terms": [
            {"id": "o_risk_covered", "weight": 1,
             "expression": {"sum": {"mul": [{"attr": {"of": "p", "name": "risk"}}, covered]}, "over": each_place}},
            {"id": "o_running_cost", "weight": 1,
             "expression": {"mul": [{"const": -1}, {"sum": {"mul": [{"attr": {"of": "s", "name": "running_cost"}}, opened]},
                                                   "over": [{"index": "s", "set": "station"}]}]}},
        ]},
    }
