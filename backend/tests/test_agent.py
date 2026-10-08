"""The platform assistant (app/agent, app/api/agent.py) and the spec build it uses
(app/api/model_spec.py).

The LLM is replaced by a script (`core.llm_chat`), and the assistant's own API
calls go in-process through TestClient with the caller's token -- so everything
below the model is real: the routes, the capability checks, the IR validator,
the database.
"""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.agent import core
from app.api import agent as agent_api
from app.main import app
from tests.test_quadratic import empty_queue  # noqa: F401
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


def _in_process_caller(settings: core.Settings, token: str) -> core.CallFn:
    client = TestClient(app)

    def call(method, path, query=None, body=None, form=None, headers=None) -> dict:
        response = client.request(method, path, params=query, json=body, data=form,
                                  headers={**(headers or {}), "Authorization": f"Bearer {token}"})
        try:
            payload: Any = response.json()
        except ValueError:
            payload = response.text
        return {"status": response.status_code, "ok": response.is_success, "body": payload}

    return call


class ScriptedLLM:
    """Plays the model: each reply is the next entry, a tool call or a final answer."""

    def __init__(self, replies: list):
        self.replies = list(replies)
        self.requests: list[dict] = []

    def __call__(self, settings, messages, native, tools=None, max_tokens=None):
        self.requests.append({"messages": copy.deepcopy(messages), "tools": [t["function"]["name"] for t in tools or []]})
        reply = self.replies.pop(0)
        if isinstance(reply, str):
            return {"role": "assistant", "content": reply}, True
        name, args = reply
        return {"role": "assistant", "content": None, "tool_calls": [
            {"id": f"c{len(self.requests)}", "type": "function",
             "function": {"name": name, "arguments": json.dumps(args)}}]}, True


@pytest.fixture
def assistant(monkeypatch):
    monkeypatch.setattr(agent_api, "make_caller", _in_process_caller)

    def install(replies: list) -> ScriptedLLM:
        llm = ScriptedLLM(replies)
        monkeypatch.setattr(core, "llm_chat", llm)
        return llm

    return install


def _chat(headers: dict, **body) -> list[dict]:
    response = TestClient(app).post("/api/v1/agent/chat", json=body, headers=headers)
    assert response.status_code == 200, response.text
    events = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    assert events[-1]["type"] == "state", events
    return events


def _spec(name: str) -> dict:
    spec = copy.deepcopy(core.EXAMPLE_SPEC)
    spec["domain_name"] = f"City projects {name}"
    return spec


# -- the spec build -----------------------------------------------------------


def test_the_prompts_example_spec_is_a_valid_model_and_builds_all_or_nothing(tenants, db):
    client = TestClient(app)
    spec = _spec("example")

    dry = client.post("/api/v1/problems/from-spec", json={**spec, "dry_run": True}, headers=tenants["b"])
    assert dry.status_code == 200, dry.text
    assert dry.json()["would_create"]["entities"] == 4
    assert db.execute(text("SELECT count(*) FROM domain WHERE name = :n"), {"n": spec["domain_name"]}).scalar() == 0

    built = client.post("/api/v1/problems/from-spec", json=spec, headers=tenants["b"])
    assert built.status_code == 200, built.text
    body = built.json()
    scenario = client.get(f"/api/v1/scenarios/{body['scenario_id']}", headers=tenants["b"])
    assert scenario.status_code == 200 and scenario.json()["name"] == "Base"
    version = client.get(f"/api/v1/versions/{body['model_version_id']}", headers=tenants["b"]).json()
    assert version["ir"]["objective"]["sense"] == "maximize"


def test_a_spec_that_would_be_half_built_is_refused_with_every_place_named(tenants, db):
    spec = _spec("broken")
    spec["seed"]["parameters"].append({"name": "demand", "index": ["day"]})            # no such type
    spec["seed"]["entities"].append({"type": "project", "key": "x", "attrs": {"colour": "red"}})  # no such field, cost missing
    spec["seed"]["parameter_values"] = [{"parameter": "budget", "entities": [["project", "roof"]], "value": 1}]
    response = TestClient(app).post("/api/v1/problems/from-spec", json=spec, headers=tenants["b"])
    assert response.status_code == 422
    places = {tuple(e["loc"]) for e in response.json()["detail"]}
    assert ("seed", "parameters", 1, "index") in places
    assert ("seed", "entities", 4, "attrs", "colour") in places
    assert ("seed", "entities", 4, "attrs") in places
    assert ("seed", "parameter_values", 0, "entities") in places
    assert db.execute(text("SELECT count(*) FROM domain WHERE name = :n"), {"n": spec["domain_name"]}).scalar() == 0


def test_an_ir_the_validator_refuses_rolls_the_whole_build_back(tenants, db):
    spec = _spec("bad-ir")
    spec["ir"]["constraints"][0]["left"]["sum"]["mul"][1]["index"] = ["q"]  # unbound index
    response = TestClient(app).post("/api/v1/problems/from-spec", json=spec, headers=tenants["b"])
    assert response.status_code == 422, response.text
    assert response.json()["detail"][0]["loc"][0] == "ir"
    assert db.execute(text("SELECT count(*) FROM domain WHERE name = :n"), {"n": spec["domain_name"]}).scalar() == 0


# -- model mode: interview, plan, approval, build ------------------------------


def test_model_mode_interviews_before_it_plans_and_builds_only_what_was_approved(tenants, db, assistant):
    spec = _spec("conversation")
    bad = copy.deepcopy(spec)
    bad["seed"]["entities"][0]["attrs"].pop("cost")
    llm = assistant([
        # Turn 1: tries to plan straight away -- refused, so it asks instead.
        ("propose_plan", {"summary": "fund projects", "spec": spec}),
        # A write that is not data preparation (a problem made outside the plan) is refused.
        ("call_api", {"method": "POST", "path": "/api/v1/problems", "body": {"name": "sneaky", "domain_id": 1}}),
        "So far: choose projects within a budget. 1. What is the budget? 2. Any limits per district?",
        # Turn 2: a spec with a mistake goes back to the model, the fixed one goes to the person.
        ("propose_plan", {"summary": "**Problem** fund the best projects", "spec": bad}),
        ("propose_plan", {"summary": "**Problem** fund the best projects", "spec": spec}),
        # After approval: it reports.
        "Built: the domain, 4 projects, the budget rule, the district A rule and the benefit goal.",
    ])
    first = _chat(tenants["b"], text="I need to pick which city projects to fund.", mode="model")
    results = [e for e in first if e["type"] == "result"]
    assert results[0]["name"] == "propose_plan" and "not discussed" in results[0]["preview"]
    assert results[1]["name"] == "call_api" and "Refused" in results[1]["preview"]
    assert first[-2]["type"] == "answer"
    assert {"propose_plan", "check_spec", "describe_workspace"} <= set(llm.requests[0]["tools"])
    assert db.execute(text("SELECT count(*) FROM problem WHERE name = 'sneaky'")).scalar() == 0

    second = _chat(tenants["b"], messages=first[-1]["messages"], mode="model",
                   text="Budget 500k, at most two in district A, maximise benefit.")
    fixes = [e for e in second if e["type"] == "result" and e["name"] == "propose_plan"]
    assert fixes and "cost is required" in fixes[0]["preview"]
    plan = next(e for e in second if e["type"] == "plan")
    assert plan["counts"]["entities"] == 4
    assert db.execute(text("SELECT count(*) FROM domain WHERE name = :n"), {"n": spec["domain_name"]}).scalar() == 0

    third = _chat(tenants["b"], messages=second[-1]["messages"], mode="model", confirm={"allow": True})
    built = next(e for e in third if e["type"] == "built")
    assert third[-1]["wrote"] is True
    assert db.execute(text("SELECT count(*) FROM scenario WHERE id = :s"), {"s": built["scenario_id"]}).scalar() == 1
    assert "BUILT" in llm.requests[-1]["messages"][-1]["content"]
    assert next(e for e in third if e["type"] == "answer")["text"].startswith("Built:")


def test_a_reply_instead_of_approval_is_feedback_and_nothing_is_built(tenants, db, assistant):
    spec = _spec("feedback")
    assistant([
        "1. Budget? 2. Districts?",
        ("propose_plan", {"summary": "plan", "spec": spec}),
        "Understood: district B gets at most one as well. Here is the revised plan.",
    ])
    first = _chat(tenants["b"], text="pick projects", mode="model")
    second = _chat(tenants["b"], messages=first[-1]["messages"], mode="model", text="500k, two in A")
    assert any(e["type"] == "plan" for e in second)
    third = _chat(tenants["b"], messages=second[-1]["messages"], mode="model", text="Also at most one in B.")
    history = third[-1]["messages"]
    assert any(m["role"] == "tool" and m["content"].startswith("Not approved") for m in history)
    assert db.execute(text("SELECT count(*) FROM domain WHERE name = :n"), {"n": spec["domain_name"]}).scalar() == 0


# -- assistant mode -------------------------------------------------------------


def test_assistant_mode_acts_as_the_caller_and_asks_before_deleting(tenants, db, assistant):
    assistant([
        ("search_endpoints", {"query": "domains"}),
        ("call_api", {"method": "POST", "path": "/api/domain/", "body": {"name": "made-by-assistant"}}),
        ("call_api", {"method": "DELETE", "path": "/api/domain/999999999"}),
        "Done.",
    ])
    first = _chat(tenants["b"], text="make a domain, then delete domain 999999999")
    assert any(e["type"] == "confirm" for e in first)
    assert db.execute(text("SELECT count(*) FROM domain WHERE name = 'made-by-assistant'")).scalar() == 1
    second = _chat(tenants["b"], messages=first[-1]["messages"], confirm={"allow": False})
    declined = [e for e in second if e["type"] == "result"]
    assert declined and "declined" in declined[0]["preview"]


def test_the_assistant_cannot_reach_itself_or_sign_in(tenants, assistant):
    assistant([
        ("call_api", {"method": "POST", "path": "/api/auth/login", "form": {"username": "admin", "password": "x"}}),
        ("call_api", {"method": "POST", "path": "/api/v1/agent/chat", "body": {}}),
        "no",
    ])
    events = _chat(tenants["b"], text="log in as admin")
    assert all("not available" in e["preview"] for e in events if e["type"] == "result")


def test_status_and_chat_need_a_signed_in_user():
    client = TestClient(app)
    assert client.get("/api/v1/agent/status").status_code == 401
    assert client.post("/api/v1/agent/chat", json={"text": "hi"}).status_code == 401


def test_confirm_with_nothing_waiting_is_a_409(tenants, assistant):
    assistant([])
    response = TestClient(app).post("/api/v1/agent/chat", json={"confirm": {"allow": True}}, headers=tenants["b"])
    assert response.status_code == 409


# -- attached files -------------------------------------------------------------

SHOPS_CSV = "shop,name,demand_trays\nS1,Corner Cafe,20\nS2,Main St,35\nS3,Station,15\nS4,Market,40\n"


def _bakery_spec(name: str) -> dict:
    v, s = {"index": "v", "set": "van"}, {"index": "s", "set": "shop"}
    return {
        "domain_name": f"Bakery {name}",
        "problem_name": "Vans to shops",
        "seed": {
            "entity_types": [
                {"name": "van", "role": "resource", "attributes": [
                    {"name": "capacity", "data_type": "integer", "required": True, "unit": "trays"},
                    {"name": "run_cost", "data_type": "number", "required": True}]},
                {"name": "shop", "role": "location", "attributes": [
                    {"name": "demand", "data_type": "integer", "required": True, "unit": "trays"}]}],
            "entities": [
                {"type": "van", "key": "v1", "attrs": {"capacity": 120, "run_cost": 1}},
                {"type": "van", "key": "v2", "attrs": {"capacity": 120, "run_cost": 1}},
                {"type": "van", "key": "v3", "attrs": {"capacity": 120, "run_cost": 2}}],
            "entities_from_file": [{"file": "shops.csv", "type": "shop", "key": "shop", "label": "name",
                                    "attrs": {"demand": "demand_trays"}}],
        },
        "ir": {
            "version": 2, "sets": ["van", "shop"], "parameters": {},
            "variables": {"assign": {"index": ["van", "shop"], "domain": "binary"},
                          "use": {"index": ["van"], "domain": "binary"}},
            "constraints": [
                {"id": "c_one_van", "note": "every shop is served by exactly one van", "forall": [s],
                 "left": {"sum": {"var": "assign", "index": ["v", "s"]}, "over": [v]},
                 "relation": "=", "right": {"const": 1}, "severity": "hard"},
                {"id": "c_capacity", "note": "a van carries at most its capacity, and only if used", "forall": [v],
                 "left": {"sum": {"mul": [{"attr": {"of": "s", "name": "demand"}}, {"var": "assign", "index": ["v", "s"]}]},
                          "over": [s]},
                 "relation": "<=",
                 "right": {"mul": [{"attr": {"of": "v", "name": "capacity"}}, {"var": "use", "index": ["v"]}]},
                 "severity": "hard"}],
            "objective": {"sense": "minimize", "terms": [{"id": "o_van_cost", "weight": 1, "expression": {
                "sum": {"mul": [{"attr": {"of": "v", "name": "run_cost"}}, {"var": "use", "index": ["v"]}]},
                "over": [v]}}]},
        },
    }


def test_an_attached_file_is_read_into_tables(tenants):
    client = TestClient(app)
    csv_file = client.post("/api/v1/agent/files", files={"file": ("shops.csv", SHOPS_CSV, "text/csv")}, headers=tenants["b"])
    assert csv_file.status_code == 200, csv_file.text
    sheet = csv_file.json()["sheets"][0]
    assert sheet["columns"] == ["shop", "name", "demand_trays"]
    assert sheet["rows"][1] == ["S2", "Main St", 35] and sheet["total_rows"] == 4

    from openpyxl import Workbook
    import io
    book = Workbook()
    book.active.title = "Vans"
    book.active.append(["van", "capacity"])
    book.active.append(["V1", 120])
    buffer = io.BytesIO()
    book.save(buffer)
    xlsx = client.post("/api/v1/agent/files", headers=tenants["b"],
                       files={"file": ("fleet.xlsx", buffer.getvalue(), "application/octet-stream")})
    assert xlsx.status_code == 200 and xlsx.json()["sheets"][0]["rows"] == [["V1", 120]]

    refused = client.post("/api/v1/agent/files", files={"file": ("x.exe", b"MZ", "application/octet-stream")}, headers=tenants["b"])
    assert refused.status_code == 422
    assert client.post("/api/v1/agent/files", files={"file": ("a.csv", "a\n1", "text/csv")}).status_code == 401


def test_a_plan_loads_its_records_from_an_attached_file_and_builds(tenants, db, assistant):
    client = TestClient(app)
    shops = client.post("/api/v1/agent/files", files={"file": ("shops.csv", SHOPS_CSV, "text/csv")}, headers=tenants["b"]).json()
    spec = _bakery_spec("file")
    wrong = copy.deepcopy(spec)
    wrong["seed"]["entities_from_file"][0]["attrs"] = {"demand": "trays"}
    llm = assistant([
        ("read_file", {"file": "shops.csv"}),
        "4 shops, 3 vans of 120 trays. 1. Is V3 more expensive to run than V1 and V2? 2. May a shop be split across vans?",
        ("propose_plan", {"summary": "**Sets** van, shop", "spec": wrong}),
        ("propose_plan", {"summary": "**Sets** van, shop", "spec": spec}),
        ("call_api", {"method": "GET", "path": "/api/v1/runs"}),
        "Built and solved.",
    ])
    first = _chat(tenants["b"], mode="model", files=[shops], text="Plan which van serves which shop; shops attached.")
    assert "Corner Cafe" in next(e for e in first if e["type"] == "result")["preview"]
    assert "ATTACHED FILES" in llm.requests[0]["messages"][0]["content"]
    assert '"demand_trays"' in llm.requests[0]["messages"][0]["content"]

    second = _chat(tenants["b"], messages=first[-1]["messages"], mode="model", files=[shops],
                   text="Yes, V3 costs double. No splitting.")
    fixed = next(e for e in second if e["type"] == "result" and e["name"] == "propose_plan")
    assert 'no column "trays"' in fixed["preview"]
    plan = next(e for e in second if e["type"] == "plan")
    assert plan["counts"]["entities"] == 7  # 3 vans typed + 4 shops from the file
    assert "entities_from_file" in plan["spec"]["seed"]  # shown as written, not as 4 copied rows

    third = _chat(tenants["b"], messages=second[-1]["messages"], mode="model", files=[shops], confirm={"allow": True})
    built = next(e for e in third if e["type"] == "built")
    labels = db.execute(text(
        "SELECT e.key, e.label, e.attrs->>'demand' FROM entity e JOIN entity_type t ON t.id = e.entity_type_id"
        " WHERE t.domain_id = :d AND t.name = 'shop' ORDER BY e.key"), {"d": built["domain_id"]}).all()
    assert [tuple(r) for r in labels][1] == ("S2", "Main St", "35")
    # After the build the assistant solves: writes other than the solve stay refused, the solve is allowed.
    assert "POST /api/v1/scenarios/" in llm.requests[4]["messages"][-1]["content"]


def test_what_the_assistant_builds_solves(tenants, db):
    """The loop the assistant closes after a build: queue the Base scenario, solve, read the answer."""
    from app.worker import work_once

    client = TestClient(app)
    shops = client.post("/api/v1/agent/files", files={"file": ("shops.csv", SHOPS_CSV, "text/csv")}, headers=tenants["b"]).json()
    spec = _bakery_spec("solve")
    spec["seed"] = __import__("app.agent.files", fromlist=["expand"]).expand(spec["seed"], [shops])
    built = client.post("/api/v1/problems/from-spec", json=spec, headers=tenants["b"]).json()
    run = client.post(f"/api/v1/scenarios/{built['scenario_id']}/runs", json={}, headers=tenants["b"])
    assert run.status_code == 201, run.text
    for _ in range(5):
        if work_once(db) is None:
            break
    answer = client.get(f"/api/v1/runs/{run.json()['id']}", headers=tenants["b"]).json()
    assert answer["status"] == "optimal", answer
    assert float(answer["objective"]) == 1  # 110 trays fit one cheap van
    vans = {v for v, _ in answer["assignments"]["assign"]}
    assert len(vans) == 1 and vans <= {"v1", "v2"}
    assert answer["labels"]["shop"]["S1"] == "Corner Cafe"


# -- map files: CAD drawings and GIS files ------------------------------------------

SITES_GEOJSON = json.dumps({"type": "FeatureCollection", "features": [
    {"type": "Feature", "properties": {"site": "north", "rent": 900},
     "geometry": {"type": "Polygon", "coordinates": [[[31.20, 30.05], [31.21, 30.05], [31.21, 30.06], [31.20, 30.06], [31.20, 30.05]]]}},
    {"type": "Feature", "properties": {"site": "south", "rent": 600},
     "geometry": {"type": "Polygon", "coordinates": [[[31.22, 30.01], [31.23, 30.01], [31.23, 30.02], [31.22, 30.02], [31.22, 30.01]]]}},
]})


def _utm_drawing() -> bytes:
    """A small CAD drawing in metres, UTM zone 36N around Cairo, with no GEODATA: its system must be asked."""
    import io
    import ezdxf

    doc = ezdxf.new()
    msp = doc.modelspace()
    doc.layers.add("WELLS")
    doc.layers.add("PLOTS")
    for x, y in [(330_100, 3_326_100), (330_900, 3_326_400)]:
        msp.add_point((x, y), dxfattribs={"layer": "WELLS"})
    msp.add_lwpolyline([(330_000, 3_326_000), (330_500, 3_326_000), (330_500, 3_326_300), (330_000, 3_326_300)],
                       close=True, dxfattribs={"layer": "PLOTS"})
    stream = io.StringIO()
    doc.write(stream)
    return stream.getvalue().encode()


def test_a_gis_file_is_placed_by_itself_and_kept_for_map_import(tenants, db):
    response = TestClient(app).post("/api/v1/agent/files", headers=tenants["b"],
                                    files={"file": ("sites.geojson", SITES_GEOJSON, "application/geo+json")})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["spatial"]["placed"] is True and body["spatial"]["placement"]["code"] == 4326
    sheet = body["sheets"][0]
    assert sheet["columns"][:7] == ["feature", "kind", "lon", "lat", "area_m2", "length_m", "geometry"]
    north = sheet["rows"][0]
    assert 31.2 < north[2] < 31.21 and 30.05 < north[3] < 30.06
    assert 900_000 < north[4] < 1_100_000  # about 960 m x 1110 m
    assert north[6]["type"] == "Polygon" and sheet["columns"][7:] == ["site", "rent"]
    kept = db.execute(text("SELECT filename FROM gis_upload WHERE id = CAST(:i AS uuid)"),
                      {"i": body["spatial"]["upload_id"]}).scalar_one()
    assert kept == "sites.geojson"


def test_a_drawing_in_metres_comes_in_local_metres_and_can_still_be_placed(tenants):
    """A drawing with no coordinate system is LOCAL METRES at once, never a question and never degrees
    (the camp-bed test: EPSG:4326 offered for a metre drawing made an 88 m camp "86 km")."""
    client = TestClient(app)
    response = client.post("/api/v1/agent/files", headers=tenants["b"],
                           files={"file": ("site.dxf", _utm_drawing(), "application/dxf")})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["spatial"]["placed"] is True and body["spatial"]["local_metres"] is True
    assert {s["name"] for s in body["sheets"]} == {"WELLS", "PLOTS"}
    wells = next(s for s in body["sheets"] if s["name"] == "WELLS")
    assert wells["columns"][:4] == ["feature", "kind", "x_m", "y_m"] and wells["rows"][0][2:4] == [100.0, 100.0]
    plots = next(s for s in body["sheets"] if s["name"] == "PLOTS")
    row = dict(zip(plots["columns"], plots["rows"][0]))
    assert (row["width_m"], row["height_m"]) == (500.0, 300.0) and abs(row["area_m2"] - 150_000) < 50

    placed = client.post("/api/v1/agent/files/place", headers=tenants["b"],
                         json={"upload_id": body["spatial"]["upload_id"], "placement": {"kind": "epsg", "code": 32636}})
    assert placed.status_code == 200, placed.text
    wells = next(s for s in placed.json()["sheets"] if s["name"] == "WELLS")
    lon, lat = wells["rows"][0][2], wells["rows"][0][3]
    assert 31.1 < lon < 31.3 and 30.0 < lat < 30.1  # Cairo


def test_the_assistant_asks_for_a_drawings_system_places_it_and_builds_records_with_shapes(tenants, db, assistant):
    """The platform's order (camp-bed evaluation): the drawing ends up in the domain's map data -- put there by the
    build itself, so the model never has to find an upload id (the camp-bed retest lost five turns to it)."""
    client = TestClient(app)
    drawing = client.post("/api/v1/agent/files", headers=tenants["b"],
                          files={"file": ("site.dxf", _utm_drawing(), "application/dxf")}).json()
    domain = client.post("/api/domain/", json={"name": "Wells map"}, headers=tenants["b"]).json()["id"]
    spec = {
        "domain_id": domain, "problem_name": "Pick wells",
        "seed": {
            "entity_types": [{"name": "well", "role": "location", "attributes": [
                {"name": "location", "data_type": "geometry"},
                {"name": "lon", "data_type": "number"}, {"name": "lat", "data_type": "number"}]}],
            "entities_from_file": [{"file": "site.dxf", "sheet": "WELLS", "type": "well", "key": "feature",
                                    "attrs": {"location": "geometry", "lon": "lon", "lat": "lat"}}]},
        "ir": {"version": 2, "sets": ["well"], "parameters": {},
               "variables": {"use": {"index": ["well"], "domain": "binary"}},
               "constraints": [{"id": "c_one", "left": {"sum": {"var": "use", "index": ["w"]},
                                                         "over": [{"index": "w", "set": "well"}]},
                                "relation": "=", "right": {"const": 1}, "severity": "hard"}]},
    }
    llm = assistant([
        "Your drawing is in local metres. Must it line up with other map data? If so, is it UTM zone 36N?",
        ("place_file", {"file": "site.dxf", "epsg": 32636}),
        "It lands in Cairo, near the Nile. Is that right?",
        ("propose_plan", {"summary": "**Sets** well (from layer WELLS)", "spec": spec}),
        "Built.",
    ])
    first = _chat(tenants["b"], mode="model", files=[drawing], text="Choose a well; the drawing is attached.")
    assert "LOCAL METRES" in llm.requests[0]["messages"][0]["content"]

    second = _chat(tenants["b"], messages=first[-1]["messages"], mode="model", files=[drawing], text="Yes, UTM 36N.")
    placed = next(e for e in second if e["type"] == "file")["file"]
    assert placed["spatial"]["placed"] is True
    assert "lands within lon/lat" in next(e for e in second if e["type"] == "result" and e["name"] == "place_file")["preview"]

    third = _chat(tenants["b"], messages=second[-1]["messages"], mode="model", files=[placed], text="Yes, that's the site.")
    assert next(e for e in third if e["type"] == "plan")["counts"]["entities"] == 2
    fourth = _chat(tenants["b"], messages=third[-1]["messages"], mode="model", files=[placed], confirm={"allow": True})
    built = next(e for e in fourth if e["type"] == "built")
    on_map = db.execute(text("SELECT count(*) FROM gis_dataset WHERE domain_id = :d"), {"d": built["domain_id"]}).scalar_one()
    assert on_map == 1  # the build put the drawing on the domain's map
    shape = db.execute(text(
        "SELECT e.attrs->'location' FROM entity e JOIN entity_type t ON t.id = e.entity_type_id"
        " WHERE t.domain_id = :d AND t.name = 'well' ORDER BY e.key LIMIT 1"), {"d": built["domain_id"]}).scalar_one()
    assert shape["type"] == "Point" and 31.1 < shape["coordinates"][0] < 31.3


def test_a_scenario_and_run_named_by_number_are_looked_up_for_the_model():
    """The live what-if test (October 2026): with another workspace selected, "scenario 53 (its latest run is
    144)" was called missing twice. The platform now looks named ones up and says where they are."""
    rows = {"/api/v1/runs/144": {"status": "optimal", "scenario_id": 53},
            "/api/v1/scenarios/53": {"name": "Base", "problem_id": 7},
            "/api/v1/problems/7": {"name": "Transport", "domain_id": 12}}

    def call(method, path, query=None, body=None, form=None, headers=None):
        return {"ok": path in rows, "status": 200 if path in rows else 404, "body": rows.get(path, {"detail": "no"})}

    agent = core.Agent.__new__(core.Agent)
    agent.call = call
    agent.ctx = type("Ctx", (), {"domain_id": 55})()
    note = agent._named_records("For scenario 53 (its latest run is 144): what if demand rose? And run 999?")
    assert note.startswith(core.PLATFORM)
    assert 'scenario 53 "Base" belongs to problem 7 "Transport" in workspace (domain) 12 -- not the selected' in note
    assert "run 144 (optimal) is a run of scenario 53" in note and "run 999: not found" in note
    assert agent._named_records("Nothing named here.") is None
