"""FK-dropdown options endpoint: `GET /api/{schema}/{table}/options`.

Registered as one router with one route per `TABLE_REGISTRY` entry (built
in `app/api/routers.py`, which this module imports to guarantee the
registry is populated before the loop below runs). Must be included in
`app.main` *before* `crud_router` -- otherwise the CRUD router's
`GET /api/{schema}/{table}/{item_id}` matches first (FastAPI matches
routes in registration order) and "options" gets parsed as a UUID,
answering 422 instead of resolving here.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.routers import router as crud_router  # noqa: F401  (populates TABLE_REGISTRY)
from app.core.db import get_db
from app.crud.factory import _column_attr_keys, searchable_columns
from app.crud.labels import label_for
from app.crud.registry import TABLE_REGISTRY, TableMeta
from app.models.iam import UserAccount

router = APIRouter(tags=["options"])


def _searchable_columns_for(meta: TableMeta) -> list:
    """Same restriction as list_items' `q`: intersect with read_schema
    fields so a `hidden=` column (e.g. hashed_password) isn't searchable."""
    allowed_field_names = set(meta.read_schema.model_fields.keys())
    column_keys = _column_attr_keys(meta.model)
    return [c for c in searchable_columns(meta.model) if column_keys.get(c) in allowed_field_names]


def _register_options_route(meta: TableMeta) -> None:
    model = meta.model
    columns = _searchable_columns_for(meta)

    def get_options(
        q: str | None = Query(None),
        ids: str | None = Query(None),
        limit: int = Query(50, ge=1, le=200),
        db: Session = Depends(get_db),
        _: UserAccount = Depends(get_current_user),
    ) -> list[dict]:
        query = db.query(model)

        if ids is not None:
            id_values = []
            for raw in ids.split(","):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    id_values.append(uuid.UUID(raw))
                except ValueError:
                    raise HTTPException(status_code=422, detail=f"invalid uuid {raw!r}")
            if len(id_values) > 200:
                raise HTTPException(status_code=422, detail="too many ids (max 200)")
            if not id_values:
                return []
            # `ids` means "return exactly these rows" (Task 3 batches every
            # distinct FK id on a page into one call), so `limit` -- which
            # exists to cap an unbounded `q`/browse listing -- does not
            # apply here; only the 200-id cap above bounds the query.
            rows = query.filter(model.id.in_(id_values)).all()
            return [{"id": str(row.id), "label": label_for(db, row, meta.schema, meta.table)} for row in rows]

        if q and columns:
            query = query.filter(or_(*[col.ilike(f"%{q}%") for col in columns]))

        rows = query.limit(limit).all()
        return [{"id": str(row.id), "label": label_for(db, row, meta.schema, meta.table)} for row in rows]

    get_options.__name__ = f"get_options_{meta.schema}_{meta.table}"
    router.get(f"/api/{meta.schema}/{meta.table}/options")(get_options)


for _meta in TABLE_REGISTRY:
    _register_options_route(_meta)
