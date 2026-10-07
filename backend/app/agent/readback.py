"""A spec read back in plain formulas, from the spec itself -- not from what the model says it wrote.

The retest of the nurse roster (October 2026): a plan passed every check while its summary said "1.3x
night premium" and "no morning after a night", and the model it would build charged every shift 1.3x (one
number for all) and forbade a morning followed by a NIGHT the next day. A summary is the model's account of
its intent; this is what will actually be built. check_spec returns it for the model to compare with the
user's words, and the plan the person approves shows it under "As built".
"""

from __future__ import annotations

import json
from typing import Any

MAX_CHARS = 5000


def _num(v: Any) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return json.dumps(v, ensure_ascii=False)
    return str(int(f)) if f.is_integer() else f"{f:g}"


def _filters(where: list[dict[str, Any]]) -> str:
    parts = []
    for f in where or []:
        if "any" in f:
            parts.append("(" + " or ".join(_filters([g]) for g in f["any"]) + ")")
        elif "index" in f:
            parts.append(f"{f['op']} {f['index']}")
        else:
            value = f.get("value")
            if isinstance(value, dict) and "par" in value:
                value = f"{value['par']}[{', '.join(value.get('index') or [])}]"
            else:
                value = json.dumps(value, ensure_ascii=False)
            parts.append(f"{f.get('attr')} {f.get('op')} {value}")
    return " and ".join(parts)


def binding(b: dict[str, Any]) -> str:
    text = f"{b.get('index')} ∈ {b.get('set')}"
    via = b.get("via")
    if isinstance(via, dict):
        if "from" in via:
            text += f" that {via['from']} links to by {via.get('rel')} ({via['from']} → {b.get('index')})"
        elif "to" in via:
            text += f" linking to {via['to']} by {via.get('rel')} ({b.get('index')} → {via['to']})"
        elif "both" in via:
            text += f" linked with {via['both']} by {via.get('rel')}"
    if b.get("where"):
        text += f" where {_filters(b['where'])}"
    return text


def term(t: Any) -> str:
    if not isinstance(t, dict):
        return json.dumps(t, ensure_ascii=False)
    if "const" in t:
        return _num(t["const"])
    if "par" in t:
        return f"{t['par']}[{', '.join(map(str, t.get('index') or []))}]" if t.get("index") else str(t["par"])
    if "var" in t:
        return f"{t['var']}[{', '.join(map(str, t.get('index') or []))}]"
    if "attr" in t:
        a = t["attr"] or {}
        return f"{a.get('of')}.{a.get('name')}"
    if "sum" in t:
        return f"Σ over {', '.join(binding(b) for b in t.get('over') or [])} of ({term(t['sum'])})"
    if "add" in t:
        return " + ".join(term(x) for x in t["add"] or [])
    if "mul" in t:
        return " × ".join(term(x) if not (isinstance(x, dict) and "add" in x) else f"({term(x)})"
                          for x in t["mul"] or [])
    for kind in ("fn", "pwl", "predict"):
        if kind in t:
            return f"{kind}({json.dumps(t[kind], ensure_ascii=False)[:80]})"
    return json.dumps(t, ensure_ascii=False)[:120]


def readback(spec: dict[str, Any]) -> str:
    seed = spec.get("seed") if isinstance(spec.get("seed"), dict) else {}
    ir = spec.get("ir") if isinstance(spec.get("ir"), dict) else {}
    lines = ["AS BUILT (read back from the spec by the platform):"]
    cells: dict[str, int] = {}
    for v in seed.get("parameter_values") or []:
        if isinstance(v, dict):
            cells[v.get("parameter")] = cells.get(v.get("parameter"), 0) + 1
    links: dict[str, int] = {}
    for r in seed.get("relationships") or []:
        if isinstance(r, dict):
            links[r.get("type")] = links.get(r.get("type"), 0) + 1
    # Which records each kind gets (the paper-cutting test: 15 cutting patterns typed by hand, none of them shown).
    kinds: dict[str, list[str]] = {}
    for e in seed.get("entities") or []:
        if isinstance(e, dict) and e.get("type"):
            kinds.setdefault(str(e["type"]), []).append((str(e.get("key")), str(e.get("label") or e.get("key"))))
    for kind, pairs in list(kinds.items()):
        labels = [label for _, label in pairs]
        # Labels that repeat say nothing of which record is which (the live job-shop test: "Gear, Gear, Gear"):
        # then the keys are shown.
        kinds[kind] = labels if len(set(labels)) == len(labels) else [key for key, _ in pairs]
    for kind, names in kinds.items():
        lines.append(f"- records {kind}: {len(names)}: {', '.join(names[:12])}" + (", ..." if len(names) > 12 else ""))
    for p in seed.get("parameters") or []:
        if not isinstance(p, dict):
            continue
        name, index = p.get("name"), p.get("index") or []
        if not index:
            set_value = next((v.get("value") for v in seed.get("parameter_values") or []
                              if isinstance(v, dict) and v.get("parameter") == name), p.get("default_value"))
            lines.append(f"- {name}: ONE number for the whole problem = {_num(set_value)}")
        else:
            lines.append(f"- {name}[{', '.join(index)}]: {cells.get(name, 0)} cells given, every other cell "
                         f"{_num(p.get('default_value', 0))}")
    for rt in seed.get("relationship_types") or []:
        if isinstance(rt, dict):
            sample = [f"{r['from'][1]} → {r['to'][1]}" for r in seed.get("relationships") or []
                      if isinstance(r, dict) and r.get("type") == rt.get("name")][:8]
            lines.append(f"- link {rt.get('name')} ({rt.get('from')} → {rt.get('to')}): {links.get(rt.get('name'), 0)} "
                         f"links: {', '.join(sample)}")
    for name, v in (ir.get("variables") or {}).items():
        v = v or {}
        bounds = ""
        if v.get("domain") != "binary" and ("lower" in v or "upper" in v):
            bounds = f", {_num(v.get('lower', 0))} ≤ {name} ≤ {_num(v['upper']) if 'upper' in v else 'the platform ceiling'}"
        elif v.get("domain") in ("continuous", "integer"):
            bounds = f", 0 ≤ {name} (no upper bound given; the platform's safety ceiling applies)"
        if v.get("domain") == "interval":
            # The job-shop retest: "task[operation]: interval" said nothing of what the interval spans.
            parts = [f"{k} {v[k] if isinstance(v[k], str) else _num(v[k])}" for k in ("start", "end", "size", "presence")
                     if v.get(k) is not None]
            bounds = (" with " + ", ".join(parts)) if parts else " (no start, end or size named)"
        if v.get("stage") == 1:
            bounds += "; decided NOW, before the uncertain data is known"
        elif v.get("stage") == 2:
            bounds += "; decided LATER, once the uncertain data is known (per future)"
        lines.append(f"- decision {name}[{', '.join(v.get('index') or [])}]: {v.get('domain')}{bounds}")
    # Uncertain numbers (the bakery test: the read-back said nothing of the range the plan rests on).
    for name, p in (ir.get("parameters") or {}).items():
        u = (p or {}).get("uncertainty") if isinstance(p, dict) else None
        if not isinstance(u, dict):
            continue
        if u.get("kind") == "interval":
            lines.append(f"- {name} is UNCERTAIN: any value within +/- {_num(float(u.get('deviation') or 0) * 100)}% "
                         f"of its given value, evenly likely")
        elif u.get("kind") == "scenarios":
            futures = ", ".join(f"{f.get('label') or '?'} x{_num(f.get('factor'))}" for f in u.get("futures") or []
                                if isinstance(f, dict))
            lines.append(f"- {name} is UNCERTAIN: one of these futures (its value times the factor): {futures}")
        else:
            lines.append(f"- {name} is UNCERTAIN: {json.dumps(u, ensure_ascii=False)[:120]}")
    for c in ir.get("constraints") or []:
        if not isinstance(c, dict):
            continue
        scope = ", ".join(binding(b) for b in c.get("forall") or [])
        severity = "hard" if c.get("severity", "hard") == "hard" else f"soft, weight {c.get('weight')}"
        if isinstance(c.get("route"), dict):
            # Read back in words, as the network rule is (the evaluation's routing test: "c_route: null None null").
            body = c["route"]
            vehicles, stops = (body.get("vehicles") or {}).get("set"), (body.get("stops") or {}).get("set")
            extra = []
            if body.get("demand") and body.get("capacity"):
                extra.append(f"each {vehicles}'s load of {stops}.{body['demand']} <= its {body['capacity']}")
            if body.get("earliest") or body.get("latest"):
                extra.append(f"arrivals within {stops}.{body.get('earliest')}..{body.get('latest')}, travel "
                             f"{body.get('travel')}, service {body.get('service')}")
            lines.append(f"- rule {c.get('id')}: routes of {vehicles} from and back to {body.get('depot')!r}; every "
                         f"other {stops} visited exactly once (no loops away from the depot)"
                         + ("; " + "; ".join(extra) if extra else "") + " (hard)")
            continue
        for kind in ("no_overlap", "cumulative"):
            if isinstance(c.get(kind), dict):
                body = c[kind]
                scope = ", ".join(binding(b) for b in c.get("forall") or [])
                over = ", ".join(binding(b) for b in body.get("over") or [])
                cap = (f"; demand {term(body.get('demand'))}, capacity {term(body.get('capacity'))}"
                       if kind == "cumulative" else "")
                lines.append(f"- rule {c.get('id')}: " + (f"for every {scope}: " if scope else "")
                             + f"{term(body.get('interval'))} for {over} "
                             + ("never overlap" if kind == "no_overlap" else "share the capacity") + cap + " (hard)")
                break
        else:
            kind = None
        if kind:
            continue
        if isinstance(c.get("connected"), dict):
            # Read back in words (the fibre test showed "rule c_connectivity: null None null").
            body = c["connected"]
            var, units = (body.get("assign") or {}).get("var"), (body.get("units") or {}).get("set")
            sources = body.get("sources")
            start = (f"a {units} with {sources} set" if isinstance(sources, str) else
                     f"a {units} where {_filters(sources)}" if isinstance(sources, list) else None)
            groups = (body.get("groups") or {}).get("set") if isinstance(body.get("groups"), dict) else None
            lines.append(f"- rule {c.get('id')}: every {units} with {var} = 1 "
                         + (f"is joined along {body.get('via')} to {start}, through others with {var} = 1"
                            if start else f"forms one connected piece along {body.get('via')}")
                         + (f", per {groups}" if groups else "") + " (hard)")
            continue
        lines.append(f"- rule {c.get('id')}: " + (f"for every {scope}: " if scope else "")
                     + f"{term(c.get('left'))} {c.get('relation')} {term(c.get('right'))} ({severity})")
    objective = ir.get("objective") or {}
    if objective.get("terms"):
        mode = " in order (lex)" if objective.get("mode") == "lex" else ""
        lines.append(f"- goal: {objective.get('sense')}{mode}")
        for i, t in enumerate(objective["terms"], start=1):
            weight = "" if objective.get("mode") == "lex" else f" × weight {t.get('weight', 1)}"
            lines.append(f"  {i}. {t.get('id')}{weight}: {term(t.get('expression'))}")
    text = "\n".join(lines)
    return text if len(text) <= MAX_CHARS else text[:MAX_CHARS] + "\n...[read-back shortened]"
