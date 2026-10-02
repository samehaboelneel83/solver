"""Data what-ifs on a scenario (improvement plan 3.3).

A scenario could only bend or drop rules. A planner's questions are as often
about the data: "what if yard Y3 is not available?", "what if it rains 30%
more?", "what if this truck carries 300, not 250?". The scenario's patch now
carries those, and they are applied to a copy of the run's frozen data when
it is solved -- the stored dataset never changes, so every run stays
reproducible and two scenarios on the same data can be compared:

- `remove`: {set: [keys]} -- records left out: the set's rows, every value of
  a parameter keyed by them, and every link to or from them;
- `set_param`: [{param, index, value}] -- one value changed (or given);
- `scale_param`: {param: factor} -- every stored value of a parameter, and
  its default, times a factor;
- `set_attr`: [{set, key, attr, value}] -- a record's field changed;
- `scale_attr`: [{set, attr, factor, where?}] -- a field of every record of a set, or of those the
  conditions keep, times a factor (demand +30%).
"""
from __future__ import annotations

from typing import Any

DATA_KEYS = ("remove", "set_param", "scale_param", "set_attr", "scale_attr")


def has_data_changes(patch: dict[str, Any] | None) -> bool:
    return bool(patch) and any(patch.get(k) for k in DATA_KEYS)


def _param_keys(ir: dict[str, Any], param: str) -> list[str]:
    sets = ((ir.get("parameters") or {}).get(param) or {}).get("index") or []
    return sets if len(set(sets)) == len(sets) else [str(p) for p in range(len(sets))]


def apply(data: dict[str, Any], ir: dict[str, Any], patch: dict[str, Any] | None) -> dict[str, Any]:
    """A copy of `data` with the patch's data changes made; `data` itself is left as it was."""
    if not has_data_changes(patch):
        return data
    from app.solve.whynot import overridden

    sets = {name: [dict(r) for r in rows] for name, rows in (data.get("sets") or {}).items()}
    parameters = {name: [dict(r) for r in rows] for name, rows in (data.get("parameters") or {}).items()}
    relationships = {name: [dict(r) for r in rows] for name, rows in (data.get("relationships") or {}).items()}
    defaults = dict(data.get("defaults") or {})
    out = {**data, "sets": sets, "parameters": parameters, "relationships": relationships}
    if defaults:
        out["defaults"] = defaults

    removed: dict[str, set[str]] = {s: {str(k) for k in keys} for s, keys in (patch.get("remove") or {}).items()}
    for set_name, keys in removed.items():
        if set_name in sets:
            sets[set_name] = [r for r in sets[set_name] if str(r.get("id")) not in keys]
    if removed:
        for param, rows in parameters.items():
            fields = _param_keys(ir, param)
            sets_of = ((ir.get("parameters") or {}).get(param) or {}).get("index") or []
            def gone(row: dict[str, Any]) -> bool:
                return any(str(row.get(field)) in removed.get(set_name, set())
                           for field, set_name in zip(fields, sets_of))
            parameters[param] = [r for r in rows if not gone(r)]
        everything = set().union(*removed.values())
        for rel, rows in relationships.items():
            relationships[rel] = [r for r in rows if str(r.get("from")) not in everything and str(r.get("to")) not in everything]

    for change in patch.get("set_attr") or []:
        for row in sets.get(change["set"], []):
            if str(row.get("id")) == str(change["key"]):
                row[change["attr"]] = change["value"]

    if patch.get("scale_attr"):
        from app.solve.compile import _passes

        for change in patch["scale_attr"]:
            for row in sets.get(change["set"], []):
                value = row.get(change["attr"])
                if isinstance(value, (int, float)) and not isinstance(value, bool) and _passes(row, change.get("where") or []):
                    row[change["attr"]] = value * change["factor"]

    for param, factor in (patch.get("scale_param") or {}).items():
        for row in parameters.get(param, []):
            if isinstance(row.get("value"), (int, float)):
                row["value"] = row["value"] * factor
        if isinstance(defaults.get(param), (int, float)):
            defaults[param] = defaults[param] * factor

    if patch.get("set_param"):
        out = overridden(out, ir, [{"param": c["param"], "index": c["index"], "value": c["value"]}
                                   for c in patch["set_param"]])
    return out


def describe(patch: dict[str, Any] | None) -> list[str]:
    """The data changes in words, for a scenario's card."""
    if not has_data_changes(patch):
        return []
    said = []
    for set_name, keys in (patch.get("remove") or {}).items():
        said.append(f"without {set_name} {', '.join(map(str, keys))}")
    for param, factor in (patch.get("scale_param") or {}).items():
        said.append(f"{param} × {factor:g}")
    for c in patch.get("set_param") or []:
        said.append(f"{c['param']}[{', '.join(map(str, c['index']))}] = {c['value']:g}")
    for c in patch.get("set_attr") or []:
        said.append(f"{c['set']} {c['key']}: {c['attr']} = {c['value']}")
    for c in patch.get("scale_attr") or []:
        kept = " where " + " and ".join(f"{f['attr']} {f['op']} {f['value']}" for f in c["where"]) if c.get("where") else ""
        said.append(f"{c['attr']} × {c['factor']:g} for every {c['set']}{kept}")
    return said
