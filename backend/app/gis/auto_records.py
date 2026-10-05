"""Map data to records, for a whole domain at once.

`to_records` turns one layer into records when a person says which kind, which key and which fields.
This says it for them, for every layer of every map data of a domain, and maps onto the kinds of
record the domain already has rather than beside them:

- **Which kind.** Each layer is scored against every kind of the domain on three things: the share of
  its features whose value of some property is already a record key of that kind (the strongest
  sign: the drawing and the records name the same places), how alike the layer's (or the file's)
  name and the kind's name are, and how many of its properties are fields of the kind. The best kind
  over the bar is chosen; otherwise a new kind named after the layer is proposed.
- **Which records.** The property whose values are the kind's keys is the key: those features update
  the records they name -- their shape, measures and mapped fields -- and the rest become new records.
- **Which fields.** A property goes to the field of the same name (or a close one), with that field's
  type. On a kind that exists, other properties are left out unless asked for; on a new kind they
  become fields, typed as the spreadsheet import types a column.

Nothing is written by `propose`: it also runs the conversion, so the person sees every value that
would not fit and every required field nothing fills before applying. `apply` writes every chosen
layer in one transaction, through the same `plant_domain_seed` and `update_existing` that "Make
records" uses, so it can run again: records are matched by key and refreshed.
"""
from __future__ import annotations

import difflib
import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.gis import to_records

#: The score a kind must reach to be chosen for a layer (0..1).
THRESHOLD = 0.5
#: Two names this alike (difflib ratio, after normalising) are the same name.
NAME_ALIKE = 0.85
MAX_LAYERS = 200


def _norm(name: str) -> str:
    from app.api.start import _singular

    n = to_records.to_name(name or "")
    return "_".join(_singular(p) for p in n.split("_") if p)


def name_score(layer: str, dataset: str, kind: str) -> float:
    """How alike a layer's name (or, for a generic layer, its file's) and a kind's name are, 0..1."""
    k = _norm(kind)
    if not k:
        return 0.0
    best = 0.0
    for candidate in (layer, dataset):
        c = _norm(candidate)
        if not c or c in {_norm(g) for g in to_records._GENERIC}:
            continue
        if c == k:
            return 1.0
        parts = set(c.split("_"))
        if k in parts or set(k.split("_")) <= parts:
            best = max(best, 0.9)  # "existing_wells" names wells
        best = max(best, difflib.SequenceMatcher(None, c, k).ratio())
    return best


def _attribute_for(prop: str, attributes: dict[str, dict[str, Any]]) -> str | None:
    name = to_records.to_name(prop)
    if name in attributes:
        return name
    singular = _norm(prop)
    for attr in attributes:
        if _norm(attr) == singular:
            return attr
    close = difflib.get_close_matches(name, list(attributes), n=1, cutoff=NAME_ALIKE)
    return close[0] if close else None


def _kinds(db: Session, domain_id: int) -> dict[str, dict[str, Any]]:
    """The domain's kinds: their fields (name -> type, required, default) and record keys."""
    kinds: dict[str, dict[str, Any]] = {}
    for row in db.execute(text("SELECT id, name FROM entity_type WHERE domain_id = :d AND NOT is_abstract ORDER BY name"),
                          {"d": domain_id}).mappings():
        kinds[row["name"]] = {"id": row["id"], "attributes": {}, "keys": set()}
    ids = {v["id"]: k for k, v in kinds.items()}
    if not ids:
        return kinds
    for a in db.execute(text("SELECT entity_type_id, name, data_type, required, default_value, enum_values"
                             " FROM attribute_def WHERE entity_type_id = ANY(:ids)"), {"ids": list(ids)}).mappings():
        kinds[ids[a["entity_type_id"]]]["attributes"][a["name"]] = {
            "data_type": a["data_type"], "required": a["required"] and a["default_value"] is None,
            "enum_values": a["enum_values"]}
    for e in db.execute(text("SELECT entity_type_id, key FROM entity WHERE entity_type_id = ANY(:ids)"),
                        {"ids": list(ids)}).mappings():
        kinds[ids[e["entity_type_id"]]]["keys"].add(e["key"])
    return kinds


def _layers(db: Session, domain_id: int, dataset_ids: list[int] | None) -> list[dict[str, Any]]:
    rows = db.execute(text(
        "SELECT d.id AS dataset_id, d.name AS dataset, l.name AS layer, l.feature_count"
        " FROM gis_dataset d JOIN gis_layer l ON l.dataset_id = d.id"
        " WHERE d.domain_id = :d AND l.feature_count > 0 AND (CAST(:ids AS bigint[]) IS NULL OR d.id = ANY(:ids))"
        " ORDER BY d.id, l.sort_order, l.name LIMIT :m"),
        {"d": domain_id, "ids": dataset_ids, "m": MAX_LAYERS}).mappings().all()
    return [dict(r) for r in rows]


def _columns(features: list[dict[str, Any]]) -> dict[str, list[Any]]:
    columns: dict[str, list[Any]] = {}
    for f in features:
        for k, v in to_records._properties(f).items():
            columns.setdefault(k, []).append(v)
    return columns


def _best_key(columns: dict[str, list[Any]], keys: set[str], n: int) -> tuple[str | None, int]:
    best, hits = None, 0
    for col, values in columns.items():
        m = sum(1 for v in values if to_records._as_key(v) in keys)
        if m > hits:
            best, hits = col, m
    return best, hits


def _score(layer: dict[str, Any], columns: dict[str, list[Any]], n: int, kind: str, info: dict[str, Any]) -> dict[str, Any]:
    key, hits = _best_key(columns, info["keys"], n) if info["keys"] else (None, 0)
    key_share = hits / n if n else 0.0
    names = name_score(layer["layer"], layer["dataset"], kind)
    props = [p for p in columns if to_records.to_name(p) != (to_records.to_name(key) if key else None)]
    fields = (sum(1 for p in props if _attribute_for(p, info["attributes"])) / len(props)) if props else 0.0
    # Keys in common decide; a name that is the kind's (or holds it) is enough on its own.
    score = round(min(1.0, 0.6 * key_share + 0.3 * names + 0.1 * fields + (0.3 if key_share >= 0.5 else 0)
                      + (0.3 if names >= 0.9 else 0)), 3)
    reasons = []
    if hits:
        reasons.append(f"{hits} of {n} features name a {kind} record by their “{key}”")
    if names >= NAME_ALIKE:
        reasons.append(f"the name matches “{kind}”")
    if fields:
        reasons.append(f"{round(fields * 100)}% of its properties are {kind} fields")
    return {"kind": kind, "score": score, "key": key if hits else None, "key_matches": hits, "reasons": reasons}


def _mapping(layer: dict[str, Any], features: list[dict[str, Any]], kind: str, info: dict[str, Any] | None,
             key: str | None, score: float, reasons: list[str]) -> dict[str, Any]:
    """One layer's mapping onto `kind` (an existing one when `info` is given), with what it would do."""
    from app.api.start import infer

    usable = [f for f in features if f.get("kind") != "text"]
    columns = _columns(usable)
    attributes = (info or {}).get("attributes", {})
    base = to_records.propose(usable, [layer["layer"]], set(), layer["dataset"])
    if key is None:
        key = base["key"]
    label = base["label"] if base["label"] != key else None
    fields = []
    for prop, values in columns.items():
        if prop == key:
            continue
        target = _attribute_for(prop, attributes) if info else None
        if target:
            a = attributes[target]
            fields.append({"property": prop, "name": target, "data_type": a["data_type"], "enum_values": a["enum_values"],
                           "new": False, "skip": a["data_type"] in ("geometry", "reference")})
        else:
            data_type, choices = infer(values)
            fields.append({"property": prop, "name": to_records.to_name(prop) or "field", "data_type": data_type,
                           "enum_values": choices, "new": True, "skip": info is not None})
    geometry_field = next((a for a, d in attributes.items() if d["data_type"] == "geometry"), to_records.GEOMETRY_FIELD)
    keys = info["keys"] if info else set()
    feature_keys = [to_records._as_key(f["properties"][key]) for f in usable
                    if key and (f.get("properties") or {}).get(key) not in (None, "")] if key else []
    updates = sum(1 for k in feature_keys if k in keys)
    creates = len(usable) - updates
    mapped = {f["name"] for f in fields if not f["skip"]} | {geometry_field, "area_m2", "length_m"}
    missing = sorted(a for a, d in attributes.items() if d["required"] and a not in mapped)
    plan = {"action": "existing" if info else "new", "dataset_id": layer["dataset_id"], "dataset": layer["dataset"],
            "layer": layer["layer"], "features": len(usable), "skipped_text": len(features) - len(usable),
            "type": kind, "confidence": score, "reasons": reasons, "key": key, "key_candidates": base["key_candidates"],
            "label": label, "fields": fields, "geometry_field": geometry_field,
            "updates": updates, "creates": creates,
            # New records of a kind with required fields nothing here fills would be refused: update only.
            "create_missing": not missing, "required_unfilled": missing}
    plan["faults"] = _faults(usable, plan)
    return plan


def _seed_plan(plan: dict[str, Any]) -> dict[str, Any]:
    return {"name": plan["type"], "key": plan.get("key"), "label": plan.get("label"),
            "geometry_field": plan.get("geometry_field") or to_records.GEOMETRY_FIELD,
            "fields": [{"property": f["property"], "name": f["name"], "data_type": f["data_type"],
                        "enum_values": f.get("enum_values")} for f in plan.get("fields") or [] if not f.get("skip")]}


def _faults(features: list[dict[str, Any]], plan: dict[str, Any]) -> list[str]:
    _seed, faults = to_records.build_seed(features, _seed_plan(plan))
    return faults[:20]


def propose(db: Session, domain_id: int, dataset_ids: list[int] | None = None,
            choices: dict[tuple[int, str], dict[str, Any]] | None = None) -> dict[str, Any]:
    """Every layer's mapping, chosen automatically -- or, for a (dataset, layer) in `choices`, onto the kind
    named there (`type`: an existing one, or a new name; None leaves the layer out), keyed by `key` when given."""
    kinds = _kinds(db, domain_id)
    out = []
    for layer in _layers(db, domain_id, dataset_ids):
        features = to_records.load(db, layer["dataset_id"], [layer["layer"]])
        usable = [f for f in features if f.get("kind") != "text"]
        if not usable:
            continue
        columns = _columns(usable)
        n = len(usable)
        scored = sorted((_score(layer, columns, n, k, info) for k, info in kinds.items()), key=lambda s: -s["score"])
        choice = (choices or {}).get((layer["dataset_id"], layer["layer"]))
        chosen = "auto" if choice is None else choice.get("type")
        key_choice = (choice or {}).get("key") or None
        if key_choice is not None and key_choice not in columns:
            key_choice = None
        if chosen is None:
            plan = _mapping(layer, features, to_records.kind_name([layer["layer"]], layer["dataset"]), None, None, 0, [])
            plan["action"] = "skip"
        elif chosen != "auto":
            name = to_records.to_name(chosen)
            match = next((s for s in scored if s["kind"] == name), None)
            plan = _mapping(layer, features, name, kinds.get(name), key_choice or (match["key"] if match else None),
                            match["score"] if match else 0.0, ["chosen by you"])
        elif scored and scored[0]["score"] >= THRESHOLD:
            best = scored[0]
            plan = _mapping(layer, features, best["kind"], kinds[best["kind"]], key_choice or best["key"], best["score"],
                            best["reasons"])
        else:
            name = to_records.kind_name([layer["layer"]], layer["dataset"])
            plan = _mapping(layer, features, name, kinds.get(name), key_choice, 0.0,
                            ["no kind of this domain matches it well: a new kind"] if name not in kinds else
                            [f"named like the kind “{name}”"])
        plan["alternatives"] = [{"type": s["kind"], "confidence": s["score"]} for s in scored[:5]]
        out.append(plan)
    return {"domain_id": domain_id, "types": sorted(kinds), "mappings": out}


def apply(db: Session, domain_id: int, mappings: list[dict[str, Any]]) -> dict[str, Any]:
    """Write the chosen mappings, all or nothing. Returns per layer what was made and updated, or the faults."""
    from app.seed import plant_domain_seed

    results, faults = [], []
    for plan in mappings:
        if plan.get("action") == "skip":
            continue
        name = to_records.to_name(plan.get("type") or "")
        if not name:
            faults.append(f'{plan.get("layer")}: no kind of record named')
            continue
        features = [f for f in to_records.load(db, int(plan["dataset_id"]), [plan["layer"]]) if f.get("kind") != "text"]
        if not features:
            faults.append(f'{plan.get("layer")}: the layer has no features')
            continue
        seed, bad = to_records.build_seed(features, _seed_plan({**plan, "type": name}))
        if bad:
            faults.extend(f'{plan["layer"]}: {b}' for b in bad[:20])
            continue
        before = to_records.existing_keys(db, domain_id, name)
        if not plan.get("create_missing", True):
            seed["entities"] = [e for e in seed["entities"] if e["key"] in before]
        plant_domain_seed(db, domain_id, seed)
        updated = to_records.update_existing(db, domain_id, seed, before)
        db.execute(text("UPDATE entity_type SET role = 'location' WHERE domain_id = :d AND name = :n AND role = 'other'"),
                   {"d": domain_id, "n": name})
        type_id = db.execute(text("SELECT id FROM entity_type WHERE domain_id = :d AND name = :n"),
                             {"d": domain_id, "n": name}).scalar_one()
        results.append({"dataset_id": plan["dataset_id"], "layer": plan["layer"], "type": name,
                        "entity_type_id": int(type_id), "made": len([e for e in seed["entities"] if e["key"] not in before]),
                        "updated": updated})
    return {"results": results, "faults": faults}
