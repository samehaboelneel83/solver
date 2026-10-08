"""A web source: a REST endpoint's JSON list, or a CSV / Excel file over HTTPS -- read into a table's rows under the
same policy as a database (approved networks, verified TLS, no redirects, a size cap), with failures by class."""
from __future__ import annotations

import io
import json
from threading import Event
from uuid import uuid4

import httpx
import pytest

from app.integrations.contracts import ExtractionError, ExtractionLimits, ExtractionRequest
from app.integrations.http_source import HttpConnector, HttpSource
from tests.test_integrations import setup  # noqa: F401
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401

ORG = uuid4()


def _source(**kw):
    base = dict(organization_id=ORG, connection_id=7, url="https://data.internal/api/projects", format="json",
                columns=("project", "cost"), allowed_networks=("10.0.0.0/8",), root_certificate="")
    return HttpSource(**{**base, **kw})


def _read(source, answer, secret="tok"):
    seen = {}

    def handle(request: httpx.Request):
        seen["auth"] = request.headers.get("authorization")
        return answer(request) if callable(answer) else answer

    connector = HttpConnector(source, lambda _: secret, transport=httpx.MockTransport(handle))
    request = ExtractionRequest(ORG, 7, source.table, source.columns, ExtractionLimits())
    return list(connector.extract(request, Event())), seen


def test_json_records_at_a_path_with_a_token():
    body = {"data": {"items": [{"project": "P1", "cost": 40, "extra": 1}, {"project": "P2", "cost": 30.5}]}}
    rows, seen = _read(_source(records_at="data.items", auth="bearer", secret_ref="x"), httpx.Response(200, json=body))
    assert rows == [{"project": "P1", "cost": 40}, {"project": "P2", "cost": 30.5}]
    assert seen["auth"] == "Bearer tok"


def test_csv_and_excel_files():
    rows, _ = _read(_source(url="https://files.internal/plan/projects.csv", format="csv"),
                    httpx.Response(200, content=b"project;cost\nP1;40\nP2;30\n"))
    assert rows == [{"project": "P1", "cost": "40"}, {"project": "P2", "cost": "30"}]
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.title = "Q3"
    sheet.append(["project", "cost"])
    sheet.append(["P1", 40])
    data = io.BytesIO()
    book.save(data)
    rows, _ = _read(_source(url="https://files.internal/plan.xlsx", format="xlsx", sheet="Q3"),
                    httpx.Response(200, content=data.getvalue()))
    assert rows == [{"project": "P1", "cost": 40}]
    assert _source(url="https://files.internal/plan.xlsx", format="xlsx", sheet="Q3").table == "Q3"


@pytest.mark.parametrize("answer,code", [
    (httpx.Response(401), "authentication_failed"),
    (httpx.Response(403), "not_permitted"),
    (httpx.Response(404), "source_missing"),
    (httpx.Response(302, headers={"location": "https://elsewhere.example/"}), "source_missing"),
    (httpx.Response(500), "source_unreachable"),
    (httpx.Response(200, content=b"<html>not json</html>"), "format_invalid"),
    (httpx.Response(200, json={"items": 3}), "format_invalid"),
    (httpx.Response(200, json=[{"project": "P1"}]), "source_missing"),  # no "cost" column
])
def test_failures_are_named(answer, code):
    with pytest.raises(ExtractionError) as failed:
        _read(_source(), answer)
    assert failed.value.code == code


def test_the_address_must_be_https_and_without_a_login_in_it():
    for url in ("http://data.internal/x", "https://user:pw@data.internal/x", "ftp://x"):
        with pytest.raises(ValueError):
            _source(url=url)


def test_a_web_source_without_a_login_needs_no_password(setup):  # noqa: F811
    from app.core.db import SessionLocal
    from app.integrations.worker import process_one

    client, body, tenants = setup
    made = client.post("/api/v1/connections", headers=tenants["a"], json={
        "domain_id": body["domain_id"], "name": "Projects API",
        "source": {"kind": "http", "url": "https://127.0.0.1:9/projects", "format": "json", "columns": ["project", "cost"]}})
    assert made.status_code == 201, made.text
    # A login without a credential is refused.
    assert client.post("/api/v1/connections", headers=tenants["a"], json={
        "domain_id": body["domain_id"], "name": "Locked API",
        "source": {"kind": "http", "url": "https://127.0.0.1:9/x", "format": "json", "columns": ["a"], "auth": "bearer"}}
    ).status_code == 422
    job = client.post(f"/api/v1/connections/{made.json()['id']}/jobs", headers=tenants["a"]).json()
    import tempfile

    assert process_one(SessionLocal, tempfile.mkdtemp())
    done = client.get(f"/api/v1/ingestion-jobs/{job['id']}", headers=tenants["a"]).json()
    # No credential was needed (else credential_unreadable): the worker reached the trust check, and this test's
    # configured CA file does not exist.
    assert done["state"] == "failed" and done["error_code"] == "trust_unavailable", done
