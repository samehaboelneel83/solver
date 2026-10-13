"""used_only_where_given -- a decision kept to the pairs a parameter has a value for (construct 2.9).

    {"id": "c_given", "used_only_where_given": {
        "for": [{"index": "r", "set": ...}, {"index": "o", "set": ...}],   the pair's indices
        "amount": {"var": "amount", "index": ["r", "o"]},                    what is only there where given
        "given": {"par": "rate", "index": ["r", "o"]},                       the parameter whose cells say where
        "most": term}}                                                       the largest the amount can be (optional)

The mistake it makes impossible (the evaluation of 11 October 2026: a rate given for some pairs, the amount
free on the others at the default of 0, so the cheapest plan used what had no rate): the platform makes a 0/1
parameter that is 1 exactly where the given parameter has a cell, and writes amount <= most x that.
"""

from __future__ import annotations

import copy
from typing import Any

from app.agent.constructs._common import ConstructRefused, bindings, body_object, var

KEYS = ("used_only_where_given",)

FIELDS = {
    "for": "the pair's indices (bindings)",
    "amount": "the amount that is only there where the parameter is given (a decision over the pair)",
    "given": "the parameter whose cells say where (read with the same indices as the amount)",
    "most": "the largest the amount can be (a term; optional when the decision declares an upper bound)",
}

DESCRIPTION = (
    'used_only_where_given: a decision kept to the pairs a parameter has a value for. Write {"id": ..., '
    '"used_only_where_given": {"for": [<the pair\'s indices>], "amount": <the decision over the pair>, "given": '
    '<the parameter read over the pair>, "most": <the largest the amount can be>}}. The platform makes a 0/1 '
    'parameter that is 1 exactly where the given parameter has a cell and writes amount <= most x that, so a '
    'pair with no value is never used.'
)


def expand(rid: str, body: Any, rule: dict, ir: dict, seed: dict, _kind: str) -> list[dict[str, Any]]:
    body = body_object(body)
    for_ = bindings(body.get("for"), '"for"')
    if not for_:
        raise ConstructRefused('"for" is the pair\'s bindings: [{"index": "r", "set": ...}, {"index": "o", "set": ...}]')
    amount = var(body.get("amount"), '"amount"')
    given = body.get("given")
    if not (isinstance(given, dict) and isinstance(given.get("par"), str) and isinstance(given.get("index"), list)):
        raise ConstructRefused('"given" is the parameter read over the pair: {"par": "<name>", "index": ["r", "o"]}')
    name = given["par"]
    declared = next((p for p in seed.get("parameters") or [] if isinstance(p, dict) and p.get("name") == name), None)
    if declared is None or not isinstance(declared.get("index"), list) or not declared["index"]:
        raise ConstructRefused(f'"{name}" is declared in the seed\'s parameters over the pair\'s kinds, with its cells '
                               "typed there or loaded from a file")
    if len(given["index"]) != len(declared["index"]):
        raise ConstructRefused(f'"{name}" is declared over {len(declared["index"])} kind(s), so "given" reads it with '
                               "that many indices")
    cells = [v for v in seed.get("parameter_values") or [] if isinstance(v, dict) and v.get("parameter") == name]
    if not cells:
        raise ConstructRefused(f'"{name}" has no cells: type its values or load them from a file')
    most = body.get("most")
    if most is None:
        upper = (ir.get("variables") or {}).get(amount["var"]) or {}
        upper = 1 if upper.get("domain") == "binary" else upper.get("upper")
        if not isinstance(upper, (int, float)):
            raise ConstructRefused(f'"most" (the largest the amount can be) is needed: decision {amount["var"]} '
                                   "declares no upper bound")
        most = {"const": upper}
    flag = f"{rid}_given"
    seen: set[str] = set()
    flags = []
    for v in cells:
        entities = [list(e) for e in v.get("entities") or [] if isinstance(e, (list, tuple)) and len(e) == 2]
        key = repr(entities)
        if len(entities) == len(declared["index"]) and key not in seen:
            seen.add(key)
            flags.append({"parameter": flag, "entities": entities, "value": 1})
    seed.setdefault("parameters", []).append({"name": flag, "index": list(declared["index"]), "default_value": 0})
    seed["parameter_values"] = list(seed.get("parameter_values") or []) + flags
    ir.setdefault("parameters", {})[flag] = {"index": list(declared["index"])}
    note = rule.get("note") or f"only where {name} is given"
    return [{"id": rid,
             "note": f"{note} (the construct used_only_where_given: amount <= most x {flag}, which is 1 for the "
                     f"{len(flags)} cell(s) {name} has)",
             "forall": for_, "left": amount, "relation": "<=",
             "right": {"mul": [copy.deepcopy(most), {"par": flag, "index": list(given["index"])}]}}]


#: The hand-worked example: two records each needing 10 units from three options of 8 each; a rate is given
#: for r1 on o1 (2) and o2 (3), and for r2 on o2 (1) and o3 (4). r1 and r2 share o2: r1 takes 2 of it, r2 takes
#: 6: (8 x 2 + 2 x 3) + (6 x 1 + 4 x 4) = 44.
EXAMPLE: dict[str, Any] = {
    "objective": 44,
    "seed": {"entity_types": [{"name": "record", "attributes": [{"name": "needed", "data_type": "number"}]},
                              {"name": "option", "attributes": [{"name": "most", "data_type": "number"}]}],
             "entities": [{"type": "record", "key": r, "attrs": {"needed": 10}} for r in ("r1", "r2")]
             + [{"type": "option", "key": o, "attrs": {"most": 8}} for o in ("o1", "o2", "o3")],
             "parameters": [{"name": "rate", "index": ["record", "option"], "default_value": 0}],
             "parameter_values": [{"parameter": "rate", "entities": [["record", r], ["option", o]], "value": c}
                                  for r, o, c in (("r1", "o1", 2), ("r1", "o2", 3), ("r2", "o2", 1), ("r2", "o3", 4))]},
    "ir": {"version": 2, "sets": ["record", "option"], "parameters": {"rate": {"index": ["record", "option"]}},
           "variables": {"amount": {"index": ["record", "option"], "domain": "continuous", "lower": 0, "upper": 10}},
           "constraints": [
               {"id": "c_need", "forall": [{"index": "r", "set": "record"}],
                "left": {"sum": {"var": "amount", "index": ["r", "o"]}, "over": [{"index": "o", "set": "option"}]},
                "relation": "=", "right": {"attr": {"of": "r", "name": "needed"}}, "severity": "hard"},
               {"id": "c_most", "forall": [{"index": "o", "set": "option"}],
                "left": {"sum": {"var": "amount", "index": ["r", "o"]}, "over": [{"index": "r", "set": "record"}]},
                "relation": "<=", "right": {"attr": {"of": "o", "name": "most"}}, "severity": "hard"},
               {"id": "c_given", "used_only_where_given": {
                   "for": [{"index": "r", "set": "record"}, {"index": "o", "set": "option"}],
                   "amount": {"var": "amount", "index": ["r", "o"]}, "given": {"par": "rate", "index": ["r", "o"]}}}],
           "objective": {"sense": "minimize", "terms": [{"id": "o", "weight": 1, "expression": {
               "sum": {"mul": [{"par": "rate", "index": ["r", "o"]}, {"var": "amount", "index": ["r", "o"]}]},
               "over": [{"index": "r", "set": "record"}, {"index": "o", "set": "option"}]}}]}},
}

#: The mistake written by hand: no rule at all -- the amount free where the rate has no cell, at the default
#: rate of 0, so the cheapest plan uses exactly those pairs: 0.
WRONG: dict[str, Any] = {
    "why": "no rule: the amount free where the rate has no cell, at the default of 0",
    "objective": 0,
    "constraints": [{"id": "c_given", "forall": [{"index": "r", "set": "record"}],
                     "left": {"const": 0}, "relation": "<=", "right": {"const": 1}, "severity": "hard"}],
}
