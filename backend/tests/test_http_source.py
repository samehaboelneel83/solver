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


def _pages(pages: dict[str, httpx.Response]):
    """A server answering each address (path and query) from `pages`, and the addresses asked, in order."""
    asked = []

    def answer(request: httpx.Request):
        key = request.url.raw_path.decode()
        asked.append(key)
        return pages.get(key, httpx.Response(404))
    return answer, asked


def test_pages_by_a_next_link_in_the_answer():
    answer, asked = _pages({
        "/api/projects": httpx.Response(200, json={"items": [{"project": "P1", "cost": 1}], "next": "/api/projects?cursor=b"}),
        "/api/projects?cursor=b": httpx.Response(200, json={"items": [{"project": "P2", "cost": 2}],
                                                             "next": "https://data.internal/api/projects?cursor=c"}),
        "/api/projects?cursor=c": httpx.Response(200, json={"items": [{"project": "P3", "cost": 3}], "next": None})})
    rows, _ = _read(_source(records_at="items", paging="next_link", next_at="next"), answer)
    assert [r["project"] for r in rows] == ["P1", "P2", "P3"] and len(asked) == 3


def test_pages_by_a_link_header_and_by_page_number():
    answer, _ = _pages({
        "/api/projects": httpx.Response(200, json=[{"project": "P1", "cost": 1}],
                                        headers={"Link": '</api/projects?p=2>; rel="next"'}),
        "/api/projects?p=2": httpx.Response(200, json=[{"project": "P2", "cost": 2}])})
    rows, _ = _read(_source(paging="link_header"), answer)
    assert [r["project"] for r in rows] == ["P1", "P2"]
    answer, asked = _pages({
        "/api/projects?size=2&page=1": httpx.Response(200, json={"value": [{"project": "P1", "cost": 1}]}),
        "/api/projects?size=2&page=2": httpx.Response(200, json={"value": [{"project": "P2", "cost": 2}]}),
        "/api/projects?size=2&page=3": httpx.Response(200, json={"value": []})})
    rows, _ = _read(_source(url="https://data.internal/api/projects?size=2", records_at="value",
                            paging="page_number", page_param="page"), answer)
    assert [r["project"] for r in rows] == ["P1", "P2"] and asked[-1].endswith("page=3")


def test_a_next_page_elsewhere_is_refused_and_a_loop_ends():
    answer, _ = _pages({"/api/projects": httpx.Response(200, json={
        "items": [{"project": "P1", "cost": 1}], "@odata.nextLink": "https://evil.example/steal"})})
    with pytest.raises(ExtractionError) as refused:
        _read(_source(records_at="items", paging="next_link", next_at="@odata.nextLink"), answer)
    assert refused.value.code == "network_not_allowed"
    answer, asked = _pages({"/api/projects": httpx.Response(200, json={
        "items": [{"project": "P1", "cost": 1}], "next": "/api/projects"})})
    rows, _ = _read(_source(records_at="items", paging="next_link", next_at="next"), answer)
    assert len(rows) == 1 and len(asked) == 1  # the same address again: read once
    with pytest.raises(ValueError):
        _source(paging="next_link")  # where the link is must be said


def _oauth(**kw):
    return _source(auth="oauth_client", secret_ref="x", token_url="https://login.internal/oauth/token",
                   client_id="planner", scope="read:projects", **kw)


def _signing_in(tokens: list[str], data_refusals: int = 0, token_answer=None):
    """A token endpoint giving `tokens` in turn, and a data address refusing its first `data_refusals` reads."""
    asked = []

    def answer(request: httpx.Request):
        if request.url.host == "login.internal":
            from urllib.parse import parse_qsl

            asked.append(("token", dict(parse_qsl(request.content.decode())), request.headers.get("authorization")))
            if token_answer is not None:
                return token_answer
            return httpx.Response(200, json={"access_token": tokens.pop(0), "token_type": "Bearer", "expires_in": 60})
        asked.append(("data", request.headers.get("authorization")))
        if sum(1 for a in asked if a[0] == "data") <= data_refusals:
            return httpx.Response(401)
        return httpx.Response(200, json=[{"project": "P1", "cost": 4}])
    return answer, asked


def test_client_credentials_sign_in_sends_the_secret_as_basic_and_reads_with_the_token():
    import base64

    answer, asked = _signing_in(["t1"])
    rows, seen = _read(_oauth(), answer, secret="s3")
    assert rows == [{"project": "P1", "cost": 4}]
    kind, form, header = asked[0]
    assert kind == "token" and form == {"grant_type": "client_credentials", "scope": "read:projects"}
    assert header == "Basic " + base64.b64encode(b"planner:s3").decode()
    assert asked[1] == ("data", "Bearer t1")


def test_client_credentials_may_go_in_the_form_with_an_audience():
    answer, asked = _signing_in(["t1"])
    _read(_oauth(client_auth="post", audience="https://api.internal"), answer, secret="s3")
    kind, form, header = asked[0]
    assert header is None
    assert form == {"grant_type": "client_credentials", "scope": "read:projects", "audience": "https://api.internal",
                    "client_id": "planner", "client_secret": "s3"}


def test_a_refused_token_is_renewed_once_then_the_refusal_stands():
    answer, asked = _signing_in(["t1", "t2"], data_refusals=1)
    rows, _ = _read(_oauth(), answer)
    assert rows and [a for a in asked if a[0] == "data"] == [("data", "Bearer t1"), ("data", "Bearer t2")]
    answer, asked = _signing_in(["t1", "t2", "t3"], data_refusals=5)
    with pytest.raises(ExtractionError) as failed:
        _read(_oauth(), answer)
    assert failed.value.code == "authentication_failed"
    assert sum(1 for a in asked if a[0] == "token") == 2


@pytest.mark.parametrize("token_answer,code", [
    (httpx.Response(401), "authentication_failed"),
    (httpx.Response(400, json={"error": "invalid_client"}), "authentication_failed"),
    (httpx.Response(302, headers={"location": "https://elsewhere.example/"}), "source_missing"),
    (httpx.Response(500), "source_unreachable"),
    (httpx.Response(200, json={"token_type": "bearer"}), "authentication_failed"),
    (httpx.Response(200, json={"access_token": "t", "token_type": "mac"}), "authentication_failed"),
    (httpx.Response(200, content=b"x" * (65 * 1024)), "format_invalid"),
])
def test_token_failures_are_named(token_answer, code):
    answer, _ = _signing_in([], token_answer=token_answer)
    with pytest.raises(ExtractionError) as failed:
        _read(_oauth(), answer)
    assert failed.value.code == code


def test_client_credentials_need_an_https_token_address_and_a_client_id():
    good = dict(auth="oauth_client", secret_ref="x", token_url="https://login.internal/t", client_id="planner")
    _source(**good)
    for bad in (dict(token_url="http://login.internal/token"), dict(token_url="https://u:p@login.internal/t"),
                dict(token_url=""), dict(client_id=""), dict(client_auth="jwt")):
        with pytest.raises(ValueError):
            _source(**{**good, **bad})


def test_the_token_address_must_resolve_inside_the_approved_networks(monkeypatch):
    import socket

    from app.integrations import http_source

    monkeypatch.setattr(socket, "getaddrinfo", lambda host, *a, **k: [(0, 0, 0, "", ("8.8.8.8" if host == "login.internal" else "10.0.0.4", 443))])
    connector = HttpConnector(_oauth(), lambda _: "s")
    with pytest.raises(ExtractionError) as failed:
        connector._token(True, Event())
    assert failed.value.code == "network_not_allowed"
    assert http_source.resolve(_oauth()) == "10.0.0.4"


def test_a_client_credential_source_is_saved_with_its_token_address_never_its_secret(setup):  # noqa: F811
    client, body, tenants = setup
    source = {"kind": "http", "url": "https://127.0.0.1:9/projects", "format": "json", "columns": ["project"],
              "auth": "oauth_client", "token_url": "https://127.0.0.1:9/token", "client_id": "planner", "scope": "read"}
    made = client.post("/api/v1/connections", headers=tenants["a"], json={
        "domain_id": body["domain_id"], "name": "Signed-in API", "source": source, "password": "client-secret"})
    assert made.status_code == 201, made.text
    listed = client.get(f"/api/v1/connections?domain_id={body['domain_id']}", headers=tenants["a"]).json()
    saved = next(c for c in listed["items"] if c["id"] == made.json()["id"])
    assert saved["config"]["token_url"] == "https://127.0.0.1:9/token" and saved["config"]["client_id"] == "planner"
    assert "client-secret" not in json.dumps(listed)
    for bad in ({"token_url": ""}, {"token_url": "http://127.0.0.1:9/token"}, {"client_id": ""}):
        assert client.post("/api/v1/connections", headers=tenants["a"], json={
            "domain_id": body["domain_id"], "name": "x", "source": {**source, **bad}, "password": "s"}).status_code == 422
    # The sign-in fields belong to the client-credential sign-in only.
    assert client.post("/api/v1/connections", headers=tenants["a"], json={
        "domain_id": body["domain_id"], "name": "x", "source": {**source, "auth": "bearer"}, "password": "s"}).status_code == 422
    from app.integrations.policy import source_for

    row = {"organization_id": ORG, "id": 1, "config": saved["config"]}
    assert source_for(row).token_url == "https://127.0.0.1:9/token"
