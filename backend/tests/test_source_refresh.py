"""A domain built from a database source remembers it, and is refreshed from a newer extraction: what changes is
reported first, then written in one go (records gone set inactive), and the Assistant asks before writing."""
from __future__ import annotations

import json
from uuid import uuid4

from sqlalchemy import text

from app.agent import core
from app.agent import files as agent_files
from app.api import agent as agent_api
from tests.test_import_mapping import extracted  # noqa: F401
from tests.test_integrations import create, setup  # noqa: F401
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401

FIRST = [{"staff_id": "n1", "full_name": "Ada", "hours": "37.5", "grade": 3},
         {"staff_id": "n2", "full_name": "Ben", "hours": "30", "grade": 2},
         {"staff_id": "n3", "full_name": "Cy", "hours": "20", "grade": 1}]
LATER = [{"staff_id": "n1", "full_name": "Ada", "hours": "40", "grade": 3},
         {"staff_id": "n2", "full_name": "Benjamin", "hours": "30", "grade": 4},
         {"staff_id": "n4", "full_name": "Dee", "hours": "10", "grade": 5}]


def _build(client, tenants, job_id):
    sheet = client.get(f"/api/v1/agent/sources/{job_id}/file", headers=tenants["a"]).json()
    kind, grade = f"staff_{uuid4().hex[:6]}", f"grade_{uuid4().hex[:6]}"
    seed = agent_files.expand({
        "entity_types": [{"name": kind, "role": "resource", "attributes": [
            {"name": "hours", "data_type": "number", "required": True}]}],
        "parameters": [{"name": grade, "index": [kind], "default_value": 0}],
        "entities_from_file": [{"file": sheet["name"], "sheet": "staff", "type": kind, "key": "staff_id",
                                "label": "full_name", "attrs": {"hours": "hours"}}],
        "parameter_values_from_file": [{"file": sheet["name"], "sheet": "staff", "parameter": grade,
                                        "entities": [[kind, "staff_id"]], "value": "grade"}]}, [sheet])
    assert [b["kind"] for b in seed["source_bindings"]] == ["entities", "parameter_values"]
    ir = {"version": 2, "sets": [kind], "parameters": {grade: {"index": [kind]}},
          "variables": {"pick": {"index": [kind], "domain": "binary"}},
          "constraints": [{"id": "few", "left": {"sum": {"var": "pick", "index": ["s"]}, "over": [{"index": "s", "set": kind}]},
                           "relation": "<=", "right": {"const": 2}, "severity": "hard"}],
          "objective": {"sense": "maximize", "terms": [{"id": "worth", "weight": 1, "expression": {
              "sum": {"mul": [{"par": grade, "index": ["s"]}, {"var": "pick", "index": ["s"]}]},
              "over": [{"index": "s", "set": kind}]}}]}}
    built = client.post("/api/v1/problems/from-spec", headers=tenants["a"], json={
        "domain_id": tenants["domain_a"], "problem_name": f"staff {uuid4().hex[:6]}", "seed": seed, "ir": ir})
    assert built.status_code == 200, built.text
    assert built.json()["created"]["bound_to_sources"] == 2
    return kind, grade


def test_build_binds_and_refresh_reports_then_applies(extracted, db):  # noqa: F811
    client, tenants, connection, _, job, _ = extracted
    domain = tenants["domain_a"]
    kind, grade = _build(client, tenants, job(FIRST))
    listed = client.get(f"/api/v1/domains/{domain}/source-bindings", headers=tenants["a"]).json()["items"]
    assert {(b["kind"], b["target"]) for b in listed} == {("entities", kind), ("parameter_values", grade)}

    later = job(LATER)
    url = f"/api/v1/domains/{domain}/sources/refresh"
    report = client.post(url, json={"jobs": {str(connection): later}}, headers=tenants["a"])
    assert report.status_code == 200, report.text
    body = report.json()
    assert body["applied"] is False
    records, cells = body["bindings"]
    assert records["counts"] == {"added": 1, "changed": 2, "removed": 1, "unchanged": 0}
    assert records["added"][0]["key"] == "n4"
    changed = {c["key"]: c["fields"] for c in records["changed"]}
    assert changed["n1"] == [{"field": "hours", "before": 37.5, "after": 40}]
    assert changed["n2"] == [{"field": "label", "before": "Ben", "after": "Benjamin"}]
    assert records["removed"] == [{"key": "n3"}]
    assert cells["counts"] == {"added": 1, "changed": 1, "removed": 1, "unchanged": 1}
    # Nothing written by a report.
    assert db.execute(text("SELECT count(*) FROM entity e JOIN entity_type t ON t.id = e.entity_type_id"
                           " WHERE t.name = :k AND e.active"), {"k": kind}).scalar_one() == 3

    applied = client.post(url, json={"jobs": {str(connection): later}, "apply": True}, headers=tenants["a"]).json()
    assert applied["applied"] is True and applied["changes"] == 7
    rows = db.execute(text("SELECT e.key, e.label, e.attrs->>'hours', e.active FROM entity e JOIN entity_type t"
                           " ON t.id = e.entity_type_id WHERE t.name = :k ORDER BY e.key"), {"k": kind}).all()
    assert [(k, lab, float(h), a) for k, lab, h, a in rows] == [
        ("n1", "Ada", 40.0, True), ("n2", "Benjamin", 30.0, True), ("n3", "Cy", 20.0, False), ("n4", "Dee", 10.0, True)]
    values = db.execute(text("SELECT e.key, v.value FROM parameter_value v JOIN parameter_def d ON d.id = v.parameter_def_id"
                             " JOIN entity e ON e.id = v.entity_ids[1] WHERE d.name = :g ORDER BY e.key"), {"g": grade}).all()
    assert [(k, float(v)) for k, v in values] == [("n1", 3.0), ("n2", 4.0), ("n4", 5.0)]

    # The same extraction again: nothing to do, and said so.
    again = client.post(url, json={"jobs": {str(connection): later}}, headers=tenants["a"]).json()
    assert again["changes"] == 0 and all(b["same_extraction"] for b in again["bindings"])
    # The first extraction once more: n3 comes back (active again), n4 goes.
    back = client.post(url, json={"jobs": {str(connection): later - 1}, "apply": True}, headers=tenants["a"]).json()
    assert back["bindings"][0]["added"][0] == {"key": "n3", "label": "Cy", "attrs": {"hours": 20}, "returning": True}
    assert client.post(url, json={}, headers=tenants["b"]).status_code == 404


def test_nothing_bound_is_said(extracted):
    client, tenants, _, _, _, _ = extracted
    res = client.post(f"/api/v1/domains/{tenants['domain_a']}/sources/refresh", json={}, headers=tenants["a"])
    assert res.status_code == 409 and "nothing to refresh" in res.json()["detail"]


def test_the_assistant_reports_before_it_writes():
    sent = []

    def call(method, path, query=None, body=None, form=None, headers=None):
        sent.append((method, path, body))
        if path.endswith("/source-bindings"):
            return {"ok": True, "status": 200, "body": {"items": [
                {"connection_id": 4, "connection": "Products", "enabled": True, "kind": "entities", "target": "product"}]}}
        if path == "/api/v1/connections/4/jobs" and method == "GET":
            return {"ok": True, "status": 200, "body": {"items": []}}
        if path == "/api/v1/connections/4/jobs":
            return {"ok": True, "status": 202, "body": {"id": 9, "state": "extracted"}}
        if path.endswith("/sources/refresh"):
            return {"ok": True, "status": 200, "body": {"applied": body["apply"], "changes": 1, "bindings": [
                {"source": "Products", "kind": "entities", "target": "product", "same_extraction": False,
                 "counts": {"added": 0, "changed": 1, "removed": 0, "unchanged": 4}, "added": [], "removed": [],
                 "changed": [{"key": "P1", "fields": [{"field": "profit", "before": 45, "after": 50}]}]}]}}
        if path.startswith("/api/v1/agent/sources/"):
            return {"ok": True, "status": 200, "body": {"name": "Products", "sheets": [], "source": {"connection_id": 4}}}
        raise AssertionError(path)

    agent = core.Agent(core.Settings(), agent_api._index, call, core.Context("x", mode="model", domain_id=3))
    assert not agent._needs_ok({"function": {"name": "refresh_sources", "arguments": "{}"}})
    # Nothing reported yet: an apply would only report, so there is nothing to allow.
    assert not agent._needs_ok({"function": {"name": "refresh_sources", "arguments": '{"apply": true}'}})
    first = agent.run_tool("refresh_sources", {"apply": True})
    assert first.startswith("REFRESH REPORT -- NOT APPLIED")  # nothing reported yet: a report, not a write
    agent._refresh_pending = None
    sent.clear()
    said = agent.run_tool("refresh_sources", {})
    assert said.startswith("REFRESH REPORT") and "P1: profit 45 -> 50" in said
    assert '(reported: {"domain":3,"jobs":{"4":9},"files":{},"changes":1})' in said
    # The person's yes comes in a later turn, to a new Agent: it reads the report from the conversation.
    later = core.Agent(core.Settings(), agent_api._index, call, core.Context("x", mode="model", domain_id=3))
    later._messages = [{"role": "tool", "name": "refresh_sources", "content": said}]
    assert later._needs_ok({"function": {"name": "refresh_sources", "arguments": '{"apply": true}'}})
    assert "(1 change)" in later._asking({"function": {"name": "refresh_sources", "arguments": '{"apply": true}'}})
    applied = later.run_tool("refresh_sources", {"apply": True})
    assert applied.startswith("REFRESH APPLIED")
    # Only one extraction: the one reported is the one written.
    assert len([1 for m, p, _ in sent if m == "POST" and p.endswith("/jobs")]) == 1
    # Applied once: the same report is not applied again.
    again = core.Agent(core.Settings(), agent_api._index, call, core.Context("x", mode="model", domain_id=3))
    again._messages = later._messages + [{"role": "tool", "name": "refresh_sources", "content": applied}]
    assert again.run_tool("refresh_sources", {"apply": True}).startswith("REFRESH REPORT -- NOT APPLIED")
    posts = [b for m, p, b in sent if p.endswith("/sources/refresh")]
    assert posts[0]["apply"] is False and posts[1]["apply"] is True and posts[0]["jobs"] == posts[1]["jobs"] == {"4": 9}


def test_what_the_person_allows_is_said_in_words():
    agent = core.Agent(core.Settings(), agent_api._index, lambda *a, **k: {"ok": True, "body": {}},
                       core.Context("x", mode="model", domain_id=3))
    agent._refresh_pending = {"domain": 3, "jobs": {4: 9}, "changes": 4}
    said = agent._asking({"function": {"name": "refresh_sources", "arguments": '{"apply": true}'}})
    assert said.startswith("Write the changes just reported") and "(4 changes)" in said
    assert agent._asking({"function": {"name": "call_api", "arguments": '{"method": "delete", "path": "/api/v1/runs/9"}'}}) \
        == "DELETE /api/v1/runs/9"
    assert "scenario 12" in agent._asking({"function": {"name": "what_if", "arguments": '{"scenario_id": 12, "name": "x"}'}})


def test_an_attached_file_is_kept_by_version_and_refreshed(tenants, db):  # noqa: F811
    from fastapi.testclient import TestClient

    from app.main import app
    from tests.test_agent import _in_process_caller

    client, domain = TestClient(app), tenants["domain_a"]
    name = f"crews_{uuid4().hex[:6]}.csv"
    week1 = agent_files.parse(name, b"crew,size\nA,4\nB,6\nC,3\n")
    kind = f"crew_{uuid4().hex[:6]}"
    seed = agent_files.expand({
        "entity_types": [{"name": kind, "role": "resource", "attributes": [{"name": "size", "data_type": "number",
                                                                             "required": True}]}],
        "entities_from_file": [{"file": name, "type": kind, "key": "crew", "attrs": {"size": "size"}}]}, [week1])
    assert seed["source_bindings"] == [{"file_name": name, "kind": "entities", "target": kind,
                                        "mapping": {"type": kind, "key": "crew", "attrs": {"size": "size"}}}]
    assert [f["name"] for f in seed["source_files"]] == [name]
    ir = {"version": 2, "sets": [kind], "parameters": {}, "variables": {"use": {"index": [kind], "domain": "binary"}},
          "constraints": [{"id": "two", "left": {"sum": {"var": "use", "index": ["c"]}, "over": [{"index": "c", "set": kind}]},
                           "relation": "<=", "right": {"const": 2}, "severity": "hard"}],
          "objective": {"sense": "maximize", "terms": [{"id": "size", "weight": 1, "expression": {
              "sum": {"mul": [{"attr": {"of": "c", "name": "size"}}, {"var": "use", "index": ["c"]}]},
              "over": [{"index": "c", "set": kind}]}}]}}
    built = client.post("/api/v1/problems/from-spec", headers=tenants["a"], json={
        "domain_id": domain, "problem_name": f"crews {uuid4().hex[:6]}", "seed": seed, "ir": ir})
    assert built.status_code == 200, built.text
    kept = client.get(f"/api/v1/domains/{domain}/files", headers=tenants["a"]).json()["items"]
    assert any(f["name"] == name and f["latest"] == 1 and f["rows"] == 3 for f in kept)
    space = client.get("/api/v1/agent/workspace", params={"domain_id": domain}, headers=tenants["a"]).json()
    assert any(f["name"] == name for f in space["files"])

    # Next week: the same file name, new content, attached in a conversation.
    week2 = agent_files.parse(name, b"crew,size\nA,5\nB,6\nD,7\n")
    token = tenants["a"]["Authorization"].split(" ", 1)[1]
    agent = core.Agent(core.Settings(), agent_api._index, _in_process_caller(core.Settings(), token),
                       core.Context("x", mode="model", domain_id=domain, files=[week2]))
    said = agent.run_tool("refresh_sources", {"sources": [name]})
    assert said.startswith("REFRESH REPORT"), said
    assert "kept as version 2" in said and "(version 1 -> 2)" in said
    assert "+ D" in said and "~ A: size 4 -> 5" in said and "- C" in said
    # The person's page shows another workspace: the workspace is named (the one this conversation built in).
    later = core.Agent(core.Settings(), agent_api._index, _in_process_caller(core.Settings(), token),
                       core.Context("x", mode="model", domain_id=None))
    later._messages = [{"role": "tool", "name": "refresh_sources", "content": said}]
    assert later._needs_ok({"function": {"name": "refresh_sources",
                                         "arguments": json.dumps({"apply": True, "domain_id": domain})}})
    assert later.run_tool("refresh_sources", {"sources": [name], "apply": True, "domain_id": domain}
                          ).startswith("REFRESH APPLIED")
    rows = db.execute(text("SELECT e.key, (e.attrs->>'size')::numeric, e.active FROM entity e JOIN entity_type t"
                           " ON t.id = e.entity_type_id WHERE t.name = :k ORDER BY e.key"), {"k": kind}).all()
    assert [(k, float(v), a) for k, v, a in rows] == [("A", 5.0, True), ("B", 6.0, True), ("C", 3.0, False), ("D", 7.0, True)]
    # The same file again is no new version; a kept file can be attached by name.
    assert client.post(f"/api/v1/domains/{domain}/files", json={"file": week2}, headers=tenants["a"]).json()["new"] is False
    reader = core.Agent(core.Settings(), agent_api._index, _in_process_caller(core.Settings(), token),
                        core.Context("x", mode="model", domain_id=domain))
    assert "version 2" in reader.run_tool("use_source", {"source": name})
    db.execute(text("DELETE FROM source_binding WHERE file_name = :n"), {"n": name})
    db.commit()


def test_a_refresh_from_an_incremental_read_adds_and_updates_but_takes_nothing_away(extracted, db):  # noqa: F811
    """Migration 0118: a read of only what changed since a mark has no row for an unchanged record; that record
    is unchanged, not gone."""
    client, tenants, connection, _, job, root = extracted
    domain = tenants["domain_a"]
    kind, _ = _build(client, tenants, job(FIRST))
    partial = job([{"staff_id": "n1", "full_name": "Ada", "hours": "41", "grade": 3}])
    artifact, org = db.execute(text("SELECT artifact_id, organization_id FROM ingestion_job WHERE id = :j"),
                               {"j": partial}).one()
    path = root / str(org) / str(connection) / str(artifact) / "manifest.json"
    manifest = json.loads(path.read_text())
    path.write_text(json.dumps({**manifest, "changed_column": "updated_at", "since": "2026-10-08T09:00:00",
                                "high_water": "2026-10-08T10:00:00"}))
    body = client.post(f"/api/v1/domains/{domain}/sources/refresh", json={"jobs": {str(connection): partial}},
                       headers=tenants["a"]).json()
    records = body["bindings"][0]
    assert records["counts"]["changed"] == 1 and records["counts"]["removed"] == 0, records["counts"]
    applied = client.post(f"/api/v1/domains/{domain}/sources/refresh", json={"jobs": {str(connection): partial},
                                                                             "apply": True}, headers=tenants["a"]).json()
    assert applied["applied"] is True
    active = db.execute(text("SELECT count(*) FROM entity e JOIN entity_type t ON t.id = e.entity_type_id"
                             " WHERE t.name = :k AND e.active"), {"k": kind}).scalar_one()
    assert active == 3  # n2 and n3 kept


def test_a_source_of_two_tables_is_two_sheets_and_each_can_be_previewed(extracted, db):  # noqa: F811
    """One source, several tables: the refresh reads a sheet per table, and the preview and import name one."""
    import hashlib

    client, tenants, connection, _, job, root = extracted
    staff = job(FIRST)
    artifact, org = db.execute(text("SELECT artifact_id, organization_id FROM ingestion_job WHERE id = :j"),
                               {"j": staff}).one()
    folder = root / str(org) / str(connection) / str(artifact)
    rows = [{"site": "S1", "beds": 4}, {"site": "S2", "beds": 6}]
    lines = b"".join((json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n").encode() for r in rows)
    (folder / "rows-2.jsonl").write_bytes(lines)
    manifest = json.loads((folder / "manifest.json").read_text())
    manifest["tables"] = [{"file": "rows.jsonl", "source_object": "staff", "columns": manifest["columns"],
                           "rows": manifest["rows"], "sha256": manifest["sha256"]},
                          {"file": "rows-2.jsonl", "source_object": "sites", "columns": ["site", "beds"], "rows": 2,
                           "sha256": hashlib.sha256(lines).hexdigest()}]
    (folder / "manifest.json").write_text(json.dumps(manifest))
    sheet = client.get(f"/api/v1/agent/sources/{staff}/file", headers=tenants["a"]).json()
    assert [s["name"] for s in sheet["sheets"]] == ["staff", "sites"] and sheet["sheets"][1]["rows"][1][1] in (6, "6")
    second = client.get(f"/api/v1/ingestion-jobs/{staff}/preview?table=sites", headers=tenants["a"]).json()
    assert second["columns"] == ["site", "beds"] and second["rows"][0]["site"] == "S1"
    assert second["tables"] == ["staff", "sites"]
    first = client.get(f"/api/v1/ingestion-jobs/{staff}/preview", headers=tenants["a"]).json()
    assert first["source_object"] == "staff"
    assert client.get(f"/api/v1/ingestion-jobs/{staff}/preview?table=nowhere", headers=tenants["a"]).status_code == 409


def test_a_load_from_the_sources_page_can_be_kept_refreshed(extracted, db):  # noqa: F811
    """Without the Assistant (owner, 9 October 2026): the import wizard's load binds what it wrote to its source."""
    client, tenants, connection, person, job, _ = extracted
    domain = db.execute(text("SELECT domain_id FROM integration_connection WHERE id = :c"), {"c": connection}).scalar_one()
    first = job(FIRST)
    mapping = {"entity_type_id": person, "columns": {"staff_id": "key", "full_name": "label", "hours": "hours"}}
    report = client.post(f"/api/v1/ingestion-jobs/{first}/validate", json=mapping, headers=tenants["a"]).json()
    loaded = client.post(f"/api/v1/ingestion-jobs/{first}/load", json={"validation_id": report["validation_id"],
                                                                      "keep_refreshed": True}, headers=tenants["a"])
    assert loaded.status_code == 200, loaded.text
    assert loaded.json()["kept_refreshed"] is True
    bound = client.get(f"/api/v1/domains/{domain}/source-bindings", headers=tenants["a"]).json()["items"]
    mine = [b for b in bound if b["connection_id"] == connection]
    assert [(b["kind"], b["mapping"]) for b in mine] == [
        ("entities", {"key": "staff_id", "label": "full_name", "attrs": {"hours": "hours"}})]
    later = job(LATER)
    url = f"/api/v1/domains/{domain}/sources/refresh"
    changes = client.post(url, json={"connections": [connection], "jobs": {str(connection): later}},
                          headers=tenants["a"]).json()
    assert changes["bindings"][0]["counts"] == {"added": 1, "changed": 2, "removed": 1, "unchanged": 0}
    # Stopped: what it loaded stays, and the next refresh has nothing of it.
    assert client.delete(f"/api/v1/domains/{domain}/source-bindings/{mine[0]['id']}",
                         headers=tenants["a"]).status_code == 204
    left = client.get(f"/api/v1/domains/{domain}/source-bindings", headers=tenants["a"]).json()["items"]
    assert not [b for b in left if b["connection_id"] == connection]


def test_a_kept_file_is_loaded_into_records_and_kept_refreshed_without_the_assistant(tenants, db):  # noqa: F811
    from fastapi.testclient import TestClient

    from app.main import app

    client, domain = TestClient(app), tenants["domain_a"]
    kind = f"crew_{uuid4().hex[:6]}"
    made = client.post("/api/v1/entity-types", headers=tenants["a"], json={
        "domain_id": domain, "name": kind, "role": "resource"})
    assert made.status_code in (200, 201), made.text
    type_id = made.json()["id"]
    assert client.post(f"/api/v1/entity-types/{type_id}/attributes", headers=tenants["a"],
                       json={"name": "size", "data_type": "number"}).status_code in (200, 201)
    name = f"crews_{uuid4().hex[:6]}.csv"
    kept = client.post(f"/api/v1/domains/{domain}/files", headers=tenants["a"],
                       json={"file": agent_files.parse(name, b"crew,size\nA,4\nB,6\n")})
    assert kept.status_code == 201, kept.text
    url = f"/api/v1/domains/{domain}/source-bindings"
    bad = client.post(url, headers=tenants["a"], json={"file_name": name, "kind": "entities", "target": kind,
                                                         "mapping": {"key": "crew", "attrs": {"size": "weight"}}})
    assert bad.status_code == 422 and "weight" in bad.text
    bound = client.post(url, headers=tenants["a"], json={"file_name": name, "kind": "entities", "target": kind,
                                                           "mapping": {"key": "crew", "attrs": {"size": "size"}}})
    assert bound.status_code == 201 and bound.json()["rows"] == 2
    first = client.post(f"/api/v1/domains/{domain}/sources/refresh", headers=tenants["a"],
                        json={"files": {name: 1}, "apply": True}).json()
    assert first["applied"] and first["bindings"][0]["counts"]["added"] == 2
    rows = db.execute(text("SELECT e.key, e.attrs->>'size' FROM entity e JOIN entity_type t ON t.id = e.entity_type_id"
                           " WHERE t.name = :k ORDER BY e.key"), {"k": kind}).all()
    assert [(k, float(s)) for k, s in rows] == [("A", 4.0), ("B", 6.0)]
