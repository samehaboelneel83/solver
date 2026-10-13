"""share_of_total -- a part at least, or at most, a share of the whole (build-protocol plan, construct 2.7).

    {"id": "c_share", "share_of_total": {
        "for": [bindings],                                   where the rule holds (optional: once)
        "part": term,                                        the part of the mix (a record named by its key is bound)
        "total": {"sum": term, "over": [bindings]},          the whole (a term; usually a sum over the parts)
        "relation": "<=" | ">=",                             at most / at least
        "share": 0.3 | term}}                                the share, as a fraction

The language has no division, so part / total <= share cannot be written; the platform writes the linear
form, part <= share x total (the mistake it makes impossible: the division written as is, or a part held to
the share itself without the total).
"""

from __future__ import annotations

import copy
from typing import Any

from app.agent.constructs._common import ConstructRefused, bindings, body_object

KEYS = ("share_of_total",)

FIELDS = {
    "for": "where the rule holds (bindings; optional: once)",
    "part": "the part of the mix (a term)",
    "total": "the whole (a term, usually the sum over all the parts)",
    "relation": '"<=" for at most the share, ">=" for at least',
    "share": "the share as a fraction (a number, or a term over a parameter or field)",
}

DESCRIPTION = (
    'share_of_total: a part that is at least, or at most, a share of the whole. Write {"id": ..., '
    '"share_of_total": {"for": [<where it holds>], "part": <the part>, "total": <the whole, a sum over the parts>, '
    '"relation": "<=" or ">=", "share": <the fraction>}}. The platform writes part <= share x total (or >=): '
    'there is no division in a rule, and a share is never compared to the part alone.'
)


def _term(value: Any, what: str) -> dict[str, Any]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return {"const": value}
    if not isinstance(value, dict):
        raise ConstructRefused(f"{what} is a term")
    return copy.deepcopy(value)


def expand(rid: str, body: Any, rule: dict, ir: dict, seed: dict, _kind: str) -> list[dict[str, Any]]:
    body = body_object(body)
    for_ = bindings(body.get("for"), '"for"')
    part = _term(body.get("part"), '"part"')
    total = _term(body.get("total"), '"total" (the whole, usually {"sum": <a part>, "over": [<the parts>]})')
    if "const" in part:
        raise ConstructRefused('"part" is the part of the mix (a term over a decision), not a number')
    relation = body.get("relation")
    if relation not in ("<=", ">="):
        raise ConstructRefused('"relation" is "<=" (at most the share) or ">=" (at least the share)')
    share = body.get("share")
    if isinstance(share, (int, float)) and not isinstance(share, bool) and not 0 <= share <= 1:
        raise ConstructRefused(f'"share" is a fraction between 0 and 1 ({share} is not); 30% is 0.3')
    share = _term(share, '"share" (a fraction such as 0.3, or a parameter)')
    note = rule.get("note") or ("at most a share of the whole" if relation == "<=" else "at least a share of the whole")
    return [{"id": rid, "note": f"{note} (the construct share_of_total: part {relation} share x total)",
             **({"forall": for_} if for_ else {}),
             "left": part, "relation": relation, "right": {"mul": [share, total]}}]


#: The hand-worked example: three parts at 2, 5 and 8 per unit make 10 units in all; the third is at least 30%
#: of the whole, the first at most 50%. The cheapest fills the first to 5, the third to its 3, the second takes
#: the 2 left: 10 + 10 + 24 = 44 (without the shares the first alone would do, 20).
EXAMPLE: dict[str, Any] = {
    "objective": 44,
    "seed": {"entity_types": [{"name": "part", "attributes": [{"name": "cost", "data_type": "number"}]}],
             "entities": [{"type": "part", "key": k, "attrs": {"cost": c}} for k, c in (("p1", 2), ("p2", 5), ("p3", 8))],
             "parameters": [{"name": "needed", "index": [], "default_value": 10}], "parameter_values": []},
    "ir": {"version": 2, "sets": ["part"], "parameters": {"needed": {"index": []}},
           "variables": {"amount": {"index": ["part"], "domain": "continuous", "lower": 0}},
           "constraints": [
               {"id": "c_total", "left": {"sum": {"var": "amount", "index": ["i"]}, "over": [{"index": "i", "set": "part"}]},
                "relation": "=", "right": {"par": "needed", "index": []}, "severity": "hard"},
               {"id": "c_third", "share_of_total": {
                   "part": {"var": "amount", "index": ["p3"]},
                   "total": {"sum": {"var": "amount", "index": ["i"]}, "over": [{"index": "i", "set": "part"}]},
                   "relation": ">=", "share": 0.3}},
               {"id": "c_first", "share_of_total": {
                   "part": {"var": "amount", "index": ["p1"]},
                   "total": {"sum": {"var": "amount", "index": ["i"]}, "over": [{"index": "i", "set": "part"}]},
                   "relation": "<=", "share": 0.5}}],
           "objective": {"sense": "minimize", "terms": [{"id": "o", "weight": 1, "expression": {
               "sum": {"mul": [{"attr": {"of": "i", "name": "cost"}}, {"var": "amount", "index": ["i"]}]},
               "over": [{"index": "i", "set": "part"}]}}]}},
}

#: The mistake written by hand: the share compared to the part alone (amount[p3] >= 0.3, amount[p1] <= 0.5),
#: as a model writes "at least 30%" without the whole -- the first part is capped at 0.5 and the second takes
#: the rest: 2 x 0.5 + 5 x 9.2 + 8 x 0.3 = 49.4.
WRONG: dict[str, Any] = {
    "why": "the share compared to the part alone (amount >= 0.3), the whole left out",
    "objective": 49.4,
    "constraints": [
        {"id": "c_third", "left": {"var": "amount", "index": ["k_p3"]}, "relation": ">=", "right": {"const": 0.3},
         "severity": "hard", "forall": [{"index": "k_p3", "set": "part", "where": [{"attr": "id", "op": "=", "value": "p3"}]}]},
        {"id": "c_first", "left": {"var": "amount", "index": ["k_p1"]}, "relation": "<=", "right": {"const": 0.5},
         "severity": "hard", "forall": [{"index": "k_p1", "set": "part", "where": [{"attr": "id", "op": "=", "value": "p1"}]}]}],
}
