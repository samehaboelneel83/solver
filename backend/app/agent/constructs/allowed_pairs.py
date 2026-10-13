"""allowed_pairs -- an amount only where a 0/1 list of pairs allows it (build-protocol plan, construct 2.2).

    {"id": "c_pairs", "allowed_pairs": {
        "for": [{"index": "r", "set": ...}, {"index": "o", "set": ...}],   the pair's indices; the first is the
                                                                            record a partial list names
        "amount": {"var": "amount", "index": ["r", "o"]},                    what is only there where allowed
        "pairs": {"par": "allowed", "index": ["r", "o"]},                    the list: 1 where the pair is allowed
        "most": term,                                                        the largest the amount can be (optional)
        "partial": true | false}}                                            the reading, when the data should not decide

Two readings of a list, and the data decides between them (the evaluation of 11 October 2026: the one
approved pair typed as allowed = 1 on a default of 1 changed nothing; a partial list flipped to default 0 made
every unlisted record unservable): a list naming every record of the first index is complete -- a pair not
listed is not allowed; a list naming some restricts those alone, and the rest are free. The platform sets the
list's default to 0 and writes amount <= most x allowed[r, o], or for a partial list
amount <= most x (1 - listed[r] + allowed[r, o]) with listed made from the list.
"""

from __future__ import annotations

import copy
from typing import Any

from app.agent.constructs._common import ConstructRefused, bindings, body_object, neg, var

KEYS = ("allowed_pairs",)

FIELDS = {
    "for": "the pair's indices (two or more bindings); the first is the record a partial list names",
    "amount": "the amount that is only there where the pair is allowed (a decision over the pair)",
    "pairs": "the 0/1 list, 1 where the pair is allowed (a parameter over the pair, declared in the seed, its cells "
             "typed or loaded from a file)",
    "most": "the largest the amount can be (a term; optional when the decision declares an upper bound)",
    "partial": "true or false to fix the reading; left out, the data decides: a list naming every record of the "
               "first index is complete, one naming some restricts only those",
}

DESCRIPTION = (
    'allowed_pairs: an amount only where a 0/1 list of pairs allows it. Write {"id": ..., "allowed_pairs": {"for": '
    '[<the record>, <the option>], "amount": <the decision over the pair>, "pairs": <the 0/1 parameter of the '
    'list>, "most": <the largest the amount can be>}}. The data decides the reading: a list that names every '
    'record is complete (a pair not listed is not allowed); a list that names some restricts only those records '
    'to their listed pairs and leaves the rest free. The platform sets the list\'s default to 0, writes amount <= '
    'most x allowed (or, for a partial list, amount <= most x (1 - listed + allowed)) and says which reading it '
    'took; "partial": true or false fixes the reading when the data should not decide.'
)


def expand(rid: str, body: Any, rule: dict, ir: dict, seed: dict, _kind: str) -> list[dict[str, Any]]:
    body = body_object(body)
    for_ = bindings(body.get("for"), '"for"')
    if len(for_) < 2:
        raise ConstructRefused('"for" is the pair\'s bindings: [{"index": "r", "set": ...}, {"index": "o", "set": ...}]')
    amount = var(body.get("amount"), '"amount"')
    pairs = body.get("pairs")
    if not (isinstance(pairs, dict) and isinstance(pairs.get("par"), str)):
        raise ConstructRefused('"pairs" is the 0/1 parameter of the list: {"par": "<name>", "index": ["r", "o"]}')
    name = pairs["par"]
    declared = next((p for p in seed.get("parameters") or [] if isinstance(p, dict) and p.get("name") == name), None)
    if declared is None or not isinstance(declared.get("index"), list):
        raise ConstructRefused(f'the list "{name}" is declared in the seed\'s parameters, over the pair\'s kinds; '
                               "its 0/1 cells are typed there or loaded from a file")
    cells = [v for v in seed.get("parameter_values") or [] if isinstance(v, dict) and v.get("parameter") == name]
    if not cells:
        raise ConstructRefused(f'the list "{name}" has no cells: type the allowed pairs (value 1) or load them from a file')
    r, kind = str(for_[0]["index"]), str(for_[0]["set"])
    if kind not in [str(s) for s in declared["index"]]:
        raise ConstructRefused(f'the list "{name}" is declared over {", ".join(map(str, declared["index"]))}, which does '
                               f'not include "{kind}", the first binding of "for"')
    at = [str(s) for s in declared["index"]].index(kind)
    named = {str(e[at][1]) for v in cells for e in [v.get("entities") or []]
             if len(e) > at and isinstance(e[at], (list, tuple)) and len(e[at]) == 2}
    every = {str(e.get("key")) for e in seed.get("entities") or [] if isinstance(e, dict) and e.get("type") == kind}
    if not every:
        raise ConstructRefused(f'no records of "{kind}" in the plan: load them in the seed')
    if declared.get("default_value") not in (0, None):
        declared["default_value"] = 0  # the list names what is allowed; a pair it does not name is 0
    most = body.get("most")
    if most is None:
        upper = (ir.get("variables") or {}).get(amount["var"]) or {}
        upper = 1 if upper.get("domain") == "binary" else upper.get("upper")
        if not isinstance(upper, (int, float)):
            raise ConstructRefused(f'"most" (the largest the amount can be) is needed: decision {amount["var"]} '
                                   "declares no upper bound")
        most = {"const": upper}
    partial = body["partial"] if isinstance(body.get("partial"), bool) else not (named >= every)
    allowed: Any = copy.deepcopy(pairs)
    if partial:
        listed = f"{rid}_listed"
        seed.setdefault("parameters", []).append({"name": listed, "index": [kind], "default_value": 0})
        seed["parameter_values"] = list(seed.get("parameter_values") or []) + [
            {"parameter": listed, "entities": [[kind, k]], "value": 1} for k in sorted(named)]
        ir.setdefault("parameters", {})[listed] = {"index": [kind]}
        allowed = {"add": [{"const": 1}, neg({"par": listed, "index": [r]}), allowed]}
        reading = (f"the list names {len(named)} of {len(every)} {kind}: those are kept to their listed pairs, "
                   "the others are free")
    else:
        reading = f"the list names every {kind}: a pair not listed is not allowed"
    note = rule.get("note") or "only where the list allows"
    return [{"id": rid,
             "note": f"{note} (the construct allowed_pairs: amount <= most x "
                     + ("(1 - listed + allowed); " if partial else "allowed; ") + reading + ")",
             "forall": for_, "left": amount, "relation": "<=", "right": {"mul": [copy.deepcopy(most), allowed]}}]


#: The hand-worked example (the test and the mutation check both read it): three records, two options, each
#: record takes exactly one option; costs a1 5 / 1, a2 2 / 3, a3 4 / 1 (option o1 / o2); the list names a1
#: alone (a1 -> o1). a1 is held to o1 at 5, a2 and a3 are free (2 + 1): 8.
EXAMPLE: dict[str, Any] = {
    "objective": 8,
    "seed": {"entity_types": [{"name": "record", "attributes": []}, {"name": "option", "attributes": []}],
             "entities": [{"type": "record", "key": k} for k in ("a1", "a2", "a3")]
             + [{"type": "option", "key": o} for o in ("o1", "o2")],
             "parameters": [{"name": "allowed", "index": ["record", "option"], "default_value": 1},
                            {"name": "cost", "index": ["record", "option"], "default_value": 0}],
             "parameter_values": [{"parameter": "cost", "entities": [["record", r], ["option", o]], "value": c}
                                  for r, o, c in (("a1", "o1", 5), ("a1", "o2", 1), ("a2", "o1", 2), ("a2", "o2", 3),
                                                  ("a3", "o1", 4), ("a3", "o2", 1))]
             + [{"parameter": "allowed", "entities": [["record", "a1"], ["option", "o1"]], "value": 1}]},
    "ir": {"version": 2, "sets": ["record", "option"],
           "parameters": {"allowed": {"index": ["record", "option"]}, "cost": {"index": ["record", "option"]}},
           "variables": {"go": {"index": ["record", "option"], "domain": "binary"}},
           "constraints": [{"id": "c_pairs", "allowed_pairs": {
               "for": [{"index": "r", "set": "record"}, {"index": "o", "set": "option"}],
               "amount": {"var": "go", "index": ["r", "o"]}, "pairs": {"par": "allowed", "index": ["r", "o"]}}},
               {"id": "c_one", "exactly_one": {"for": [{"index": "r", "set": "record"}],
                                               "over": [{"index": "o", "set": "option"}],
                                               "pick": {"var": "go", "index": ["r", "o"]}}}],
           "objective": {"sense": "minimize", "terms": [{"id": "o", "weight": 1, "expression": {
               "sum": {"mul": [{"par": "cost", "index": ["r", "o"]}, {"var": "go", "index": ["r", "o"]}]},
               "over": [{"index": "r", "set": "record"}, {"index": "o", "set": "option"}]}}]}},
}

#: The mistake the construct makes impossible, written by hand on the example: the partial list kept on its
#: default of 1 (go <= allowed, every pair allowed by default), which changes nothing -- the goal would be 4.
WRONG: dict[str, Any] = {
    "why": "a partial list on a default of 1, written by hand as amount <= allowed, changes nothing",
    "objective": 4,
    "constraints": [{"id": "c_pairs", "forall": [{"index": "r", "set": "record"}, {"index": "o", "set": "option"}],
                     "left": {"var": "go", "index": ["r", "o"]}, "relation": "<=",
                     "right": {"par": "allowed", "index": ["r", "o"]}, "severity": "hard"}],
}
