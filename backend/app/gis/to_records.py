"""Map layers as records (improvement plan, phase 1.1 and 1.3).

Map data was view-only: a layer of yards, hotspots or districts could be
seen on the map but not used by a model, so the same places were typed in
again as spreadsheet rows. This turns the features of one or more layers of
an imported dataset into ordinary records of a kind -- with no knowledge of
what the places are -- or attaches their shapes to records that already
exist:

- **make records** (`propose`, `build_seed`): one record per feature. The key
  is a property the person picks (`name`, `id`, ...), or the feature's number.
  Every other property is a field, typed as the spreadsheet import types a
  column (`app.api.start.infer`). The shape is a `geometry` field: points,
  polygons and multi-polygons as they are; a line keeps its length and a
  point on it (the platform's geometry fields hold points and areas). Two
  measured fields come for free: `area_m2` for an area, `length_m` for a line,
  geodesic on WGS 84.
- **attach shapes** (`attach`): for records already there (from Excel, say),
  match each feature to a record by a property whose value is the record's
  key, and write only the geometry field. Unmatched features and records
  without a shape are reported, never guessed.

Both write through `plant_domain_seed`, as the spreadsheet import does, so a
kind or field that already exists is reused. Running again updates the
records it made, by key: places move, fields change.
"""
from __future__ import annotations

import re

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

#: Properties the importers add for their own bookkeeping, not the person's data.
INTERNAL = {"entity", "kind", "handle", "layer", "part", "block", "block_path", "color", "colour", "linetype",
            "elevation", "lineweight", "text_height", "rotation"}
MAX_FEATURES = 20000
GEOMETRY_FIELD = "shape"


def to_name(text_: str) -> str:
    from app.api.start import to_name as _to_name

    return _to_name(text_)


#: Layer names a file gives that say nothing about the places: the kind is named after the file instead.
_GENERIC = {"points", "point", "polygons", "polygon", "lines", "line", "layer", "layer_0", "0", "default", "features",
            "feature", "geometry", "geometries", "areas", "area", "shapes", "shape", "data", "sheet1", "field"}


def kind_name(layers: list[str], dataset: str | None = None) -> str:
    """A kind named after what the places are: the layer's own name, or -- when the layer is only
    "points" or "polygons", as a GeoJSON file's are (user trial) -- the map data's name."""
    from app.api.start import _singular

    layer = to_name(layers[0]) if len(layers) == 1 else ""
    if (not layer or layer in _GENERIC) and dataset and to_name(dataset) not in _GENERIC:
        return _singular(to_name(dataset)) or "place"
    return _singular(layer or "place") or "place"


def measure(geometry: dict[str, Any]) -> dict[str, float]:
    """`area_m2` of an area, `length_m` of a line -- geodesic on WGS 84, rounded to the metre (or m2)."""
    from pyproj import Geod
    from shapely.geometry import shape

    geod = Geod(ellps="WGS84")
    shp = shape(geometry)
    if shp.geom_type in ("Polygon", "MultiPolygon"):
        area, _ = geod.geometry_area_perimeter(shp)
        return {"area_m2": round(abs(area), 1)}
    if shp.geom_type in ("LineString", "MultiLineString"):
        return {"length_m": round(geod.geometry_length(shp), 1)}
    return {}


def storable(geometry: dict[str, Any]) -> dict[str, Any] | None:
    """The shape as a geometry field holds it: a point, a line or an area as is (lines since migration 0103)."""
    from shapely.geometry import mapping, shape

    kind = geometry.get("type")
    if kind in ("Point", "LineString", "MultiLineString", "Polygon", "MultiPolygon"):
        return geometry
    if kind == "MultiPoint":
        shp = shape(geometry)
        return dict(mapping(shp.representative_point()))
    return None


def _as_key(value: Any) -> str:
    from app.api.start import _as_key as as_key

    return as_key(value)


def _properties(feature: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in (feature.get("properties") or {}).items()
            if k not in INTERNAL and v is not None and not isinstance(v, (dict, list))}


def propose(features: list[dict[str, Any]], layers: list[str], existing: set[str], dataset: str | None = None) -> dict[str, Any]:
    """What making records of these features would make: the kind, its key, its fields."""
    from app.api.start import infer

    usable = [f for f in features if f.get("kind") != "text"]
    columns: dict[str, list[Any]] = {}
    for f in usable:
        for k, v in _properties(f).items():
            columns.setdefault(k, []).append(v)
    n = len(usable)
    key_candidates = [c for c, values in columns.items()
                      if len(values) == n and len({_as_key(v) for v in values}) == n]
    # An id or a code tells records apart better than a name, which is what people read (benchmark,
    # October 2026: "name" became the key, and the records were shown as "—").
    coded = [c for c in key_candidates if to_name(c) in ("id", "key", "code") or to_name(c).endswith(("_id", "_code"))]
    named = [c for c in key_candidates if to_name(c) == "name"]
    key = (coded or named or key_candidates or [None])[0]
    label = next((c for c in columns if c != key and (to_name(c) in ("name", "label", "title") or to_name(c).endswith("_name"))),
                 None)
    fields = []
    for column, values in columns.items():
        data_type, choices = infer(values)
        # The key is offered too, left out: choosing another key keeps it as a field.
        fields.append({"property": column, "name": to_name(column) or "field", "data_type": data_type,
                       "enum_values": choices, "samples": [_as_key(v) for v in values[:3]], "skip": column == key})
    kinds = sorted({f.get("kind") for f in usable})
    name = kind_name(layers, dataset)
    return {
        "layers": layers, "name": name, "exists": name in existing, "features": n,
        "skipped_text": len(features) - n, "shapes": kinds, "key": key, "key_candidates": key_candidates, "label": label,
        "fields": fields, "geometry_field": GEOMETRY_FIELD,
        "measures": [m for m, k in (("area_m2", "polygon"), ("length_m", "line")) if k in kinds],
    }


def build_seed(features: list[dict[str, Any]], plan: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """The plan and the features as a seed, and every value that does not fit its field."""
    from app.api.start import convert
    from app.api.validation import validate_name

    faults: list[str] = []
    # "Grid cell" is grid_cell: the words a person types, made a name (benchmark re-test, October
    # 2026: a space refused the whole layer with only "fix these first").
    name = re.sub(r"[^a-z0-9]+", "_", str(plan["name"]).strip().lower()).strip("_")
    if name and name[0].isdigit():
        name = f"kind_{name}"
    try:
        validate_name(name)
    except ValueError:
        faults.append(f"the kind is named {name!r}; a name is lower case letters, digits and _, starting with a letter")
    fields = [f for f in plan.get("fields") or [] if not f.get("skip")]
    geometry_field = plan.get("geometry_field") or GEOMETRY_FIELD
    usable = [f for f in features if f.get("kind") != "text"]
    kinds = {f.get("kind") for f in usable}
    measures = [m for m, k in (("area_m2", "polygon"), ("length_m", "line")) if k in kinds]
    attributes = [{"name": f["name"], "data_type": f["data_type"],
                   **({"enum_values": f["enum_values"]} if f["data_type"] == "enum" else {})} for f in fields]
    attributes.append({"name": geometry_field, "data_type": "geometry"})
    attributes += [{"name": m, "data_type": "number", "unit": "m2" if m == "area_m2" else "m"} for m in measures]
    seed: dict[str, Any] = {"entity_types": [{"name": name, "role": "location", "attributes": attributes}], "entities": []}
    seen: set[str] = set()
    key_property = plan.get("key")
    label_property = plan.get("label")
    for n, feature in enumerate(usable, start=1):
        props = _properties(feature)
        key = _as_key(props[key_property]) if key_property and props.get(key_property) not in (None, "") \
            else f"{name}_{n}"
        if key in seen:
            faults.append(f"feature {n}: the key {key!r} is used twice; pick another key property")
            continue
        seen.add(key)
        attrs: dict[str, Any] = {}
        for f in fields:
            value = props.get(f["property"])
            if value is None or value == "":
                continue
            try:
                attrs[f["name"]] = convert(value, f["data_type"], f.get("enum_values"))
            except ValueError as exc:
                faults.append(f"feature {key!r}, property {f['property']!r}: {_as_key(value)!r} {exc}")
        shape = storable(feature["geometry"])
        if shape is not None:
            attrs[geometry_field] = shape
        try:
            attrs.update(measure(feature["geometry"]))
        except Exception:  # noqa: BLE001 -- a shape shapely cannot read keeps no measure, and says so
            faults.append(f"feature {key!r}: its shape could not be measured")
        label = _as_key(props[label_property]) if label_property and props.get(label_property) not in (None, "") else None
        seed["entities"].append({"type": name, "key": key, "label": label, "sort_order": n, "attrs": attrs})
    return seed, faults


def match(features: list[dict[str, Any]], match_property: str, keys: set[str]) -> tuple[dict[str, dict], list[str]]:
    """Each record key's shape, found by a feature property; and the property values no record has."""
    shapes: dict[str, dict] = {}
    unmatched: list[str] = []
    for feature in features:
        if feature.get("kind") == "text":
            continue
        value = (feature.get("properties") or {}).get(match_property)
        if value in (None, ""):
            continue
        key = _as_key(value)
        shape = storable(feature["geometry"])
        if key in keys and shape is not None:
            shapes[key] = shape
        else:
            unmatched.append(key)
    return shapes, unmatched


# --- the database ------------------------------------------------------------------


def dataset_domain(db: Session, dataset_id: int, organization_id) -> int | None:
    return db.execute(text("SELECT domain_id FROM gis_dataset WHERE id = :i AND organization_id = :o"),
                      {"i": dataset_id, "o": organization_id}).scalar_one_or_none()


def load(db: Session, dataset_id: int, layers: list[str]) -> list[dict[str, Any]]:
    rows = db.execute(
        text("SELECT f.kind, f.geometry, f.properties, l.name AS layer FROM gis_feature f"
             " JOIN gis_layer l ON l.id = f.layer_id"
             " WHERE f.dataset_id = :d AND l.name = ANY(:layers) ORDER BY l.sort_order, f.id LIMIT :m"),
        {"d": dataset_id, "layers": list(layers), "m": MAX_FEATURES + 1},
    ).mappings().all()
    return [dict(r) for r in rows]


def update_existing(db: Session, domain_id: int, seed: dict[str, Any], existed: set[str]) -> int:
    """Records that were there before: their fields refreshed from the features (places move)."""
    name = seed["entity_types"][0]["name"]
    changed = 0
    for spec in seed["entities"]:
        if spec["key"] not in existed:
            continue
        changed += db.execute(
            text("UPDATE entity e SET attrs = e.attrs || CAST(:a AS jsonb) FROM entity_type t"
                 " WHERE t.id = e.entity_type_id AND t.domain_id = :d AND t.name = :n AND e.key = :k"),
            {"a": json.dumps(spec["attrs"]), "d": domain_id, "n": name, "k": spec["key"]},
        ).rowcount
    return changed


def existing_keys(db: Session, domain_id: int, type_name: str) -> set[str]:
    return set(db.execute(
        text("SELECT e.key FROM entity e JOIN entity_type t ON t.id = e.entity_type_id"
             " WHERE t.domain_id = :d AND t.name = :n"), {"d": domain_id, "n": type_name}).scalars())


def write_shapes(db: Session, domain_id: int, type_name: str, field: str, shapes: dict[str, dict]) -> int:
    from app.seed import plant_domain_seed

    plant_domain_seed(db, domain_id, {"entity_types": [{"name": type_name, "attributes": [
        {"name": field, "data_type": "geometry"}]}]})
    written = 0
    for key, shape in shapes.items():
        written += db.execute(
            text("UPDATE entity e SET attrs = jsonb_set(e.attrs, ARRAY[:f], CAST(:g AS jsonb)) FROM entity_type t"
                 " WHERE t.id = e.entity_type_id AND t.domain_id = :d AND t.name = :n AND e.key = :k"),
            {"f": field, "g": json.dumps(shape), "d": domain_id, "n": type_name, "k": key},
        ).rowcount
    return written


