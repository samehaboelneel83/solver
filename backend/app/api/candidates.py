"""Candidate records for optimization models.

    POST /api/v1/candidate-sets                 supplied candidate rows -> domain records
    POST /api/v1/candidate-sets/from-map        placement candidates + occupancy links from a CAD upload

Candidate rows are ordinary domain entities, so a Problem IR can use them as
a decision set without copying their coordinates into a prompt or request.
"""
from __future__ import annotations

import csv
import json
import re
import tempfile
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app import audit
from app.agent import files as agent_files
from app.api.deps import get_current_user, requires
from app.api.validation import NAME_PATTERN, field_error
from app.core.db import get_db
from app.crud.db_errors import translate_db_error
from app.models.iam import UserAccount
from app.models.v1_domain import EntityType, RelationshipType

router = APIRouter(prefix="/api/v1/candidate-sets", tags=["candidates"])

MAX_SUPPLIED = 100_000
MAX_GENERATED_ENTITIES = 150_000
MAX_GENERATED_LINKS = 200_000


class CandidateAttribute(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=63)
    data_type: str = Field(pattern=r"^(integer|number|text|boolean|enum|time|date|geometry|reference)$")
    required: bool = False
    unit: str | None = Field(default=None, max_length=40)
    enum_values: list[str] | None = None
    default_value: Any = None
    target: str | None = Field(default=None, min_length=1, max_length=63)


class CandidateRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1, max_length=255)
    label: str | None = Field(default=None, max_length=500)
    attrs: dict[str, Any] = Field(default_factory=dict)


class CandidateSetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    domain_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=100)
    role: str = Field(default="resource", pattern=r"^(agent|resource|time|location|task|org|other)$")
    attributes: list[CandidateAttribute] = Field(default_factory=list, max_length=60)
    candidates: list[CandidateRecord] = Field(min_length=1, max_length=MAX_SUPPLIED)


class LayoutItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=63)
    length: float = Field(gt=0)
    width: float = Field(gt=0)
    rotations: list[int] = Field(default_factory=lambda: [0, 90], min_length=1, max_length=2)
    value: float = 1


class LayoutCandidatesCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    domain_id: int = Field(gt=0)
    upload_id: str
    name: str = Field(min_length=1, max_length=80)
    area_layers: list[str] = Field(min_length=1, max_length=20)
    blocked_layers: list[str] = Field(default_factory=list, max_length=20)
    label_layer: str | None = Field(default=None, max_length=255)
    items: list[LayoutItem] = Field(min_length=1, max_length=20)
    aisle: float = Field(default=0, ge=0, le=20)
    aisle_side: str = Field(default="short", pattern=r"^(short|long|any|none)$")
    step: float | None = Field(default=None, gt=0)
    area_indices: list[int] | None = Field(default=None, max_length=1000)


def _domain(db: Session, domain_id: int, user: UserAccount) -> None:
    exists = db.execute(text("SELECT 1 FROM domain WHERE id = :d AND organization_id = :o"),
                        {"d": domain_id, "o": user.organization_id}).scalar_one_or_none()
    if exists is None:
        raise HTTPException(404, "Domain not found")


def _names(name: str) -> tuple[str, str]:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "candidates"
    suffix = uuid4().hex[:8]
    prefix = f"cs_{slug[:28]}_{suffix}"
    return f"{prefix}_candidate", f"{prefix}_cell"


def _check_attributes(attributes: list[CandidateAttribute]) -> None:
    names = [a.name for a in attributes]
    if any(not re.fullmatch(NAME_PATTERN, name) or name == "id" for name in names):
        raise field_error("attributes", "attribute names use lower case letters, digits and _ (not id)", names)
    if len(set(names)) != len(names):
        raise field_error("attributes", "attribute names must be unique", names)
    for attribute in attributes:
        if (attribute.data_type == "enum") != (attribute.enum_values is not None):
            raise field_error(["attributes", attribute.name, "enum_values"],
                              "enum values are required exactly when data_type is enum", attribute.enum_values)
        if attribute.enum_values is not None and (not attribute.enum_values or len(set(attribute.enum_values)) != len(attribute.enum_values)):
            raise field_error(["attributes", attribute.name, "enum_values"],
                              "enum values must be non-empty and unique", attribute.enum_values)
        if (attribute.data_type == "reference") != (attribute.target is not None):
            raise field_error(["attributes", attribute.name, "target"],
                              "target is required exactly when data_type is reference", attribute.target)


def _commit_seed(db: Session, user: UserAccount, domain_id: int, seed: dict[str, Any],
                 candidate_type: str, counts: dict[str, int]) -> dict[str, Any]:
    from app.seed import plant_domain_seed

    try:
        # Both routes mint unique, suffixed entity and relationship names, so
        # the seed writer can skip scanning existing records/links in a large
        # domain before inserting a large candidate batch.
        plant_domain_seed(db, domain_id, seed, fresh_types=True)
        entity_type = db.execute(select(EntityType).where(
            EntityType.domain_id == domain_id, EntityType.name == candidate_type)).scalar_one()
        db.flush()
        audit.record(db, organization_id=user.organization_id, actor_id=user.id,
                     api_key_id=getattr(user, "api_key_id", None), action="candidates.create",
                     object_type="candidate_set", object_id=entity_type.id, after=counts)
        db.commit()
        return {"candidate_type_id": entity_type.id, "candidate_type": candidate_type}
    except DBAPIError as exc:
        db.rollback()
        raise translate_db_error(exc, "candidate set") from exc
    except Exception:
        db.rollback()
        raise


@router.post("", status_code=201)
def create_candidate_set(body: CandidateSetCreate, db: Session = Depends(get_db),
                         user: UserAccount = Depends(requires("domain.edit"))) -> dict[str, Any]:
    """Create a set from candidate records a client already has (for example a CSV-derived shortlist)."""
    _domain(db, body.domain_id, user)
    _check_attributes(body.attributes)
    reference_targets = {a.target for a in body.attributes if a.target}
    if reference_targets:
        found = set(db.execute(select(EntityType.name).where(
            EntityType.domain_id == body.domain_id, EntityType.name.in_(reference_targets))).scalars())
        missing = reference_targets - found
        if missing:
            raise field_error("attributes", f"reference target types are not in this domain: {sorted(missing)}", None)
    keys = [c.key for c in body.candidates]
    if len(set(keys)) != len(keys):
        raise field_error("candidates", "candidate keys must be unique within a set", None)
    declared = {a.name for a in body.attributes}
    for i, candidate in enumerate(body.candidates):
        unknown = set(candidate.attrs) - declared
        if unknown:
            raise field_error(["candidates", i, "attrs"], f"undeclared attributes: {sorted(unknown)}", candidate.attrs)

    candidate_type, _ = _names(body.name)
    seed = {"entity_types": [{"name": candidate_type, "role": body.role,
                              "attributes": [a.model_dump(exclude_none=True) for a in body.attributes]}],
            "entities": [{"type": candidate_type, **c.model_dump()} for c in body.candidates]}
    counts = {"candidates": len(body.candidates), "cells": 0, "links": 0}
    result = _commit_seed(db, user, body.domain_id, seed, candidate_type, counts)
    return {**result, "domain_id": body.domain_id, "counts": counts,
            "read_candidates": f"/api/v1/entities?entity_type_id={result['candidate_type_id']}"}


def _csv_rows(path: Path) -> list[dict[str, Any]]:
    def cell(value: str) -> Any:
        if value == "":
            return None
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value

    with path.open(newline="", encoding="utf-8") as source:
        return [{k: cell(v) for k, v in row.items()} for row in csv.DictReader(source)]


def _renamed(value: Any, names: dict[str, str]) -> Any:
    if isinstance(value, str):
        return names.get(value, value)
    if isinstance(value, list):
        return [_renamed(item, names) for item in value]
    if isinstance(value, dict):
        return {key: _renamed(item, names) for key, item in value.items()}
    return value


@router.post("/from-map", status_code=201)
def create_layout_candidate_set(body: LayoutCandidatesCreate, db: Session = Depends(get_db),
                                user: UserAccount = Depends(requires("domain.edit"))) -> dict[str, Any]:
    """Generate exact-size placement candidates server-side from a stored CAD/GIS upload."""
    _domain(db, body.domain_id, user)
    try:
        upload_id = str(UUID(body.upload_id))
    except ValueError as exc:
        raise field_error("upload_id", "must be a valid upload id", body.upload_id) from exc
    upload = db.execute(text("SELECT filename, data, summary FROM gis_upload WHERE id = CAST(:i AS uuid) "
                             "AND organization_id = :o"),
                        {"i": upload_id, "o": user.organization_id}).mappings().one_or_none()
    if upload is None:
        raise HTTPException(404, "Map upload not found")
    summary = upload["summary"] or {}
    if summary.get("domain_id") not in (None, body.domain_id):
        raise HTTPException(422, "the map upload belongs to a different domain")
    try:
        source = agent_files.parse_spatial(upload["filename"], bytes(upload["data"]))
    except agent_files.FileRefused as exc:
        raise HTTPException(422, str(exc)) from exc

    from app.agent import layout

    candidate_type, cell_type = _names(body.name)
    prefix = candidate_type.removesuffix("_candidate")
    rel_occupies, rel_keeps = f"{prefix}_occupies", f"{prefix}_keeps_free"
    with tempfile.TemporaryDirectory(prefix="oaas-candidates-") as temp:
        try:
            out = layout.make([source], temp, area_layers=body.area_layers, blocked_layers=body.blocked_layers,
                              label_layer=body.label_layer, items=[i.model_dump() for i in body.items],
                              aisle=body.aisle, aisle_side=body.aisle_side, step=body.step,
                              area_indices=body.area_indices, prefix="candidate_set")
        except (layout.LayoutRefused, TypeError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc
        root = Path(temp)
        item_rows = _csv_rows(root / "candidate_set_items.csv")
        cell_rows = _csv_rows(root / "candidate_set_cells.csv")
        occupies = _csv_rows(root / "candidate_set_occupies.csv")
        keeps = _csv_rows(root / "candidate_set_keeps_free.csv") if "candidate_set_keeps_free.csv" in out["files"] else []

    if len(item_rows) + len(cell_rows) > MAX_GENERATED_ENTITIES:
        raise HTTPException(413, f"candidate and cell records exceed {MAX_GENERATED_ENTITIES:,}; generate fewer areas per request")
    if len(occupies) + len(keeps) > MAX_GENERATED_LINKS:
        raise HTTPException(413, f"candidate links exceed {MAX_GENERATED_LINKS:,}; generate fewer areas per request")

    entities = []
    for row in item_rows:
        attrs = {k: row[k] for k in ("kind", "rot", "aisle_side", "x_m", "y_m", "min_x_m", "min_y_m",
                                      "width_m", "height_m", "zone", "value")}
        entities.append({"type": candidate_type, "key": row["item"], "label": row["item"], "attrs": attrs})
    entities.extend({"type": cell_type, "key": row["cell"], "label": row["cell"],
                     "attrs": {k: row[k] for k in ("x_m", "y_m", "zone")}} for row in cell_rows)
    relationships = [{"type": rel_occupies, "from": [candidate_type, row["item"]], "to": [cell_type, row["cell"]]}
                     for row in occupies]
    relationships.extend({"type": rel_keeps, "from": [candidate_type, row["item"]], "to": [cell_type, row["cell"]]}
                         for row in keeps)
    seed = {
        "entity_types": [
            {"name": candidate_type, "role": "resource", "attributes": [
                {"name": n, "data_type": t, **({"unit": "m"} if n.endswith("_m") else {})}
                for n, t in (("kind", "text"), ("rot", "integer"), ("aisle_side", "text"), ("x_m", "number"),
                             ("y_m", "number"), ("min_x_m", "number"), ("min_y_m", "number"),
                             ("width_m", "number"), ("height_m", "number"), ("zone", "text"), ("value", "number"))]},
            {"name": cell_type, "role": "location", "attributes": [
                {"name": n, "data_type": "number" if n in ("x_m", "y_m") else "text",
                 **({"unit": "m"} if n in ("x_m", "y_m") else {})} for n in ("x_m", "y_m", "zone")]},
        ],
        "relationship_types": [{"name": rel_occupies, "from": candidate_type, "to": cell_type,
                                "cardinality": "many_to_many"}],
        "entities": entities,
        "relationships": relationships,
    }
    if keeps:
        seed["relationship_types"].append({"name": rel_keeps, "from": candidate_type, "to": cell_type,
                                           "cardinality": "many_to_many"})
    item_values = {float(item.value) for item in body.items}
    value_parameter = f"{prefix}_value"
    if len(item_values) > 1:
        seed["parameters"] = [{"name": value_parameter, "index": [candidate_type], "default_value": 1}]
        seed["parameter_values"] = [{"parameter": value_parameter,
                                     "entities": [[candidate_type, row["item"]]], "value": row["value"]}
                                    for row in item_rows]
    counts = {"candidates": len(item_rows), "cells": len(cell_rows), "occupies": len(occupies), "keeps_free": len(keeps)}
    result = _commit_seed(db, user, body.domain_id, seed, candidate_type, counts)
    ids = {row.name: row.id for row in db.execute(select(EntityType).where(
        EntityType.domain_id == body.domain_id, EntityType.name.in_([candidate_type, cell_type]))).scalars()}
    rel_ids = {row.name: row.id for row in db.execute(select(RelationshipType).where(
        RelationshipType.domain_id == body.domain_id,
        RelationshipType.name.in_([rel_occupies, rel_keeps]))).scalars()}
    renames = {"item": candidate_type, "cell": cell_type, "occupies": rel_occupies,
               "keeps_free": rel_keeps, "item_value": value_parameter}
    return {**result, "domain_id": body.domain_id, "cell_type_id": ids[cell_type], "cell_type": cell_type,
            "relationship_types": [{"name": rel_occupies, "id": rel_ids[rel_occupies]},
                                   *([{"name": rel_keeps, "id": rel_ids[rel_keeps]}] if keeps else [])],
            "counts": counts, "grid_step_m": out["grid_step_m"], "aisle_m": out["aisle_m"],
            "zones": out["zones"], "upper_bound": out["upper_bound"], "not_modelled": out["not_modelled"],
            "ir": _renamed(out["spec"]["ir"], renames),
            "read_candidates": f"/api/v1/entities?entity_type_id={result['candidate_type_id']}",
            "read_cells": f"/api/v1/entities?entity_type_id={ids[cell_type]}"}
