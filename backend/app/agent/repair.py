"""Shapes a model writes for a sum, a rule's scope or a bound, put back in the IR's own form before the check.

The feed-blend field test (October 2026): Qwen wrote the same `sum` four times without `over` beside it
(the check refused it each time, and the turn gave up), an empty `"forall": []` for a rule over nothing,
and `"upper": "available_kg"` for a bound that differs by ingredient. Each has exactly one meaning, so it
is rewritten here and the model is told what changed -- never silently.
"""

from __future__ import annotations

import json
from typing import Any

BODY_KEYS = ("body", "term", "of", "expr", "expression", "value", "sum")
SCOPE_KEYS = ("for", "forall", "bindings", "over_set", "for_each", "foreach")


def _binding_from(node: dict[str, Any]) -> list[dict[str, Any]] | None:
    """`{"index": "i", "set": "ingredient"}` or `{"i": "ingredient"}` written beside or inside a sum."""
    if isinstance(node.get("index"), str) and isinstance(node.get("set"), str):
        return [{"index": node["index"], "set": node["set"]}]
    return None


def _lift_sum(term: dict[str, Any], notes: list[str]) -> None:
    if "sum" not in term or "over" in term:
        return
    inner = term["sum"]
    over = None
    if isinstance(inner, dict) and "over" in inner:
        inner = dict(inner)
        over = inner.pop("over")
        body_key = next((k for k in BODY_KEYS if k in inner), None)
        if body_key is not None and len(inner) == 1:
            inner = inner[body_key]
        term["sum"] = inner
        notes.append('a sum\'s "over" written inside its body was moved beside "sum"')
    else:
        for key in SCOPE_KEYS:
            if key in term:
                over = term.pop(key)
                notes.append(f'a sum\'s "{key}" was taken as its "over"')
                break
        else:
            binding = _binding_from(term)
            if binding is not None:
                term.pop("index"), term.pop("set")
                over = binding
                notes.append('a sum\'s "index"/"set" beside it were made its "over"')
    if over is None:
        return
    if isinstance(over, dict):
        over = [over]
    term["over"] = over


def _walk(node: Any, notes: list[str]) -> None:
    if isinstance(node, dict):
        if "sum" in node:
            _lift_sum(node, notes)
        for key in ("sub", "subtract", "minus", "neg", "negate"):
            # a - b, written as the arithmetic reads (the production-plan test: stock[q] - owed[q] as "sub"); the
            # language has add and mul only, so it is a + (-1 * b).
            if key in node and len(node) == 1:
                parts = node.pop(key)
                parts = parts if isinstance(parts, list) else [parts]
                negated = [{"mul": [{"const": -1}, t]} for t in parts[1 if key in ("sub", "subtract", "minus") else 0:]]
                if key in ("sub", "subtract", "minus") and parts:
                    node["add"] = [parts[0], *negated]
                elif len(negated) == 1:
                    node.update(negated[0])
                else:
                    node["add"] = negated
                notes.append(f'"{key}" was written as "add" with -1 times the part taken away (the language adds and '
                             'multiplies: a - b is {"add":[a,{"mul":[{"const":-1},b]}]})')
                break
        number = (int, float)
        for key in ("left", "right", "expression"):
            if isinstance(node.get(key), number) and not isinstance(node[key], bool):
                node[key] = {"const": node[key]}
                notes.append(f'a bare number in "{key}" was written as {{"const": ...}}')
        for key in ("add", "mul"):
            if isinstance(node.get(key), list) and any(isinstance(t, number) and not isinstance(t, bool)
                                                       for t in node[key]):
                node[key] = [{"const": t} if isinstance(t, number) and not isinstance(t, bool) else t
                             for t in node[key]]
                notes.append(f'a bare number in "{key}" was written as {{"const": ...}}')
        factors = node.get("mul")
        if isinstance(factors, list) and len(factors) > 2:
            # a * b * c nested as a * (b * c): the language multiplies pairs (fibre test: 500 * households * pick).
            nested = factors[-1]
            for f in reversed(factors[1:-1]):
                nested = {"mul": [f, nested]}
            node["mul"] = [factors[0], nested]
            notes.append(f"a product of {len(factors)} factors was nested into pairs")
        for value in node.values():
            _walk(value, notes)
    elif isinstance(node, list):
        for value in node:
            _walk(value, notes)


def _scalar_indices(ir: dict[str, Any], notes: list[str]) -> None:
    """A one-number decision or parameter read with an index (the live job-shop test: makespan[o]) is read with
    none: it has one value."""
    scalars = {("var", n) for n, v in (ir.get("variables") or {}).items() if isinstance(v, dict) and v.get("index") == []}
    scalars |= {("par", n) for n, p in (ir.get("parameters") or {}).items() if isinstance(p, dict) and p.get("index") == []}
    fixed: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for kind in ("var", "par"):
                if isinstance(node.get(kind), str) and (kind, node[kind]) in scalars and node.get("index"):
                    node["index"] = []
                    fixed.add(node[kind])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk([ir.get("constraints"), ir.get("objective")])
    if fixed:
        notes.append(f"{', '.join(sorted(fixed))} hold one number and were read with no index ([])")


def _bound_rules(ir: dict[str, Any], seed: dict[str, Any], notes: list[str]) -> None:
    """A bound given as a field or parameter name becomes a rule over the decision's records."""
    variables = ir.get("variables") if isinstance(ir.get("variables"), dict) else {}
    params = {p.get("name"): p for p in (seed.get("parameters") or []) if isinstance(p, dict)}
    fields: dict[str, set[str]] = {}
    for et in seed.get("entity_types") or []:
        if isinstance(et, dict):
            fields[str(et.get("name"))] = {str(a.get("name")) for a in et.get("attributes") or [] if isinstance(a, dict)}
    constraints = ir.setdefault("constraints", [])
    if not isinstance(constraints, list):
        return
    for name, spec in variables.items():
        if not isinstance(spec, dict):
            continue
        index = [str(s) for s in spec.get("index") or []]
        for key, relation in (("upper", "<="), ("lower", ">=")):
            value = spec.get(key)
            if value is None or isinstance(value, (int, float)) and not isinstance(value, bool):
                continue
            ref = value.get("par") or (value.get("attr") or {}).get("name") if isinstance(value, dict) else value
            if not isinstance(ref, str) or not index:
                continue
            names = [f"i{n}" if n else "i" for n in range(len(index))]
            right: dict[str, Any] | None = None
            param = params.get(ref)
            if param is not None and [str(s) for s in param.get("index") or []] == index:
                right = {"par": ref, "index": names}
            elif param is not None and not param.get("index"):
                right = {"par": ref}
            elif len(index) == 1 and ref in fields.get(index[0], set()):
                right = {"attr": {"of": "i", "name": ref}}
            if right is None:
                continue
            spec.pop(key)
            constraints.append({
                "id": f"{name}_{key}_{ref}"[:60],
                "note": f"{name} {relation} {ref} for every {', '.join(index)}",
                "forall": [{"index": n, "set": s} for n, s in zip(names, index)],
                "left": {"var": name, "index": names},
                "relation": relation,
                "right": right,
                "severity": "hard",
            })
            notes.append(f'{name}\'s {key} bound "{ref}" differs by record, so it became the rule '
                         f'{name}_{key}_{ref}: {name}[{", ".join(names)}] {relation} {ref}')


SEED_ONLY = ("entity_types", "relationship_types", "entities", "entities_from_file", "relationships",
             "relationships_from_file", "relationships_in_order", "distances_from_fields", "patterns_that_fit",
             "parameter_values",
             "parameter_values_from_file")
IR_ONLY = ("version", "sets", "variables", "constraints", "objective")


def _joined_key(key: Any) -> Any:
    if isinstance(key, list) and key and all(isinstance(k, (str, int, float)) and not isinstance(k, bool) for k in key):
        return "-".join(str(int(k)) if isinstance(k, float) and k.is_integer() else str(k) for k in key)
    return key


def joined_keys(spec: dict[str, Any]) -> list[str]:
    """A record named by a list of key parts (["Gear", 1]) is the record with the joined key ("Gear-1"), as
    `"key": ["job","step"]` makes it (the job-shop retest typed its step links that way)."""
    seed = spec.get("seed") if isinstance(spec.get("seed"), dict) else {}
    changed = 0
    for e in seed.get("entities") or []:
        if isinstance(e, dict) and isinstance(e.get("key"), list):
            e["key"] = _joined_key(e["key"]); changed += 1
    for r in seed.get("relationships") or []:
        for end in ("from", "to"):
            pair = r.get(end) if isinstance(r, dict) else None
            if isinstance(pair, list) and len(pair) == 2 and isinstance(pair[1], list):
                pair[1] = _joined_key(pair[1]); changed += 1
    for v in seed.get("parameter_values") or []:
        for pair in (v.get("entities") or []) if isinstance(v, dict) else []:
            if isinstance(pair, list) and len(pair) == 2 and isinstance(pair[1], list):
                pair[1] = _joined_key(pair[1]); changed += 1
    return [f'{changed} record key(s) given as lists were joined with "-" (["Gear", 1] is "Gear-1")'] if changed else []


#: Keys a spec holds; a call that gives them at its top level (no "spec") meant them as the spec.
SPEC_KEYS = ("ir", "seed", "domain_name", "domain_id", "problem_name", "scenario_name")


def spec_of(args: Any) -> tuple[dict[str, Any], list[str]]:
    """The spec of a check_spec / propose_plan call, wherever the model put it (the production-planning trace,
    10 October 2026: a local model's spec came back "has no ir" three times running): the `spec` argument as an
    object; or as a JSON string -- parsed, and repaired as tool calls are; or, with no `spec`, the spec's own keys
    written beside the summary. A model the spec carries inside `seed`, or under `model`, is lifted to `ir`."""
    from app.agent import toolcall

    notes: list[str] = []
    args = args if isinstance(args, dict) else {}
    raw = args.get("spec")
    spec: Any = raw
    if isinstance(raw, str) and raw.strip():
        try:
            spec = toolcall.strict_loads(raw)
        except Exception:  # noqa: BLE001 -- the repairs the tool calls get
            fixed = toolcall.fix_spec(raw)
            try:
                spec = toolcall.strict_loads(fixed if fixed is not None else toolcall._repair(raw))
                notes.append("the spec was written as a string with JSON slips; it was read and put right")
            except Exception:  # noqa: BLE001
                spec = None
        else:
            notes.append("the spec was written as a JSON string; send it as an object next time")
    if not isinstance(spec, dict):
        top = {k: args[k] for k in SPEC_KEYS if k in args}
        if "ir" in top or "seed" in top:
            spec = top
            notes.append("the spec's parts were written beside the summary, not inside \"spec\"; they were taken as the spec")
        else:
            spec = {}
    spec = dict(spec)
    if not isinstance(spec.get("ir"), dict):
        seed = spec.get("seed")
        if isinstance(seed, dict) and isinstance(seed.get("ir"), dict):
            spec["ir"] = seed.pop("ir")
            notes.append("ir written inside seed was moved beside it")
        elif isinstance(spec.get("model"), dict) and ("variables" in spec["model"] or "constraints" in spec["model"]):
            spec["ir"] = spec.pop("model")
            notes.append('the model written under "model" was taken as "ir"')
    return spec, notes


def misplaced(spec: dict[str, Any]) -> list[str]:
    """Keys written beside `seed` and `ir` that belong inside them, moved there (the fibre test, October 2026:
    entities_from_file, relationships_from_file and parameters at the top, and no `ir`; the platform answered
    with a bare "Field required")."""
    notes: list[str] = []
    moved = [k for k in SEED_ONLY if k in spec]
    if moved or ("parameters" in spec and not isinstance(spec.get("ir"), dict)) or (
            "parameters" in spec and isinstance(spec.get("parameters"), list)):
        seed = spec.setdefault("seed", {}) if isinstance(spec.get("seed"), dict) or "seed" not in spec else None
        if seed is not None:
            if isinstance(spec.get("parameters"), list):
                moved.append("parameters")  # a list of declarations is the seed's; the IR's is an object
            for k in moved:
                value = spec.pop(k)
                if k in seed and isinstance(seed[k], list) and isinstance(value, list):
                    # Written in both places: one copy of each (by name when it has one).
                    have = {json.dumps(x, sort_keys=True) for x in seed[k]}
                    names = {x.get("name") for x in seed[k] if isinstance(x, dict) and x.get("name")}
                    seed[k] = [*seed[k], *(x for x in value if json.dumps(x, sort_keys=True) not in have
                                           and not (isinstance(x, dict) and x.get("name") in names))]
                else:
                    seed.setdefault(k, value)
            notes.append(f"{', '.join(moved)} written beside seed were moved into seed")
    ir = spec.get("ir")
    inside = [k for k in SEED_ONLY if k not in ("parameter_values", "relationships") and isinstance(ir, dict) and k in ir]
    if inside and (isinstance(spec.get("seed"), dict) or "seed" not in spec):
        # Seed data written inside the IR (the live cutting-stock test: patterns_that_fit in ir).
        seed = spec.setdefault("seed", {})
        for k in inside:
            seed.setdefault(k, ir.pop(k))
        notes.append(f"{', '.join(inside)} written inside ir were moved into seed, where data is made")
    if not isinstance(spec.get("ir"), dict):
        lifted = {k: spec.pop(k) for k in IR_ONLY if k in spec}
        if "variables" in lifted or "constraints" in lifted:
            if isinstance(spec.get("parameters"), dict):
                lifted["parameters"] = spec.pop("parameters")
            spec["ir"] = {"version": 2, **lifted}
            notes.append(f"{', '.join(lifted)} written beside seed were moved into ir")
    return notes


def repair(spec: dict[str, Any]) -> list[str]:
    """Rewrite the spec's IR in place; returns what changed, for the model."""
    ir = spec.get("ir")
    if not isinstance(ir, dict):
        return []
    notes: list[str] = []
    seed = spec.get("seed") if isinstance(spec.get("seed"), dict) else {}
    for p in seed.get("parameters") or []:
        # An uncertainty written on the seed's parameter (the bakery retest): the IR declares it, the seed only
        # holds the value, so it is moved where the model reads it.
        if isinstance(p, dict) and isinstance(p.get("uncertainty"), dict) and p.get("name"):
            params = ir.setdefault("parameters", {})
            target = params.setdefault(p["name"], {"index": list(p.get("index") or [])})
            if isinstance(target, dict) and "uncertainty" not in target:
                target["uncertainty"] = p.pop("uncertainty")
                notes.append(f'the "uncertainty" of {p["name"]} was moved from the seed into ir.parameters, '
                             'where the model declares it')
            else:
                p.pop("uncertainty")
    if "sets" not in ir:
        # A model over no records (the bakery test: one quantity, one uncertain number) still states its sets.
        ir["sets"] = []
        notes.append('"sets" was missing and was written as [] (a model over no records)')
    for c in ir.get("constraints") or []:
        if isinstance(c, dict) and c.get("forall") in ([], {}, None) and "forall" in c:
            c.pop("forall")
            notes.append(f'rule {c.get("id")}\'s empty "forall" was left out (a rule over nothing has none)')
        elif isinstance(c, dict) and isinstance(c.get("forall"), dict):
            c["forall"] = [c["forall"]]
    for name, var in (ir.get("variables") or {}).items():
        # A decision with no index is one number (the job-shop retest: "makespan" without "index").
        if isinstance(var, dict) and var.get("index") is None:
            var["index"] = []
            notes.append(f'decision {name} had no "index" and is one number ("index": [])')
        if isinstance(var, dict) and var.get("domain") == "interval":
            # An interval's start, end and size name a decision or parameter; written as a term (the live job-shop
            # test: "size": {"par": "duration", "index": ["operation"]}) they are reduced to the name.
            for key in ("start", "end", "size", "presence"):
                ref = var.get(key)
                if isinstance(ref, dict) and isinstance(ref.get("var") or ref.get("par"), str):
                    var[key] = ref.get("var") or ref.get("par")
                    notes.append(f'interval {name}\'s "{key}" was written as a term; it names {var[key]}')
        for bound in ("lower", "upper"):
            # "upper": null for "no limit" (the paper-cutting test): a bound left out is the platform's own.
            if isinstance(var, dict) and bound in var and var[bound] is None:
                var.pop(bound)
                notes.append(f'decision {name}\'s "{bound}": null was left out (no {bound} bound of your own)')
    for c in ir.get("constraints") or []:
        # A rule with no severity (or null) and no weight is a must-hold rule; a connected or route rule can only
        # be hard (the fibre test, October 2026: "null is not a severity; a connected rule is hard" three times).
        if isinstance(c, dict) and c.get("severity") is None and "weight" not in c:
            c["severity"] = "hard"
            notes.append(f'rule {c.get("id")} had no severity and was made "hard" (must hold)')
    _scalar_indices(ir, notes)
    _walk(ir.get("constraints"), notes)
    _walk(ir.get("objective"), notes)
    seed = spec.get("seed") if isinstance(spec.get("seed"), dict) else {}
    _bound_rules(ir, seed, notes)
    seen: list[str] = []
    for n in notes:
        if n not in seen:
            seen.append(n)
    return seen
