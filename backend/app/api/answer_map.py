"""Any run's answer on a map (improvement plan 3.1).

    GET /api/v1/runs/{id}/answer-map
    GET /api/v1/runs/{id}/answer-map/compare/{other}   what changed from `other` to `id`, on the map

`run_map` draws one kind of model -- a partition into connected zones. A
planner placing depots, assigning clinics or routing crews also needs the
answer where it happens. This reads the run's frozen dataset and stored
answer, never today's records, and turns every decision that touches a set
whose members have a shape into map features, without knowing what the
places are:

- a decision over one placed set (`open[yard]`, `covered[hotspot]`): each
  place carries the value -- chosen or not, or the amount;
- a decision over two placed sets (`serve[depot, customer]`): a line for
  each chosen pair, from one place to the other;
- a decision over a placed set and another (`station[yard, truck]`): each
  place carries how many it got and which;
- a rule that bent or broke, per instance over a placed set (`H09 short by
  2`): the place is marked, with the rule and the amount.

The answer is a list of layers, each a FeatureCollection-ready list of
features with a `layer`, a `status` (chosen, not_chosen, short, place) and a
title in words. A run with nothing placed answers `none` and why.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from shapely.geometry import shape
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models.iam import UserAccount

router = APIRouter(prefix="/api/v1", tags=["spatial"])

MAX_FEATURES = 20_000
SHAPES = ("Point", "Polygon", "MultiPolygon", "LineString", "MultiLineString")


def _shape_of(row: dict[str, Any]) -> dict[str, Any] | None:
    for value in row.values():
        if isinstance(value, dict) and value.get("type") in SHAPES and isinstance(value.get("coordinates"), list):
            return value
    return None


def _point(geometry: dict[str, Any]) -> list[float]:
    g = shape(geometry)
    p = g if g.geom_type == "Point" else g.representative_point()
    return [round(p.x, 7), round(p.y, 7)]


def _label(row: dict[str, Any], key: str) -> str:
    for name in ("label", "name", "title"):
        if isinstance(row.get(name), str) and row[name].strip():
            return row[name]
    return key


def _words(name: str) -> str:
    """A kind's name as words in a title a person reads: candidate_site -> candidate site."""
    return name.replace("_", " ")


def _numbers(row: dict[str, Any]) -> dict[str, float]:
    """A record's number fields, for a map that colours areas by one (population, vulnerability)."""
    return {k: v for k, v in row.items()
            if k != "id" and isinstance(v, (int, float)) and not isinstance(v, bool) and v == v}


def answer_map(ir: dict[str, Any], data: dict[str, Any], assignments: dict[str, Any] | None,
               amounts: dict[str, Any] | None, results: list[dict[str, Any]], labels: dict[str, dict[str, str]] | None = None
               ) -> dict[str, Any]:
    """The map of one answered run, from its model, frozen data, answer and rule results."""
    sets = data.get("sets") or {}
    labels = labels or data.get("labels") or {}
    placed: dict[str, dict[str, dict[str, Any]]] = {}
    for set_name, rows in sets.items():
        members = {}
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, dict) and (geometry := _shape_of(row)) is not None:
                key = str(row.get("id"))
                members[key] = {"geometry": geometry, "label": (labels.get(set_name) or {}).get(key) or _label(row, key),
                                "data": _numbers(row)}
        if members:
            placed[set_name] = members
    if not placed:
        return {"none": "no set of this model has records with a shape", "layers": [], "features": []}
    variables = ir.get("variables") or {}
    chosen = {name: {tuple(str(k) for k in row) for row in rows} for name, rows in (assignments or {}).items()}
    amount = {name: {tuple(str(k) for k in e.get("index") or []): float(e.get("value") or 0) for e in entries}
              for name, entries in (amounts or {}).items()}
    layers: list[dict[str, Any]] = []
    features: list[dict[str, Any]] = []

    def add(feature: dict[str, Any]) -> None:
        if len(features) < MAX_FEATURES:
            features.append(feature)

    drawn_sets: set[str] = set()
    for var, spec in variables.items():
        index = list(spec.get("index") or [])
        domain = spec.get("domain") or "binary"
        if domain == "interval":
            continue
        binary = domain == "binary"
        placed_positions = [i for i, s in enumerate(index) if s in placed]
        if not placed_positions:
            continue
        if len(index) == 1:
            s = index[0]
            drawn_sets.add(s)
            on = 0
            for key, member in placed[s].items():
                if binary:
                    is_on = (key,) in chosen.get(var, set())
                    on += is_on
                    value: Any = 1 if is_on else 0
                    status = "chosen" if is_on else "not_chosen"
                    title = f"{member['label']}: {var} {'yes' if is_on else 'no'}"
                else:
                    value = amount.get(var, {}).get((key,), 0.0)
                    status = "chosen" if abs(value) > 1e-9 else "not_chosen"
                    on += status == "chosen"
                    title = f"{member['label']}: {var} = {value:g}"
                add({"type": "Feature", "geometry": member["geometry"],
                     "properties": {"layer": var, "set": s, "key": key, "label": member["label"], "value": value,
                                    "status": status, "title": title, "data": member["data"]}})
            layers.append({"id": var, "kind": "places", "set": s, "title": f"{var}: {on} of {len(placed[s])} {_words(s)}"})
        elif len(index) == 2 and len(placed_positions) == 2:
            a, b = index
            drawn_sets.update(index)
            n = 0
            cells = chosen.get(var, set()) if binary else {k for k, v in amount.get(var, {}).items() if abs(v) > 1e-9}
            for cell in sorted(cells):
                if len(cell) != 2 or cell[0] not in placed[a] or cell[1] not in placed[b]:
                    continue
                n += 1
                pa, pb = placed[a][cell[0]], placed[b][cell[1]]
                value = 1 if binary else amount[var][cell]
                add({"type": "Feature",
                     "geometry": {"type": "LineString", "coordinates": [_point(pa["geometry"]), _point(pb["geometry"])]},
                     "properties": {"layer": var, "set": f"{a}-{b}", "key": f"{cell[0]}|{cell[1]}", "value": value,
                                    "status": "chosen", "title": f"{var}: {pa['label']} → {pb['label']}"
                                    + ("" if binary else f" ({value:g})")}})
            layers.append({"id": var, "kind": "links", "set": f"{a}-{b}", "title": f"{var}: {n} links"})
        else:
            # Over a placed set and others: each place says how many it got, and which.
            p = placed_positions[0]
            s = index[p]
            drawn_sets.add(s)
            cells = chosen.get(var, set()) if binary else {k for k, v in amount.get(var, {}).items() if abs(v) > 1e-9}
            per: dict[str, list[str]] = {}
            for cell in cells:
                if len(cell) == len(index):
                    rest = [cell[i] for i in range(len(index)) if i != p]
                    per.setdefault(cell[p], []).append(" · ".join(rest))
            total = 0
            for key, member in placed[s].items():
                got = sorted(per.get(key, []))
                total += len(got)
                shown = ", ".join(got[:8]) + (f" and {len(got) - 8} more" if len(got) > 8 else "")
                add({"type": "Feature", "geometry": member["geometry"],
                     "properties": {"layer": var, "set": s, "key": key, "label": member["label"], "value": len(got),
                                    "status": "chosen" if got else "not_chosen", "data": member["data"],
                                    "title": f"{member['label']}: {var} {len(got)}" + (f" — {shown}" if got else "")}})
            layers.append({"id": var, "kind": "counts", "set": s, "title": f"{var}: {total} over {len(placed[s])} {_words(s)}"})

    # Who serves whom: 0/1 reach data between two placed sets and a yes/no choice over one of them
    # (open[yard] with reach[yard, hotspot]) -- each item joined to the nearest chosen place that
    # reaches it, and an item no chosen place reaches marked. Read from the data, so it holds for
    # depots and customers, stations and districts, schools and pupils alike.
    for layer, found in _coverage(ir, data, placed, chosen):
        layers.append(layer)
        for feature in found:
            add(feature)

    # Rules that bent or broke, at the places their instances name.
    rules = {c.get("id"): c for c in ir.get("constraints") or [] if isinstance(c, dict)}
    short = 0
    for result in results:
        if result.get("satisfied") or not result.get("violations"):
            continue
        rule = rules.get(result.get("constraint_id")) or {}
        over = [b.get("set") for b in rule.get("forall") or [] if isinstance(b, dict)]
        for violation in result["violations"]:
            instance = [str(k) for k in violation.get("index") or violation.get("instance") or []]
            by = float(violation.get("by") if violation.get("by") is not None else violation.get("amount") or 0)
            for position, s in enumerate(over):
                if s in placed and position < len(instance) and instance[position] in placed[s]:
                    member = placed[s][instance[position]]
                    short += 1
                    amount_text = f"{by:g}"
                    add({"type": "Feature", "geometry": member["geometry"],
                         "properties": {"layer": "unmet", "set": s, "key": instance[position], "label": member["label"],
                                        "value": by, "status": "short",
                                        "title": f"{member['label']}: {result['constraint_id']} short by {amount_text}"}})
                    break
    if short:
        layers.append({"id": "unmet", "kind": "unmet", "set": None, "title": f"rules not met: {short} places"})

    # Placed sets no decision is over (hospitals, schools): drawn as context.
    for s, members in placed.items():
        if s in drawn_sets:
            continue
        for key, member in members.items():
            add({"type": "Feature", "geometry": member["geometry"],
                 "properties": {"layer": s, "set": s, "key": key, "label": member["label"], "value": None,
                                "status": "place", "title": member["label"], "data": member["data"]}})
        layers.append({"id": s, "kind": "context", "set": s, "title": f"{_words(s)}: {len(members)}"})
    return {"layers": layers, "features": features, "truncated": len(features) >= MAX_FEATURES}


def _coverage(ir: dict[str, Any], data: dict[str, Any], placed: dict[str, dict[str, dict[str, Any]]],
              chosen: dict[str, set[tuple[str, ...]]]) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
    flags = {spec["index"][0]: name for name, spec in (ir.get("variables") or {}).items()
             if (spec.get("domain") or "binary") == "binary" and len(spec.get("index") or []) == 1
             and spec["index"][0] in placed}
    defaults = data.get("defaults") or {}
    out = []
    for par, spec in (ir.get("parameters") or {}).items():
        index = list(spec.get("index") or [])
        if len(index) != 2 or len(set(index)) != 2 or not all(s in placed for s in index):
            continue
        rows = [r for r in ((data.get("parameters") or {}).get(par) or []) if isinstance(r, dict)]
        values = {float(r.get("value") or 0) for r in rows}
        if not rows or not values <= {0.0, 1.0} or 1.0 not in values or float(defaults.get(par, 0) or 0) != 0:
            continue  # not 0/1 reach data (a distance, a cost): nothing to join
        for server, item in ((index[0], index[1]), (index[1], index[0])):
            var = flags.get(server)
            if var is None:
                continue
            open_ = {cell[0] for cell in chosen.get(var, set()) if cell}
            reach: dict[str, set[str]] = {}
            for r in rows:
                if float(r.get("value") or 0) == 1.0:
                    reach.setdefault(str(r.get(item)), set()).add(str(r.get(server)))
            features, served = [], 0
            for key, member in placed[item].items():
                here = _point(member["geometry"])
                near = [k for k in reach.get(key, set()) & open_ if k in placed[server]]
                if near:
                    best = min(near, key=lambda k: _gap(here, _point(placed[server][k]["geometry"])))
                    served += 1
                    by = placed[server][best]
                    features.append({"type": "Feature",
                                     "geometry": {"type": "LineString", "coordinates": [_point(by["geometry"]), here]},
                                     "properties": {"layer": f"{par}_served", "set": f"{server}-{item}", "key": f"{best}|{key}",
                                                    "label": member["label"], "value": len(near), "status": "chosen",
                                                    "title": f"{member['label']}: served from {by['label']}"
                                                    + (f" (and {len(near) - 1} more within reach)" if len(near) > 1 else "")}})
                else:
                    features.append({"type": "Feature", "geometry": member["geometry"],
                                     "properties": {"layer": f"{par}_served", "set": item, "key": key, "label": member["label"],
                                                    "value": 0, "status": "short", "data": member.get("data") or {},
                                                    "title": f"{member['label']}: no chosen {_words(server)} within {par}"}})
            out.append(({"id": f"{par}_served", "kind": "links", "set": f"{server}-{item}",
                         "title": f"{_words(item)} served from a chosen {_words(server)} ({par}): {served} of {len(placed[item])}"}, features))
            break
    return out


def _gap(a: list[float], b: list[float]) -> float:
    import math

    dx = (a[0] - b[0]) * math.cos(math.radians((a[1] + b[1]) / 2))
    return dx * dx + (a[1] - b[1]) ** 2


def _map_of(db: Session, run_id: int) -> dict[str, Any]:
    row = db.execute(
        text("SELECT r.status, mv.ir, d.data, sol.assignments, sol.amounts FROM run r"
             " JOIN scenario s ON s.id = r.scenario_id JOIN model_version mv ON mv.id = r.model_version_id"
             " JOIN dataset d ON d.id = r.dataset_id LEFT JOIN solution sol ON sol.run_id = r.id WHERE r.id = :r"),
        {"r": run_id},
    ).mappings().one_or_none()
    if row is None:
        raise HTTPException(404, "run not found")
    if row["assignments"] is None and row["amounts"] is None:
        return {"none": f"this run has no answer to draw (it is {row['status']})", "layers": [], "features": []}
    results = [dict(r) for r in db.execute(
        text("SELECT constraint_id, satisfied, violations FROM constraint_result WHERE run_id = :r"), {"r": run_id}
    ).mappings()]
    return answer_map(row["ir"], row["data"] or {}, row["assignments"], row["amounts"], results)


@router.get("/runs/{run_id}/answer-map")
def get_answer_map(run_id: int, db: Session = Depends(get_db),
                   user: UserAccount = Depends(get_current_user)) -> dict[str, Any]:
    return _map_of(db, run_id)


def compare_maps(now: dict[str, Any], before: dict[str, Any]) -> dict[str, Any]:
    """What changed between two answer maps, as a map of its own (improvement plan 3.4): a place or link
    chosen now and not before is `added`, chosen before and not now `removed`, chosen in both `same`; a
    place a rule falls short at now and not before is `short` (newly), one that no longer is `fixed`.
    Places with nothing to say are left out, so the drawing shows only the change."""
    def chosen(m: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
        return {(f["properties"]["layer"], f["properties"]["key"]): f for f in m.get("features") or []
                if f["properties"]["status"] in ("chosen", "short")}

    a, b = chosen(now), chosen(before)
    features: list[dict[str, Any]] = []
    counts: dict[str, dict[str, int]] = {}
    for key in sorted(set(a) | set(b)):
        f = a.get(key) or b[key]
        layer = key[0]
        was_short = key in b and b[key]["properties"]["status"] == "short"
        is_short = key in a and a[key]["properties"]["status"] == "short"
        if layer == "unmet":
            status = "short" if is_short and not was_short else "fixed" if was_short and not is_short else "same"
        else:
            status = "added" if key in a and key not in b else "removed" if key in b and key not in a else "same"
        counts.setdefault(layer, {}).setdefault(status, 0)
        counts[layer][status] += 1
        label = f["properties"].get("label") or f["properties"]["key"]
        words = {"added": "now chosen", "removed": "no longer chosen", "same": "unchanged",
                 "short": "now falls short", "fixed": "no longer falls short"}[status]
        features.append({"type": "Feature", "geometry": f["geometry"],
                         "properties": {**f["properties"], "status": status, "title": f"{label}: {layer} {words}"}})
    layers = []
    for layer, c in counts.items():
        parts = [f"+{c['added']}" if c.get("added") else "", f"−{c['removed']}" if c.get("removed") else "",
                 f"{c['short']} newly short" if c.get("short") else "", f"{c['fixed']} fixed" if c.get("fixed") else ""]
        said = ", ".join(p for p in parts if p) or "no change"
        layers.append({"id": layer, "kind": "change", "title": f"{layer}: {said}"})
    return {"layers": layers, "features": features,
            "changed": sum(1 for f in features if f["properties"]["status"] != "same")}


@router.get("/runs/{run_id}/answer-map/compare/{other_id}")
def get_compare_map(run_id: int, other_id: int, db: Session = Depends(get_db),
                    user: UserAccount = Depends(get_current_user)) -> dict[str, Any]:
    now, before = _map_of(db, run_id), _map_of(db, other_id)
    if now.get("none") or before.get("none"):
        return {"none": now.get("none") or before.get("none"), "layers": [], "features": []}
    return compare_maps(now, before)
