"""Map data: CAD drawings imported as GIS layers (DXF -> GIS).

    POST   /api/v1/gis/uploads                       a .dxf (multipart `file`, `domain_id`) -> its layers,
                                                     extent, units and the likely coordinate systems
    POST   /api/v1/gis/uploads/{id}/candidates       {region?, point?} -> the likely systems for a site roughly there
    POST   /api/v1/gis/uploads/{id}/preview          {placement, units?, layers?} -> where it lands, as GeoJSON
    GET    /api/v1/gis/regions                       the countries a site can be said to be in
    POST   /api/v1/gis/datasets                      {upload_id, domain_id, name, placement, units?, layers?}
    GET    /api/v1/gis/datasets?domain_id=
    GET    /api/v1/gis/datasets/{id}                 the dataset and its layers
    GET    /api/v1/gis/datasets/{id}/features        ?layers=1,2&bbox=w,s,e,n&limit= -> GeoJSON (WGS 84)
    GET    /api/v1/gis/datasets/{id}/candidates      the likely coordinate systems for its drawing, as for an upload
    PUT    /api/v1/gis/datasets/{id}/placement       {placement, units?} -> placed again from the drawing's coordinates
    PATCH  /api/v1/gis/datasets/{id}                 {name}
    DELETE /api/v1/gis/datasets/{id}
    GET    /api/v1/gis/datasets/{id}/export          ?format=geojson|csv&layer= -> a file
    PATCH  /api/v1/gis/layers/{id}                   {name?, color?, visible?}
    GET    /api/v1/gis/crs?q=                        coordinate systems in the EPSG registry
    GET    /api/v1/gis/crs/{code}                    one, with its area of use

The pipeline: parse (`app.gis.cad`) -> choose where it is (`app.gis.crs`:
any EPSG code, or local coordinates anchored on the map) -> geometry in WGS
84 (`app.gis.convert`) -> the database (`app.gis.store`; PostGIS `geom`
when the extension is there) -> the map. An upload is kept a day so the
placement can be tried and previewed before anything is imported.

Reads need a signed-in user; writes need `domain.edit`.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import audit
from app.api.deps import get_current_user, requires
from app.core.db import get_db
from app.gis import cad, crs, store
from app.gis.convert import bounds, to_geojson
from app.models.iam import UserAccount

router = APIRouter(prefix="/api/v1/gis", tags=["map data"])

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
PREVIEW_FEATURES = 6000
MAX_FEATURES_PAGE = 100_000
_DATASET = "id, domain_id, name, source, placement, bbox, stats, notes, created_at, updated_at"


class PreviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    placement: dict[str, Any]
    units: float | None = Field(default=None, gt=0)
    layers: list[str] | None = None


class WhereBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    region: str | None = Field(default=None, max_length=60)
    #: [lon, lat]: a position near the site, more precise than a country.
    point: tuple[float, float] | None = None


def _where(region: str | None, point) -> tuple[str | None, tuple[float, float] | None]:
    if region and region not in crs.REGIONS:
        raise HTTPException(422, f"no region called {region!r}; see GET /api/v1/gis/regions")
    if point is not None and not (-180 <= point[0] <= 180 and -90 <= point[1] <= 90):
        raise HTTPException(422, "point is [longitude, latitude]")
    return region or None, (float(point[0]), float(point[1])) if point is not None else None


class ImportBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    upload_id: str
    domain_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=200)
    placement: dict[str, Any]
    units: float | None = Field(default=None, gt=0)
    layers: list[str] | None = None


class PlaceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    placement: dict[str, Any]
    units: float | None = Field(default=None, gt=0)


class DatasetPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)


class LayerPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=255)
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    visible: bool | None = None


def _domain(db: Session, domain_id: int, user: UserAccount) -> None:
    if db.execute(text("SELECT 1 FROM domain WHERE id = :d AND organization_id = :o"),
                  {"d": domain_id, "o": user.organization_id}).scalar_one_or_none() is None:
        raise HTTPException(404, "Domain not found")


def _audit(db: Session, user: UserAccount, action: str, identity: int) -> None:
    audit.record(db, organization_id=user.organization_id, actor_id=user.id,
                 api_key_id=getattr(user, "api_key_id", None), action=action,
                 object_type="gis_dataset", object_id=identity)


def _upload(db: Session, upload_id: str, user: UserAccount) -> Any:
    try:
        row = db.execute(text("SELECT id, filename, size_bytes, data, summary FROM gis_upload"
                              " WHERE id = CAST(:i AS uuid) AND organization_id = :o"),
                         {"i": upload_id, "o": user.organization_id}).mappings().one_or_none()
    except Exception:  # noqa: BLE001 -- not a uuid
        db.rollback()
        row = None
    if row is None:
        raise HTTPException(404, "That upload is gone (uploads are kept a day); upload the file again")
    return row


def _dataset(db: Session, dataset_id: int, user: UserAccount) -> Any:
    row = db.execute(text(f"SELECT {_DATASET} FROM gis_dataset WHERE id = :i AND organization_id = :o"),
                     {"i": dataset_id, "o": user.organization_id}).mappings().one_or_none()
    if row is None:
        raise HTTPException(404, "Map data not found")
    return row


def _placement(data: dict[str, Any], units: float | None) -> crs.Placement:
    try:
        return crs.Placement.parse(data, units)
    except crs.PlacementError as exc:
        raise HTTPException(422, [{"type": "value_error", "loc": ["body", "placement"], "msg": str(exc), "input": None}]) from exc


def _hints(db: Session, domain_id: int) -> tuple[int | None, tuple[float, float] | None]:
    from app.settings_resolve import resolve

    try:
        usual = int(resolve(db, domain_id=domain_id)["spatial.drawing_crs"].value or 0) or None
    except (KeyError, TypeError, ValueError):
        usual = None
    near = db.execute(text("SELECT bbox FROM gis_dataset WHERE domain_id = :d AND bbox IS NOT NULL"
                           " ORDER BY updated_at DESC LIMIT 1"), {"d": domain_id}).scalar_one_or_none()
    return usual, ((near[0] + near[2]) / 2, (near[1] + near[3]) / 2) if near else None


@router.get("/regions")
def regions(user: UserAccount = Depends(get_current_user)) -> dict[str, Any]:
    return {"items": [{"name": k, "bbox": list(v)} for k, v in crs.REGIONS.items()]}


@router.post("/uploads", status_code=201)
def upload(
    file: UploadFile = File(...),
    domain_id: int = Form(..., gt=0),
    region: str = Form("", max_length=60),
    db: Session = Depends(get_db),
    user: UserAccount = Depends(requires("domain.edit")),
) -> dict[str, Any]:
    _domain(db, domain_id, user)
    name = (file.filename or "drawing.dxf")[:255]
    if not name.lower().endswith(".dxf"):
        raise HTTPException(415, "send a .dxf drawing (a .dwg must be saved as DXF from your CAD program first)")
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "the drawing is larger than 50 MB")
    try:
        drawing = store.read_bytes(data)
    except cad.CadError as exc:
        raise HTTPException(422, str(exc)) from exc
    if not drawing.features:
        raise HTTPException(422, "the drawing's model space has nothing we can show on a map")
    summary = drawing.summary()
    usual, near = _hints(db, domain_id)
    where_region, _ = _where(region or None, None)
    offered = crs.candidates(drawing.extent, drawing.unit_metres, geodata=drawing.geodata, usual=usual, near=near,
                             region=where_region)
    db.execute(text("DELETE FROM gis_upload WHERE created_at < now() - make_interval(days => :d)"),
               {"d": store.UPLOAD_DAYS})
    upload_id = db.execute(text(
        "INSERT INTO gis_upload (organization_id, created_by, filename, size_bytes, data, summary)"
        " VALUES (:o, :u, :f, :s, :d, CAST(:sm AS jsonb)) RETURNING id"),
        {"o": user.organization_id, "u": str(user.id), "f": name, "s": len(data), "d": data,
         "sm": json.dumps({**summary, "sha256": hashlib.sha256(data).hexdigest(), "domain_id": domain_id})}).scalar_one()
    db.commit()
    return {"upload_id": str(upload_id), "filename": name, "size_bytes": len(data), "summary": summary,
            "candidates": offered, "utm_zones": crs.utm_zones(drawing.extent, drawing.unit_metres),
            "unit_choices": cad.UNIT_CHOICES}


@router.post("/uploads/{upload_id}/candidates")
def upload_candidates(
    upload_id: str,
    body: WhereBody,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(get_current_user),
) -> dict[str, Any]:
    """The likely coordinate systems again, for a site said to be in `region` or near `point`."""
    row = _upload(db, upload_id, user)
    s = row["summary"]
    region, point = _where(body.region, body.point)
    usual, near = _hints(db, s["domain_id"]) if s.get("domain_id") else (None, None)
    return {"candidates": crs.candidates(s.get("extent"), s.get("unit_metres"), geodata=s.get("geodata"), usual=usual,
                                         near=near, region=region, point=point)}


@router.post("/uploads/{upload_id}/preview")
def preview(
    upload_id: str,
    body: PreviewBody,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(get_current_user),
) -> dict[str, Any]:
    row = _upload(db, upload_id, user)
    drawing = store.read_bytes(bytes(row["data"]))
    placement = _placement(body.placement, body.units or drawing.unit_metres)
    keep = set(body.layers) if body.layers else None
    feats = [f for f in drawing.features if keep is None or f.layer in keep]
    step = max(1, len(feats) // PREVIEW_FEATURES)
    shown = feats[::step]
    geo, stats = to_geojson(shown, placement)
    box = bounds(to_geojson(feats, placement)[0]) if step > 1 else bounds(geo)
    warnings = []
    if box is None:
        warnings.append("nothing could be placed with this coordinate system")
    else:
        w, s, e, n = box
        if not (-180 <= w <= 180 and -90 <= s <= 90 and -180 <= e <= 180 and -90 <= n <= 90):
            warnings.append("the drawing would fall off the map: this is not its coordinate system")
        elif (e - w) > 5 or (n - s) > 5:
            warnings.append(f"the drawing would be {e - w:.1f}° wide: check the units and the coordinate system")
        if placement.kind == "epsg":
            info = crs.crs_info(placement.code)
            if info["bounds"] and not crs._inside((w + e) / 2, (s + n) / 2, info["bounds"]):
                warnings.append(f"it would fall outside {info['name']}'s area of use ({info['area']})")
    return {"placement": placement.to_json(), "bbox": box, "features": {"type": "FeatureCollection", "features": geo},
            "sampled": step > 1, "total": len(feats), "warnings": warnings, **stats}


@router.post("/datasets", status_code=201)
def import_dataset(
    body: ImportBody,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(requires("domain.edit")),
) -> dict[str, Any]:
    _domain(db, body.domain_id, user)
    row = _upload(db, body.upload_id, user)
    drawing = store.read_bytes(bytes(row["data"]))
    placement = _placement(body.placement, body.units or drawing.unit_metres)
    unknown = set(body.layers or []) - set(drawing.layers)
    if unknown:
        raise HTTPException(422, f"the drawing has no layer {sorted(unknown)[0]!r}")
    source = {"filename": row["filename"], "format": "dxf", "size_bytes": row["size_bytes"],
              "version": drawing.version, "units": drawing.units_name, "unit_metres": drawing.unit_metres,
              "extent": list(drawing.extent) if drawing.extent else None, "sha256": row["summary"].get("sha256"),
              "geodata": drawing.geodata}
    dataset_id = store.import_drawing(db, organization_id=user.organization_id, user_id=user.id,
                                      domain_id=body.domain_id, name=body.name, drawing=drawing,
                                      placement=placement, layers=body.layers, source=source)
    db.execute(text("DELETE FROM gis_upload WHERE id = CAST(:i AS uuid)"), {"i": body.upload_id})
    _audit(db, user, "gis.import", dataset_id)
    db.commit()
    return get_dataset(dataset_id, db, user)


@router.get("/datasets")
def list_datasets(
    domain_id: int = Query(gt=0),
    db: Session = Depends(get_db),
    user: UserAccount = Depends(get_current_user),
) -> dict[str, Any]:
    _domain(db, domain_id, user)
    rows = db.execute(text(
        f"SELECT {_DATASET}, (SELECT count(*) FROM gis_layer l WHERE l.dataset_id = d.id) AS layers"
        " FROM gis_dataset d WHERE domain_id = :d AND organization_id = :o ORDER BY updated_at DESC"),
        {"d": domain_id, "o": user.organization_id}).mappings().all()
    return {"items": [dict(r) for r in rows], "postgis": store.has_postgis(db)}


@router.get("/datasets/{dataset_id}")
def get_dataset(
    dataset_id: int,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(get_current_user),
) -> dict[str, Any]:
    row = _dataset(db, dataset_id, user)
    layers = db.execute(text("SELECT id, name, color, visible, kinds, feature_count, sort_order FROM gis_layer"
                             " WHERE dataset_id = :d ORDER BY sort_order, name"), {"d": dataset_id}).mappings().all()
    return {**dict(row), "layers": [dict(l) for l in layers], "postgis": store.has_postgis(db)}


@router.patch("/datasets/{dataset_id}")
def rename_dataset(
    dataset_id: int,
    body: DatasetPatch,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(requires("domain.edit")),
) -> dict[str, Any]:
    _dataset(db, dataset_id, user)
    db.execute(text("UPDATE gis_dataset SET name = :n WHERE id = :i"), {"n": body.name, "i": dataset_id})
    _audit(db, user, "gis.rename", dataset_id)
    db.commit()
    return get_dataset(dataset_id, db, user)


@router.delete("/datasets/{dataset_id}", status_code=204)
def delete_dataset(
    dataset_id: int,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(requires("domain.edit")),
) -> Response:
    _dataset(db, dataset_id, user)
    db.execute(text("DELETE FROM gis_dataset WHERE id = :i"), {"i": dataset_id})
    _audit(db, user, "gis.delete", dataset_id)
    db.commit()
    return Response(status_code=204)


def _layer_ids(db: Session, dataset_id: int, layers: str | None) -> list[int] | None:
    if not layers:
        return None
    try:
        return [int(x) for x in layers.split(",") if x.strip()]
    except ValueError as exc:
        raise HTTPException(422, "layers is a comma-separated list of layer ids") from exc


@router.get("/datasets/{dataset_id}/features")
def features(
    dataset_id: int,
    layers: str | None = Query(None, description="comma-separated layer ids; all when absent"),
    bbox: str | None = Query(None, description="west,south,east,north in degrees"),
    limit: int = Query(MAX_FEATURES_PAGE, ge=1, le=MAX_FEATURES_PAGE),
    db: Session = Depends(get_db),
    user: UserAccount = Depends(get_current_user),
) -> dict[str, Any]:
    _dataset(db, dataset_id, user)
    where = ["f.dataset_id = :d"]
    params: dict[str, Any] = {"d": dataset_id, "lim": limit}
    ids = _layer_ids(db, dataset_id, layers)
    if ids is not None:
        where.append("f.layer_id = ANY(:ids)")
        params["ids"] = ids
    if bbox:
        try:
            w, s, e, n = [float(v) for v in bbox.split(",")]
        except ValueError as exc:
            raise HTTPException(422, "bbox is west,south,east,north") from exc
        where.append("f.maxx >= :w AND f.minx <= :e AND f.maxy >= :s AND f.miny <= :n")
        params.update(w=w, s=s, e=e, n=n)
    rows = db.execute(text(
        "SELECT f.id, f.layer_id, l.name AS layer, f.kind, f.geometry, f.properties FROM gis_feature f"
        " JOIN gis_layer l ON l.id = f.layer_id WHERE " + " AND ".join(where) + " ORDER BY f.id LIMIT :lim"),
        params).mappings().all()
    return {"type": "FeatureCollection", "truncated": len(rows) >= limit,
            "features": [{"type": "Feature", "id": r["id"], "geometry": r["geometry"],
                          "properties": {"layer_id": r["layer_id"], "layer": r["layer"], "kind": r["kind"],
                                         **r["properties"]}} for r in rows]}


@router.get("/datasets/{dataset_id}/candidates")
def dataset_candidates(
    dataset_id: int,
    region: str | None = Query(None, max_length=60),
    lon: float | None = Query(None, ge=-180, le=180),
    lat: float | None = Query(None, ge=-90, le=90),
    db: Session = Depends(get_db),
    user: UserAccount = Depends(get_current_user),
) -> dict[str, Any]:
    row = _dataset(db, dataset_id, user)
    source = row["source"] or {}
    extent = source.get("extent")
    usual, _ = _hints(db, row["domain_id"])
    where_region, point = _where(region, (lon, lat) if lon is not None and lat is not None else None)
    return {"candidates": crs.candidates(extent, source.get("unit_metres"), geodata=source.get("geodata"), usual=usual,
                                         region=where_region, point=point),
            "utm_zones": crs.utm_zones(extent, source.get("unit_metres")), "extent": extent, "units": source.get("units")}


@router.put("/datasets/{dataset_id}/placement")
def place_again(
    dataset_id: int,
    body: PlaceBody,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(requires("domain.edit")),
) -> dict[str, Any]:
    row = _dataset(db, dataset_id, user)
    placement = _placement(body.placement, body.units or (row["source"] or {}).get("unit_metres"))
    store.replace(db, dataset_id, placement)
    _audit(db, user, "gis.place", dataset_id)
    db.commit()
    return get_dataset(dataset_id, db, user)


@router.patch("/layers/{layer_id}")
def edit_layer(
    layer_id: int,
    body: LayerPatch,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(requires("domain.edit")),
) -> dict[str, Any]:
    row = db.execute(text("SELECT id, dataset_id FROM gis_layer WHERE id = :i AND organization_id = :o"),
                     {"i": layer_id, "o": user.organization_id}).mappings().one_or_none()
    if row is None:
        raise HTTPException(404, "Layer not found")
    sets, params = [], {"i": layer_id}
    for key, value in body.model_dump(exclude_none=True).items():
        sets.append(f"{key} = :{key}")
        params[key] = value.lower() if key == "color" else value
    if sets:
        try:
            db.execute(text(f"UPDATE gis_layer SET {', '.join(sets)} WHERE id = :i"), params)
        except Exception as exc:  # noqa: BLE001 -- a name the dataset already has
            db.rollback()
            raise HTTPException(409, "this map data already has a layer of that name") from exc
        db.commit()
    return dict(db.execute(text("SELECT id, name, color, visible, kinds, feature_count, sort_order FROM gis_layer"
                                " WHERE id = :i"), {"i": layer_id}).mappings().one())


@router.get("/datasets/{dataset_id}/export")
def export(
    dataset_id: int,
    format: str = Query("geojson", pattern="^(geojson|csv)$"),
    layer: int | None = None,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(get_current_user),
) -> Response:
    row = _dataset(db, dataset_id, user)
    collection = features(dataset_id, str(layer) if layer else None, None, MAX_FEATURES_PAGE, db, user)
    stem = "".join(c if c.isalnum() or c in "-_" else "_" for c in row["name"])[:60] or "map-data"
    if format == "geojson":
        body = json.dumps({"type": "FeatureCollection", "name": row["name"],
                           "crs_note": "WGS 84 longitude, latitude (EPSG:4326)",
                           "features": collection["features"]})
        return Response(body, media_type="application/geo+json",
                        headers={"Content-Disposition": f'attachment; filename="{stem}.geojson"'})
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["id", "layer", "kind", "entity", "text", "wkt", "properties"])
    from shapely.geometry import shape

    for f in collection["features"]:
        p = f["properties"]
        writer.writerow([f["id"], p.get("layer"), p.get("kind"), p.get("entity"), p.get("text", ""),
                         shape(f["geometry"]).wkt,
                         json.dumps({k: v for k, v in p.items() if k not in ("layer", "kind", "entity", "text", "layer_id")})])
    return Response(out.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{stem}.csv"'})


@router.get("/crs")
def search_crs(q: str = Query(..., min_length=1, max_length=80),
               user: UserAccount = Depends(get_current_user)) -> dict[str, Any]:
    return {"items": crs.search(q)}


@router.get("/crs/{code}")
def get_crs(code: int, user: UserAccount = Depends(get_current_user)) -> dict[str, Any]:
    try:
        return crs.crs_info(code)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(404, f"EPSG:{code} is not in the registry") from exc
