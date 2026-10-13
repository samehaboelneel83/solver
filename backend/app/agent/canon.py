"""The canonical form: one ordered pass over a spec between the model's reply and the contract check.

Every rule here rewrites one spelling the model uses into the contract's spelling, or supplies something the
spec itself determines, and says so in a note the model reads -- never silently. The inventory of the rules,
with the incident each came from and its class, is docs/plans/canonical-form.md (build-protocol plan,
Phase 1.1); this module is Phase 1.2: the rules as small named functions, in one documented order, with the
fixed-point test on the gold corpus (tests/test_canon.py: canonical(gold) == gold).

    spec, notes = canonical(args, messages=..., load=..., domain_id=...)

The order (top to bottom): where the spec is (`spec_of`) -> a patch completed from the draft (`draft.complete`)
-> `misplaced` -> `joined_keys` -> the files loaded (`load`, the caller's) -> the idiom expansions -> the
seed-level rules -> the IR-level rules -> the literal keys bound. Then the pydantic contract, in the caller.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from app.agent import draft as agent_draft
from app.agent import idioms as agent_idioms
from app.agent.files import FileRefused

BODY_KEYS = ("body", "term", "of", "expr", "expression", "value", "sum")
SCOPE_KEYS = ("for", "forall", "bindings", "over_set", "for_each", "foreach")

NO_IR = ('the spec has no "ir" (the model: {"version": 2, "sets", "relationships", "parameters", "variables", '
         '"constraints", "objective"}) -- it goes beside "seed", which holds the data')


# ---------------------------------------------------------------------------------------------------------------
# Where the spec is


#: Keys a spec holds; a call that gives them at its top level (no "spec") meant them as the spec.
SPEC_KEYS = ("ir", "seed", "domain_name", "domain_id", "problem_name", "scenario_name")


def spec_of(args: Any) -> tuple[dict[str, Any], list[str]]:
    """The spec of a check_spec / propose_plan call, wherever the model put it (the production-planning trace,
    10 October 2026: a local model's spec came back "has no ir" three times running): the `spec` argument as an
    object; or as a JSON string -- parsed, and repaired as tool calls are; or, with no `spec`, the spec's own keys
    written beside the summary; a part written beside a `spec` that lacks it joins it. A model the spec carries inside `seed`, or under `model`, is lifted to `ir`."""
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
    else:
        # A spec with some of its parts beside it (the same trace's last refused call: the names and the seed
        # inside "spec", "ir" next to it). What the spec itself says stands.
        beside = [k for k in SPEC_KEYS if k in args and k not in spec]
        if beside:
            spec = {**spec, **{k: args[k] for k in beside}}
            notes.append(f"{', '.join(beside)} written beside \"spec\" was taken as part of it; put it inside next time")
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


# ---------------------------------------------------------------------------------------------------------------
# The spec's sections


SEED_ONLY = ("entity_types", "relationship_types", "entities", "entities_from_file", "relationships",
             "relationships_from_file", "relationships_in_order", "distances_from_fields", "patterns_that_fit",
             "parameter_values",
             "parameter_values_from_file")
IR_ONLY = ("version", "sets", "variables", "constraints", "objective")


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


# ---------------------------------------------------------------------------------------------------------------
# The seed-level rules: each `rule(spec, notes)`, the seed and the IR both present


def _seed(spec: dict[str, Any]) -> dict[str, Any]:
    return spec.get("seed") if isinstance(spec.get("seed"), dict) else {}


def uncertainty_declared_in_ir(spec: dict[str, Any], notes: list[str]) -> None:
    """An uncertainty written on the seed's parameter (the bakery retest) is moved into `ir.parameters`: the IR
    declares it, the seed only holds the value.

    `seed.parameters: [{"name": "demand", "uncertainty": {...}}]` -> `ir.parameters.demand.uncertainty`."""
    ir = spec["ir"]
    for p in _seed(spec).get("parameters") or []:
        if isinstance(p, dict) and isinstance(p.get("uncertainty"), dict) and p.get("name"):
            params = ir.setdefault("parameters", {})
            target = params.setdefault(p["name"], {"index": list(p.get("index") or [])})
            if isinstance(target, dict) and "uncertainty" not in target:
                target["uncertainty"] = p.pop("uncertainty")
                notes.append(f'the "uncertainty" of {p["name"]} was moved from the seed into ir.parameters, '
                             'where the model declares it')
            else:
                p.pop("uncertainty")


def complete_list_default(spec: dict[str, Any], notes: list[str]) -> None:
    """A 0/1 list typed as 1 on a default of 1 changes nothing (the evaluation, 11 October 2026: the one approved
    pair typed as allowed = 1, every other pair allowed by default): what it does not name is 0 -- an inference,
    taken only when the cells name every record of the first index. A list naming some restricts those alone
    (11 October 2026: flipping it made every unlisted record unservable), so a partial list is a note.

    `allowed` over (a, b), default 1, cells = 1 for every a -> default 0."""
    seed = _seed(spec)
    cells = [v for v in seed.get("parameter_values") or [] if isinstance(v, dict)]
    for p in seed.get("parameters") or []:
        mine = [v for v in cells if v.get("parameter") == (p.get("name") if isinstance(p, dict) else None)]
        given = [v.get("value") for v in mine]
        if isinstance(p, dict) and p.get("index") and given and all(g == 1 for g in given) \
                and p.get("default_value") == 1:
            first = str(p["index"][0])
            named = {str(e[0][1]) for v in mine for e in [v.get("entities") or []] if e and isinstance(e[0], (list, tuple))}
            every = {str(e.get("key")) for e in seed.get("entities") or [] if isinstance(e, dict) and e.get("type") == first}
            if every and named >= every:
                p["default_value"] = 0
                notes.append(f'{p["name"]} gave 1 for {len(given)} cell(s) on a default of 1 and names every {first}: '
                             "every cell not given is now 0")
            else:
                notes.append(f'{p["name"]} gives 1 for {len(given)} cell(s) on a default of 1, so as written it changes '
                             f"nothing; it names {len(named)} of {len(every) or '?'} {first}. If it restricts only "
                             "those it names, add a 0/1 parameter per record (1 for those named) and write "
                             f"amount <= most x (1 - listed[r] + {p['name']}[r, o]); if it is complete, give it default 0")


def declared_from_values(spec: dict[str, Any], notes: list[str]) -> None:
    """Values for a parameter only the IR declares (the Nile Juice trace: 48 cells of "demand", refused until the
    seed declared it too): the seed's declaration is the IR's, when every cell fits its index -- an inference
    the spec determines.

    `ir.parameters.demand.index = ["week"]`, cells over one record each -> `seed.parameters += {demand, [week]}`."""
    ir = spec["ir"]
    seed = _seed(spec)
    cells = [v for v in seed.get("parameter_values") or [] if isinstance(v, dict)]
    declared = {p.get("name") for p in seed.get("parameters") or [] if isinstance(p, dict)}
    for name in dict.fromkeys(v.get("parameter") for v in cells):
        reads = (ir.get("parameters") or {}).get(name) if isinstance(ir.get("parameters"), dict) else None
        index = reads.get("index") if isinstance(reads, dict) else None
        if not isinstance(name, str) or name in declared or not isinstance(index, list) \
                or not all(isinstance(t, str) for t in index) or not isinstance(spec.get("seed"), dict):
            continue
        if all(len(v.get("entities") or []) == len(index) for v in cells if v.get("parameter") == name):
            seed.setdefault("parameters", []).append({"name": name, "index": list(index)})
            declared.add(name)
            notes.append(f"parameter {name} had values in the seed but was declared only in ir.parameters; it was "
                         f"declared in the seed's parameters too, over {', '.join(index) or 'nothing'}")


# ---------------------------------------------------------------------------------------------------------------
# The IR-level rules


def relationships_by_name(spec: dict[str, Any], notes: list[str]) -> None:
    """Relationships written as objects ({"name": "next", "from": "week", "to": "week"}): the IR lists their names;
    what they link is the seed's (the evaluation, 10 October 2026: four turns lost to it)."""
    ir = spec["ir"]
    rels = ir.get("relationships")
    if isinstance(rels, list) and any(isinstance(r, dict) for r in rels):
        ir["relationships"] = [r.get("name") if isinstance(r, dict) else r for r in rels
                               if isinstance(r, str) or (isinstance(r, dict) and isinstance(r.get("name"), str))]
        notes.append("relationships written as objects were listed by their names; what they link is the seed's")


def sets_stated(spec: dict[str, Any], notes: list[str]) -> None:
    """A model over no records (the bakery test: one quantity, one uncertain number) still states its sets:
    a missing `sets` is `[]`."""
    ir = spec["ir"]
    if "sets" not in ir:
        ir["sets"] = []
        notes.append('"sets" was missing and was written as [] (a model over no records)')


def forall_shape(spec: dict[str, Any], notes: list[str]) -> None:
    """A rule's empty `forall` ([] / {} / null) is left out (a rule over nothing has none); one binding written
    as an object is a list of one (the feed-blend test)."""
    for c in spec["ir"].get("constraints") or []:
        if isinstance(c, dict) and c.get("forall") in ([], {}, None) and "forall" in c:
            c.pop("forall")
            notes.append(f'rule {c.get("id")}\'s empty "forall" was left out (a rule over nothing has none)')
        elif isinstance(c, dict) and isinstance(c.get("forall"), dict):
            c["forall"] = [c["forall"]]


def decision_shape(spec: dict[str, Any], notes: list[str]) -> None:
    """A decision with no `index` is one number (the job-shop retest: "makespan" without "index"); an interval's
    start, end, size and presence name a decision or parameter, so written as a term they are reduced to the
    name (the live job-shop test); `"upper": null` for "no limit" (the paper-cutting test) is left out."""
    for name, var in (spec["ir"].get("variables") or {}).items():
        if isinstance(var, dict) and var.get("index") is None:
            var["index"] = []
            notes.append(f'decision {name} had no "index" and is one number ("index": [])')
        if isinstance(var, dict) and var.get("domain") == "interval":
            for key in ("start", "end", "size", "presence"):
                ref = var.get(key)
                if isinstance(ref, dict) and isinstance(ref.get("var") or ref.get("par"), str):
                    var[key] = ref.get("var") or ref.get("par")
                    notes.append(f'interval {name}\'s "{key}" was written as a term; it names {var[key]}')
        for bound in ("lower", "upper"):
            if isinstance(var, dict) and bound in var and var[bound] is None:
                var.pop(bound)
                notes.append(f'decision {name}\'s "{bound}": null was left out (no {bound} bound of your own)')


def hard_by_default(spec: dict[str, Any], notes: list[str]) -> None:
    """A rule with no severity (or null) and no weight is a must-hold rule; a connected or route rule can only be
    hard (the fibre test, October 2026: "null is not a severity; a connected rule is hard" three times). An
    inference: a rule the model wrote without a weight is one it meant to hold."""
    for c in spec["ir"].get("constraints") or []:
        if isinstance(c, dict) and c.get("severity") is None and "weight" not in c:
            c["severity"] = "hard"
            notes.append(f'rule {c.get("id")} had no severity and was made "hard" (must hold)')


def _scalar_indices(ir: dict[str, Any], notes: list[str], seed: dict[str, Any] | None = None) -> None:
    """A one-number decision or parameter read with an index (the live job-shop test: makespan[o]) is read with
    none: it has one value."""
    scalars = {("var", n) for n, v in (ir.get("variables") or {}).items() if isinstance(v, dict) and v.get("index") == []}
    scalars |= {("par", n) for n, p in (ir.get("parameters") or {}).items() if isinstance(p, dict) and p.get("index") == []}
    # One number declared only in the seed (the evaluation, 11 October 2026: a cost per ton-minute, refused seven
    # times as "declared over 0 sets") is one number too, unless the IR declares it with an index.
    ir_pars = ir.get("parameters") if isinstance(ir.get("parameters"), dict) else {}
    scalars |= {("par", p["name"]) for p in (seed or {}).get("parameters") or []
                if isinstance(p, dict) and isinstance(p.get("name"), str) and not p.get("index")
                and not (isinstance(ir_pars.get(p["name"]), dict) and ir_pars[p["name"]].get("index"))}
    fixed: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for kind in ("var", "par"):
                # Read with an index, or with no "index" at all: either way one number reads as "index": [].
                if isinstance(node.get(kind), str) and (kind, node[kind]) in scalars and node.get("index") != []:
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


def scalar_indices(spec: dict[str, Any], notes: list[str]) -> None:
    """One number (a decision or parameter declared over no set, in the IR or only in the seed) is read with
    `"index": []` wherever a term reads it with an index or with none at all (the live job-shop test:
    makespan[o]; the evaluation of 11 October 2026: a cost per ton-minute refused seven times)."""
    _scalar_indices(spec["ir"], notes, _seed(spec))


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
        if "over" in node and "sum" not in node and any(k in node for k in ("add", "mul", "var", "par", "attr", "const")):
            # A term written with "over" and no "sum" (the evaluation, 11 October 2026: {"add": [...], "over":
            # [b]} refused six times as '"over" is not a key an add term carries', and the Assistant gave up):
            # it is the sum of that term over the binding.
            over = node.pop("over")
            inner = {k: node.pop(k) for k in list(node) if k not in ("note",)}
            node["sum"] = inner
            node["over"] = over
            notes.append('a term written with "over" and no "sum" was read as {"sum": <the term>, "over": [...]}')
        if "sum" in node:
            _lift_sum(node, notes)
            if "default" in node and node["default"] in (0, None) and not isinstance(node["default"], bool):
                # A sum over nothing is 0 already (the Nile Juice trace: "default": 0 on a sum was refused).
                node.pop("default")
                notes.append('"default": 0 on a sum was left out (a sum over nothing is 0)')
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
        for key in ("mul", "add"):
            # A product or a sum of one part is that part (the Delta Pharma trace: {"mul": [ship[w, c]]} under a
            # sum, refused four times running as "mul has exactly two factors").
            if len(node) == 1 and isinstance(node.get(key), list) and len(node[key]) == 1 \
                    and isinstance(node[key][0], dict):
                only = node.pop(key)[0]
                node.update(only)
                notes.append(f'"{key}" of one part was written as the part itself')
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


def term_shapes(spec: dict[str, Any], notes: list[str]) -> None:
    """The shapes a model writes for a term, put in the language's own form, over every rule and goal term:
    `over` with no `sum` -> a sum; a sum's `over` inside its body or beside it as for/forall/index+set -> beside
    `sum`; `"default": 0` on a sum -> left out; `sub`/`neg` -> `add` with -1 times; a `mul`/`add` of one part ->
    the part; a bare number -> `{"const": n}`; a product of 3+ factors -> nested pairs (feed blend, Nile Juice,
    production plan, Delta Pharma, fibre, the evaluation of 11 October 2026)."""
    _walk(spec["ir"].get("constraints"), notes)
    _walk(spec["ir"].get("objective"), notes)


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


def bound_rules(spec: dict[str, Any], notes: list[str]) -> None:
    """A decision's bound given as a field or parameter name (the feed-blend test: `"upper": "available_kg"`,
    which differs by ingredient) becomes a hard rule over the decision's records: `amount[i] <= available_kg`."""
    _bound_rules(spec["ir"], _seed(spec), notes)


def bind_literal_keys(ir: dict) -> list[str]:
    """`work[n, d, "night"]`: a record named by its key where an index belongs. The IR wants every index
    bound, so the roster field test's model wrote it again and again and was refused each time. Each such
    key becomes an index bound to that one record -- {"index": "k_night", "set": "shift", "where": id =
    "night"} -- added to the rule's forall (a goal term: summed over it); one record, so nothing else
    changes. Rewrites `ir` in place; returns what it did, for the model to read."""
    declared = {**{n: (v or {}).get("index") or [] for n, v in (ir.get("variables") or {}).items()},
                **{n: (v or {}).get("index") or [] for n, v in (ir.get("parameters") or {}).items()}}
    done: list[str] = []

    def walk(term, scope: set[str], added: dict[str, dict]):
        if isinstance(term, list):
            for t in term:
                walk(t, scope, added)
            return
        if not isinstance(term, dict):
            return
        inner = set(scope)
        for b in term.get("over") or []:
            if isinstance(b, dict) and isinstance(b.get("index"), str):
                inner.add(b["index"])
        ref = term.get("var") if "var" in term else term.get("par")
        if isinstance(ref, str) and isinstance(term.get("index"), list) and ref in declared:
            sets = declared[ref]
            for j, key in enumerate(term["index"]):
                if isinstance(key, str) and key not in inner and j < len(sets):
                    name = "k_" + "".join(ch if ch.isascii() and ch.isalnum() else "_" for ch in key.lower())[:40]
                    if name not in added:
                        added[name] = {"index": name, "set": sets[j],
                                       "where": [{"attr": "id", "op": "=", "value": key}]}
                        done.append(f'{ref}[..."{key}"...] -> index {name} bound to the {sets[j]} "{key}"')
                    term["index"][j] = name
        for k, v in term.items():
            if k not in ("index", "where"):
                walk(v, inner, added)

    for c in ir.get("constraints") or []:
        if not isinstance(c, dict):
            continue
        scope = {b["index"] for b in c.get("forall") or [] if isinstance(b, dict) and isinstance(b.get("index"), str)}
        added: dict[str, dict] = {}
        walk([c.get("left"), c.get("right")], scope, added)
        if added:
            c["forall"] = list(c.get("forall") or []) + list(added.values())
    for t in ((ir.get("objective") or {}).get("terms") or []):
        if not isinstance(t, dict):
            continue
        added = {}
        walk(t.get("expression"), set(), added)
        if added:
            t["expression"] = {"sum": t["expression"], "over": list(added.values())}
    return done


def literal_keys(spec: dict[str, Any], notes: list[str]) -> None:
    """A record named by its key where an index belongs (`work[n, d, "night"]`, the roster field test) is bound
    to that one record by a `where` binding added to the rule's scope."""
    bound = bind_literal_keys(spec["ir"])
    if bound:
        notes.append("records named by their key where an index belongs were bound to them: " + "; ".join(bound))


#: The rules of the pass on a spec that has its `ir`, in the order they run. Each is `rule(spec, notes)`, in
#: place; docs/plans/canonical-form.md names the incident behind each.
RULES: tuple[Callable[[dict[str, Any], list[str]], None], ...] = (
    uncertainty_declared_in_ir,
    complete_list_default,
    declared_from_values,
    relationships_by_name,
    sets_stated,
    forall_shape,
    decision_shape,
    hard_by_default,
    scalar_indices,
    term_shapes,
    bound_rules,
    literal_keys,
)


def _dedup(notes: list[str]) -> list[str]:
    seen: list[str] = []
    for n in notes:
        if n not in seen:
            seen.append(n)
    return seen


def repair(spec: dict[str, Any]) -> list[str]:
    """The seed- and IR-level rules on a spec in place (the pass after the files are loaded); returns what
    changed, for the model. Nothing happens on a spec with no `ir`."""
    if not isinstance(spec.get("ir"), dict):
        return []
    notes: list[str] = []
    for rule in RULES[:-1]:  # the literal keys are bound by the caller's own step, after these
        rule(spec, notes)
    return _dedup(notes)


def canonical(args: Any, *, messages: list[dict[str, Any]] | None = None,
              load: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
              domain_id: int | None = None,
              notes: list[str] | None = None) -> tuple[dict[str, Any], list[str]]:
    """The one pass: the spec of a call as the model wrote it, in the contract's form, and the notes that say
    what was rewritten. `messages` is the conversation (a partial plan is completed from the last one proposed);
    `load`, when given, turns the seed's file references into records (the caller's, since the files are its)
    and turns the idiom expansions on, which need the records; `domain_id` is written on a spec that names no
    domain. Raises FileRefused when the spec has no `ir` after every move, or when a load or an idiom refuses --
    the notes said before the refusal stay in `notes`, when the caller gives its own list (the model reads them
    beside the refusal)."""
    notes = notes if notes is not None else []
    start = len(notes)
    spec, first = spec_of(args)
    notes.extend(first)
    spec, completed = agent_draft.complete(spec, messages or [])
    if completed:
        notes.append(completed)
    spec = {k: v for k, v in spec.items() if k != "dry_run"}
    notes.extend(misplaced(spec))
    notes.extend(joined_keys(spec))
    if not isinstance(spec.get("ir"), dict):
        raise FileRefused(NO_IR)
    if "domain_id" not in spec and not spec.get("domain_name") and domain_id is not None:
        spec["domain_id"] = domain_id
    if load is not None and isinstance(spec.get("seed"), dict):
        spec["seed"] = load(spec["seed"])  # FileRefused: told
    spec["ir"] = json.loads(json.dumps(spec["ir"]))  # never the model's own copy
    for term in ((spec["ir"].get("objective") or {}).get("terms") or []):
        # A goal term has no "note" (rules do): a refusal for it cost Qwen a whole 2-minute reply.
        if isinstance(term, dict):
            term.pop("note", None)
    if load is not None:
        # Modelling idioms written as compact rules become the rules they stand for (app/agent/idioms.py);
        # they need the loaded records, so only on the expanded spec. IdiomRefused is a FileRefused: told.
        notes.extend(agent_idioms.expand(spec))
    for rule in RULES:
        rule(spec, notes)
    notes[start:] = _dedup(notes[start:])
    return spec, notes
