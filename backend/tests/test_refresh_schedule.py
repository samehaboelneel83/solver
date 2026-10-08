"""A workspace refreshed on a schedule (migration 0116): the ingestion worker's tick starts the extractions, then
compares, keeps the report, applies it in `apply` mode and solves again -- as the schedule's owner."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.agent import files as agent_files
from app.core.db import SessionLocal, engine
from app.integrations import schedule
from app.main import app
from tests.test_import_mapping import _artifact, extracted  # noqa: F401
from tests.test_integrations import create, setup  # noqa: F401
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


def _build_from_file(client, tenants, name, kind):
    week1 = agent_files.parse(name, b"crew,size\nA,4\nB,6\nC,3\n")
    seed = agent_files.expand({
        "entity_types": [{"name": kind, "role": "resource", "attributes": [{"name": "size", "data_type": "number",
                                                                             "required": True}]}],
        "entities_from_file": [{"file": name, "type": kind, "key": "crew", "attrs": {"size": "size"}}]}, [week1])
    ir = {"version": 2, "sets": [kind], "parameters": {}, "variables": {"use": {"index": [kind], "domain": "binary"}},
          "constraints": [{"id": "two", "left": {"sum": {"var": "use", "index": ["c"]}, "over": [{"index": "c", "set": kind}]},
                           "relation": "<=", "right": {"const": 2}, "severity": "hard"}],
          "objective": {"sense": "maximize", "terms": [{"id": "size", "weight": 1, "expression": {
              "sum": {"mul": [{"attr": {"of": "c", "name": "size"}}, {"var": "use", "index": ["c"]}]},
              "over": [{"index": "c", "set": kind}]}}]}}
    built = client.post("/api/v1/problems/from-spec", headers=tenants["a"], json={
        "domain_id": tenants["domain_a"], "problem_name": f"crews {uuid4().hex[:6]}", "seed": seed, "ir": ir})
    assert built.status_code == 200, built.text
    return built.json()


def _cleanup(domain, name=None):
    with SessionLocal() as s:
        s.execute(text("DELETE FROM source_schedule WHERE domain_id = :d"), {"d": domain})
        if name:
            s.execute(text("DELETE FROM source_binding WHERE file_name = :n"), {"n": name})
        s.commit()


def test_a_scheduled_refresh_of_a_kept_file_applies_and_solves_again(tenants, db):  # noqa: F811
    client, domain = TestClient(app), tenants["domain_a"]
    name, kind = f"crews_{uuid4().hex[:6]}.csv", f"crew_{uuid4().hex[:6]}"
    built = _build_from_file(client, tenants, name, kind)
    url = f"/api/v1/domains/{domain}/refresh-schedule"
    try:
        assert client.put(url, json={"every_hours": 24, "solve": True}, headers=tenants["a"]).status_code == 422
        made = client.put(url, json={"every_hours": 24, "mode": "apply", "solve": True}, headers=tenants["a"])
        assert made.status_code == 200, made.text
        assert made.json()["schedule"]["every_hours"] == 24 and made.json()["schedule"]["state"] == "idle"
        week2 = agent_files.parse(name, b"crew,size\nA,5\nB,6\nD,7\n")
        assert client.post(f"/api/v1/domains/{domain}/files", json={"file": week2}, headers=tenants["a"]).json()["version"] == 2

        now = datetime.now(timezone.utc) + timedelta(seconds=1)
        assert schedule.tick(engine, now) >= 1
        got = client.get(url, headers=tenants["a"]).json()["schedule"]
        assert got["last_error"] is None, got
        report = got["last_report"]
        assert report["applied"] is True and report["changes"] == 3
        assert report["bindings"][0]["counts"] == {"added": 1, "changed": 1, "removed": 1, "unchanged": 1}
        runs = report["runs"]
        assert [r["scenario_id"] for r in runs] == [built["scenario_id"]] and runs[0]["run_id"]
        assert datetime.fromisoformat(got["next_at"]) > now + timedelta(hours=23)
        rows = db.execute(text("SELECT e.key, e.active FROM entity e JOIN entity_type t ON t.id = e.entity_type_id"
                               " WHERE t.name = :k ORDER BY e.key"), {"k": kind}).all()
        assert [(k, a) for k, a in rows] == [("A", True), ("B", True), ("C", False), ("D", True)]
        # Not due again yet: nothing happens.
        assert schedule.tick(engine, now + timedelta(hours=1)) == 0
        # Someone else's workspace schedule is not theirs.
        assert client.get(url, headers=tenants["b"]).status_code == 404
    finally:
        _cleanup(domain, name)


def test_a_report_only_schedule_writes_nothing_and_says_what_changed(tenants, db):  # noqa: F811
    client, domain = TestClient(app), tenants["domain_a"]
    name, kind = f"crews_{uuid4().hex[:6]}.csv", f"crew_{uuid4().hex[:6]}"
    _build_from_file(client, tenants, name, kind)
    url = f"/api/v1/domains/{domain}/refresh-schedule"
    try:
        client.put(url, json={"every_hours": 168, "mode": "report"}, headers=tenants["a"])
        client.post(f"/api/v1/domains/{domain}/files", headers=tenants["a"],
                    json={"file": agent_files.parse(name, b"crew,size\nA,9\nB,6\nC,3\n")})
        schedule.tick(engine, datetime.now(timezone.utc) + timedelta(seconds=1))
        got = client.get(url, headers=tenants["a"]).json()["schedule"]
        assert got["last_report"]["applied"] is False and got["last_report"]["changes"] == 1
        assert got["last_report"]["bindings"][0]["changed"] == [
            {"key": "A", "fields": [{"field": "size", "before": 4, "after": 9}]}]
        size = db.execute(text("SELECT (e.attrs->>'size')::numeric FROM entity e JOIN entity_type t"
                               " ON t.id = e.entity_type_id WHERE t.name = :k AND e.key = 'A'"), {"k": kind}).scalar()
        assert float(size) == 4.0
        # Run now brings it forward.
        assert client.post(url + "/run-now", headers=tenants["a"]).status_code == 200
    finally:
        _cleanup(domain, name)


def test_a_scheduled_refresh_extracts_first_then_compares(extracted, db):  # noqa: F811
    client, tenants, connection, _, job, tmp_path = extracted
    from tests.test_source_refresh import FIRST, LATER, _build

    domain = tenants["domain_a"]
    kind, _ = _build(client, tenants, job(FIRST))
    url = f"/api/v1/domains/{domain}/refresh-schedule"
    try:
        assert client.put(url, json={"every_hours": 24, "mode": "apply"}, headers=tenants["a"]).status_code == 200
        now = datetime.now(timezone.utc) + timedelta(seconds=1)
        schedule.tick(engine, now)
        got = client.get(url, headers=tenants["a"]).json()["schedule"]
        assert got["state"] == "extracting"
        queued = db.execute(text("SELECT id FROM ingestion_job WHERE connection_id = :c AND state = 'queued'"),
                            {"c": connection}).scalar()
        assert queued
        # Still extracting: the tick waits.
        assert schedule.tick(engine, now) == 0
        # The ingestion worker finishes it (here: an artifact written as the worker would).
        org = db.execute(text("SELECT organization_id FROM integration_connection WHERE id = :c"), {"c": connection}).scalar()
        artifact = _artifact(tmp_path, org, connection, LATER)
        with SessionLocal() as s:
            s.execute(text("UPDATE ingestion_job SET state = 'extracted', artifact_id = CAST(:a AS uuid),"
                           " finished_at = now() WHERE id = :j"), {"a": artifact, "j": queued})
            s.commit()
        assert schedule.tick(engine, now) == 1
        got = client.get(url, headers=tenants["a"]).json()["schedule"]
        assert got["state"] == "idle" and got["last_error"] is None, got
        assert got["last_report"]["applied"] is True and got["last_report"]["changes"] == 7
        active = db.execute(text("SELECT count(*) FROM entity e JOIN entity_type t ON t.id = e.entity_type_id"
                                 " WHERE t.name = :k AND e.active"), {"k": kind}).scalar()
        assert active == 3
    finally:
        _cleanup(domain)


def test_the_owner_needs_the_permissions_at_each_run(tenants, db):  # noqa: F811
    client, domain = TestClient(app), tenants["domain_a"]
    name, kind = f"crews_{uuid4().hex[:6]}.csv", f"crew_{uuid4().hex[:6]}"
    _build_from_file(client, tenants, name, kind)
    url = f"/api/v1/domains/{domain}/refresh-schedule"
    try:
        client.put(url, json={"every_hours": 24, "mode": "apply"}, headers=tenants["a"])
        from app.api import deps

        real = deps.capabilities_of
        deps.capabilities_of = lambda db, user: {"integration.run"}
        try:
            schedule.tick(engine, datetime.now(timezone.utc) + timedelta(seconds=1))
        finally:
            deps.capabilities_of = real
        got = client.get(url, headers=tenants["a"]).json()["schedule"]
        assert "may no longer domain.edit" in got["last_error"] and got["last_report"] is None
    finally:
        _cleanup(domain, name)


def test_the_assistant_sets_a_schedule_with_the_persons_approval(tenants, db):  # noqa: F811
    from app.agent import core
    from app.api import agent as agent_api
    from tests.test_agent import _in_process_caller

    client, domain = TestClient(app), tenants["domain_a"]
    name, kind = f"crews_{uuid4().hex[:6]}.csv", f"crew_{uuid4().hex[:6]}"
    _build_from_file(client, tenants, name, kind)
    token = tenants["a"]["Authorization"].split(" ", 1)[1]
    agent = core.Agent(core.Settings(), agent_api._index, _in_process_caller(core.Settings(), token),
                       core.Context("x", mode="model", domain_id=domain))
    call = {"function": {"name": "schedule_refresh",
                         "arguments": '{"every_hours": 168, "mode": "apply", "solve": true}'}}
    try:
        assert agent._needs_ok(call)
        assert agent._asking(call) == ("Refresh this workspace from its sources every week, as you; apply the changes "
                                       "and solve its scenarios again.")
        said = agent.run_tool("schedule_refresh", {"every_hours": 168, "mode": "apply", "solve": True})
        assert said.startswith("SCHEDULED: every 168 h, mode apply, solve again True, on; the first run starts now"), said
        assert core._when_next("2030-01-02T03:04:05+00:00") == "next run 2030-01-02 03:04 UTC"
        space = client.get("/api/v1/agent/workspace", params={"domain_id": domain}, headers=tenants["a"]).json()
        assert space["refresh_schedule"]["every_hours"] == 168 and space["refresh_schedule"]["solve"] is True
    finally:
        _cleanup(domain, name)
