"""exactly_one / at_most_one -- one pick per group (build-protocol plan, construct 2.4).

    {"id": "c_one", "at_most_one" | "exactly_one": {"for": [bindings], "over": [bindings], "pick": {"var": ...}}}
"""

from __future__ import annotations

from typing import Any

from app.agent.constructs._common import ConstructRefused, bindings, body_object, var

KEYS = ("at_most_one", "exactly_one")

FIELDS = {
    "for": "each group (bindings; optional: with none, one group of everything)",
    "over": 'the group\'s members: [{"index": "m", "set": ..., "via" or "where": ...}]',
    "pick": "whether a member is picked (a yes/no decision)",
}

DESCRIPTION = (
    'exactly_one / at_most_one: one pick per group. Write {"id": ..., "exactly_one": {"for": [<each group>], '
    '"over": [<the group\'s members>], "pick": <whether a member is picked>}} (or "at_most_one"). The platform '
    'writes the sum of the picks over the members = 1 (or <= 1) for every group.'
)


def expand(rid: str, body: Any, rule: dict, ir: dict, seed: dict, kind: str) -> list[dict[str, Any]]:
    body = body_object(body)
    over = bindings(body.get("over"), '"over"')
    if not over:
        raise ConstructRefused('"over" names the group\'s members: [{"index": "m", "set": ..., "via" or "where": ...}]')
    pick = var(body.get("pick"), '"pick"')
    note = rule.get("note") or ("exactly one per group" if kind == "exactly_one" else "at most one per group")
    return [{"id": rid, "note": f"{note} (the idiom {kind})",
             **({"forall": bindings(body.get("for"), '"for"')} if body.get("for") else {}),
             "left": {"sum": pick, "over": over}, "relation": "=" if kind == "exactly_one" else "<=",
             "right": {"const": 1}}]


#: The hand-worked example: each of two tasks goes to exactly one of two places, each place takes at most one;
#: only the pairs the list allows (only_if over a 0/1 list); cheapest 4 + 3 = 7.
EXAMPLE: dict[str, Any] = {
    "objective": 7,
    "seed": {"entity_types": [{"name": "task", "attributes": []}, {"name": "place", "attributes": []}],
             "entities": [{"type": "task", "key": k} for k in ("k1", "k2")] + [{"type": "place", "key": p} for p in ("p1", "p2")],
             "parameters": [{"name": "allowed", "index": ["task", "place"], "default_value": 0},
                            {"name": "cost", "index": ["task", "place"], "default_value": 0}],
             "parameter_values": [
                 {"parameter": "allowed", "entities": [["task", "k1"], ["place", "p2"]], "value": 1},
                 {"parameter": "allowed", "entities": [["task", "k2"], ["place", "p1"]], "value": 1},
                 {"parameter": "allowed", "entities": [["task", "k2"], ["place", "p2"]], "value": 1}]
             + [{"parameter": "cost", "entities": [["task", k], ["place", p]], "value": c}
                for k, p, c in (("k1", "p1", 1), ("k1", "p2", 4), ("k2", "p1", 3), ("k2", "p2", 2))]},
    "ir": {"version": 2, "sets": ["task", "place"],
           "parameters": {"allowed": {"index": ["task", "place"]}, "cost": {"index": ["task", "place"]}},
           "variables": {"go": {"index": ["task", "place"], "domain": "binary"}},
           "constraints": [{"id": "c_allowed", "only_if": {"for": [{"index": "k", "set": "task"}, {"index": "p", "set": "place"}],
                                                           "amount": {"var": "go", "index": ["k", "p"]},
                                                           "chosen": {"par": "allowed", "index": ["k", "p"]}}},
                           {"id": "c_one", "exactly_one": {"for": [{"index": "k", "set": "task"}],
                                                           "over": [{"index": "p", "set": "place"}],
                                                           "pick": {"var": "go", "index": ["k", "p"]}}},
                           {"id": "c_place", "at_most_one": {"for": [{"index": "p", "set": "place"}],
                                                             "over": [{"index": "k", "set": "task"}],
                                                             "pick": {"var": "go", "index": ["k", "p"]}}}],
           "objective": {"sense": "minimize", "terms": [{"id": "o", "weight": 1, "expression": {
               "sum": {"mul": [{"par": "cost", "index": ["k", "p"]}, {"var": "go", "index": ["k", "p"]}]},
               "over": [{"index": "k", "set": "task"}, {"index": "p", "set": "place"}]}}]}},
}

#: The mistake written by hand: exactly one as at least one (>= 1); with costs to pay it changes nothing here
#: (7), which the table counts as harmless -- the plan lists no mutation for this construct.
WRONG: dict[str, Any] = {
    "why": "exactly one written as at least one (>= 1)",
    "objective": 7,
    "constraints": [{"id": "c_one", "forall": [{"index": "k", "set": "task"}],
                     "left": {"sum": {"var": "go", "index": ["k", "p"]}, "over": [{"index": "p", "set": "place"}]},
                     "relation": ">=", "right": {"const": 1}, "severity": "hard"}],
}
