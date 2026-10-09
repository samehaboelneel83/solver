"""Lay items out on a drawing, without the Assistant (owner, 9 October 2026: everything in the platform itself).

    POST /api/v1/layouts/drawings            a DXF (or any map file): its layers, kept a day as an upload
    POST /api/v1/layouts/preview             the layout's counts, grid, aisle and bound, nothing kept
    POST /api/v1/layouts/build               the problem built from it (or checked: dry_run, trial)

The same code the Assistant's `make_layout` runs (`app.agent.layout`): the placement form (`place`, no list of
positions: the placement solver lays items out on the exact grid) or the candidate form (every position listed,
stored as its recipe and built by the run: `generate` positions). The build goes through `/problems/from-spec`,
so it is checked and kept exactly as a plan the Assistant proposes.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.agent import files as agent_files
from app.agent import layout
from app.api.deps import get_current_user, requires
from app.core.db import get_db
from app.models.iam import UserAccount

router = APIRouter(prefix="/api/v1/layouts", tags=["drawing layouts"])


class Item(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    length: float = Field(gt=0, le=10_000, description="metres")
    width: float = Field(gt=0, le=10_000, description="metres")
    rotations: list[Literal[0, 90]] = Field(default_factory=lambda: [0, 90], min_length=1)
    value: float = Field(default=1, description="worth of one")
    count: int | None = Field(default=None, gt=0, description="at most this many (placement form)")


class LayoutOptions(BaseModel):
    upload_id: str
    area_layers: list[str] = Field(min_length=1, description="layers whose polygons are where items may go")
    blocked_layers: list[str] = Field(default_factory=list, description="layers no item may cover")
    access_layers: list[str] = Field(default_factory=list, description="doors, exits: every item reachable from one")
    label_layer: str | None = Field(default=None, description="a text layer naming each area")
    items: list[Item] = Field(min_length=1, max_length=20)
    aisle: float = Field(default=0, ge=0, le=100, description="free width beside each item, metres")
    aisle_side: Literal["long", "short", "any", "none"] = "any"
    step: float | None = Field(default=None, gt=0, le=100, description="grid step in metres; empty: the exact one")
    form: Literal["place", "candidates"] = "place"


class LayoutBuild(LayoutOptions):
    domain_id: int | None = None
    domain_name: str | None = Field(default=None, max_length=200)
    problem_name: str = Field(min_length=1, max_length=200)
    dry_run: bool = False
    trial: bool = False


def _layers(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    """Each layer of a parsed drawing: its name, how many features, and which kinds (polygon, line, point, text)."""
    out = []
    for sheet in parsed.get("sheets") or []:
        name = str(sheet.get("name") or "")
        layer = name.split("__", 1)[1] if "__" in name else name
        columns = sheet.get("columns") or []
        kinds: dict[str, int] = {}
        if "kind" in columns:
            at = columns.index("kind")
            for row in sheet.get("rows") or []:
                kinds[str(row[at])] = kinds.get(str(row[at]), 0) + 1
        out.append({"name": layer, "features": int(sheet.get("total_rows") or len(sheet.get("rows") or [])),
                    "kinds": kinds})
    return out


@router.post("/drawings")
def read_drawing(file: UploadFile = File(...), domain_id: int | None = Form(default=None),
                 db: Session = Depends(get_db), user: UserAccount = Depends(get_current_user)) -> dict[str, Any]:
    """A drawing's layers, and an upload id to lay it out with (kept a day, as a Map Import upload is)."""
    from app.api.gis import MAX_UPLOAD_BYTES

    name = (file.filename or "drawing")[:255]
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(422, "a drawing can be at most 50 MB")
    if not agent_files.is_spatial(name, data):
        raise HTTPException(422, "this is not a drawing or map file the platform reads (DXF, DWG, GeoJSON, KML, "
                                 "shapefile, GeoPackage)")
    try:
        parsed = agent_files.parse_spatial(name, data)
    except agent_files.FileRefused as exc:
        raise HTTPException(422, str(exc)) from exc
    summary = {"sha256": hashlib.sha256(data).hexdigest(), "domain_id": domain_id, "from": "layout",
               "format": parsed["spatial"]["format"]}
    upload_id = db.execute(text(
        "INSERT INTO gis_upload (organization_id, created_by, filename, size_bytes, data, summary)"
        " VALUES (:o, :u, :f, :s, :d, CAST(:sm AS jsonb)) RETURNING id"),
        {"o": user.organization_id, "u": str(user.id), "f": name, "s": len(data), "d": data,
         "sm": json.dumps(summary)}).scalar_one()
    db.commit()
    spatial = parsed.get("spatial") or {}
    return {"upload_id": str(upload_id), "filename": name, "layers": _layers(parsed),
            "local_metres": bool(spatial.get("local_metres")), "notes": spatial.get("notes") or []}


def _drawing(db: Session, upload_id: str, user: UserAccount) -> dict[str, Any]:
    from app.api.gis import _upload

    row = _upload(db, upload_id, user)
    try:
        return agent_files.parse_spatial(row["filename"], bytes(row["data"]), upload_id=upload_id)
    except agent_files.FileRefused as exc:
        raise HTTPException(422, str(exc)) from exc


def _lay_out(options: LayoutOptions, drawing: dict[str, Any], folder: str) -> dict[str, Any]:
    known = {layer["name"] for layer in _layers(drawing)}
    for field in ("area_layers", "blocked_layers", "access_layers"):
        missing = [name for name in getattr(options, field) if name not in known]
        if missing:
            raise HTTPException(422, detail=[{"loc": [field], "msg": f"not a layer of this drawing: {', '.join(missing)}"}])
    if options.label_layer and options.label_layer not in known:
        raise HTTPException(422, detail=[{"loc": ["label_layer"], "msg": "not a layer of this drawing"}])
    kwargs = dict(area_layers=options.area_layers, blocked_layers=options.blocked_layers,
                  label_layer=options.label_layer, items=[item.model_dump() for item in options.items],
                  aisle=options.aisle, aisle_side=options.aisle_side, step=options.step,
                  access_layers=options.access_layers or None)
    try:
        if options.form == "place":
            return layout.place([drawing], folder, **kwargs)
        return layout.generated([drawing], folder, **kwargs)
    except (layout.LayoutRefused, ValueError) as exc:
        raise HTTPException(422, detail=[{"loc": ["layout"], "msg": str(exc)}]) from exc


@router.post("/preview")
def preview(options: LayoutOptions, db: Session = Depends(get_db),
            user: UserAccount = Depends(get_current_user)) -> dict[str, Any]:
    """What the layout would be -- the grid, the aisle as modelled, the counts and the upper bound -- and the model
    it makes; nothing is kept."""
    drawing = _drawing(db, options.upload_id, user)
    with tempfile.TemporaryDirectory(prefix="layout-") as folder:
        out = _lay_out(options, drawing, folder)
    spec = out.pop("spec")
    out["model"] = spec["ir"]
    return out


@router.post("/build")
def build(body: LayoutBuild, request: Request, db: Session = Depends(get_db),
          user: UserAccount = Depends(requires("model.publish"))) -> dict[str, Any]:
    """The problem the layout makes, checked and built through `/problems/from-spec` (with `dry_run` and `trial`
    as there): its records, model and Base scenario."""
    from app.api.model_spec import ModelSpec, build_from_spec

    drawing = _drawing(db, body.upload_id, user)
    with tempfile.TemporaryDirectory(prefix="layout-") as folder:
        out = _lay_out(body, drawing, folder)
        files = []
        for name in out["files"]:
            with open(os.path.join(folder, name), "rb") as handle:
                files.append(agent_files.parse(name, handle.read(), max_rows=agent_files.MAX_GENERATED_ROWS))
    spec = out.pop("spec")
    seed = agent_files.expand(spec["seed"], files)
    built = build_from_spec(ModelSpec(domain_id=body.domain_id, domain_name=body.domain_name,
                                      problem_name=body.problem_name, seed=seed, ir=spec["ir"],
                                      note=f"Laid out on {drawing.get('name', 'a drawing')} ({out.get('form')})",
                                      dry_run=body.dry_run, trial=body.trial), request, db, user)
    return {**built, "layout": out}
