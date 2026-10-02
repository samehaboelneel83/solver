"""Predictors: trained models a domain holds, for the IR's `predict` term (Epic ML).

    GET    /api/v1/predictors                  ?domain_id=&limit=&offset=
    POST   /api/v1/predictors                  upload a model as `tree-ensemble/1` JSON
    POST   /api/v1/predictors/train            train one from the domain's own entities
                                               (?background=true: 202 and a training to ask after)
    GET    /api/v1/predictor-trainings/{id}    how that training stands: running, done or failed
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
import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import audit
from app.api.deps import get_current_user, requires
from app.core.db import engine, enter_tenant, get_db
from app.ml import train as training
from app.ml import trees
from app.models.iam import UserAccount

router = APIRouter(prefix="/api/v1", tags=["predictors"])
logger = logging.getLogger(__name__)

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
    kind: str = Field(default="random_forest", pattern="^(random_forest|gradient_boosting|random_forest_classifier)$")
    #: For a yes-or-no model: which of the target's two values counts as yes
    #: (`true` for a boolean, otherwise the later of the two by default).
    positive: str | None = Field(default=None, max_length=200)
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


def _type_id(db: Session, body: "TrainBody") -> int:
    type_id = db.execute(
        text("SELECT id FROM entity_type WHERE domain_id = :d AND name = :n"),
        {"d": body.domain_id, "n": body.entity_type},
    ).scalar_one_or_none()
    if type_id is None:
        raise HTTPException(422, f"The domain has no entity type called {body.entity_type!r}")
    return type_id


def _train(db: Session, body: "TrainBody", user: UserAccount) -> dict[str, Any]:
    """Read the records, train, and store the predictor; the request and a background training share it."""
    rows = db.execute(
        text(
            "SELECT e.attrs FROM entity e"
            " WHERE e.active AND e.entity_type_id = ANY (entity_type_family(:t))"
            " ORDER BY e.id LIMIT :cap"
        ),
        {"t": _type_id(db, body), "cap": training.MAX_ROWS + 1},
    ).scalars().all()
    try:
        trained = training.train(
            [dict(r or {}) for r in rows], body.features, body.target, kind=body.kind, trees=body.trees,
            max_depth=body.max_depth, min_samples_leaf=body.min_samples_leaf, seed=body.seed,
            positive=body.positive,
        )
    except training.TrainingError as exc:
        raise HTTPException(422, str(exc)) from exc
    source = {
        "kind": body.kind, "entity_type": body.entity_type, "features": body.features, "target": body.target,
        "trees": body.trees, "max_depth": body.max_depth, "min_samples_leaf": body.min_samples_leaf,
        "seed": body.seed,
        **({"positive": trained.metrics["positive"]} if "positive" in trained.metrics else {}),
    }
    return _store(
        db, user, domain_id=body.domain_id, name=body.name, note=body.note, model=trained.model,
        metrics=trained.metrics, source=source, replace=body.replace,
    )


#: A training still "running" this long after it began was lost with its server (a restart).
STALE_TRAINING_SECONDS = 3600


def _train_in_background(job_id: int, organization_id, user_id, body: dict[str, Any]) -> None:
    """Run one training on a connection of its own, as the user who asked, and record how it ended."""
    connection = engine.connect()
    db = Session(bind=connection, autoflush=False)
    try:
        enter_tenant(db, organization_id)
        user = db.get(UserAccount, user_id)
        try:
            if user is None:
                raise HTTPException(403, "the account that asked for this training no longer exists")
            made = _train(db, TrainBody.model_validate(body), user)
        except HTTPException as exc:
            db.rollback()
            detail = exc.detail if isinstance(exc.detail, str) else json.dumps(exc.detail)
            db.execute(text("UPDATE predictor_training SET state = 'failed', error = :e, finished_at = now()"
                            " WHERE id = :j"), {"e": detail[:4000], "j": job_id})
        except Exception:
            db.rollback()
            logger.exception("predictor training %s failed", job_id)
            db.execute(text("UPDATE predictor_training SET state = 'failed', finished_at = now(),"
                            " error = 'the training failed on the server; see the server log' WHERE id = :j"),
                       {"j": job_id})
        else:
            db.execute(text("UPDATE predictor_training SET state = 'done', predictor_id = :p, finished_at = now()"
                            " WHERE id = :j"), {"p": made["id"], "j": job_id})
        db.commit()
    finally:
        db.close()
        connection.close()


def _training_row(row: Any) -> dict[str, Any]:
    out = dict(row)
    if out["state"] == "running" and out["seconds"] > STALE_TRAINING_SECONDS:
        out.update(state="failed", error="the server stopped while this was training; train it again")
    out["request"] = {k: out["request"].get(k) for k in ("name", "entity_type", "target", "kind")}
    return out


@router.post("/predictors/train", status_code=201)
def train_predictor(
    body: TrainBody,
    background_tasks: BackgroundTasks,
    response: Response,
    background: bool = Query(False, description="answer at once with a training to ask after (F31)"),
    db: Session = Depends(get_db),
    user: UserAccount = Depends(requires("domain.edit")),
) -> dict[str, Any]:
    _domain(db, body.domain_id, user)
    if not background:
        return _train(db, body, user)
    # What can be refused at once is refused at once; the training itself goes on after the answer.
    _type_id(db, body)
    taken = db.execute(text("SELECT 1 FROM predictor WHERE domain_id = :d AND name = :n"),
                       {"d": body.domain_id, "n": body.name}).scalar_one_or_none()
    if taken and not body.replace:
        raise HTTPException(409, f"This domain already has a predictor called {body.name!r}; retrain it with replace")
    job = db.execute(
        text("INSERT INTO predictor_training (organization_id, domain_id, request, created_by)"
             " VALUES (:o, :d, CAST(:r AS jsonb), :u) RETURNING id"),
        {"o": user.organization_id, "d": body.domain_id, "r": body.model_dump_json(), "u": str(user.id)},
    ).scalar_one()
    db.commit()
    background_tasks.add_task(_train_in_background, job, user.organization_id, user.id, body.model_dump())
    response.status_code = 202
    return {"training_id": job, "state": "running"}


@router.get("/predictor-trainings/{identity}")
def get_training(
    identity: int,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(get_current_user),
) -> dict[str, Any]:
    row = db.execute(
        text("SELECT id, domain_id, request, state, predictor_id, error, created_at, finished_at,"
             " extract(epoch FROM coalesce(finished_at, now()) - created_at)::float AS seconds"
             " FROM predictor_training WHERE id = :i AND organization_id = :o"),
        {"i": identity, "o": user.organization_id},
    ).mappings().one_or_none()
    if row is None:
        raise HTTPException(404, "Training not found")
    return _training_row(row)


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
    out: dict[str, Any] = {"inputs": model["inputs"], "predictions": [trees.predict(model, x) for x in body.inputs]}
    # An averaged ensemble also says how far its trees disagree (10th to 90th percentile).
    ranges = [trees.spread(model, x) for x in body.inputs]
    if all(r is not None for r in ranges):
        out["ranges"] = [{"low": r[0], "high": r[1]} for r in ranges]  # type: ignore[index]
    return out


class Over(BaseModel):
    """One prediction per record and period: the input `feature` takes each period's `field` (its key,
    when that is a number) -- hour by hour, month by month."""

    model_config = ConfigDict(extra="forbid")
    kind: str = Field(pattern=_NAME, max_length=63)
    feature: str = Field(max_length=63)
    field: str = Field(default="key", max_length=63)


class ApplyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    #: The number field the predictions go into: made if the kind has none of that name. With `over`,
    #: the data value `field[kind, period]` instead.
    field: str = Field(pattern=_NAME, max_length=63)
    #: Only the records whose own target is empty -- the future days, the new sites.
    only_missing: bool = False
    #: The records predicted for: the kind trained on, or another (customers, for demand learnt from
    #: orders) -- benchmark re-test, October 2026.
    entity_type: str | None = Field(default=None, pattern=_NAME, max_length=63)
    #: Where each input comes from, when not a field of the same name: another field, a linked record's
    #: field (`road.lanes`), or a number held fixed (`month: 7`).
    inputs: dict[str, str | float] | None = None
    over: Over | None = None


@router.post("/predictors/{identity}/apply")
def apply_predictor(
    identity: int,
    body: ApplyBody,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(requires("domain.edit")),
) -> dict[str, Any]:
    """Predict for the records of the kind the predictor was trained on, and keep each prediction in
    a number field: a forecast a model reads as data (benchmark, October 2026: a demand model
    trained, but its forecasts for the coming days could be seen nowhere and used nowhere)."""
    row = _load(db, identity, user)
    source = row["training"] or {}
    if not source.get("entity_type") or not source.get("features"):
        raise HTTPException(422, f"{row['name']} was uploaded, not trained on records here; it cannot say which records to predict for")
    if source.get("positive") is not None:
        raise HTTPException(422, f"{row['name']} predicts yes or no; keep its chance with a model that reads it")
    features, target = list(source["features"]), source.get("target")
    if body.field in features:
        raise HTTPException(422, f"{body.field} is one of {row['name']}'s inputs; choose another field for the predictions")
    kind_name = body.entity_type or source["entity_type"]
    type_id = db.execute(text("SELECT id FROM entity_type WHERE domain_id = :d AND name = :n"),
                         {"d": row["domain_id"], "n": kind_name}).scalar_one_or_none()
    if type_id is None:
        raise HTTPException(422, f"there is no kind {kind_name!r} here" if body.entity_type else
                            f"the kind {source['entity_type']!r} it was trained on is gone")
    inputs = dict(body.inputs or {})
    unknown = [k for k in inputs if k not in features]
    if unknown:
        raise HTTPException(422, f"{row['name']} has no input {unknown[0]!r}; its inputs are {', '.join(features)}")
    if body.over is not None and body.over.feature not in features:
        raise HTTPException(422, f"{row['name']} has no input {body.over.feature!r} for the periods to feed")
    # Linked records' fields (`road.lanes`): each link field's target records, by key.
    linked: dict[str, dict[str, dict[str, Any]]] = {}
    for spec in inputs.values():
        if isinstance(spec, str) and "." in spec:
            link = spec.split(".", 1)[0]
            if link in linked:
                continue
            target_type = db.execute(text(
                "SELECT rt.to_type_id FROM attribute_def ad JOIN relationship_type rt ON rt.id = ad.references_id"
                " WHERE ad.entity_type_id = ANY (entity_type_lineage(:t)) AND ad.name = :n"), {"t": type_id, "n": link}).scalar_one_or_none()
            if target_type is None:
                raise HTTPException(422, f"{link!r} is not a link field of {kind_name}")
            linked[link] = {k: (a or {}) for k, a in db.execute(text(
                "SELECT key, attrs FROM entity WHERE entity_type_id = ANY (entity_type_family(:t))"), {"t": target_type})}

    def value_of(attrs: dict[str, Any], feature: str) -> Any:
        spec = inputs.get(feature, feature)
        if isinstance(spec, (int, float)) and not isinstance(spec, bool):
            return spec
        if "." in spec:
            link, name = spec.split(".", 1)
            return (linked[link].get(str(attrs.get(link))) or {}).get(name)
        return attrs.get(spec)

    model = row["model"]
    written, skipped = 0, []
    records = db.execute(text("SELECT id, key, attrs FROM entity WHERE active AND entity_type_id = ANY (entity_type_family(:t))"
                              " ORDER BY sort_order, key"), {"t": type_id}).all()
    if body.over is not None:
        return _apply_over(db, user, identity, row, body, type_id, records, features, value_of)
    kind = db.execute(text("SELECT data_type::text FROM attribute_def WHERE entity_type_id = ANY (entity_type_lineage(:t))"
                           " AND name = :n"), {"t": type_id, "n": body.field}).scalar_one_or_none()
    if kind is None:
        db.execute(text("INSERT INTO attribute_def (entity_type_id, name, data_type) VALUES (:t, :n, 'number')"),
                   {"t": type_id, "n": body.field})
    elif kind not in ("number", "integer"):
        raise HTTPException(422, f"{body.field} is a {kind} field; predictions go into a number field")
    for entity_id, key, attrs in records:
        attrs = dict(attrs or {})
        if body.only_missing and target and training._number(attrs.get(target)):
            continue
        values = [value_of(attrs, f) for f in features]
        if not all(training._number(v) for v in values):
            skipped.append(key)
            continue
        value = trees.predict(model, [float(v) for v in values])
        db.execute(text("UPDATE entity SET attrs = attrs || jsonb_build_object(:f, CAST(:v AS numeric)) WHERE id = :id"),
                   {"f": body.field, "v": round(float(value), 6), "id": entity_id})
        written += 1
    _audit(db, user, "predictor.apply", identity)
    db.commit()
    return {"field": body.field, "entity_type": kind_name, "written": written,
            "skipped": skipped[:50], "skipped_count": len(skipped)}


#: The most predictions one "per period" writes.
MAX_OVER_CELLS = 200_000


def _apply_over(db: Session, user: UserAccount, identity: int, row: Any, body: ApplyBody, type_id: int,
                records: list[Any], features: list[str], value_of) -> dict[str, Any]:
    """A prediction for each record and each period, kept as the data value `field[kind, period]` a
    rule reads (benchmark re-test, October 2026: a forecast could only be read with its inputs held
    constant, not road by road and hour by hour)."""
    over = body.over
    assert over is not None
    period_type = db.execute(text("SELECT id FROM entity_type WHERE domain_id = :d AND name = :n"),
                             {"d": row["domain_id"], "n": over.kind}).scalar_one_or_none()
    if period_type is None:
        raise HTTPException(422, f"there is no kind {over.kind!r}")
    periods = db.execute(text("SELECT id, key, attrs FROM entity WHERE active AND entity_type_id = ANY (entity_type_family(:t))"
                              " ORDER BY sort_order, key"), {"t": period_type}).all()
    if len(records) * len(periods) > MAX_OVER_CELLS:
        raise HTTPException(422, f"{len(records) * len(periods):,} predictions is more than {MAX_OVER_CELLS:,}")
    existing = db.execute(text("SELECT id, index_type_ids FROM parameter_def WHERE domain_id = :d AND name = :n"),
                          {"d": row["domain_id"], "n": body.field}).mappings().one_or_none()
    if existing is not None and list(existing["index_type_ids"]) != [type_id, period_type]:
        raise HTTPException(409, f"there is already a data value {body.field!r} over other kinds; choose another name")
    source = {"kind": "predicted", "predictor": row["name"], "over": over.kind, "feature": over.feature,
              **({"inputs": body.inputs} if body.inputs else {})}
    if existing is None:
        parameter_id = db.execute(text(
            "INSERT INTO parameter_def (domain_id, name, index_type_ids, default_value, source)"
            " VALUES (:d, :n, :i, 0, CAST(:s AS jsonb)) RETURNING id"),
            {"d": row["domain_id"], "n": body.field, "i": [type_id, period_type], "s": json.dumps(source)}).scalar_one()
    else:
        parameter_id = existing["id"]
        db.execute(text("UPDATE parameter_def SET source = CAST(:s AS jsonb) WHERE id = :p"), {"s": json.dumps(source), "p": parameter_id})
        db.execute(text("DELETE FROM parameter_value WHERE parameter_def_id = :p"), {"p": parameter_id})
    model = row["model"]
    written, skipped = 0, []
    for entity_id, key, attrs in records:
        attrs = dict(attrs or {})
        base = [value_of(attrs, f) for f in features]
        at = features.index(over.feature)
        for period_id, period_key, period_attrs in periods:
            fed = period_key if over.field == "key" else (period_attrs or {}).get(over.field)
            try:
                fed = float(fed)
            except (TypeError, ValueError):
                fed = None
            values = [*base[:at], fed, *base[at + 1:]]
            if not all(training._number(v) for v in values):
                skipped.append(f"{key} · {period_key}")
                continue
            value = trees.predict(model, [float(v) for v in values])
            db.execute(text("INSERT INTO parameter_value (parameter_def_id, entity_ids, value) VALUES (:p, :e, :v)"),
                       {"p": parameter_id, "e": [entity_id, period_id], "v": round(float(value), 6)})
            written += 1
    _audit(db, user, "predictor.apply", identity)
    db.commit()
    return {"parameter_id": parameter_id, "parameter": body.field, "written": written,
            "skipped": skipped[:50], "skipped_count": len(skipped)}


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
