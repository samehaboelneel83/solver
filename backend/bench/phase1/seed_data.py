"""A plan's seed as the frozen dataset a run carries (build-protocol plan, Phase 2: the construct examples are
checked without the database). The shape is the gold's `data`: sets as rows with an id and the fields,
parameters as rows with the value and one key per set, relationships as from/to pairs, the defaults.

Only what the construct examples need: typed records, cells and links. A parameter over the same set twice
and the loads from files are not handled here (the database builds those).
"""

from __future__ import annotations

from typing import Any


def data_of(seed: dict[str, Any]) -> dict[str, Any]:
    sets: dict[str, list[dict[str, Any]]] = {}
    for e in seed.get("entities") or []:
        if isinstance(e, dict) and e.get("type") and e.get("key") is not None:
            sets.setdefault(str(e["type"]), []).append({"id": str(e["key"]), **(e.get("attrs") or {})})
    index = {p["name"]: [str(s) for s in p.get("index") or []] for p in seed.get("parameters") or []
             if isinstance(p, dict) and p.get("name")}
    parameters: dict[str, list[dict[str, Any]]] = {name: [] for name in index}
    for v in seed.get("parameter_values") or []:
        if not isinstance(v, dict) or v.get("parameter") not in index:
            continue
        row: dict[str, Any] = {"value": v.get("value")}
        for pair in v.get("entities") or []:
            if isinstance(pair, (list, tuple)) and len(pair) == 2:
                row[str(pair[0])] = str(pair[1])
        parameters[v["parameter"]].append(row)
    relationships: dict[str, list[dict[str, Any]]] = {}
    for r in seed.get("relationships") or []:
        if isinstance(r, dict) and r.get("type") and isinstance(r.get("from"), (list, tuple)) \
                and isinstance(r.get("to"), (list, tuple)):
            relationships.setdefault(str(r["type"]), []).append({"from": str(r["from"][1]), "to": str(r["to"][1])})
    defaults = {p["name"]: p.get("default_value", 0) for p in seed.get("parameters") or []
                if isinstance(p, dict) and p.get("name")}
    return {"sets": sets, "parameters": parameters, "relationships": relationships, "parameter_defaults": defaults,
            "labels": {}}
