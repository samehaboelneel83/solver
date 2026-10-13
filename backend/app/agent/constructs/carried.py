"""carried -- a quantity carried from one period to the next (build-protocol plan, construct 2.1).

    {"id": "c_bal", "carried": {
        "periods": {"index": "t", "set": "period", "by": "#row" | <ordering field>},
        "for": [bindings],                              the other indices (optional)
        "level": {"var": "left", "index": [..., "t"]},  what is left at the end of t
        "in": [terms], "out": [terms],                  what comes in and goes out during t
        "initial": term,                                the starting amount: counted in the FIRST period only
        "owed": {"var": "owed", "index": [..., "t"]}}}  still owed at the end of t (optional)

The mistake it makes impossible (the Nile Juice trace): the starting amount counted in every period.
"""

from __future__ import annotations

import copy
from typing import Any

from app.agent.constructs._common import ConstructRefused, add, bindings, body_object, neg, renamed, var

KEYS = ("carried",)

FIELDS = {
    "periods": 'the periods in order: {"index": "t", "set": "<the periods\' kind>", "by": "#row" or an ordering field}',
    "for": "the other indices the balance holds for (bindings; optional)",
    "level": "what is left at the end of each period (a decision read with the period's index)",
    "in": "what comes in during the period (terms)",
    "out": "what goes out during the period (terms)",
    "initial": "the starting amount, counted in the first period only (a term; optional)",
    "owed": "what is still owed at the end of the period (a decision; optional)",
}

DESCRIPTION = (
    'carried: a quantity carried from one period to the next. Write {"id": ..., "carried": {"periods": {"index": '
    '"t", "set": <the periods\' kind>, "by": "#row" or an ordering field}, "level": <what is left at the end of '
    't>, "in": [<what comes in>], "out": [<what goes out>], "initial": <the starting amount>, "owed": <what is '
    'still owed, optional>}}. The platform makes the period links, finds the first period, counts the starting '
    'amount there only and writes the balance: what was left before + in + the starting amount (first period) = '
    'out + what is left - what is owed.'
)


def expand(rid: str, body: Any, rule: dict, ir: dict, seed: dict, _kind: str) -> tuple[list[dict[str, Any]], list[str]]:
    from app.seed import order_links

    body = body_object(body)
    periods = body.get("periods")
    if not (isinstance(periods, dict) and periods.get("index") and periods.get("set")):
        raise ConstructRefused('"periods" is {"index": "t", "set": "<the periods\' kind>", "by": "#row" or a field}')
    t, kind, by = str(periods["index"]), str(periods["set"]), periods.get("by") or "#row"
    level = var(body.get("level"), '"level"')
    owed = var(body["owed"], '"owed"') if body.get("owed") is not None else None
    for_ = bindings(body.get("for"), '"for"')
    ins = body.get("in") or []
    outs = body.get("out") or []
    ins = [ins] if isinstance(ins, dict) else list(ins)
    outs = [outs] if isinstance(outs, dict) else list(outs)
    said: list[str] = []
    for term in ins:
        # A bare number among what comes in is counted in every period (the Nile Juice mistake: the amount on
        # hand at the start written as an inflow). Said, not refused: a fixed inflow every period is a real thing.
        if isinstance(term, dict) and set(term) == {"const"}:
            said.append(f'the number {term["const"]} in "in" is counted in EVERY period; if it is the amount on '
                        'hand at the start, write it as "initial" (counted in the first period only)')
    rel = f"{rid}_next"
    first = f"{rid}_first"
    # The periods in order, linked; the first one is the one nothing comes before.
    types = seed.setdefault("relationship_types", [])
    if not any(isinstance(r, dict) and r.get("name") == rel for r in types):
        types.append({"name": rel, "from": kind, "to": kind, "cardinality": "one_to_one"})
    linked = order_links({"entities": seed.get("entities") or [],
                          "relationships_in_order": [{"type": rel, "of": kind, "by": by}]})
    links = [r for r in linked.get("relationships") or [] if r.get("type") == rel]
    members = [str(e.get("key")) for e in seed.get("entities") or [] if isinstance(e, dict) and e.get("type") == kind]
    if not members:
        raise ConstructRefused(f'no records of "{kind}" in the plan to put in order: load them in the seed')
    if not links and len(members) > 1:
        raise ConstructRefused(f'the "{kind}" records could not be put in order by {by!r}: give an ordering field they all have, or "#row"')
    seed["relationships"] = list(seed.get("relationships") or []) + links
    has_before = {r["to"][1] for r in links}
    starts = [k for k in members if k not in has_before]
    rels = ir.setdefault("relationships", [])
    if rel not in rels:
        rels.append(rel)
    initial = body.get("initial")
    in_terms = list(ins)
    if initial is not None:
        seed.setdefault("parameters", []).append({"name": first, "index": [kind], "default_value": 0})
        seed["parameter_values"] = list(seed.get("parameter_values") or []) + [
            {"parameter": first, "entities": [[kind, k]], "value": 1} for k in starts]
        ir.setdefault("parameters", {})[first] = {"index": [kind]}
        in_terms.append({"mul": [copy.deepcopy(initial), {"par": first, "index": [t]}]})
    prev = f"{t}_before"
    before = add([renamed(level, t, prev)] + ([neg(renamed(owed, t, prev))] if owed else []))
    left = add([{"sum": before, "over": [{"index": prev, "set": kind, "via": {"rel": rel, "to": t}}]}] + in_terms)
    right = add(list(outs) + [level] + ([neg(owed)] if owed else []))
    note = rule.get("note") or "a quantity carried from one period to the next"
    return [{"id": rid, "note": f"{note} (the idiom carried: what was left before + in"
                                + (" + the starting amount, first period only" if initial is not None else "")
                                + " = out + what is left)",
             "forall": for_ + [{"index": t, "set": kind}], "left": left, "relation": "=", "right": right}], said


#: The hand-worked example: demand 5, 7, 4 over three periods; 3 on hand at the start; at most 6 made a period
#: at 1 each; 2 to carry one over a period. Period 2 needs 7 > 6, so 1 is made early and carried: 13 made +
#: 2 carrying = 15. Counting the 3 in every period (the Nile Juice mistake) would make it 7.
EXAMPLE: dict[str, Any] = {
    "objective": 15,
    "seed": {"entity_types": [{"name": "period", "attributes": [{"name": "demand", "data_type": "number"}]}],
             "entities": [{"type": "period", "key": k, "attrs": {"demand": d}} for k, d in (("t1", 5), ("t2", 7), ("t3", 4))]},
    "ir": {"version": 2, "sets": ["period"], "parameters": {},
           "variables": {"make": {"index": ["period"], "domain": "continuous", "lower": 0, "upper": 6},
                         "left": {"index": ["period"], "domain": "continuous", "lower": 0}},
           "constraints": [{"id": "c_balance", "carried": {
               "periods": {"index": "t", "set": "period", "by": "#row"},
               "level": {"var": "left", "index": ["t"]}, "in": [{"var": "make", "index": ["t"]}],
               "out": [{"attr": {"of": "t", "name": "demand"}}], "initial": {"const": 3}}}],
           "objective": {"sense": "minimize", "terms": [{"id": "o", "weight": 1, "expression": {"add": [
               {"sum": {"var": "make", "index": ["t"]}, "over": [{"index": "t", "set": "period"}]},
               {"sum": {"mul": [{"const": 2}, {"var": "left", "index": ["t"]}]}, "over": [{"index": "t", "set": "period"}]}]}}]}},
}

#: The mistake: the starting amount written among what comes in, so it is counted in every period (7).
WRONG: dict[str, Any] = {
    "why": "the starting amount written in \"in\", counted in every period",
    "objective": 7,
    "constraints": [{"id": "c_balance", "carried": {
        "periods": {"index": "t", "set": "period", "by": "#row"},
        "level": {"var": "left", "index": ["t"]}, "in": [{"var": "make", "index": ["t"]}, {"const": 3}],
        "out": [{"attr": {"of": "t", "name": "demand"}}]}}],
}
