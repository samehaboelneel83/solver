"""covering -- every requirement met by at least one chosen option (build-protocol plan, construct 2.5).

    {"id": "c_cover", "covering": {
        "for": {"index": "n", "set": "need"},                 each requirement (bindings)
        "options": {"index": "o", "set": "option"},           the options that could cover it (one binding)
        "covers": {"par": "covers", "index": ["o", "n"]}      1 where option o covers requirement n
               | {"rel": "covers"},                            or the relationship linking an option to what it covers
        "chosen": {"var": "open", "index": ["o"]},            whether option o is chosen
        "at_least": term}}                                     how many chosen options must cover it (optional: 1)

The platform writes, for every requirement: the sum over the options of covers x chosen >= at_least (with a
relationship, the sum over the options linked to it of chosen).
"""

from __future__ import annotations

import copy
from typing import Any

from app.agent.constructs._common import ConstructRefused, bindings, body_object, var

KEYS = ("covering",)

FIELDS = {
    "for": "each requirement (bindings)",
    "options": 'the options that could cover it: one binding {"index": "o", "set": <the options\' kind>}',
    "covers": 'which option covers which requirement: a 0/1 parameter {"par": ..., "index": ["o", "n"]} or a '
              'relationship from the option to what it covers {"rel": ...}',
    "chosen": "whether an option is chosen (a yes/no decision over the options)",
    "at_least": "how many chosen options must cover each requirement (a term; optional: 1)",
}

DESCRIPTION = (
    'covering: every requirement met by at least one chosen option. Write {"id": ..., "covering": {"for": '
    '[<each requirement>], "options": {"index": "o", "set": <the options\' kind>}, "covers": <a 0/1 parameter over '
    '(option, requirement) or {"rel": <the relationship from an option to what it covers>}>, "chosen": <whether '
    'an option is chosen>, "at_least": <how many, optional: 1>}}. The platform writes, for every requirement, '
    'the sum over the options that cover it of chosen >= at_least.'
)


def expand(rid: str, body: Any, rule: dict, ir: dict, seed: dict, _kind: str) -> list[dict[str, Any]]:
    body = body_object(body)
    for_ = bindings(body.get("for"), '"for"')
    if not for_:
        raise ConstructRefused('"for" names each requirement: [{"index": "n", "set": "<the requirements\' kind>"}]')
    options = bindings(body.get("options"), '"options"')
    if len(options) != 1:
        raise ConstructRefused('"options" is one binding: {"index": "o", "set": "<the options\' kind>"}')
    chosen = var(body.get("chosen"), '"chosen"')
    covers = body.get("covers")
    n = str(for_[-1]["index"])
    o = str(options[0]["index"])
    at_least = body.get("at_least")
    at_least = {"const": 1} if at_least is None else (
        {"const": at_least} if isinstance(at_least, (int, float)) and not isinstance(at_least, bool) else at_least)
    if isinstance(covers, dict) and isinstance(covers.get("rel"), str):
        rel = covers["rel"]
        if rel not in [str(r) for r in ir.get("relationships") or []]:
            raise ConstructRefused(f'"covers" names the relationship "{rel}", which the model does not list in '
                                   '"relationships" (declare it there and in the seed\'s relationship_types)')
        over = [{**options[0], "via": {"rel": rel, "to": n}}]
        left: Any = {"sum": copy.deepcopy(chosen), "over": over}
        how = f'the options linked to it by "{rel}"'
    elif isinstance(covers, dict) and isinstance(covers.get("par"), str):
        left = {"sum": {"mul": [copy.deepcopy(covers), copy.deepcopy(chosen)]}, "over": options}
        how = f'covers x chosen over the options ("{covers["par"]}" 1 where the option covers it)'
    else:
        raise ConstructRefused('"covers" is a 0/1 parameter {"par": ..., "index": ["o", "n"]} (1 where option o '
                               'covers requirement n) or a relationship {"rel": ...} from the option to what it covers')
    note = rule.get("note") or "every requirement covered"
    return [{"id": rid, "note": f"{note} (the construct covering: for every {n}, the sum of {how} >= "
                                + (str(at_least["const"]) if "const" in at_least else "at_least") + ")",
             "forall": for_, "left": left, "relation": ">=", "right": at_least}]


#: The hand-worked example: four requirements, three options; o1 covers n1 and n2 (cost 3), o2 covers n2, n3
#: and n4 (cost 4), o3 covers n1 and n4 (cost 3). o1 + o3 leaves n3 uncovered, so o2 is in every cover; with
#: o1 or o3 it costs 7.
EXAMPLE: dict[str, Any] = {
    "objective": 7,
    "seed": {"entity_types": [{"name": "need", "attributes": []},
                              {"name": "option", "attributes": [{"name": "cost", "data_type": "number"}]}],
             "entities": [{"type": "need", "key": k} for k in ("n1", "n2", "n3", "n4")]
             + [{"type": "option", "key": o, "attrs": {"cost": c}} for o, c in (("o1", 3), ("o2", 4), ("o3", 3))],
             "parameters": [{"name": "covers", "index": ["option", "need"], "default_value": 0}],
             "parameter_values": [{"parameter": "covers", "entities": [["option", o], ["need", k]], "value": 1}
                                  for o, k in (("o1", "n1"), ("o1", "n2"), ("o2", "n2"), ("o2", "n3"), ("o2", "n4"),
                                               ("o3", "n1"), ("o3", "n4"))]},
    "ir": {"version": 2, "sets": ["need", "option"], "parameters": {"covers": {"index": ["option", "need"]}},
           "variables": {"open": {"index": ["option"], "domain": "binary"}},
           "constraints": [{"id": "c_cover", "covering": {
               "for": [{"index": "n", "set": "need"}], "options": {"index": "o", "set": "option"},
               "covers": {"par": "covers", "index": ["o", "n"]}, "chosen": {"var": "open", "index": ["o"]}}}],
           "objective": {"sense": "minimize", "terms": [{"id": "o", "weight": 1, "expression": {
               "sum": {"mul": [{"attr": {"of": "o", "name": "cost"}}, {"var": "open", "index": ["o"]}]},
               "over": [{"index": "o", "set": "option"}]}}]}},
}

#: The mistake written by hand: the cover per pair, chosen[o] >= covers[o, n] for every option and requirement,
#: which makes every option that covers anything chosen -- all three, 10.
WRONG: dict[str, Any] = {
    "why": "the cover written per pair (chosen >= covers for every option and requirement) chooses every covering option",
    "objective": 10,
    "constraints": [{"id": "c_cover", "forall": [{"index": "o", "set": "option"}, {"index": "n", "set": "need"}],
                     "left": {"var": "open", "index": ["o"]}, "relation": ">=",
                     "right": {"par": "covers", "index": ["o", "n"]}, "severity": "hard"}],
}
