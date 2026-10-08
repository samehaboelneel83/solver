"""Authenticated integration lifecycle and real PostgreSQL RLS/queue tests."""
import base64
import json

import psycopg2
import pytest
import multiprocessing as mp
from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.main import app
from app.core.db import SessionLocal
from app.integrations.secrets import decrypt
from app.integrations.worker import process_one
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


@pytest.fixture
def setup(tenants, monkeypatch, tmp_path):
    monkeypatch.setenv("OAAS_INTEGRATION_KEYS", json.dumps({"test": base64.b64encode(b"x" * 32).decode()}))
    monkeypatch.setenv("OAAS_INTEGRATION_ACTIVE_KEY", "test")
    monkeypatch.setenv("OAAS_INTEGRATION_NETWORKS", "127.0.0.1/32")
    monkeypatch.setenv("OAAS_INTEGRATION_CA", str(tmp_path / "missing-ca.pem"))
    client = TestClient(app)
    body = {"domain_id": tenants["domain_a"], "name": "Staff source", "password": "never-return-me",
            "source": {"host": "127.0.0.1", "database": "source", "username": "reader", "schema": "planning", "table": "staff", "columns": ["id"]}}
    yield client, body, tenants
    with SessionLocal() as session:
        session.execute(text("DELETE FROM source_binding"))
        session.execute(text("DELETE FROM ingestion_job"))
        session.execute(text("DELETE FROM integration_connection"))
        session.commit()


def create(setup):
    client, body, tenants = setup
    response = client.post("/api/v1/connections", json=body, headers=tenants["a"])
    assert response.status_code == 201, response.text
    assert "never-return-me" not in response.text
    return response.json()["id"]


def test_credentials_encrypted_rotation_redaction_and_cross_tenant_refusal(setup):
    identity = create(setup)
    client, body, tenants = setup
    listed = client.get("/api/v1/connections", params={"domain_id": body["domain_id"]}, headers=tenants["a"])
    assert listed.status_code == 200
    assert "credential" not in listed.text and "never-return-me" not in listed.text
    assert client.get("/api/v1/connections", params={"domain_id": body["domain_id"]}, headers=tenants["b"]).json()["items"] == []
    assert client.post(f"/api/v1/connections/{identity}/jobs", headers=tenants["b"]).status_code == 404
    assert client.post("/api/v1/connections", json=body, headers=tenants["b"]).status_code == 404
    with SessionLocal() as session:
        row = session.execute(text("SELECT * FROM integration_connection WHERE id=:id"), {"id": identity}).mappings().one()
        assert "never-return-me" not in json.dumps(row["credential"])
        assert decrypt(row["credential"], row["organization_id"], identity) == "never-return-me"
    rotated = client.put(f"/api/v1/connections/{identity}/credential", json={"password": "rotated"}, headers=tenants["a"])
    assert rotated.status_code == 204
    with SessionLocal() as session:
        row = session.execute(text("SELECT * FROM integration_connection WHERE id=:id"), {"id": identity}).mappings().one()
        assert decrypt(row["credential"], row["organization_id"], identity) == "rotated"


def test_capability_limited_key_cannot_read_or_create_connections(setup):
    client, body, tenants = setup
    key = client.post("/api/v1/api-keys", json={"name": "limited", "capabilities": ["run.submit"]}, headers=tenants["a"]).json()
    headers = {"Authorization": f"Bearer {key['token']}"}
    assert client.post("/api/v1/connections", json=body, headers=headers).status_code == 403
    assert client.get("/api/v1/connections", params={"domain_id": body["domain_id"]}, headers=headers).status_code == 403
    with SessionLocal() as db:
        db.execute(text("DELETE FROM iam.api_key WHERE id=:id"), {"id": key["id"]})
        db.commit()


def test_queued_cancel_duplicate_and_disable(setup, tmp_path):
    identity = create(setup)
    client, body, tenants = setup
    job = client.post(f"/api/v1/connections/{identity}/jobs", headers=tenants["a"])
    assert job.status_code == 202
    job_id = job.json()["id"]
    assert client.post(f"/api/v1/connections/{identity}/jobs", headers=tenants["a"]).status_code == 409
    assert client.get(f"/api/v1/ingestion-jobs/{job_id}", headers=tenants["b"]).status_code == 404
    assert client.post(f"/api/v1/ingestion-jobs/{job_id}/cancel", headers=tenants["a"]).status_code == 204
    assert process_one(SessionLocal, str(tmp_path))
    assert client.get(f"/api/v1/ingestion-jobs/{job_id}", headers=tenants["a"]).json()["state"] == "cancelled"
    assert client.post(f"/api/v1/connections/{identity}/disable", headers=tenants["a"]).status_code == 204
    assert client.post(f"/api/v1/connections/{identity}/jobs", headers=tenants["a"]).status_code == 409


def test_worker_records_safe_failure_and_releases_active_slot(setup, tmp_path):
    identity = create(setup)
    client, _, tenants = setup
    job = client.post(f"/api/v1/connections/{identity}/jobs", headers=tenants["a"]).json()
    assert process_one(SessionLocal, str(tmp_path))
    response = client.get(f"/api/v1/ingestion-jobs/{job['id']}", headers=tenants["a"])
    assert response.json()["state"] == "failed", response.text
    # The configured CA file does not exist: the job names that class of cause, nothing more.
    assert response.json()["error_code"] == "trust_unavailable"
    assert "never-return-me" not in response.text
    assert client.post(f"/api/v1/connections/{identity}/jobs", headers=tenants["a"]).status_code == 202


@pytest.mark.parametrize("race", ["none", "cancel", "new_attempt"])
def test_worker_completion_fenced_against_cancellation_and_new_attempt(setup, tmp_path, monkeypatch, race):
    identity = create(setup)
    client, _, tenants = setup
    job = client.post(f"/api/v1/connections/{identity}/jobs", headers=tenants["a"]).json()
    context = mp.get_context("spawn")
    artifact = uuid4()

    class CompletedProcess:
        pid = 1
        def __init__(self, *, target, args, daemon):
            self.sender = args[-1]
        def start(self):
            if race != "none":
                with SessionLocal() as db:
                    statement = "UPDATE ingestion_job SET cancel_requested=true WHERE id=:id" if race == "cancel" else "UPDATE ingestion_job SET attempt=gen_random_uuid() WHERE id=:id"
                    db.execute(text(statement), {"id": job["id"]})
                    db.commit()
            self.sender.send(("extracted", str(artifact)))
        def is_alive(self):
            return False
        def join(self, timeout=None):
            pass

    class Context:
        Event = staticmethod(context.Event)
        Pipe = staticmethod(context.Pipe)
        Process = CompletedProcess

    monkeypatch.setattr("app.integrations.worker.mp.get_context", lambda _: Context())
    assert process_one(SessionLocal, str(tmp_path))
    result = client.get(f"/api/v1/ingestion-jobs/{job['id']}", headers=tenants["a"]).json()
    assert result["state"] == {"none": "extracted", "cancel": "cancelled", "new_attempt": "running"}[race]
    assert result["artifact_id"] == (str(artifact) if race == "none" else None)


def test_rls_hides_connections_even_for_direct_database_queries(setup):
    identity = create(setup)
    _, _, tenants = setup
    with SessionLocal() as db:
        db.execute(text("SET LOCAL ROLE solver_app"))
        db.execute(text("SELECT set_config('app.org_id', :o, true)"), {"o": str(tenants["org_b"])})
        assert db.execute(text("SELECT id FROM integration_connection WHERE id=:id"), {"id": identity}).scalar_one_or_none() is None


def test_missing_keyring_rolls_back_connection_without_echoing_secret(setup, monkeypatch):
    client, body, tenants = setup
    monkeypatch.setenv("OAAS_INTEGRATION_KEYS", "{}")
    response = client.post("/api/v1/connections", json=body, headers=tenants["a"])
    assert response.status_code == 503
    assert "never-return-me" not in response.text
    listed = client.get("/api/v1/connections", params={"domain_id": body["domain_id"]}, headers=tenants["a"])
    assert listed.json()["items"] == []


def test_expired_running_job_is_failed_without_automatic_replay(setup, tmp_path):
    identity = create(setup)
    client, _, tenants = setup
    job = client.post(f"/api/v1/connections/{identity}/jobs", headers=tenants["a"]).json()
    with SessionLocal() as db:
        db.execute(text("UPDATE ingestion_job SET state='running',attempt=gen_random_uuid(),started_at=now()-interval '11 minutes' WHERE id=:id"), {"id": job["id"]})
        db.commit()
    assert process_one(SessionLocal, str(tmp_path)) is False
    result = client.get(f"/api/v1/ingestion-jobs/{job['id']}", headers=tenants["a"]).json()
    assert result["state"] == "failed"
    assert result["error_code"] == "worker_lost"


class _DriverError(psycopg2.OperationalError):
    def __init__(self, message, state=None):
        super().__init__(message)
        self._state = state

    @property
    def pgcode(self):
        return self._state


@pytest.mark.parametrize("message,state,code", [
    ('connection to server failed: FATAL:  password authentication failed for user "reader"', None, "authentication_failed"),
    ("", "28P01", "authentication_failed"),
    ("server certificate for \"db\" does not match host name", None, "tls_failed"),
    ("connection to server at \"10.0.0.5\", port 5432 failed: timeout expired", None, "source_unreachable"),
    ("connection refused", None, "source_unreachable"),
    ('FATAL:  database "nope" does not exist', None, "source_missing"),
    ("", "42P01", "source_missing"),
    ("", "42703", "source_missing"),
    ("", "42501", "not_permitted"),
    ("", "57014", "deadline_exceeded"),
    ("something new", None, "source_unreachable"),
])
def test_driver_failures_become_safe_classes(message, state, code):
    from app.integrations.postgres import failure_code
    assert failure_code(_DriverError(message, state)) == code


def test_unknown_failures_and_codes_stay_generic():
    from app.integrations.contracts import ExtractionError
    from app.integrations.postgres import failure_code
    assert failure_code(ValueError("x")) == "extraction_failed"
    assert ExtractionError("x", "made-up").code == "extraction_failed"


def test_address_outside_networks_and_unknown_host_are_named(tmp_path):
    from uuid import uuid4
    from app.integrations.contracts import ExtractionError
    from app.integrations.postgres import PostgresSource, resolve_address
    def source(host, networks):
        return PostgresSource(organization_id=uuid4(), connection_id=1, host=host, database="d", username="u",
                              secret_ref="s", schema="p", table="t", columns=("a",), allowed_networks=networks,
                              root_certificate=str(tmp_path / "ca.pem"))
    with pytest.raises(ExtractionError) as outside:
        resolve_address(source("127.0.0.1", ("10.0.0.0/8",)))
    assert outside.value.code == "network_not_allowed"
    with pytest.raises(ExtractionError) as unknown:
        resolve_address(source("no-such-host.invalid", ("10.0.0.0/8",)))
    assert unknown.value.code == "source_unreachable"


def test_a_refused_body_never_echoes_its_password(setup):
    """The source test of 7 October 2026: a body missing one field came back with its password in the 422."""
    client, body, tenants = setup
    wrong = {k: v for k, v in body.items() if k != "domain_id"}
    response = client.post("/api/v1/connections", json=wrong, headers=tenants["a"])
    assert response.status_code == 422
    assert "never-return-me" not in response.text and '"***"' in response.text
    assert response.json()["detail"][0]["loc"] == ["body", "domain_id"]


def test_an_incremental_job_needs_a_changed_column_and_starts_from_the_last_mark(setup, tmp_path):  # noqa: F811
    """Migration 0118: asked without a changed column, an incremental read is refused in words; with one, the
    worker starts from the high_water of the source's latest extracted read."""
    import json
    from uuid import uuid4

    from app.core.db import SessionLocal
    from app.integrations.worker import last_high_water

    client, body, tenants = setup
    connection = create(setup)
    refused = client.post(f"/api/v1/connections/{connection}/jobs", json={"incremental": True}, headers=tenants["a"])
    assert refused.status_code == 422 and "changed column" in refused.text
    with SessionLocal() as s:
        org, user = s.execute(text("SELECT organization_id, requested_by FROM ingestion_job WHERE false UNION ALL "
                                   "SELECT c.organization_id, u.id FROM integration_connection c JOIN iam.user_account u"
                                   " ON u.organization_id = c.organization_id WHERE c.id = :c LIMIT 1"),
                              {"c": connection}).one()
        artifact = str(uuid4())
        folder = tmp_path / str(org) / str(connection) / artifact
        folder.mkdir(parents=True)
        (folder / "manifest.json").write_text(json.dumps({"high_water": "2026-10-08T11:30:00"}))
        s.execute(text("INSERT INTO ingestion_job (connection_id, organization_id, requested_by, state, artifact_id,"
                       " finished_at) VALUES (:c, :o, :u, 'extracted', CAST(:a AS uuid), now())"),
                  {"c": connection, "o": org, "u": user, "a": artifact})
        s.commit()
        assert last_high_water(s, org, connection, str(tmp_path)) == "2026-10-08T11:30:00"
