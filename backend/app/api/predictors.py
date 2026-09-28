"""Predictors: trained models a domain holds, for the IR's `predict` term (Epic ML).

    GET    /api/v1/predictors                  ?domain_id=&limit=&offset=
    POST   /api/v1/predictors                  upload a model as `tree-ensemble/1` JSON
    POST   /api/v1/predictors/train            train one from the domain's own entities
    GET    /api/v1/predictors/{id}             ?include_model=true for the trees
    POST   /api/v1/predictors/{id}/predict     the model's predictions at given inputs
    DELETE /api/v1/predictors/{id}

A predictor is domain data, like a parameter: it is read by name from a model
version's `predictors` and frozen into the run's dataset by
`snapshot_dataset()` (migration 0087), so a later retrain changes the answers
of later runs and never of earlier ones.

**Never a pickle.** Models arrive and leave as `tree-ensemble/1` JSON
(`app.ml.trees`), checked before they are stored; there is no upload path
that deserialises code.

Writes need `domain.edit`, as parameters do; reads need a signed-in user.
Every write is in the audit log. A predictor a published model version
declares cannot be deleted: its next run would find nothing to freeze.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import audit
from app.api.deps import get_current_user, requires
from app.core.db import get_db
from app.ml import train as training
from app.ml import trees
from app.models.iam import UserAccount

router = APIRouter(prefix="/api/v1", tags=["predictors"])

_NAME = r"^[a-z][a-z0-9_]*$"
MAX_PREDICT_ROWS = 1000
_COLUMNS = "id, domain_id, name, note, inputs, metrics, training, created_at, updated_at"


class UploadBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    domain_id: int = Field(gt=0)
    name: str = Field(pattern=_NAME, max_length=63)
    note: str | None = Field(default=None, max_length=2000)
    model: dict[str, Any]


class TrainBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    domain_id: int = Field(gt=0)
    name: str = Field(pattern=_NAME, max_length=63)
    note: str | None = Field(default=None, max_length=2000)
    entity_type: str = Field(pattern=_NAME, max_length=63)
    features: list[str] = Field(min_length=1, max_length=trees.MAX_INPUTS)
    target: str = Field(pattern=_NAME, max_length=63)
    kind: str = Field(default="random_forest", pattern="^(random_forest|gradient_boosting)$")
    trees: int = Field(default=50, ge=1, le=training.MAX_TREES)
    max_depth: int = Field(default=6, ge=1, le=training.MAX_DEPTH)
    min_samples_leaf: int = Field(default=2, ge=1, le=10_000)
    seed: int = Field(default=0, ge=0, le=2**31 - 1)
    #: Retrain a predictor of this name in place rather than refuse the name.
    replace: bool = False


class PredictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    inputs: list[list[float]] = Field(min_length=1, max_length=MAX_PREDICT_ROWS)


def _row(row: Any, *, model: dict[str, Any] | None = None) -> dict[str, Any]:
    out = dict(row)
    out["summary"] = None
    if model is not None:
        out["summary"] = trees.summary(model)
    return out


def _domain(db: Session, domain_id: int, user: UserAccount) -> None:
    found = db.execute(
        text("SELECT id FROM domain WHERE id = :d AND organization_id = :o"),
        {"d": domain_id, "o": user.organization_id},
    ).scalar_one_or_none()
    if found is None:
        raise HTTPException(404, "Domain not found")


def _load(db: Session, identity: int, user: UserAccount) -> Any:
    row = db.execute(
        text(f"SELECT {_COLUMNS}, model FROM predictor WHERE id = :id AND organization_id = :o"),
        {"id": identity, "o": user.organization_id},
    ).mappings().one_or_none()
    if row is None:
        raise HTTPException(404, "Predictor not found")
    return row


def _audit(db: Session, user: UserAccount, action: str, identity: int) -> None:
    audit.record(
        db, organization_id=user.organization_id, actor_id=user.id,
        api_key_id=getattr(user, "api_key_id", None), action=action,
        object_type="predictor", object_id=identity,
    )


def _checked(model: dict[str, Any]) -> None:
    try:
        trees.check_ensemble(model)
    except trees.EnsembleError as exc:
        raise HTTPException(
            422,
            [{"type": "value_error", "loc": ["body", "model", *exc.path], "msg": str(exc), "input": None}],
        ) from exc


def _store(
    db: Session, user: UserAccount, *, domain_id: int, name: str, note: str | None,
    model: dict[str, Any], metrics: dict[str, Any], source: dict[str, Any] | None, replace: bool,
) -> dict[str, Any]:
    params = {
        "o": user.organization_id, "d": domain_id, "n": name, "note": note,
        "i": list(model["inputs"]), "m": json.dumps(model), "met": json.dumps(metrics),
        "t": json.dumps(source) if source is not None else None, "u": str(user.id),
    }
    existing = db.execute(
        text("SELECT id FROM predictor WHERE domain_id = :d AND name = :n AND organization_id = :o"), params
    ).scalar_one_or_none()
    if existing is not None and not replace:
        raise HTTPException(409, f"This domain already has a predictor called {name!r}; retrain it with replace")
    if existing is not None:
        row = db.execute(
            text(
                "UPDATE predictor SET note = :note, inputs = :i, model = CAST(:m AS jsonb),"
                " metrics = CAST(:met AS jsonb), training = CAST(:t AS jsonb)"
                f" WHERE id = :id RETURNING {_COLUMNS}"
            ),
            {**params, "id": existing},
        ).mappings().one()
        _audit(db, user, "predictor.replace", row["id"])
    else:
        try:
            row = db.execute(
                text(
                    "INSERT INTO predictor (organization_id, domain_id, name, note, inputs, model, metrics, training, created_by)"
                    " VALUES (:o, :d, :n, :note, :i, CAST(:m AS jsonb), CAST(:met AS jsonb), CAST(:t AS jsonb), :u)"
                    f" RETURNING {_COLUMNS}"
                ),
                params,
            ).mappings().one()
        except IntegrityError as exc:  # pragma: no cover -- a concurrent create of the same name
            db.rollback()
            raise HTTPException(409, f"This domain already has a predictor called {name!r}") from exc
        _audit(db, user, "predictor.create", row["id"])
    db.commit()
    return _row(row, model=model)


@router.get("/predictors")
def list_predictors(
    domain_id: int = Query(gt=0),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: UserAccount = Depends(get_current_user),
) -> dict[str, Any]:
    params = {"d": domain_id, "o": user.organization_id, "l": limit, "p": offset}
    rows = db.execute(
        text(
            f"SELECT {_COLUMNS}, model FROM predictor WHERE domain_id = :d AND organization_id = :o"
            " ORDER BY name LIMIT :l OFFSET :p"
        ),
        params,
    ).mappings().all()
    total = db.execute(
        text("SELECT count(*) FROM predictor WHERE domain_id = :d AND organization_id = :o"), params
    ).scalar_one()
    items = []
    for row in rows:
        data = {k: v for k, v in row.items() if k != "model"}
        items.append(_row(data, model=row["model"]))
    return {"items": items, "total": total}


@router.post("/predictors", status_code=201)
def upload_predictor(
    body: UploadBody,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(requires("domain.edit")),
) -> dict[str, Any]:
    _domain(db, body.domain_id, user)
    _checked(body.model)
    return _store(
        db, user, domain_id=body.domain_id, name=body.name, note=body.note, model=body.model,
        metrics={"evaluated_on": "uploaded; no accuracy is claimed by the platform"},
        source={"kind": "upload"}, replace=False,
    )


@router.post("/predictors/train", status_code=201)
def train_predictor(
    body: TrainBody,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(requires("domain.edit")),
) -> dict[str, Any]:
    _domain(db, body.domain_id, user)
    type_id = db.execute(
        text("SELECT id FROM entity_type WHERE domain_id = :d AND name = :n"),
        {"d": body.domain_id, "n": body.entity_type},
    ).scalar_one_or_none()
    if type_id is None:
        raise HTTPException(422, f"The domain has no entity type called {body.entity_type!r}")
    rows = db.execute(
        text(
            "SELECT e.attrs FROM entity e"
            " WHERE e.active AND e.entity_type_id = ANY (entity_type_family(:t))"
            " ORDER BY e.id LIMIT :cap"
        ),
        {"t": type_id, "cap": training.MAX_ROWS + 1},
    ).scalars().all()
    try:
        trained = training.train(
            [dict(r or {}) for r in rows], body.features, body.target, kind=body.kind, trees=body.trees,
            max_depth=body.max_depth, min_samples_leaf=body.min_samples_leaf, seed=body.seed,
        )
    except training.TrainingError as exc:
        raise HTTPException(422, str(exc)) from exc
    source = {
        "kind": body.kind, "entity_type": body.entity_type, "features": body.features, "target": body.target,
        "trees": body.trees, "max_depth": body.max_depth, "min_samples_leaf": body.min_samples_leaf,
        "seed": body.seed,
    }
    return _store(
        db, user, domain_id=body.domain_id, name=body.name, note=body.note, model=trained.model,
        metrics=trained.metrics, source=source, replace=body.replace,
    )


@router.get("/predictors/{identity}")
def get_predictor(
    identity: int,
    include_model: bool = Query(False),
    db: Session = Depends(get_db),
    user: UserAccount = Depends(get_current_user),
) -> dict[str, Any]:
    row = _load(db, identity, user)
    data = {k: v for k, v in row.items() if k != "model"}
    out = _row(data, model=row["model"])
    if include_model:
        out["model"] = row["model"]
    return out


@router.post("/predictors/{identity}/predict")
def predict_with(
    identity: int,
    body: PredictBody,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(get_current_user),
) -> dict[str, Any]:
    row = _load(db, identity, user)
    model = row["model"]
    width = len(model["inputs"])
    for i, x in enumerate(body.inputs):
        if len(x) != width:
            raise HTTPException(422, f"row {i} has {len(x)} inputs; {row['name']} takes {width} ({', '.join(model['inputs'])})")
    return {"inputs": model["inputs"], "predictions": [trees.predict(model, x) for x in body.inputs]}


@router.delete("/predictors/{identity}", status_code=204)
def delete_predictor(
    identity: int,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(requires("domain.edit")),
) -> Response:
    row = _load(db, identity, user)
    used = db.execute(
        text(
            "SELECT mv.id FROM model_version mv JOIN problem p ON p.id = mv.problem_id"
            " WHERE p.domain_id = :d AND mv.ir -> 'predictors' ? :n ORDER BY mv.id LIMIT 1"
        ),
        {"d": row["domain_id"], "n": row["name"]},
    ).scalar_one_or_none()
    if used is not None:
        raise HTTPException(
            409, f"Model version {used} reads {row['name']!r}; its next run would have nothing to freeze"
        )
    db.execute(text("DELETE FROM predictor WHERE id = :id"), {"id": identity})
    _audit(db, user, "predictor.delete", identity)
    db.commit()
    return Response(status_code=204)
