"""A grid over a boundary, written into the domain (GIS 3, spatial spec §3).

    POST /api/v1/domains/{id}/grids

One transaction: the cell entity type and its attributes (created if
missing), one entity per cell, the `adjacent` relationship type (on the
cell type, to itself) and one edge per shared side. Cells are ordinary
entities: a scenario freezes them like any other data. A grid whose type
already has cells is replaced only when asked (`replace`), after the refusal
has said how many cells and which scenarios use them; runs already made keep
their frozen data.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import requires
from app.core.db import get_db
from app.models.iam import UserAccount
from app.models.v1_domain import AttributeDef, Entity, EntityType, Relationship, RelationshipType
from app.settings_resolve import resolve
from app.spatial.geometry import validate_geometry
from app.spatial.grid import TooManyCells, make_grid, sum_points
from app.spatial.project import OutOfRange

router = APIRouter(prefix="/api/v1", tags=["spatial"])

#: What every cell carries, beside whatever layers are summed into it.
CELL_ATTRIBUTES = [("geometry", "geometry"), ("centroid", "geometry"), ("area_m2", "number"),
                   ("row", "integer"), ("col", "integer"), ("coverage", "number")]
ADJACENT = "adjacent"
MAX_LAYER_ROWS = 200_000


class GridRequest(BaseModel):
    #: An entity whose first geometry attribute is the area to cover...
    boundary_entity_id: int | None = None
    #: ...or GeoJSON given here.
    boundary: dict[str, Any] | None = None
    shape: Literal["square", "hex"]
    size_m: float = Field(gt=0, le=1_000_000)
    entity_type: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=63)
    keep: Literal["centre", "overlap"] = "centre"
    #: Points whose numeric values are summed per cell: rows of
    #: {"lon", "lat", <column>: number}, or GeoJSON Point features.
    layers: list[dict[str, Any]] = Field(default_factory=list, max_length=MAX_LAYER_ROWS)
    replace: bool = False


class GridReport(BaseModel):
    entity_type_id: int
    relationship_type_id: int
    cells: int
    edges: int
    dropped: int
    layer_totals: dict[str, float]
    layer_outside: dict[str, float]


def _points(layers: list[dict[str, Any]]) -> list[tuple[float, float, dict[str, float]]]:
    out = []
    for i, row in enumerate(layers):
        if row.get("type") == "Feature":
            coordinates = (row.get("geometry") or {}).get("coordinates") or [None, None]
            x, y, values = coordinates[0], coordinates[1], row.get("properties") or {}
        else:
            x, y = row.get("lon"), row.get("lat")
            values = {k: v for k, v in row.items() if k not in ("lon", "lat")}
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (x, y)):
            raise HTTPException(422, f"layer row {i} has no numeric lon/lat (or Point coordinates)")
        numbers = {k: float(v) for k, v in values.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
        bad = [k for k in numbers if not k.replace("_", "a").isalnum() or not k[:1].isalpha() or k != k.lower()]
        if bad:
            raise HTTPException(422, f"layer column {bad[0]!r} is not a name an attribute can have (^[a-z][a-z0-9_]*$)")
        out.append((x, y, numbers))
    return out


def _boundary(db: Session, body: GridRequest) -> dict[str, Any]:
    boundary = body.boundary
    if body.boundary_entity_id is not None:
        boundary = db.execute(
            text(
                "SELECT e.attrs -> ad.name FROM entity e JOIN attribute_def ad ON ad.entity_type_id = e.entity_type_id"
                " WHERE e.id = :e AND ad.data_type::text = 'geometry' AND e.attrs ? ad.name"
                " ORDER BY ad.sort_order, ad.name LIMIT 1"
            ),
            {"e": body.boundary_entity_id},
        ).scalar_one_or_none()
        if boundary is None:
            raise HTTPException(422, "that entity has no shape to draw a grid over")
    if boundary is None:
        raise HTTPException(422, "name a boundary: an entity with a geometry, or GeoJSON in `boundary`")
    fault = validate_geometry(boundary)
    if fault:
        raise HTTPException(422, f"boundary: {fault}")
    if boundary.get("type") == "Point":
        raise HTTPException(422, "boundary: a point has no area to cover; give a polygon")
    return boundary


def _scenarios_using(db: Session, domain_id: int, entity_type: str) -> list[int]:
    return list(
        db.execute(
            text(
                "SELECT s.id FROM scenario s JOIN problem p ON p.id = s.problem_id"
                " JOIN model_version mv ON mv.id = s.model_version_id"
                " WHERE p.domain_id = :d AND mv.ir -> 'sets' ? :n ORDER BY s.id"
            ),
            {"d": domain_id, "n": entity_type},
        ).scalars()
    )


def write_grid(db: Session, domain_id: int, body: GridRequest, *, commit: bool = True) -> GridReport:
    """The grid, written; raises HTTPException with a named cause. Commits,
    unless the caller's own transaction is to hold it (template apply)."""
    if db.execute(text("SELECT 1 FROM domain WHERE id = :d"), {"d": domain_id}).first() is None:
        raise HTTPException(404, "domain not found")
    boundary = _boundary(db, body)
    crs = int(resolve(db, domain_id=domain_id)["spatial.crs"].value)
    try:
        cells, edges, dropped = make_grid(boundary, crs=crs, shape=body.shape, size_m=body.size_m, keep=body.keep)
    except (TooManyCells, OutOfRange) as exc:
        raise HTTPException(422, str(exc)) from exc
    sums, lost = sum_points(cells, _points(body.layers), crs)
    columns = sorted({name for values in sums.values() for name in values} | set(lost))
    clash = [c for c in columns if c in {name for name, _ in CELL_ATTRIBUTES}]
    if clash:
        raise HTTPException(422, f"layer column {clash[0]!r} is one every cell already carries; rename it")

    cell_type = db.query(EntityType).filter_by(domain_id=domain_id, name=body.entity_type).one_or_none()
    if cell_type is not None:
        existing = db.execute(text("SELECT count(*) FROM entity WHERE entity_type_id = :t"), {"t": cell_type.id}).scalar_one()
        if existing and not body.replace:
            raise HTTPException(
                409,
                {
                    "message": f"{body.entity_type} already has {existing} cells; send replace: true to make them again "
                               "(runs already made keep their frozen data)",
                    "cells": existing,
                    "scenarios": _scenarios_using(db, domain_id, body.entity_type),
                },
            )
        # Their edges go with them (ON DELETE CASCADE).
        db.execute(text("DELETE FROM entity WHERE entity_type_id = :t"), {"t": cell_type.id})
    else:
        cell_type = EntityType(domain_id=domain_id, name=body.entity_type, role="location")
        db.add(cell_type)
        db.flush()
    have = {a.name: a.data_type for a in db.query(AttributeDef).filter_by(entity_type_id=cell_type.id)}
    for name, kind in [*CELL_ATTRIBUTES, *((c, "number") for c in columns)]:
        if name not in have:
            db.add(AttributeDef(entity_type_id=cell_type.id, name=name, data_type=kind))
        elif have[name] != kind:
            raise HTTPException(422, f"{body.entity_type}.{name} is a {have[name]} attribute; a grid writes a {kind} there")
    db.flush()

    rows = [
        Entity(
            entity_type_id=cell_type.id,
            key=cell.key,
            label=cell.key,
            sort_order=n,
            attrs={"geometry": cell.geometry, "centroid": cell.centroid, "area_m2": cell.area_m2, "row": cell.row,
                   "col": cell.col, "coverage": cell.coverage, **{c: sums.get(cell.key, {}).get(c, 0.0) for c in columns}},
        )
        for n, cell in enumerate(cells)
    ]
    db.add_all(rows)
    db.flush()
    ids = {row.key: row.id for row in rows}

    adjacent = db.query(RelationshipType).filter_by(domain_id=domain_id, name=ADJACENT).one_or_none()
    if adjacent is None:
        adjacent = RelationshipType(domain_id=domain_id, name=ADJACENT, from_type_id=cell_type.id,
                                    to_type_id=cell_type.id, cardinality="many_to_many", is_hierarchy=False)
        db.add(adjacent)
        db.flush()
        db.add(AttributeDef(relationship_type_id=adjacent.id, name="shared_m", data_type="number"))
        db.flush()
    elif (adjacent.from_type_id, adjacent.to_type_id) != (cell_type.id, cell_type.id):
        raise HTTPException(422, f"this domain's {ADJACENT!r} relationship joins other types; it cannot hold this grid's edges")
    db.add_all(
        Relationship(relationship_type_id=adjacent.id, from_entity_id=ids[e.a], to_entity_id=ids[e.b],
                     attrs={"shared_m": e.shared_m})
        for e in edges
    )
    if commit:
        db.commit()
    else:
        db.flush()
    totals = {c: sum(v.get(c, 0.0) for v in sums.values()) for c in columns}
    return GridReport(entity_type_id=cell_type.id, relationship_type_id=adjacent.id, cells=len(cells),
                      edges=len(edges), dropped=dropped, layer_totals=totals, layer_outside=lost)


@router.post("/domains/{domain_id}/grids", status_code=201, response_model=GridReport)
def make_domain_grid(
    domain_id: int,
    body: GridRequest,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(requires("domain.edit")),
) -> GridReport:
    return write_grid(db, domain_id, body)
