"""The heatwave_cooling template (user trial, October 2026): where to open cooling centres during a
heatwave, from the map -- the problem the trial solved by hand, as a ready example.

Forty neighbourhood zones (areas, with their people, share over 65 and a vulnerability score), thirty
candidate sites (schools, youth centres, halls: seats, a daily cost, whether they have a generator),
four hospitals and eight medical teams based at them, and three areas at risk of power cuts. Nothing
about reach is typed in: applying the template computes, from the shapes,

- `covers[zone, site]`: 1 where a site is within 1.5 km of a zone;
- `hosp_reach[hospital, site]`: 1 where a site is within 6 km of a hospital;
- `in_outage_area`: each site linked to the outage area it lies in.

The model is what the model editor's coverage recipe writes for it: open sites so the most vulnerable
older people find a seat within reach, within a daily budget, each open site with a team its hospital
reaches, none in an outage area without a generator; goals in order -- the most covered worth, then
the least cost.
"""

from __future__ import annotations

import random
from typing import Any

HEATWAVE_COOLING = "heatwave_cooling"
BUDGET = 60_000
SEAT_SHARE = 0.05
_WEST, _SOUTH, _EAST, _NORTH = 31.135, 29.982, 31.227, 30.0995
_DISTRICTS = ["Imbaba", "Warraq", "Kit Kat", "Mohandessin", "Dokki", "Bulaq Dakrour", "Faisal", "Haram", "Omraniya"]
_HOSPITALS = [("imbaba_general", "Imbaba General Hospital", 31.207, 30.081),
              ("om_el_masryeen", "Om El Masryeen Hospital", 31.206, 30.012),
              ("haram", "Haram Hospital", 31.150, 29.995),
              ("agouza", "Agouza Hospital", 31.215, 30.058)]
_KINDS = ["Youth Centre", "Prep School", "Mosque Hall", "Community Hall"]


def _square(west: float, south: float, east: float, north: float) -> dict[str, Any]:
    ring = [[west, south], [east, south], [east, north], [west, north], [west, south]]
    return {"type": "Polygon", "coordinates": [[[round(x, 5), round(y, 5)] for x, y in ring]]}


def _places() -> dict[str, list[dict[str, Any]]]:
    rnd = random.Random(HEATWAVE_COOLING)
    cols, rows = 8, 5
    dx, dy = (_EAST - _WEST) / cols, (_NORTH - _SOUTH) / rows
    zones = []
    for r in range(rows):
        for c in range(cols):
            district = _DISTRICTS[min(len(_DISTRICTS) - 1, (c * rows + (rows - 1 - r)) * len(_DISTRICTS) // (cols * rows))]
            n = sum(1 for z in zones if z["label"].startswith(district)) + 1
            zones.append({"key": f"z{len(zones) + 1:02d}", "label": f"{district} {n}", "attrs": {
                "shape": _square(_WEST + c * dx, _SOUTH + r * dy, _WEST + (c + 1) * dx, _SOUTH + (r + 1) * dy),
                "population": rnd.randint(12, 60) * 1000, "share_over65": round(rnd.uniform(0.05, 0.14), 3),
                "vulnerability": rnd.randint(1, 5)}})
    sites, used = [], {}
    for k in range(30):
        district = rnd.choice(_DISTRICTS)
        kind = rnd.choice(_KINDS)
        used[(district, kind)] = used.get((district, kind), 0) + 1
        label = f"{district} {kind}" + ("" if used[(district, kind)] == 1 else f" {used[(district, kind)]}")
        sites.append({"key": f"s{k + 1:02d}", "label": label, "attrs": {
            "shape": {"type": "Point", "coordinates": [round(rnd.uniform(_WEST + 0.004, _EAST - 0.004), 5),
                                                       round(rnd.uniform(_SOUTH + 0.004, _NORTH - 0.004), 5)]},
            "seats": rnd.choice([100, 120, 150, 160, 180, 200, 250, 300, 400]),
            "cost_egp_day": rnd.randint(30, 110) * 100, "has_generator": rnd.random() < 0.3}})
    hospitals = [{"key": key, "label": label, "attrs": {"shape": {"type": "Point", "coordinates": [lon, lat]}}}
                 for key, label, lon, lat in _HOSPITALS]
    teams = [{"key": f"t{k + 1}", "label": f"Team {k + 1} ({_HOSPITALS[k % 4][1].replace(' Hospital', '')})",
              "attrs": {"base_hospital": _HOSPITALS[k % 4][0], "max_centres": 4}} for k in range(8)]
    outages = []
    for k, (cx, cy, area) in enumerate([(31.18, 30.07, "Imbaba feeder 7"), (31.16, 30.01, "Faisal substation"),
                                        (31.205, 30.04, "Dokki ring")]):
        outages.append({"key": f"o{k + 1}", "label": area,
                        "attrs": {"shape": _square(cx - 0.008, cy - 0.006, cx + 0.008, cy + 0.006)}})
    return {"zone": zones, "site": sites, "hospital": hospitals, "medical_team": teams, "outage_area": outages}


def build_seed() -> dict[str, Any]:
    found = _places()
    shape = {"name": "shape", "data_type": "geometry"}
    return {
        "note": ("Where to open cooling centres in a heatwave, from the map: the vulnerable older people seated "
                 "within reach, a medical team at each centre, nothing in an outage area without a generator."),
        "entity_types": [
            {"name": "zone", "role": "location", "colour": "#f97316", "attributes": [
                shape, {"name": "population", "data_type": "integer"}, {"name": "share_over65", "data_type": "number"},
                {"name": "vulnerability", "data_type": "integer"}]},
            {"name": "site", "role": "location", "colour": "#2563eb", "attributes": [
                shape, {"name": "seats", "data_type": "integer"}, {"name": "cost_egp_day", "data_type": "integer"},
                {"name": "has_generator", "data_type": "boolean"}]},
            {"name": "hospital", "role": "location", "colour": "#dc2626", "attributes": [shape]},
            {"name": "medical_team", "role": "agent", "colour": "#059669", "attributes": [
                {"name": "base_hospital", "data_type": "reference", "target": "hospital"},
                {"name": "max_centres", "data_type": "integer"}]},
            {"name": "outage_area", "role": "location", "colour": "#475569", "attributes": [shape]},
        ],
        "entities": [{"type": kind, **e} for kind in ("zone", "site", "hospital", "medical_team", "outage_area")
                     for e in found[kind]],
        "within": [{"name": "covers", "from": "zone", "to": "site", "max_m": 1500, "output": "parameter"},
                   {"name": "hosp_reach", "from": "hospital", "to": "site", "max_m": 6000, "output": "parameter"}],
        "inside": [{"name": "in_outage_area", "from": "site", "to": "outage_area"}],
    }


def _attr(of: str, name: str) -> dict[str, Any]:
    return {"attr": {"of": of, "name": name}}


def build_ir() -> dict[str, Any]:
    opened = {"var": "open", "index": ["s"]}
    covered = {"var": "covered", "index": ["p"]}
    seat = {"var": "seated", "index": ["p", "s"]}
    assign = {"var": "assign", "index": ["t", "s"]}
    each_zone = [{"index": "p", "set": "zone"}]
    each_site = [{"index": "s", "set": "site"}]
    each_team = [{"index": "t", "set": "medical_team"}]
    reach = {"par": "covers", "index": ["p", "s"]}
    people = {"mul": [{"mul": [_attr("p", "population"), _attr("p", "share_over65")]}, {"const": SEAT_SHARE}]}
    cost = {"sum": {"mul": [_attr("s", "cost_egp_day"), opened]}, "over": each_site}
    return {
        "version": 2,
        "sets": ["site", "zone", "hospital", "medical_team", "outage_area"],
        "relationships": ["base_hospital", "in_outage_area"],
        "parameters": {"covers": {"index": ["zone", "site"]}, "hosp_reach": {"index": ["hospital", "site"]}},
        "variables": {"open": {"index": ["site"], "domain": "binary"}, "covered": {"index": ["zone"], "domain": "binary"},
                      "seated": {"index": ["zone", "site"], "domain": "continuous", "lower": 0},
                      "assign": {"index": ["medical_team", "site"], "domain": "binary"}},
        "constraints": [
            {"id": "covered_needs_open", "note": "a zone counts as covered only with an open site within reach",
             "forall": each_zone, "left": covered, "relation": "<=",
             "right": {"sum": {"mul": [reach, opened]}, "over": each_site}, "severity": "hard"},
            {"id": "budget", "note": f"the open sites cost at most {BUDGET} a day", "left": cost, "relation": "<=",
             "right": {"const": BUDGET}, "severity": "hard"},
            {"id": "seats_for_covered", "note": f"a covered zone has seats for {round(SEAT_SHARE * 100)}% of its over-65s",
             "forall": each_zone, "left": {"sum": seat, "over": each_site}, "relation": ">=",
             "right": {"mul": [people, covered]}, "severity": "hard"},
            {"id": "seats_within_reach", "note": "people are seated only at sites within reach",
             "forall": [*each_zone, *each_site], "left": seat, "relation": "<=", "right": {"mul": [people, reach]},
             "severity": "hard"},
            {"id": "seats_capacity", "note": "an open site seats at most its seats, a closed one none",
             "forall": each_site, "left": {"sum": seat, "over": each_zone}, "relation": "<=",
             "right": {"mul": [_attr("s", "seats"), opened]}, "severity": "hard"},
            {"id": "one_per_open_site", "note": "each open site has one medical team, a closed one none",
             "forall": each_site, "left": {"sum": assign, "over": each_team}, "relation": "=", "right": opened,
             "severity": "hard"},
            {"id": "staff_capacity", "note": "a medical team serves at most its max centres",
             "forall": each_team, "left": {"sum": assign, "over": each_site}, "relation": "<=",
             "right": _attr("t", "max_centres"), "severity": "hard"},
            {"id": "staff_reach", "note": "a medical team serves only sites its base hospital reaches",
             "forall": [*each_team, *each_site], "left": assign, "relation": "<=",
             "right": {"sum": {"par": "hosp_reach", "index": ["h", "s"]},
                       "over": [{"index": "h", "set": "hospital", "via": {"rel": "base_hospital", "from": "t"}}]},
             "severity": "hard"},
            {"id": "avoid_outage_area", "note": "no site in an outage area is opened unless it has a generator",
             "forall": [{"index": "s", "set": "site", "where": [{"attr": "has_generator", "op": "=", "value": False}]}],
             "left": {"sum": opened, "over": [{"index": "a", "set": "outage_area", "via": {"rel": "in_outage_area", "from": "s"}}]},
             "relation": "<=", "right": {"const": 0}, "severity": "hard"},
        ],
        "objective": {"sense": "maximize", "mode": "lex", "terms": [
            {"id": "covered_worth", "weight": 1, "expression": {"sum": {"mul": [
                {"mul": [{"mul": [_attr("p", "population"), _attr("p", "vulnerability")]}, _attr("p", "share_over65")]},
                covered]}, "over": each_zone}},
            {"id": "cost", "weight": 1, "expression": {"mul": [{"const": -1}, cost]}},
        ]},
    }
