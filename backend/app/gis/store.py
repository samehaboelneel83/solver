"""Map data in the database (DXF -> GIS, step 4: store).

An import writes one `gis_dataset`, its `gis_layer`s and every
`gis_feature` in bulk (`execute_values`, a few thousand rows a statement):
GeoJSON in WGS 84, the drawing's own coordinates, properties and bounds. When
the database has PostGIS, a trigger keeps `geom` from `geometry` (migration
0097). Placing a dataset again transforms the stored drawing coordinates;
the file is not needed twice.
"""
from __future__ import annotations

import json
import threading
import time
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.gis import cad
from app.gis.convert import _rebuild, _valid, bounds, place, transform_all  # noqa: F401
from app.gis.crs import Placement

UPLOAD_DAYS = 1
PAGE = 2000

# An upload is parsed once on the upload request, then previewed several times
# before the user imports it. Keep only the most recent small upload's parsed
# drawing in each API process: this avoids repeated DXF parsing while placing a
# cap on memory use. The bytes remain authoritative in `gis_upload`.
_PARSED_UPLOAD_MAX_BYTES = 10 * 1024 * 1024
_PARSED_UPLOAD_TTL_SECONDS = 15 * 60
_parsed_upload_lock = threading.RLock()
_parsed_upload: tuple[str, cad.CadDrawing, float] | None = None


def read_bytes(data: bytes, filename: str = "drawing.dxf") -> cad.CadDrawing:
    """A DXF drawing or any other spatial file (`app.gis.formats`), by its file name."""
    from app.gis.formats import read_any

    return read_any(data, filename)


def cache_upload(upload_id: str, data: bytes, drawing: cad.CadDrawing) -> None:
    """Retain the already parsed drawing for the preview/import steps."""
    global _parsed_upload
    with _parsed_upload_lock:
        _parsed_upload = (upload_id, drawing, time.monotonic()) if len(data) <= _PARSED_UPLOAD_MAX_BYTES else None


def cached_upload(upload_id: str) -> cad.CadDrawing | None:
    """Return the current parsed drawing without loading its database blob."""
    global _parsed_upload
    with _parsed_upload_lock:
        if _parsed_upload is None:
            return None
        key, drawing, cached_at = _parsed_upload
        if time.monotonic() - cached_at >= _PARSED_UPLOAD_TTL_SECONDS:
            _parsed_upload = None
            return None
        return drawing if key == upload_id else None


def clear_upload(upload_id: str) -> None:
    """Release a parsed drawing when its temporary upload is consumed."""
    global _parsed_upload
    with _parsed_upload_lock:
        if _parsed_upload is not None and _parsed_upload[0] == upload_id:
            _parsed_upload = None


def read_upload(upload_id: str, data: bytes, filename: str) -> cad.CadDrawing:
    """Reuse the current parsed upload or parse it once and keep it if small."""
    global _parsed_upload
    with _parsed_upload_lock:
        if _parsed_upload is not None and _parsed_upload[0] == upload_id and \
                time.monotonic() - _parsed_upload[2] < _PARSED_UPLOAD_TTL_SECONDS:
            return _parsed_upload[1]
        drawing = read_bytes(data, filename)
        _parsed_upload = (upload_id, drawing, time.monotonic()) if len(data) <= _PARSED_UPLOAD_MAX_BYTES else None
        return drawing


def has_postgis(db: Session) -> bool:
    return bool(db.execute(text(
        "SELECT 1 FROM information_schema.columns WHERE table_name = 'gis_feature' AND column_name = 'geom'"
    )).scalar_one_or_none())


def _bbox(geometry: dict[str, Any]) -> tuple[float, float, float, float]:
    g = geometry
    pts = [g["coordinates"]] if g["type"] == "Point" else g["coordinates"] if g["type"] == "LineString" \
        else g["coordinates"][0]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def import_drawing(db: Session, *, organization_id, user_id, domain_id: int, name: str, drawing: cad.CadDrawing,
                   placement: Placement, layers: list[str] | None, source: dict[str, Any]) -> int:
    """Store a read drawing as a dataset; returns its id."""
    from psycopg2.extras import execute_values

    keep = set(layers) if layers else None
    feats = [f for f in drawing.features if keep is None or f.layer in keep]
    placed, stats = place(feats, placement)
    by_source = [(feats[i], {"geometry": g, "properties": {"kind": feats[i].kind}}) for i, g in placed]
    geo = [g for _, g in by_source]
    box = bounds(geo)
    notes = list(drawing.notes)
    if stats["repaired"]:
        notes.append(f"{stats['repaired']} polygons crossed themselves and were repaired")
    if stats["dropped"]:
        notes.append(f"{stats['dropped']} features could not be placed and were left out")
    kinds: dict[str, int] = {}
    for _, g in by_source:
        kinds[g["properties"]["kind"]] = kinds.get(g["properties"]["kind"], 0) + 1
    dataset_id = db.execute(text(
        "INSERT INTO gis_dataset (organization_id, domain_id, name, source, placement, bbox, stats, notes, created_by)"
        " VALUES (:o, :d, :n, CAST(:s AS jsonb), CAST(:p AS jsonb), :b, CAST(:st AS jsonb), :notes, :u) RETURNING id"),
        {"o": str(organization_id), "d": domain_id, "n": name, "s": json.dumps(source),
         "p": json.dumps(placement.to_json()), "b": box, "u": str(user_id) if user_id else None,
         "st": json.dumps({"features": len(by_source), "kinds": kinds, "skipped": drawing.skipped, **stats}),
         "notes": notes}).scalar_one()
    layer_ids: dict[str, int] = {}
    order = sorted({f.layer for f, _ in by_source}, key=str.lower)
    for i, layer in enumerate(order):
        info = drawing.layers.get(layer) or cad.CadLayer(name=layer)
        counts: dict[str, int] = {}
        for f, g in by_source:
            if f.layer == layer:
                counts[g["properties"]["kind"]] = counts.get(g["properties"]["kind"], 0) + 1
        layer_ids[layer] = db.execute(text(
            "INSERT INTO gis_layer (organization_id, dataset_id, name, color, visible, kinds, feature_count, sort_order)"
            " VALUES (:o, :ds, :n, :c, :v, CAST(:k AS jsonb), :fc, :so) RETURNING id"),
            {"o": str(organization_id), "ds": dataset_id, "n": layer, "c": info.color.lower(),
             "v": info.on and not info.frozen, "k": json.dumps(counts), "fc": sum(counts.values()), "so": i}).scalar_one()
    rows = []
    for f, g in by_source:
        minx, miny, maxx, maxy = _bbox(g["geometry"])
        props = {"entity": f.entity, **f.props}
        rows.append((str(organization_id), dataset_id, layer_ids[f.layer], g["properties"]["kind"],
                     json.dumps(g["geometry"]), json.dumps({"coords": f.coords}), json.dumps(props, default=str),
                     minx, miny, maxx, maxy))
    cursor = db.connection().connection.cursor()
    for start in range(0, len(rows), PAGE):
        execute_values(cursor,
                       "INSERT INTO gis_feature (organization_id, dataset_id, layer_id, kind, geometry, source, properties,"
                       " minx, miny, maxx, maxy) VALUES %s",
                       rows[start:start + PAGE],
                       template="(%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s, %s, %s)")
    return dataset_id


def replace(db: Session, dataset_id: int, placement: Placement) -> dict[str, Any]:
    """Place a stored dataset again from its drawing coordinates; returns its new bounds and stats."""
    from psycopg2.extras import execute_values

    rows = db.execute(text("SELECT id, kind, source, properties->>'handle' AS handle FROM gis_feature"
                           " WHERE dataset_id = :d AND source IS NOT NULL ORDER BY id"),
                      {"d": dataset_id}).mappings().all()
    feats = [cad.CadFeature(r["kind"], r["source"]["coords"], "", "", {}) for r in rows]
    import numpy as np

    updates = []
    geo = []
    for r, f, pts in zip(rows, feats, transform_all(feats, placement)):
        if not np.all(np.isfinite(pts)):
            continue
        parts = _valid(_rebuild(f, pts))
        if not parts:
            continue
        g = parts[0]
        geo.append({"geometry": g})
        minx, miny, maxx, maxy = _bbox(g)
        updates.append((r["id"], json.dumps(g), minx, miny, maxx, maxy))
    cursor = db.connection().connection.cursor()
    for start in range(0, len(updates), PAGE):
        execute_values(cursor,
                       "UPDATE gis_feature f SET geometry = v.g::jsonb, minx = v.a, miny = v.b, maxx = v.c, maxy = v.e"
                       " FROM (VALUES %s) AS v(id, g, a, b, c, e) WHERE f.id = v.id",
                       updates[start:start + PAGE])
    box = bounds(geo)
    db.execute(text("UPDATE gis_dataset SET placement = CAST(:p AS jsonb), bbox = :b WHERE id = :d"),
               {"p": json.dumps(placement.to_json()), "b": box, "d": dataset_id})
    return {"bbox": box, "features": len(updates)}
