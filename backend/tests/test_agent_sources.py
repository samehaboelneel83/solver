"""Workspace data sources in the Assistant: a database table's extraction arrives as an attached sheet
(`use_source`), listed by describe_workspace, read by read_file / query_file and loaded by *_from_file."""
from __future__ import annotations

from app.agent import core
from app.api import agent as agent_api
from tests.test_agent import _in_process_caller
from tests.test_import_mapping import ROWS, extracted  # noqa: F401
from tests.test_integrations import create, setup  # noqa: F401
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


def _token(headers: dict) -> str:
    return headers["Authorization"].split(" ", 1)[1]


def _domain(client, tenants, connection) -> int:
    listed = client.get(f"/api/v1/connections/{connection}/jobs", headers=tenants["a"])
    assert listed.status_code == 200
    return tenants["domain_a"]


def test_an_extraction_reads_as_an_attached_sheet(extracted):
    client, tenants, connection, _, job, _ = extracted
    job_id = job(ROWS)
    sheet = client.get(f"/api/v1/agent/sources/{job_id}/file", headers=tenants["a"])
    assert sheet.status_code == 200, sheet.text
    body = sheet.json()
    assert body["name"] == "Staff source"
    first = body["sheets"][0]
    assert first["name"] == "staff" and first["columns"] == ["staff_id", "full_name", "hours", "grade"]
    # Numbers written as text by the extraction are numbers here, as in an attached CSV.
    assert first["rows"][0] == ["n1", "Ada", 37.5, 3] and first["total_rows"] == 3 and first["truncated"] is False
    assert body["source"]["job_id"] == job_id and len(body["source"]["sha256"]) == 64
    assert client.get(f"/api/v1/agent/sources/{job_id}/file", headers=tenants["b"]).status_code == 404


def test_the_workspace_lists_its_sources_without_credentials(extracted):
    client, tenants, connection, _, job, _ = extracted
    job_id = job(ROWS)
    space = client.get("/api/v1/agent/workspace", params={"domain_id": tenants["domain_a"]}, headers=tenants["a"]).json()
    mine = next(s for s in space["data_sources"] if s["id"] == connection)
    assert mine["table"] == "planning.staff" and mine["columns"] == ["id"]
    assert mine["last_extraction"]["job_id"] == job_id and mine["last_extraction"]["state"] == "extracted"
    assert "never-return-me" not in str(space) and "host" not in mine


def test_use_source_attaches_the_latest_extraction(extracted):
    client, tenants, connection, _, job, _ = extracted
    job_id = job(ROWS)
    agent = core.Agent(core.Settings(), agent_api._index, _in_process_caller(core.Settings(), _token(tenants["a"])),
                       core.Context("x", mode="model", domain_id=_domain(client, tenants, connection)))
    said = agent.run_tool("use_source", {"source": "staff SOURCE"})
    assert said.startswith('Data source "Staff source" is attached'), said
    assert f"job {job_id}" in said and "3 rows" in said
    attached = next(f for f in agent.ctx.files if f["name"] == "Staff source")
    assert attached["source"]["job_id"] == job_id
    assert agent.events[-1]["type"] == "file"
    # Read like any attached file.
    total = agent.run_tool("query_file", {"file": "Staff source", "aggregate": {"grade": "sum"}})
    assert "6" in total, total
    # By id too; an attached file of the same name keeps its name, the source gets its own.
    agent.ctx.files = [{"name": "Staff source", "sheets": []}]
    again = agent.run_tool("use_source", {"source": str(connection)})
    assert 'file name is "Staff source (source)"' in again
    assert [f["name"] for f in agent.ctx.files] == ["Staff source", "Staff source (source)"]


def test_use_source_names_unknown_sources_and_failures():
    calls = []

    def call(method, path, query=None, body=None, form=None, headers=None):
        calls.append((method, path))
        if path == "/api/v1/connections":
            return {"ok": True, "status": 200, "body": {"items": [{"id": 4, "name": "Plants", "enabled": True}]}}
        if path.endswith("/jobs") and method == "GET":
            return {"ok": True, "status": 200, "body": {"items": [
                {"id": 7, "state": "extracted", "finished_at": "2026-10-06T08:00:00Z"}]}}
        if path.endswith("/jobs") and method == "POST":
            return {"ok": True, "status": 202, "body": {"id": 8, "state": "queued"}}
        if path.startswith("/api/v1/domains/3/files"):
            return ({"ok": True, "status": 200, "body": {"items": []}} if path.endswith("/files")
                    else {"ok": False, "status": 404, "body": {"detail": "No such file"}})
        if path == "/api/v1/ingestion-jobs/8":
            return {"ok": True, "status": 200, "body": {"id": 8, "state": "failed", "error_code": "authentication_failed"}}
        raise AssertionError(path)

    agent = core.Agent(core.Settings(), agent_api._index, call, core.Context("x", mode="model", domain_id=3))
    assert agent.run_tool("use_source", {"source": "Lanes"}).startswith('No data source "Lanes"')
    said = agent.run_tool("use_source", {"source": "plants", "refresh": True})
    assert "refused the stored user name or password" in said and "(authentication_failed)" in said
    # The last good extraction is offered, with the warning that it may be old.
    assert "job 7" in said and "may be old" in said
    assert agent.ctx.files == []
    no_domain = core.Agent(core.Settings(), agent_api._index, call, core.Context("x", mode="model"))
    assert "no workspace" in no_domain.run_tool("use_source", {"source": "plants"})


def test_the_tool_is_offered_in_both_modes():
    assert "use_source" in [t["function"]["name"] for t in core.TOOLS]
    assert "use_source" in [t["function"]["name"] for t in core.MODEL_TOOLS]
    assert "use_source" in core.DATA_TOOLS
