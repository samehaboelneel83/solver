"""Epic ML: the predictor registry and the run-time estimate, through the API.

Two organizations (`tests.test_tenancy.tenants`): what A stores B can neither
see nor change, every write is audited, a model is only ever JSON, and a
predictor a model version reads cannot be deleted from under it.
"""

from __future__ import annotations

import json
import uuid

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.db import SessionLocal
from app.main import app
from app.ml import eta
from tests.test_ml_trees import STUMP
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db, make_model_version, make_problem  # noqa: F401


@pytest.fixture
def client(tenants):  # noqa: F811
    yield TestClient(app), tenants
    with SessionLocal() as session:
        session.execute(text("DELETE FROM predictor"))
        session.commit()


def _upload(client, headers, domain, name="demand_model", model=STUMP):
    return client.post(
        "/api/v1/predictors",
        json={"domain_id": domain, "name": name, "note": "weekly demand", "model": model},
        headers=headers,
    )


def test_an_uploaded_model_is_listed_read_and_predicts_for_its_own_organization_only(client):
    http, t = client
    created = _upload(http, t["a"], t["domain_a"])
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["inputs"] == ["price", "promo"] and body["summary"]["leaves"] == 3
    identity = body["id"]

    listed = http.get("/api/v1/predictors", params={"domain_id": t["domain_a"]}, headers=t["a"]).json()
    assert [p["name"] for p in listed["items"]] == ["demand_model"] and listed["total"] == 1
    assert "model" not in listed["items"][0]
    full = http.get(f"/api/v1/predictors/{identity}", params={"include_model": True}, headers=t["a"]).json()
    assert full["model"] == STUMP

    predicted = http.post(f"/api/v1/predictors/{identity}/predict", json={"inputs": [[5, 0], [9, 1]]}, headers=t["a"])
    assert predicted.json()["predictions"] == [120, 90]
    wrong_width = http.post(f"/api/v1/predictors/{identity}/predict", json={"inputs": [[5]]}, headers=t["a"])
    assert wrong_width.status_code == 422 and "takes 2" in wrong_width.text

    # Tenant B sees nothing and can touch nothing.
    assert http.get("/api/v1/predictors", params={"domain_id": t["domain_a"]}, headers=t["b"]).json()["items"] == []
    assert http.get(f"/api/v1/predictors/{identity}", headers=t["b"]).status_code == 404
    assert http.delete(f"/api/v1/predictors/{identity}", headers=t["b"]).status_code == 404
    assert _upload(http, t["b"], t["domain_a"]).status_code == 404

    with SessionLocal() as session:
        actions = session.execute(
            text("SELECT action FROM iam.audit_event WHERE object_type = 'predictor' AND object_id = :i"),
            {"i": str(identity)},
        ).scalars().all()
    assert actions == ["predictor.create"]


def test_a_name_taken_in_the_domain_is_a_conflict(client):
    http, t = client
    assert _upload(http, t["a"], t["domain_a"]).status_code == 201
    assert _upload(http, t["a"], t["domain_a"]).status_code == 409


@pytest.mark.parametrize(
    "model, where",
    [
        ({**STUMP, "format": "pickle"}, ["body", "model", "format"]),
        ({**STUMP, "trees": [{"nodes": [{"feature": 5, "threshold": 1, "left": 1, "right": 2}, {"value": 1}, {"value": 2}]}]},
         ["body", "model", "trees", 0, "nodes", 0, "feature"]),
    ],
)
def test_a_model_that_is_not_tree_ensemble_json_is_refused_at_the_element(client, model, where):
    http, t = client
    response = _upload(http, t["a"], t["domain_a"], model=model)
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == where


def test_a_predictor_is_trained_from_the_domain_s_own_entities_and_retrained_in_place(client, db):  # noqa: F811
    http, t = client
    domain = t["domain_a"]
    type_id = db.execute(
        text("INSERT INTO entity_type (domain_id, name, role) VALUES (:d, 'store', CAST('location' AS entity_role)) RETURNING id"),
        {"d": domain},
    ).scalar_one()
    for name in ("price", "footfall", "sales"):
        db.execute(
            text("INSERT INTO attribute_def (entity_type_id, name, data_type) VALUES (:t, :n, CAST('number' AS attr_type))"),
            {"t": type_id, "n": name},
        )
    rng = np.random.default_rng(0)
    for i in range(120):
        price, footfall = float(rng.uniform(1, 10)), float(rng.uniform(100, 1000))
        attrs = {"price": price, "footfall": footfall, "sales": footfall / price + float(rng.normal(0, 5))}
        db.execute(
            text("INSERT INTO entity (entity_type_id, key, attrs) VALUES (:t, :k, CAST(:a AS jsonb))"),
            {"t": type_id, "k": f"s{i}", "a": json.dumps(attrs)},
        )
    db.commit()
    body = {"domain_id": domain, "name": "sales_model", "entity_type": "store",
            "features": ["price", "footfall"], "target": "sales", "trees": 20, "max_depth": 6}
    trained = http.post("/api/v1/predictors/train", json=body, headers=t["a"])
    assert trained.status_code == 201, trained.text
    first = trained.json()
    assert first["metrics"]["rows"] == 120 and first["metrics"]["holdout_rows"] == 24
    assert first["metrics"]["r2"] > 0.5
    assert first["training"]["entity_type"] == "store"

    again = http.post("/api/v1/predictors/train", json=body, headers=t["a"])
    assert again.status_code == 409
    replaced = http.post("/api/v1/predictors/train", json={**body, "kind": "gradient_boosting", "replace": True},
                         headers=t["a"])
    assert replaced.status_code == 201 and replaced.json()["id"] == first["id"]
    assert replaced.json()["summary"]["aggregation"] == "sum"

    missing = http.post("/api/v1/predictors/train", json={**body, "name": "x_model", "entity_type": "nowhere"},
                        headers=t["a"])
    assert missing.status_code == 422 and "nowhere" in missing.text
    too_few = http.post("/api/v1/predictors/train", json={**body, "name": "y_model", "target": "unset"},
                        headers=t["a"])
    assert too_few.status_code == 422 and "0 rows" in too_few.text

    # In the background (operator trial F31): answered at once, then asked after.
    queued = http.post("/api/v1/predictors/train?background=true", json={**body, "name": "bg_model"}, headers=t["a"])
    assert queued.status_code == 202, queued.text
    job = http.get(f"/api/v1/predictor-trainings/{queued.json()['training_id']}", headers=t["a"]).json()
    assert job["state"] == "done" and job["error"] is None and job["request"]["name"] == "bg_model"
    made = http.get(f"/api/v1/predictors/{job['predictor_id']}", headers=t["a"]).json()
    assert made["name"] == "bg_model" and made["metrics"]["rows"] == 120
    assert http.get(f"/api/v1/predictor-trainings/{queued.json()['training_id']}", headers=t["b"]).status_code == 404
    # What can be refused at once still is; what only training finds is recorded as the failure.
    assert http.post("/api/v1/predictors/train?background=true", json=body, headers=t["a"]).status_code == 409
    failed = http.post("/api/v1/predictors/train?background=true", json={**body, "name": "z_model", "target": "unset"},
                       headers=t["a"]).json()
    failed = http.get(f"/api/v1/predictor-trainings/{failed['training_id']}", headers=t["a"]).json()
    assert failed["state"] == "failed" and "0 rows" in failed["error"]


def test_a_predictor_a_model_version_reads_cannot_be_deleted(client, db):  # noqa: F811
    http, t = client
    identity = _upload(http, t["a"], t["domain_a"]).json()["id"]
    problem = make_problem(db, t["domain_a"])
    make_model_version(db, problem, {
        "version": 2, "sets": [], "parameters": {}, "predictors": {"demand_model": {"inputs": 2}},
        "variables": {"x": {"index": [], "domain": "binary"}}, "constraints": [],
    })
    db.commit()
    refused = http.delete(f"/api/v1/predictors/{identity}", headers=t["a"])
    assert refused.status_code == 409 and "reads 'demand_model'" in refused.text
    spare = _upload(http, t["a"], t["domain_a"], name="spare_model").json()["id"]
    assert http.delete(f"/api/v1/predictors/{spare}", headers=t["a"]).status_code == 204


def test_the_estimate_waits_for_enough_history_then_answers_within_the_limit(client, db):  # noqa: F811
    http, t = client
    eta.clear()
    run = t["run_a"]
    early = http.get(f"/api/v1/runs/{run}/eta", headers=t["a"]).json()
    assert early["estimate_seconds"] is None and "not compiled" in early["reason"]

    fingerprint = {"variables": 10, "binary": 10, "rows": 5, "nnz": 20, "integral_data": True}
    db.execute(
        text("UPDATE run SET params = params || CAST(:f AS jsonb), status = 'running', started_at = now() WHERE id = :r"),
        {"f": json.dumps({"fingerprint": fingerprint}), "r": run},
    )
    db.commit()
    waiting = http.get(f"/api/v1/runs/{run}/eta", headers=t["a"]).json()
    assert waiting["estimate_seconds"] is None and f"once {eta.MIN_RUNS} runs" in waiting["reason"]

    # Settled history: bigger models took longer.
    scenario = t["scenario_a"]
    rows = []
    for i in range(eta.MIN_RUNS + 5):
        size = 10 * (i + 1)
        rows.append({"s": scenario, "p": json.dumps({"fingerprint": {**fingerprint, "variables": size, "rows": size},
                                                     "time_limit_s": 60}), "w": size / 10})
    for row in rows:
        db.execute(
            text(
                "INSERT INTO run (scenario_id, dataset_id, status, solver, params, wall_time_s, started_at, finished_at)"
                " SELECT :s, dataset_id, 'optimal', 'cp-sat', CAST(:p AS jsonb), :w, now(), now() FROM run WHERE id = :r"
            ),
            {**row, "r": run},
        )
    db.commit()
    answered = http.get(f"/api/v1/runs/{run}/eta", headers=t["a"]).json()
    assert answered["based_on_runs"] == eta.MIN_RUNS + 5
    assert 0 <= answered["low_seconds"] <= answered["estimate_seconds"] <= answered["high_seconds"]
    assert answered["estimate_seconds"] < 3  # a 10-variable model took ~1 s here
    assert "not a calibrated interval" in answered["range_is"]
    assert http.get(f"/api/v1/runs/{run}/eta", headers=t["b"]).status_code == 404


def test_the_estimate_never_exceeds_the_run_s_time_limit():
    history = [({"variables": v, "rows": v}, "highs", 5.0, 100.0) for v in range(1, 40)]
    model = eta.fit(history)
    assert model is not None
    found = model.estimate({"variables": 20, "rows": 20}, "highs", 5.0)
    assert found.seconds == 5.0 and found.high == 5.0
    assert eta.fit(history[:10]) is None


def test_a_uuid_organization_key_is_a_string_in_the_cache():
    eta.clear()
    assert eta.model_for(str(uuid.uuid4()), 3, lambda: []) is None


def test_a_yes_or_no_predictor_is_trained_and_a_forest_says_its_range(client, db):  # noqa: F811
    http, t = client
    domain = t["domain_a"]
    type_id = db.execute(
        text("INSERT INTO entity_type (domain_id, name, role) VALUES (:d, 'customer', CAST('resource' AS entity_role)) RETURNING id"),
        {"d": domain},
    ).scalar_one()
    for name, kind in (("tenure", "number"), ("spend", "number"), ("churned", "boolean")):
        db.execute(
            text("INSERT INTO attribute_def (entity_type_id, name, data_type) VALUES (:t, :n, CAST(:k AS attr_type))"),
            {"t": type_id, "n": name, "k": kind},
        )
    rng = np.random.default_rng(2)
    for i in range(100):
        tenure, spend = float(rng.uniform(0, 10)), float(rng.uniform(0, 10))
        attrs = {"tenure": tenure, "spend": spend, "churned": tenure + spend < 8}
        db.execute(
            text("INSERT INTO entity (entity_type_id, key, attrs) VALUES (:t, :k, CAST(:a AS jsonb))"),
            {"t": type_id, "k": f"c{i}", "a": json.dumps(attrs)},
        )
    db.commit()
    body = {"domain_id": domain, "name": "churn_model", "entity_type": "customer", "features": ["tenure", "spend"],
            "target": "churned", "kind": "random_forest_classifier", "trees": 20, "max_depth": 5}
    trained = http.post("/api/v1/predictors/train", json=body, headers=t["a"])
    assert trained.status_code == 201, trained.text
    made = trained.json()
    assert made["metrics"]["predicts"] == "the probability that churned is true"
    assert made["metrics"]["accuracy"] > 0.8 and made["training"]["positive"] == "true"
    predicted = http.post(f"/api/v1/predictors/{made['id']}/predict", json={"inputs": [[1, 1], [9, 9]]},
                          headers=t["a"]).json()
    first, second = predicted["predictions"]
    assert first > 0.7 and second < 0.3
    # The trees' spread; their mean may sit outside it when nearly all agree.
    assert all(0 <= s["low"] <= s["high"] <= 1 for s in predicted["ranges"])
    assert predicted["ranges"][0]["low"] > 0.5 and predicted["ranges"][1]["high"] < 0.5
    wrong = http.post("/api/v1/predictors/train", json={**body, "name": "other", "positive": "maybe"}, headers=t["a"])
    assert wrong.status_code == 422 and "not one of" in wrong.text
