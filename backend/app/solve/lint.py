"""A model that solves and still is not the problem: what its shape gives away.

A wrong model with no answer says so. One that has an answer does not: the solver proves the best plan of what
was written, and nothing shows that what was written left something out (the Assistant's evaluation, 10 October
2026: a production plan "proven optimal" at 122,826 where the problem's answer was 116,235 -- the opening stock
never read, and overtime written where it uses hours up). Two checks, on the model's shape alone, the same for
every model whatever it is about:

**A decision that can never help** (`never_helps`). Raising it never improves the goal and never gives any rule
more room -- it costs, or is free, and every rule it is in only gets tighter -- so the best plan always leaves
it at its least value, and it decides nothing. This is the dual fixing of a presolve ("dominated column"), read
as a finding: a decision somebody described is not there to stay at zero, so one of its terms is on the wrong
side or has the wrong sign.

**Data that is given and never read** (`unread`). A number field of the records, or a parameter with values,
that no rule, goal, bound or filter of the model names. Something the person supplied does not enter the
answer. A field that only numbers the records in order (1, 2, 3 ...) is left out: that is an order, not an
amount.

Neither refuses a model: both are findings, for the Assistant to act on before a person sees the plan and for
the person to read on the plan card.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.solve.compile import Compiled

#: Findings of one kind reported at most; more says the same thing again.
MOST = 8
#: Where a record is, not how much of anything: fields a map reads, which a model need not.
PLACES = frozenset({"lon", "lat", "lng", "longitude", "latitude", "x", "y", "z", "x_m", "y_m", "z_m",
                    "easting", "northing"})


def never_helps(compiled: Compiled) -> list[dict[str, Any]]:
    """Decisions whose every cell can only cost the goal and tighten the rules it is in."""
    # Left alone where a decision's effect is not in the rows alone: scheduling, curves, functions, flows,
    # goals in order, a quadratic goal.
    if (compiled.pwl or compiled.functions or getattr(compiled, "intervals", None)
            or getattr(compiled, "connectivity", None) or compiled.objective_mode != "weighted"
            or compiled.objective_quadratic or any(c.schedule is not None for c in compiled.constraints)):
        return []
    minimize = compiled.sense == "minimize"
    cost = {**compiled.objective.coeffs}
    for key, value in compiled.penalty_objective.coeffs.items():
        cost[key] = cost.get(key, Decimal(0)) + value
    minted = {key for keys in compiled.violations.values() for key in keys}
    # Per rule instance: the cells it holds back (raising them uses its room up) and the cells that give it room.
    # A cell helps when the goal wants more of it, when it is in an equation or a switch, or when it gives room to
    # a rule that matters: one no plan keeps with every cell at its least, or one that holds back a cell that
    # helps -- followed to the end (phase 1 evaluation, 10 October 2026: in `pick[CTL004] <= pick[CTL006]`, pick
    # [CTL006] gives room, but only to another pick that never helps; protection written as at least what the
    # chosen controls give made every pick useless, and the check, stopping at the first room given, was silent).
    tightens: dict[Any, set[str]] = {}
    helps: set[Any] = {k for k, w in cost.items() if (w < 0 if minimize else w > 0)}
    rows: list[tuple[str, set, set, bool]] = []  # (rule id, held back, given room, matters already)
    for c in compiled.constraints:
        if c.when is not None:
            helps.add(c.when[0])  # a switch: what it does is not a matter of more or less
        for pair in c.quadratic:
            helps.update(pair)
        held, room = set(), set()
        least = Decimal(0)
        for key in set(c.left.coeffs) | set(c.right.coeffs):
            net = c.left.coeffs.get(key, Decimal(0)) - c.right.coeffs.get(key, Decimal(0))
            if net == 0:
                continue
            var = compiled.variables.get(key)
            least += net * (var.lower if var is not None else Decimal(0))
            if c.relation == "=":
                helps.add(key)
            elif (c.relation == "<=") != (net > 0):
                room.add(key)
            else:
                held.add(key)
                tightens.setdefault(key, set()).add(c.id)
        limit = c.right.const - c.left.const
        unmet = (least > limit) if c.relation == "<=" else (least < limit) if c.relation == ">=" else False
        rows.append((c.id, held, room, unmet))
    while True:
        more = {k for _, held, room, unmet in rows if unmet or held & helps for k in room} - helps
        if not more:
            break
        helps |= more
    by_decision: dict[str, list[Any]] = {}
    for key in compiled.variables:
        if not str(key[0]).startswith("__") and key not in minted:
            by_decision.setdefault(str(key[0]), []).append(key)
    found: list[dict[str, Any]] = []
    for name, cells in by_decision.items():
        costly = False
        rules: set[str] = set()
        for key in cells:
            weight = cost.get(key, Decimal(0))
            if key in helps:
                break
            costly = costly or weight != 0
            rules |= tightens.get(key, set())
        else:
            if not costly and not rules:
                found.append({"kind": "idle", "decision": name,
                              "said": f"{name} is in no rule and not in the goal: the model decides nothing with it"})
            else:
                parts = ([f"every unit of it {'costs' if minimize else 'lowers'} the goal"] if costly else []) + (
                    [f"it only uses up room in {', '.join(sorted(rules))}"] if rules else [])
                found.append({"kind": "never_helps", "decision": name, "rules": sorted(rules), "costly": costly,
                              "said": f"{name} can never help: " + " and ".join(parts) + ", so the best plan "
                                      "always leaves it at its least value"})
    return found[:MOST]


def _names_read(node: Any, attrs: set[str], pars: set[str]) -> None:
    if isinstance(node, dict):
        attr = node.get("attr")
        if isinstance(attr, str):
            attrs.add(attr)
        elif isinstance(attr, dict) and isinstance(attr.get("name"), str):
            attrs.add(attr["name"])
        if isinstance(node.get("par"), str):
            pars.add(node["par"])
        for key in ("start", "end", "size", "presence", "lower", "upper"):
            if isinstance(node.get(key), str):  # an interval's or a bound's name of a parameter or field
                attrs.add(node[key])
                pars.add(node[key])
        for value in node.values():
            _names_read(value, attrs, pars)
    elif isinstance(node, list):
        for value in node:
            _names_read(value, attrs, pars)


def _consts(node: Any, out: set[float]) -> None:
    if isinstance(node, dict):
        if isinstance(node.get("const"), (int, float)) and not isinstance(node["const"], bool):
            out.add(float(node["const"]))
        for value in node.values():
            _consts(value, out)
    elif isinstance(node, list):
        for value in node:
            _consts(value, out)


def _is_order(values: list[Any]) -> bool:
    """1, 2, 3 ... (or 0, 1, 2 ...) once each: the records' order, not an amount."""
    try:
        numbers = sorted(float(v) for v in values)
    except (TypeError, ValueError):
        return False
    return len(numbers) > 1 and numbers[0] in (0.0, 1.0) and all(
        b - a == 1 for a, b in zip(numbers, numbers[1:]))


def unread(ir: dict[str, Any], seed: dict[str, Any]) -> list[dict[str, Any]]:
    """Number fields and parameters the spec gives values for and the model never names."""
    attrs: set[str] = set()
    pars: set[str] = set()
    _names_read({k: v for k, v in ir.items() if k != "parameters"}, attrs, pars)
    found: list[dict[str, Any]] = []
    entities = [e for e in seed.get("entities") or [] if isinstance(e, dict)]
    # A rule that is not an expression (a placement, a route, a connection) reads the records' fields by what it
    # is, not by name: nothing can be said of fields there.
    special = any(isinstance(c, dict) and "left" not in c for c in ir.get("constraints") or [])
    # Numbers that reach the model another way are in it: written out as constants (a rule per record with its
    # own number), or given again as a parameter the model reads (today's right models gave costs both as a
    # field and a parameter, and an opening stock as a parameter over product and week).
    reaching: set[float] = set()
    _consts(ir, reaching)
    cells: dict[str, int] = {}
    for value in seed.get("parameter_values") or []:
        if isinstance(value, dict) and isinstance(value.get("parameter"), str):
            cells[value["parameter"]] = cells.get(value["parameter"], 0) + 1
            if value["parameter"] in pars and isinstance(value.get("value"), (int, float)):
                reaching.add(float(value["value"]))
    for kind in [] if special else seed.get("entity_types") or []:
        if not isinstance(kind, dict):
            continue
        for attribute in kind.get("attributes") or []:
            name = attribute.get("name") if isinstance(attribute, dict) else None
            if not name or name in attrs or str(name).lower() in PLACES or str(attribute.get("data_type") or "").lower() not in (
                    "number", "integer", "decimal", "float", "int"):
                continue
            values = [e["attrs"][name] for e in entities
                      if e.get("type") == kind.get("name") and isinstance(e.get("attrs"), dict)
                      and isinstance(e["attrs"].get(name), (int, float)) and not isinstance(e["attrs"][name], bool)]
            if not values or _is_order(values) or all(float(v) == 0 or float(v) in reaching for v in values):
                continue
            found.append({"kind": "unread", "what": f"{kind.get('name')}.{name}", "values": len(values),
                          "said": f"{kind.get('name')}.{name} is given for {len(values)} record(s) and no rule "
                                  "or goal reads it"})
    for name, count in cells.items():
        if name not in pars and name not in attrs:
            found.append({"kind": "unread", "what": name, "values": count,
                          "said": f"{name} is given {count} value(s) and no rule or goal reads it"})
    return found[:MOST]


def findings(ir: dict[str, Any], seed: dict[str, Any], compiled: Compiled | None) -> list[dict[str, Any]]:
    """Both checks; a model that did not compile has only the second."""
    out = never_helps(compiled) if compiled is not None else []
    return out + unread(ir, seed)
