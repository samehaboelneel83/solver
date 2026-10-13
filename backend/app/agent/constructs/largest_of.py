"""largest_of -- overlapping effects: the best chosen option counts, they do not add up (construct 2.3).

    {"id": "c_best", "largest_of": {"for": [bindings], "level": {"var": ...}, "options": binding,
        "value": term, "chosen": {"var": ...}}}

The level is the largest value among the chosen options. The platform makes the `_best` binaries and the
three rules; the mistake it makes impossible: level >= value x pick, which adds the effects up.
"""

from __future__ import annotations

import copy
from typing import Any

from app.agent.constructs._common import ConstructRefused, bindings, body_object, var

KEYS = ("largest_of",)

FIELDS = {
    "for": "the indices the level is decided for (bindings; optional)",
    "level": "the level reached (a decision)",
    "options": 'the options that could give it: one binding {"index": "o", "set": <the options\' kind>}',
    "value": "what option o gives (a term over a parameter or field, not a decision)",
    "chosen": "whether option o is chosen (a yes/no decision)",
}

DESCRIPTION = (
    'largest_of: a level that is the best of the chosen options, when their effects overlap and do not add up. '
    'Write {"id": ..., "largest_of": {"for": [<the indices>], "level": <the decision>, "options": {"index": "o", '
    '"set": <the options\' kind>}, "value": <what option o gives>, "chosen": <whether o is chosen>}}. The '
    'platform makes a yes/no decision per option for the one that counts, and writes: the level is at most the '
    'value of the counted option, at most one option is counted, an option counts only if it is chosen.'
)


def expand(rid: str, body: Any, rule: dict, ir: dict, seed: dict, _kind: str) -> list[dict[str, Any]]:
    body = body_object(body)
    for_ = bindings(body.get("for"), '"for"')
    options = bindings(body.get("options"), '"options"')
    if len(options) != 1:
        raise ConstructRefused('"options" is one binding: {"index": "o", "set": "<the options\' kind>"}')
    level = var(body.get("level"), '"level"')
    chosen = var(body.get("chosen"), '"chosen"')
    value = body.get("value")
    if not isinstance(value, dict):
        raise ConstructRefused('"value" is a term: what option o gives (a parameter or field, not a decision)')
    o = options[0]["index"]
    best = f"{rid}_best"
    index = [options[0]["set"]] + [b["set"] for b in for_]
    ir.setdefault("variables", {})[best] = {"index": index, "domain": "binary"}
    cell = {"var": best, "index": [o] + [b["index"] for b in for_]}
    note = rule.get("note") or "the largest of the chosen options"
    return [
        {"id": rid, "note": f"{note} (the idiom largest_of: the level is at most the value of the one option counted)",
         **({"forall": for_} if for_ else {}), "left": level, "relation": "<=",
         "right": {"sum": {"mul": [copy.deepcopy(value), cell]}, "over": options}},
        {"id": f"{rid}_one", "note": "one option counted at most",
         **({"forall": copy.deepcopy(for_)} if for_ else {}),
         "left": {"sum": copy.deepcopy(cell), "over": copy.deepcopy(options)}, "relation": "<=", "right": {"const": 1}},
        {"id": f"{rid}_chosen", "note": "an option counts only if it is chosen",
         "forall": copy.deepcopy(for_) + copy.deepcopy(options), "left": copy.deepcopy(cell), "relation": "<=",
         "right": chosen},
    ]


#: The hand-worked example: two options protect the same thing at 60 and 50, each costing 10. Chosen both, the
#: level is 60, not 110; the best is the first alone: 60 - 10 = 50.
EXAMPLE: dict[str, Any] = {
    "objective": 50,
    "seed": {"entity_types": [{"name": "option", "attributes": []}, {"name": "thing", "attributes": []}],
             "entities": [{"type": "option", "key": "o1"}, {"type": "option", "key": "o2"}, {"type": "thing", "key": "a1"}],
             "parameters": [{"name": "gives", "index": ["option", "thing"], "default_value": 0}],
             "parameter_values": [{"parameter": "gives", "entities": [["option", "o1"], ["thing", "a1"]], "value": 60},
                                  {"parameter": "gives", "entities": [["option", "o2"], ["thing", "a1"]], "value": 50}]},
    "ir": {"version": 2, "sets": ["option", "thing"], "parameters": {"gives": {"index": ["option", "thing"]}},
           "variables": {"pick": {"index": ["option"], "domain": "binary"},
                         "level": {"index": ["thing"], "domain": "continuous", "lower": 0, "upper": 100}},
           "constraints": [{"id": "c_level", "largest_of": {
               "for": [{"index": "a", "set": "thing"}], "level": {"var": "level", "index": ["a"]},
               "options": {"index": "o", "set": "option"}, "value": {"par": "gives", "index": ["o", "a"]},
               "chosen": {"var": "pick", "index": ["o"]}}}],
           "objective": {"sense": "maximize", "terms": [{"id": "o", "weight": 1, "expression": {"add": [
               {"sum": {"var": "level", "index": ["a"]}, "over": [{"index": "a", "set": "thing"}]},
               {"sum": {"mul": [{"const": -10}, {"var": "pick", "index": ["o"]}]}, "over": [{"index": "o", "set": "option"}]}]}}]}},
}

#: The mistake written by hand: level >= value x pick for every option, which holds the level down by nothing:
#: the level goes to its bound of 100 with no option chosen (100).
WRONG: dict[str, Any] = {
    "why": "level >= value x pick for every option: the level is free upward, nothing need be chosen",
    "objective": 100,
    "constraints": [{"id": "c_level", "forall": [{"index": "a", "set": "thing"}, {"index": "o", "set": "option"}],
                     "left": {"var": "level", "index": ["a"]}, "relation": ">=",
                     "right": {"mul": [{"par": "gives", "index": ["o", "a"]}, {"var": "pick", "index": ["o"]}]},
                     "severity": "hard"}],
}
