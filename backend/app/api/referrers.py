"""Who names this record in a reference field.

    GET /api/v1/entities/{id}/referrers

Deleting a record that others name through a reference field does one of two things
(`entity_reference_release`, migration 0067): a **required** reference refuses the delete, an
optional one is cleared on every record that held it. The record page reads this before it
asks "delete?", so the question can say which -- and name the records -- instead of the
reader finding out from a refusal or from fields that went blank.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models.iam import UserAccount

router = APIRouter(prefix="/api/v1", tags=["entities"])

SAMPLE = 25


@router.get("/entities/{entity_id}/referrers")
def referrers(entity_id: int, db: Session = Depends(get_db), _: UserAccount = Depends(get_current_user)) -> dict[str, Any]:
    if db.execute(text("SELECT 1 FROM entity WHERE id = :e"), {"e": entity_id}).first() is None:
        raise HTTPException(404, "entity not found")
    rows = db.execute(text(
        "SELECT ad.name AS attribute, ad.required, t.name AS kind, src.id, src.key, src.label,"
        "       count(*) OVER (PARTITION BY ad.id) AS total,"
        "       row_number() OVER (PARTITION BY ad.id ORDER BY src.key) AS n"
        "  FROM relationship r JOIN attribute_def ad ON ad.references_id = r.relationship_type_id"
        "  JOIN entity src ON src.id = r.from_entity_id JOIN entity_type t ON t.id = ad.entity_type_id"
        " WHERE r.to_entity_id = :e AND r.from_entity_id <> :e"
        " ORDER BY ad.required DESC, t.name, ad.name, src.key"), {"e": entity_id}).mappings().all()
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for r in rows:
        g = groups.setdefault((r["kind"], r["attribute"]), {
            "kind": r["kind"], "attribute": r["attribute"], "required": r["required"], "count": r["total"], "records": []})
        if r["n"] <= SAMPLE:
            g["records"].append({"id": r["id"], "key": r["key"], "label": r["label"]})
    fields = list(groups.values())
    return {"entity_id": entity_id, "fields": fields, "blocks_delete": any(f["required"] for f in fields)}
