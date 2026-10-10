"""Modelling idioms the Assistant fills in instead of writing by hand (neutrality plan, step 3).

A rule in the spec may be one of these compact objects instead of `left`/`relation`/`right`; before the spec is
checked it is expanded here into ordinary rules (and the seed parts they need), so the contract, the validators and
the solvers see nothing new, and the plan card shows the rules it became. Each idiom has one way to be written, the
right one: the mistakes the phase 1 evaluation found by hand-written rules cannot be expressed.

    {"id": "c_bal", "carried": {                       a quantity carried from one period to the next
        "periods": {"index": "t", "set": "period", "by": "#row" | <ordering field>},
        "for": [bindings],                              the other indices (optional)
        "level": {"var": "left", "index": [..., "t"]},  what is left at the end of t
        "in": [terms], "out": [terms],                  what comes in and goes out during t
        "initial": term,                                the starting amount: counted in the FIRST period only
        "owed": {"var": "owed", "index": [..., "t"]}}}  still owed at the end of t (optional)
    {"id": "c_x", "only_if": {"for": [bindings], "amount": {"var": ...}, "chosen": {"var"|"par": ...}, "most": term}}
        amount <= most x chosen; `most` defaults to the amount's declared upper bound. With "chosen" a 0/1
        parameter (pairs a file allows), it keeps every pair the file does not allow at 0.
    {"id": "c_best", "largest_of": {"for": [bindings], "level": {"var": ...}, "options": binding,
        "value": term, "chosen": {"var": ...}}}
        the level is the largest value among the chosen options -- effects that overlap and do not add up.
    {"id": "c_one", "at_most_one" | "exactly_one": {"for": [bindings], "over": [bindings], "pick": {"var": ...}}}
"""

from __future__ import annotations

import copy
from typing import Any

IDIOMS = ("carried", "only_if", "largest_of", "at_most_one", "exactly_one")


from app.agent.files import FileRefused


class IdiomRefused(FileRefused):
    """An idiom written so that it cannot be expanded: the message says what to write (a refusal like a file's)."""


def _bindings(value: Any, what: str) -> list[dict[str, Any]]:
    if value in (None, []):
        return []
    value = [value] if isinstance(value, dict) else value
    if not isinstance(value, list) or not all(isinstance(b, dict) and b.get("index") and b.get("set") for b in value):
        raise IdiomRefused(f'{what} is a list of bindings like {{"index": "k", "set": "<record kind>"}}')
    return copy.deepcopy(value)


def _var(value: Any, what: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("var"), str):
        raise IdiomRefused(f'{what} is a decision: {{"var": "<name>", "index": [...]}}')
    return copy.deepcopy(value)


def _renamed(term: Any, old: str, new: str) -> Any:
    """The term with index `old` read as `new` (the period before)."""
    if isinstance(term, dict):
        out = {}
        for k, v in term.items():
            if k == "index" and isinstance(v, list):
                out[k] = [new if x == old else x for x in v]
            elif k == "of" and v == old:
                out[k] = new
            else:
                out[k] = _renamed(v, old, new)
        return out
    if isinstance(term, list):
        return [_renamed(v, old, new) for v in term]
    return term


def _add(terms: list[Any]) -> Any:
    terms = [t for t in terms if t is not None]
    if not terms:
        return {"const": 0}
    return terms[0] if len(terms) == 1 else {"add": terms}


def _neg(term: Any) -> Any:
    return {"mul": [{"const": -1}, term]}


def expand(spec: dict[str, Any]) -> list[str]:
    """Every idiom rule of the spec's IR replaced by the rules it stands for, in place; returns notes."""
    ir = spec.get("ir")
    if not isinstance(ir, dict) or not isinstance(ir.get("constraints"), list):
        return []
    if not isinstance(spec.get("seed"), dict):
        spec["seed"] = {}
    seed = spec["seed"]
    out: list[Any] = []
    notes: list[str] = []
    for rule in ir["constraints"]:
        kind = next((k for k in IDIOMS if isinstance(rule, dict) and k in rule), None)
        if kind is None:
            out.append(rule)
            continue
        rid = str(rule.get("id") or f"c_{kind}")
        try:
            made = {"carried": _carried, "only_if": _only_if, "largest_of": _largest_of,
                    "at_most_one": _one, "exactly_one": _one}[kind](rid, rule[kind], rule, ir, seed, kind)
        except IdiomRefused as exc:
            raise IdiomRefused(f'rule {rid} ("{kind}"): {exc}') from None
        for r in made:
            r.setdefault("severity", rule.get("severity", "hard"))
            if rule.get("severity") == "soft" and "weight" in rule:
                r.setdefault("weight", rule["weight"])
        out.extend(made)
        notes.append(f'rule {rid} written as the idiom "{kind}" became {", ".join(r["id"] for r in made)}')
    ir["constraints"] = out
    return notes


def _carried(rid: str, body: Any, rule: dict, ir: dict, seed: dict, _kind: str) -> list[dict[str, Any]]:
    from app.seed import order_links

    if not isinstance(body, dict):
        raise IdiomRefused("write it as an object")
    periods = body.get("periods")
    if not (isinstance(periods, dict) and periods.get("index") and periods.get("set")):
        raise IdiomRefused('"periods" is {"index": "t", "set": "<the periods\' kind>", "by": "#row" or a field}')
    t, kind, by = str(periods["index"]), str(periods["set"]), periods.get("by") or "#row"
    level = _var(body.get("level"), '"level"')
    owed = _var(body["owed"], '"owed"') if body.get("owed") is not None else None
    for_ = _bindings(body.get("for"), '"for"')
    ins = body.get("in") or []
    outs = body.get("out") or []
    ins = [ins] if isinstance(ins, dict) else list(ins)
    outs = [outs] if isinstance(outs, dict) else list(outs)
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
        raise IdiomRefused(f'no records of "{kind}" in the plan to put in order: load them in the seed')
    if not links and len(members) > 1:
        raise IdiomRefused(f'the "{kind}" records could not be put in order by {by!r}: give an ordering field they all have, or "#row"')
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
    before = _add([_renamed(level, t, prev)] + ([_neg(_renamed(owed, t, prev))] if owed else []))
    left = _add([{"sum": before, "over": [{"index": prev, "set": kind, "via": {"rel": rel, "to": t}}]}] + in_terms)
    right = _add(list(outs) + [level] + ([_neg(owed)] if owed else []))
    note = rule.get("note") or "a quantity carried from one period to the next"
    return [{"id": rid, "note": f"{note} (the idiom carried: what was left before + in"
                                + (" + the starting amount, first period only" if initial is not None else "")
                                + " = out + what is left)",
             "forall": for_ + [{"index": t, "set": kind}], "left": left, "relation": "=", "right": right}]


def _only_if(rid: str, body: Any, rule: dict, ir: dict, seed: dict, _kind: str) -> list[dict[str, Any]]:
    if not isinstance(body, dict):
        raise IdiomRefused("write it as an object")
    amount = _var(body.get("amount"), '"amount"')
    chosen = body.get("chosen")
    if not (isinstance(chosen, dict) and (isinstance(chosen.get("var"), str) or isinstance(chosen.get("par"), str))):
        raise IdiomRefused('"chosen" is a yes/no decision {"var": ...} or a 0/1 parameter {"par": ...}')
    most = body.get("most")
    if most is None:
        declared = (ir.get("variables") or {}).get(amount["var"]) or {}
        upper = 1 if declared.get("domain") == "binary" else declared.get("upper")
        if not isinstance(upper, (int, float)):
            raise IdiomRefused(f'"most" (the largest the amount can be) is needed: decision {amount["var"]} '
                               "declares no upper bound")
        most = {"const": upper}
    note = rule.get("note") or "only if chosen"
    return [{"id": rid, "note": f"{note} (the idiom only_if: amount <= most x chosen)",
             **({"forall": _bindings(body.get("for"), '"for"')} if body.get("for") else {}),
             "left": amount, "relation": "<=", "right": {"mul": [copy.deepcopy(most), copy.deepcopy(chosen)]}}]


def _largest_of(rid: str, body: Any, rule: dict, ir: dict, seed: dict, _kind: str) -> list[dict[str, Any]]:
    if not isinstance(body, dict):
        raise IdiomRefused("write it as an object")
    for_ = _bindings(body.get("for"), '"for"')
    options = _bindings(body.get("options"), '"options"')
    if len(options) != 1:
        raise IdiomRefused('"options" is one binding: {"index": "o", "set": "<the options\' kind>"}')
    level = _var(body.get("level"), '"level"')
    chosen = _var(body.get("chosen"), '"chosen"')
    value = body.get("value")
    if not isinstance(value, dict):
        raise IdiomRefused('"value" is a term: what option o gives (a parameter or field, not a decision)')
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


def _one(rid: str, body: Any, rule: dict, ir: dict, seed: dict, kind: str) -> list[dict[str, Any]]:
    if not isinstance(body, dict):
        raise IdiomRefused("write it as an object")
    over = _bindings(body.get("over"), '"over"')
    if not over:
        raise IdiomRefused('"over" names the group\'s members: [{"index": "m", "set": ..., "via" or "where": ...}]')
    pick = _var(body.get("pick"), '"pick"')
    note = rule.get("note") or ("exactly one per group" if kind == "exactly_one" else "at most one per group")
    return [{"id": rid, "note": f"{note} (the idiom {kind})",
             **({"forall": _bindings(body.get("for"), '"for"')} if body.get("for") else {}),
             "left": {"sum": pick, "over": over}, "relation": "=" if kind == "exactly_one" else "<=",
             "right": {"const": 1}}]
