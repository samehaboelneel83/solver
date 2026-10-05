"""What the first field test of the Assistant (October 2026) taught, against the real platform.

The test: a person describes a warehouse problem (5 candidate warehouses, 12 customers, 60 lanes, at most 3
open, no lane over 450 road km, each customer served by one warehouse) and attaches three CSV files. Qwen 3.5
interviewed well, but:
- it added up and counted in its head, and got it wrong (capacity 2,450 instead of 2,850; 11 lanes over the
  limit instead of 13): attached files now carry exact totals, and query_file counts, filters and adds up;
- it could not see how to write "only lanes up to 450 km" and thought aloud in circles until the length limit,
  twice, 28,000 characters shown to the person as the answer: such a reply is never shown, the step is asked
  again without thinking, and the prompt has the pattern (lane_km[w,c] * assign[w,c] <= 450);
- it sent the spec with "entity_types" twice, three times, and then an empty answer: a list split over two
  same-named keys is joined (and the model told), an empty answer is sent back;
- a spec written into the reply is run through check_spec instead of being lost.
The same problem, written with the pattern, builds and solves to the reference answer worked out separately
(Cairo-6Oct, Tanta and Assiut open; 1,338,765 EGP a month).
"""

from __future__ import annotations

import copy
import json
import math

import pytest

from fastapi.testclient import TestClient

from app.agent import core
from app.agent import files as agent_files
from app.api import agent as agent_api
from app.main import app
from tests.test_agent import _chat, _in_process_caller
from tests.test_quadratic import empty_queue  # noqa: F401
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401

WAREHOUSES = [("Cairo-6Oct", 29.94, 30.91, 900, 420000), ("Alexandria", 31.20, 29.92, 600, 310000),
              ("Tanta", 30.79, 31.00, 500, 240000), ("Ismailia", 30.60, 32.27, 450, 230000),
              ("Assiut", 27.18, 31.18, 400, 200000)]
CUSTOMERS = [("Cairo", 30.04, 31.24, 320), ("Giza", 30.01, 31.21, 180), ("Alexandria", 31.20, 29.92, 260),
             ("Mansoura", 31.04, 31.38, 140), ("Tanta", 30.79, 31.00, 110), ("Zagazig", 30.59, 31.50, 120),
             ("Port Said", 31.26, 32.30, 90), ("Suez", 29.97, 32.53, 85), ("Ismailia", 30.60, 32.27, 70),
             ("Minya", 28.10, 30.75, 95), ("Assiut", 27.18, 31.18, 105), ("Sohag", 26.56, 31.69, 80)]


def _km(a, b) -> int:
    la1, lo1, la2, lo2 = map(math.radians, (a[1], a[2], b[1], b[2]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return round(2 * 6371 * math.asin(math.sqrt(h)) * 1.25)


def _csv(header, rows) -> str:
    return "\n".join([",".join(header)] + [",".join(str(v) for v in r) for r in rows]) + "\n"


WAREHOUSES_CSV = _csv(["warehouse", "latitude", "longitude", "capacity_tons_per_month", "fixed_cost_egp_per_month"],
                      WAREHOUSES)
CUSTOMERS_CSV = _csv(["customer", "latitude", "longitude", "demand_tons_per_month"], CUSTOMERS)
LANES_CSV = _csv(["warehouse", "customer", "road_km", "cost_egp_per_ton"],
                 [(w[0], c[0], _km(w, c), round(60 + 2.4 * _km(w, c))) for w in WAREHOUSES for c in CUSTOMERS])


def _files(client, headers) -> list[dict]:
    return [client.post("/api/v1/agent/files", files={"file": (n, body, "text/csv")}, headers=headers).json()
            for n, body in (("warehouses.csv", WAREHOUSES_CSV), ("customers.csv", CUSTOMERS_CSV),
                            ("lanes.csv", LANES_CSV))]


def _parsed() -> list[dict]:
    return [agent_files.parse(n, body.encode()) for n, body in
            (("warehouses.csv", WAREHOUSES_CSV), ("customers.csv", CUSTOMERS_CSV), ("lanes.csv", LANES_CSV))]


def _warehouse_spec(name: str) -> dict:
    w, c = {"index": "w", "set": "warehouse"}, {"index": "c", "set": "customer"}
    demand = {"attr": {"of": "c", "name": "demand"}}
    assign = {"var": "assign", "index": ["w", "c"]}
    lanes = [{"file": "lanes.csv", "sheet": "lanes", "parameter": p,
              "entities": [["warehouse", "warehouse"], ["customer", "customer"]], "value": col}
             for p, col in (("lane_cost", "cost_egp_per_ton"), ("lane_km", "road_km"))]
    return {
        "domain_name": f"Egypt distribution {name}", "problem_name": "Warehouses to open",
        "note": "which warehouses to open and which serves each customer, cheapest per month",
        "seed": {
            "entity_types": [
                {"name": "warehouse", "role": "resource", "attributes": [
                    {"name": "capacity", "data_type": "number", "required": True, "unit": "t/month"},
                    {"name": "fixed_cost", "data_type": "number", "required": True, "unit": "EGP/month"}]},
                {"name": "customer", "role": "location", "attributes": [
                    {"name": "demand", "data_type": "number", "required": True, "unit": "t/month"}]}],
            "parameters": [{"name": "lane_cost", "index": ["warehouse", "customer"], "default_value": 0,
                            "unit": "EGP/t"},
                           {"name": "lane_km", "index": ["warehouse", "customer"], "default_value": 999999,
                            "unit": "km"},
                           {"name": "max_open", "index": [], "default_value": 3}],
            "entities_from_file": [
                {"file": "warehouses.csv", "type": "warehouse", "key": "warehouse",
                 "attrs": {"capacity": "capacity_tons_per_month", "fixed_cost": "fixed_cost_egp_per_month"}},
                {"file": "customers.csv", "type": "customer", "key": "customer",
                 "attrs": {"demand": "demand_tons_per_month"}}],
            "parameter_values_from_file": lanes,
        },
        "ir": {
            "version": 2, "sets": ["warehouse", "customer"],
            "parameters": {"lane_cost": {"index": ["warehouse", "customer"]},
                           "lane_km": {"index": ["warehouse", "customer"]}, "max_open": {"index": []}},
            "variables": {"open": {"index": ["warehouse"], "domain": "binary"},
                          "assign": {"index": ["warehouse", "customer"], "domain": "binary"}},
            "constraints": [
                {"id": "c_one_warehouse", "note": "each customer is served by exactly one warehouse", "forall": [c],
                 "left": {"sum": assign, "over": [w]}, "relation": "=", "right": {"const": 1}, "severity": "hard"},
                {"id": "c_capacity", "note": "an open warehouse ships at most its capacity; a closed one nothing",
                 "forall": [w], "left": {"sum": {"mul": [demand, assign]}, "over": [c]}, "relation": "<=",
                 "right": {"mul": [{"attr": {"of": "w", "name": "capacity"}}, {"var": "open", "index": ["w"]}]},
                 "severity": "hard"},
                {"id": "c_max_open", "note": "at most 3 warehouses",
                 "left": {"sum": {"var": "open", "index": ["w"]}, "over": [w]}, "relation": "<=",
                 "right": {"par": "max_open", "index": []}, "severity": "hard"},
                {"id": "c_lane_km", "note": "no lane over 450 road km (the pattern for a value per pair)",
                 "forall": [w, c], "left": {"mul": [{"par": "lane_km", "index": ["w", "c"]}, assign]},
                 "relation": "<=", "right": {"const": 450}, "severity": "hard"}],
            "objective": {"sense": "minimize", "terms": [
                {"id": "o_fixed", "weight": 1, "expression": {"sum": {"mul": [
                    {"attr": {"of": "w", "name": "fixed_cost"}}, {"var": "open", "index": ["w"]}]}, "over": [w]}},
                {"id": "o_transport", "weight": 1, "expression": {"sum": {"mul": [
                    {"mul": [{"par": "lane_cost", "index": ["w", "c"]}, demand]}, assign]}, "over": [w, c]}}]},
        },
    }


# -- exact numbers ---------------------------------------------------------------------------------


def test_attached_files_carry_exact_totals():
    text = agent_files.outline(_parsed())
    assert "capacity_tons_per_month: sum 2850 min 400 max 900" in text
    assert "demand_tons_per_month: sum 1655" in text
    assert "latitude: min" in text and "latitude: sum" not in text  # positions are not added up


def test_query_file_counts_filters_and_groups_exactly():
    files = _parsed()
    over = agent_files.query(files, "lanes.csv", None, [{"column": "road_km", "op": ">", "value": 450}],
                             aggregate={"*": "count"})
    assert over.startswith("13 of 60 rows match") and over.strip().endswith("13")
    reach = agent_files.query(files, "lanes.csv", None, [{"column": "road_km", "op": "<=", "value": 450}],
                              group_by=["customer"], aggregate={"warehouse": "count"})
    assert "Sohag,1" in reach and "Cairo,5" in reach
    rows = agent_files.query(files, "lanes.csv", None, [{"column": "customer", "op": "=", "value": "sohag"},
                                                        {"column": "road_km", "op": "<=", "value": 450}],
                             columns=["warehouse", "road_km"])
    assert rows.splitlines()[1:] == ["warehouse,road_km", "Assiut,107"]
    total = agent_files.query(files, "warehouses.csv", None, aggregate={"capacity_tons_per_month": "sum"})
    assert total.strip().endswith("2850")


def test_query_file_is_a_tool_in_both_modes():
    assert "query_file" in {t["function"]["name"] for t in core.TOOLS}
    assert "query_file" in {t["function"]["name"] for t in core.MODEL_TOOLS}


# -- the problem itself, written with the pattern -----------------------------------------------------


def test_the_field_test_problem_builds_and_solves_to_the_reference(tenants, db):
    from app.worker import work_once

    client = TestClient(app)
    spec = _warehouse_spec("reference")
    spec["seed"] = agent_files.expand(spec["seed"], _files(client, tenants["b"]))
    built = client.post("/api/v1/problems/from-spec", json=spec, headers=tenants["b"])
    assert built.status_code in (200, 201), built.text
    run = client.post(f"/api/v1/scenarios/{built.json()['scenario_id']}/runs", json={}, headers=tenants["b"])
    assert run.status_code == 201, run.text
    for _ in range(5):
        if work_once(db) is None:
            break
    answer = client.get(f"/api/v1/runs/{run.json()['id']}", headers=tenants["b"]).json()
    assert answer["status"] == "optimal", answer
    assert round(float(answer["objective"])) == 1_338_765
    opened = {k[0] if isinstance(k, list) else k for k in answer["assignments"]["open"]}
    assert opened == {"Cairo-6Oct", "Tanta", "Assiut"}
    served = {c: w for w, c in answer["assignments"]["assign"]}
    assert served["Sohag"] == "Assiut" and served["Alexandria"] == "Tanta"


# -- the loop ------------------------------------------------------------------------------------------


class Model:
    """Plays the model and records the thinking setting of each request."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.requests: list[dict] = []

    def __call__(self, settings, messages, native, tools=None, max_tokens=None):
        self.requests.append({"messages": copy.deepcopy(messages), "thinking": settings.thinking})
        kind, *rest = self.replies.pop(0)
        if kind == "text":
            return {"role": "assistant", "content": rest[0], "_finish": rest[1] if len(rest) > 1 else "stop"}, True
        name, arguments = rest
        return {"role": "assistant", "content": None, "_finish": "tool_calls", "tool_calls": [
            {"id": f"n{len(self.requests)}", "type": "function", "function": {"name": name, "arguments": arguments}}]}, True


def _install(monkeypatch, replies) -> Model:
    monkeypatch.setattr(agent_api, "make_caller", _in_process_caller)
    model = Model(replies)
    monkeypatch.setattr(core, "llm_chat", model)
    return model


def _platform(model) -> list[str]:
    return [m["content"] for m in model.requests[-1]["messages"]
            if m["role"] == "user" and str(m["content"]).startswith(core.PLATFORM)]


RAMBLE = "The user has confirmed. Actually, let me think again about the lanes... " * 200


def test_a_reply_that_rambles_to_the_limit_is_never_shown_and_asked_again_without_thinking(tenants, monkeypatch):
    model = _install(monkeypatch, [("text", RAMBLE, "length"), ("text", RAMBLE, "length"),
                                   ("text", "Which warehouses must stay open?")])
    events = _chat(tenants["b"], text="choose my warehouses")
    answers = [e["text"] for e in events if e["type"] == "answer"]
    assert answers == ["Which warehouses must stay open?"]
    assert [r["thinking"] for r in model.requests][1] == "off"  # the same step again, thinking off
    assert any("ran to the length limit" in m for m in _platform(model))
    history = json.dumps(events[-1]["messages"])
    assert "Actually, let me think again" not in history  # the ramble does not eat the context either


def test_after_rambling_every_time_the_person_gets_one_honest_line(tenants, monkeypatch):
    _install(monkeypatch, [("text", RAMBLE, "length")] * (2 + core.MAX_NUDGES))
    events = _chat(tenants["b"], text="choose my warehouses")
    answer = next(e for e in events if e["type"] == "answer")["text"]
    assert answer.startswith("I could not finish this step") and len(answer) < 300


def test_a_spec_written_into_the_reply_is_run_through_check_spec(tenants, monkeypatch):
    spec = _warehouse_spec("as text")
    model = _install(monkeypatch, [
        ("text", "Here is the spec:\n```json\n" + json.dumps(spec) + "\n```"),
        ("text", "The spec checks out; shall I propose it?"),
    ])
    events = _chat(tenants["b"], mode="model", text="propose it", files=_parsed())
    assert any(e["type"] == "tool" and e["name"] == "check_spec" for e in events)
    assert any("run through check_spec for you" in m for m in _platform(model))


def test_an_empty_answer_is_sent_back(tenants, monkeypatch):
    model = _install(monkeypatch, [("text", ""), ("text", "You have no runs yet.")])
    events = _chat(tenants["b"], text="runs?")
    assert next(e for e in events if e["type"] == "answer")["text"] == "You have no runs yet."
    assert any("reply was empty" in m for m in _platform(model))


def test_a_list_given_twice_in_a_native_call_is_joined_and_the_model_told(tenants, monkeypatch):
    args = ('{"file": "lanes.csv", "where": [{"column": "road_km", "op": ">", "value": 450}], '
            '"where": [{"column": "customer", "op": "=", "value": "Sohag"}], "aggregate": {"*": "count"}}')
    model = _install(monkeypatch, [("native", "query_file", args), ("text", "Four lanes to Sohag are too long.")])
    events = _chat(tenants["b"], text="how many long lanes reach Sohag?", files=_parsed())
    result = next(e for e in events if e["type"] == "result" and e["name"] == "query_file")
    assert result["ok"] and result["preview"].startswith("4 of 60 rows match")
    assert any('"where" was given twice' in m for m in _platform(model))


# -- the second run of the field test --------------------------------------------------------------------


def test_a_parameter_the_model_reads_but_nothing_loads_is_refused(tenants, monkeypatch):
    """The second run's plan passed every check with a goal on delivery_cost_egp[warehouse, customer] that
    nothing loaded: every lane would have cost the default, and transport would not have mattered."""
    spec = _warehouse_spec("unloaded")
    spec["seed"]["parameters"].append({"name": "delivery_cost", "index": ["warehouse", "customer"],
                                       "default_value": 999999999})
    spec["ir"]["parameters"]["delivery_cost"] = {"index": ["warehouse", "customer"]}
    model = _install(monkeypatch, [("native", "check_spec", json.dumps({"spec": spec})), ("text", "I will load it.")])
    events = _chat(tenants["b"], mode="model", text="check it; at most 3 warehouses", files=_parsed())
    result = next(e for e in events if e["type"] == "result" and e["name"] == "check_spec")
    assert not result["ok"] and 'Parameter "delivery_cost"[warehouse, customer]' in result["preview"]
    assert "999999999" in json.dumps(model.requests[-1]["messages"])
    assert core._empty_parameters(agent_files.expand(_warehouse_spec("loaded")["seed"], _parsed()) and
                                  {**_warehouse_spec("loaded"),
                                   "seed": agent_files.expand(_warehouse_spec("loaded")["seed"], _parsed())}) == []


def test_an_objective_past_a_billion_is_saved(tenants, db):
    """Migration 0107. The run was solved, optimal, and then crashed while saving an objective of
    12,000,849,988 into numeric(15, 6), which holds less than a billion; the run said only "current
    transaction is aborted"."""
    from app.worker import work_once

    client = TestClient(app)
    spec = _warehouse_spec("billions")
    spec["seed"]["entities_from_file"][0]["attrs"]["fixed_cost"] = "fixed_cost_egp_per_month"
    spec["seed"]["parameters"].append({"name": "scale", "index": [], "default_value": 10000})
    spec["ir"]["parameters"]["scale"] = {"index": []}
    fixed = spec["ir"]["objective"]["terms"][0]["expression"]["sum"]
    fixed["mul"][0] = {"mul": [{"par": "scale", "index": []}, fixed["mul"][0]]}
    spec["seed"] = agent_files.expand(spec["seed"], _files(client, tenants["b"]))
    built = client.post("/api/v1/problems/from-spec", json=spec, headers=tenants["b"])
    assert built.status_code in (200, 201), built.text
    run = client.post(f"/api/v1/scenarios/{built.json()['scenario_id']}/runs", json={}, headers=tenants["b"])
    for _ in range(5):
        if work_once(db) is None:
            break
    answer = client.get(f"/api/v1/runs/{run.json()['id']}", headers=tenants["b"]).json()
    assert answer["status"] == "optimal", answer
    assert float(answer["objective"]) > 10 ** 9


def test_a_scenario_is_not_queued_again_and_again(tenants, monkeypatch):
    model = _install(monkeypatch, [("native", "call_api", json.dumps({"method": "POST", "path": "/api/v1/scenarios/999999/runs"}))]
                     * (core.MAX_SOLVES + 1) + [("text", "The run could not be queued.")])
    agent = core.Agent(core.Settings(), agent_api._index, lambda *a, **k: {"ok": False, "body": "nope"},
                       core.Context("x"))
    for _ in range(core.MAX_SOLVES):
        assert not agent.run_tool("call_api", {"method": "POST", "path": "/api/v1/scenarios/7/runs"}).startswith("Refused")
    assert agent.run_tool("call_api", {"method": "POST", "path": "/api/v1/scenarios/7/runs"}).startswith(
        f"Refused: this scenario was already queued {core.MAX_SOLVES} times")
    failed = core.Agent(core.Settings(), agent_api._index,
                        lambda *a, **k: {"ok": True, "body": {"id": 3, "status": "error", "error": "boom"}},
                        core.Context("x"))
    assert "This run FAILED" in failed.run_tool("call_api", {"method": "GET", "path": "/api/v1/runs/3"})
    del model


def test_read_result_reports_the_answer_already_joined(tenants, db, monkeypatch):
    """The field test's report listed demand for 2 of 12 customers: the platform now joins it."""
    from app.worker import work_once

    client = TestClient(app)
    spec = _warehouse_spec("report")
    spec["seed"] = agent_files.expand(spec["seed"], _files(client, tenants["b"]))
    built = client.post("/api/v1/problems/from-spec", json=spec, headers=tenants["b"]).json()
    run = client.post(f"/api/v1/scenarios/{built['scenario_id']}/runs", json={}, headers=tenants["b"]).json()
    for _ in range(5):
        if work_once(db) is None:
            break
    text = client.get(f"/api/v1/agent/result/{run['id']}", headers=tenants["b"]).json()["text"]
    assert "optimal; goal (minimize) = 1,338,765" in text
    assert "o_fixed = 860,000" in text and "o_transport = 478,765" in text
    assert "DECISION assign[warehouse, customer]: 12 of 60 cells chosen" in text
    assert "Sohag" in text and "Assiut | 400 | 200,000 | Sohag | 80" in text
    assert "Cairo-6Oct: 6 cells; totals customer.demand 885 (its capacity 900, fixed_cost 420,000)" in text
    assert "c_capacity (hard): held" in text and "c_max_open (hard): held, tight" in text
    assert "c_one_warehouse (hard): held\n" in text  # an equality is always tight: not worth saying
    # As a tool, in both modes.
    assert "read_result" in {t["function"]["name"] for t in core.MODEL_TOOLS}
    _install(monkeypatch, [("native", "read_result", json.dumps({"run_id": run["id"]})), ("text", "Done.")])
    events = _chat(tenants["b"], text="what did run say?")
    assert next(e for e in events if e["type"] == "result" and e["name"] == "read_result")["ok"]


# -- the second field test: a week's nurse roster --------------------------------------------------------

NURSES_CSV = _csv(["nurse", "grade", "wage_per_shift_egp", "max_shifts_per_week"],
                  [("Amal", "senior", 900, 6), ("Basma", "senior", 900, 6), ("Dina", "senior", 900, 5),
                   ("Eman", "senior", 900, 6), ("Fatma", "junior", 600, 6), ("Hala", "junior", 600, 6),
                   ("Mona", "junior", 600, 6), ("Nour", "junior", 600, 6), ("Rana", "junior", 600, 5)])
DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
COVER_CSV = _csv(["day", "shift", "nurses_needed", "seniors_needed"],
                 [(d, s, 2 if d in ("Fri", "Sat") and s == "morning" else n, 1)
                  for d in DAYS for s, n in (("morning", 3), ("evening", 2), ("night", 2))])
REQUESTS_CSV = _csv(["nurse", "day", "reason"],
                    [("Amal", "Fri", "family"), ("Basma", "Fri", "family"), ("Dina", "Sat", "exam"),
                     ("Eman", "Fri", "travel"), ("Fatma", "Thu", "medical"), ("Mona", "Sun", "family"),
                     ("Nour", "Sat", "family"), ("Hala", "Fri", "course")])


def _roster_files() -> list[dict]:
    return [agent_files.parse(n, body.encode()) for n, body in
            (("nurses.csv", NURSES_CSV), ("cover.csv", COVER_CSV), ("requests_off.csv", REQUESTS_CSV))]


def _roster_spec(name: str) -> dict:
    """The roster written with the prompt's patterns: next_day for consecutive days, where id = "night",
    pay_factor[shift], a 0/1 parameter from a list ("value": 1), two goals in order (lex)."""
    n, d, s = {"index": "n", "set": "nurse"}, {"index": "d", "set": "day"}, {"index": "s", "set": "shift"}
    x = {"var": "work", "index": ["n", "d", "s"]}
    senior = {"index": "n", "set": "nurse", "where": [{"attr": "grade", "op": "=", "value": "senior"}]}
    cover = {"file": "cover.csv", "entities": [["day", "day"], ["shift", "shift"]]}
    return {
        "domain_name": f"Clinic {name}", "problem_name": "Week roster",
        "seed": {
            "entity_types": [
                {"name": "nurse", "role": "agent", "attributes": [
                    {"name": "grade", "data_type": "enum", "enum_values": ["senior", "junior"], "required": True},
                    {"name": "wage", "data_type": "number", "required": True, "unit": "EGP/shift"},
                    {"name": "max_shifts", "data_type": "integer", "required": True}]},
                {"name": "day", "role": "time", "attributes": []},
                {"name": "shift", "role": "time", "attributes": []}],
            "relationship_types": [{"name": "next_day", "from": "day", "to": "day", "cardinality": "one_to_one"}],
            "entities": [{"type": "day", "key": k} for k in DAYS]
            + [{"type": "shift", "key": k} for k in ("morning", "evening", "night")],
            "relationships": [{"type": "next_day", "from": ["day", a], "to": ["day", b]} for a, b in zip(DAYS, DAYS[1:])],
            "parameters": [
                {"name": "needed", "index": ["day", "shift"], "default_value": 0},
                {"name": "seniors_needed", "index": ["day", "shift"], "default_value": 0},
                {"name": "asked_off", "index": ["nurse", "day"], "default_value": 0},
                {"name": "pay_factor", "index": ["shift"], "default_value": 1}],
            "parameter_values": [{"parameter": "pay_factor", "entities": [["shift", "night"]], "value": 1.3}],
            "entities_from_file": [{"file": "nurses.csv", "type": "nurse", "key": "nurse",
                                    "attrs": {"grade": "grade", "wage": "wage_per_shift_egp",
                                              "max_shifts": "max_shifts_per_week"}}],
            "parameter_values_from_file": [
                {**cover, "parameter": "needed", "value": "nurses_needed"},
                {**cover, "parameter": "seniors_needed", "value": "seniors_needed"},
                {"file": "requests_off.csv", "parameter": "asked_off",
                 "entities": [["nurse", "nurse"], ["day", "day"]], "value": 1}],
        },
        "ir": {
            "version": 2, "sets": ["nurse", "day", "shift"], "relationships": ["next_day"],
            "parameters": {"needed": {"index": ["day", "shift"]}, "seniors_needed": {"index": ["day", "shift"]},
                           "asked_off": {"index": ["nurse", "day"]}, "pay_factor": {"index": ["shift"]}},
            "variables": {"work": {"index": ["nurse", "day", "shift"], "domain": "binary"}},
            "constraints": [
                {"id": "c_cover", "forall": [d, s], "left": {"sum": x, "over": [n]}, "relation": ">=",
                 "right": {"par": "needed", "index": ["d", "s"]}, "severity": "hard"},
                {"id": "c_seniors", "forall": [d, s], "left": {"sum": x, "over": [senior]}, "relation": ">=",
                 "right": {"par": "seniors_needed", "index": ["d", "s"]}, "severity": "hard"},
                {"id": "c_one_a_day", "forall": [n, d], "left": {"sum": x, "over": [s]}, "relation": "<=",
                 "right": {"const": 1}, "severity": "hard"},
                {"id": "c_max_shifts", "forall": [n], "left": {"sum": x, "over": [d, s]}, "relation": "<=",
                 "right": {"attr": {"of": "n", "name": "max_shifts"}}, "severity": "hard"},
                {"id": "c_rest", "note": "no morning right after a night",
                 "forall": [n, d, {"index": "d2", "set": "day", "via": {"rel": "next_day", "from": "d"}},
                            {"index": "s1", "set": "shift", "where": [{"attr": "id", "op": "=", "value": "night"}]},
                            {"index": "s2", "set": "shift", "where": [{"attr": "id", "op": "=", "value": "morning"}]}],
                 "left": {"add": [{"var": "work", "index": ["n", "d", "s1"]}, {"var": "work", "index": ["n", "d2", "s2"]}]},
                 "relation": "<=", "right": {"const": 1}, "severity": "hard"}],
            "objective": {"sense": "minimize", "mode": "lex", "terms": [
                {"id": "o_requests_broken", "weight": 1, "expression": {"sum": {"mul": [
                    {"par": "asked_off", "index": ["n", "d"]}, x]}, "over": [n, d, s]}},
                {"id": "o_wage_cost", "weight": 1, "expression": {"sum": {"mul": [{"mul": [
                    {"attr": {"of": "n", "name": "wage"}}, {"par": "pay_factor", "index": ["s"]}]}, x]},
                    "over": [n, d, s]}}]},
        },
    }


def test_a_list_of_pairs_loads_as_a_0_1_parameter():
    seed = agent_files.expand({"parameter_values_from_file": [
        {"file": "requests_off.csv", "parameter": "asked_off", "entities": [["nurse", "nurse"], ["day", "day"]],
         "value": 1}]}, _roster_files())
    assert len(seed["parameter_values"]) == 8
    assert seed["parameter_values"][0] == {"parameter": "asked_off", "entities": [["nurse", "Amal"], ["day", "Fri"]],
                                           "value": 1}


def test_the_roster_built_with_the_patterns_solves_to_the_reference(tenants, db):
    """Reference (HiGHS, lex): 2 requests broken (Friday has 3 senior requests and needs a senior on each
    shift), then 37,650 EGP."""
    from app.worker import work_once

    client = TestClient(app)
    files = [client.post("/api/v1/agent/files", files={"file": (n, body, "text/csv")}, headers=tenants["b"]).json()
             for n, body in (("nurses.csv", NURSES_CSV), ("cover.csv", COVER_CSV), ("requests_off.csv", REQUESTS_CSV))]
    spec = _roster_spec("reference")
    spec["seed"] = agent_files.expand(spec["seed"], files)
    built = client.post("/api/v1/problems/from-spec", json=spec, headers=tenants["b"])
    assert built.status_code in (200, 201), built.text
    run = client.post(f"/api/v1/scenarios/{built.json()['scenario_id']}/runs", json={}, headers=tenants["b"]).json()
    for _ in range(5):
        if work_once(db) is None:
            break
    text = client.get(f"/api/v1/agent/result/{run['id']}", headers=tenants["b"]).json()["text"]
    assert ": optimal;" in text or ": feasible;" in text, text
    assert "o_requests_broken = 2" in text and "o_wage_cost = 37,650" in text, text


def test_a_long_spec_closed_in_the_wrong_order_is_put_right_for_check_spec_only(tenants, monkeypatch):
    """The roster test: Qwen closed a 10,000-character spec "}]}}]}}}}}}", three times in a row."""
    from app.agent import toolcall

    good = json.dumps({"spec": _roster_spec("closers")})
    bad = good.rstrip("}]") + "}" * (len(good) - len(good.rstrip("}]")))  # the right count, all braces
    with pytest.raises(json.JSONDecodeError):
        json.loads(bad)
    assert json.loads(toolcall.fix_closers(bad)) == json.loads(good)
    assert toolcall.fix_closers(good) is None
    model = _install(monkeypatch, [("native", "check_spec", bad), ("text", "Checked.")])
    events = _chat(tenants["b"], mode="model", text="check", files=_roster_files())
    assert any(e["type"] == "tool" and e["name"] == "check_spec" for e in events)
    assert any("closing brackets" in m for m in _platform(model))
    # Never for a call that writes: the same text for call_api is refused as before.
    _install(monkeypatch, [("native", "call_api", '{"method": "POST", "path": "/api/x", "body": {"a": [1}}'),
                           ("text", "ok")])
    events = _chat(tenants["b"], text="go")
    assert not any(e["type"] == "tool" and e["name"] == "call_api" for e in events)


def test_each_kind_of_correction_has_its_own_budget(tenants, monkeypatch):
    """The roster test: three broken calls spent a shared budget of three, so an empty reply ended the turn."""
    broken = ("native", "check_spec", '{"spec": {"ir": {"version": 2,, }}}')
    model = _install(monkeypatch, [broken] * 3 + [("text", ""), ("text", "Here is where we are.")])
    events = _chat(tenants["b"], mode="model", text="go on", files=_roster_files())
    assert next(e for e in events if e["type"] == "answer")["text"] == "Here is where we are."
    assert any("reply was empty" in m for m in _platform(model))


def test_a_call_left_in_the_thinking_is_run(tenants, monkeypatch):
    """vLLM's reasoning parser keeps Qwen's thinking apart; a call written there left the reply empty."""
    monkeypatch.setattr(agent_api, "make_caller", _in_process_caller)
    replies = [
        {"role": "assistant", "content": "", "_finish": "stop", "reasoning_content":
         'I should count them.\n<tool_call>\n{"name": "query_file", "arguments": {"file": "requests_off.csv", '
         '"aggregate": {"*": "count"}}}\n</tool_call>'},
        {"role": "assistant", "content": "There are 8 requests.", "_finish": "stop"},
    ]
    monkeypatch.setattr(core, "llm_chat", lambda *a, **k: (replies.pop(0), True))
    events = _chat(tenants["b"], mode="model", text="how many requests?", files=_roster_files())
    result = next(e for e in events if e["type"] == "result" and e["name"] == "query_file")
    assert result["ok"] and result["preview"].strip().endswith("8")
    assert events[-2]["text"] == "There are 8 requests."


def test_a_record_named_by_its_key_in_an_index_is_bound_to_it(tenants, db):
    """The roster test wrote work[n, d, "night"] again and again; it means one record, so it is bound."""
    from app.worker import work_once

    spec = _roster_spec("literal")
    rest = next(c for c in spec["ir"]["constraints"] if c["id"] == "c_rest")
    rest["forall"] = rest["forall"][:3]  # no s1 / s2 bindings: the keys themselves
    rest["left"] = {"add": [{"var": "work", "index": ["n", "d", "night"]}, {"var": "work", "index": ["n", "d2", "morning"]}]}
    ir = json.loads(json.dumps(spec["ir"]))
    done = core.bind_literal_keys(ir)
    assert len(done) == 2 and '"night"' in done[0]
    rest = next(c for c in ir["constraints"] if c["id"] == "c_rest")
    assert rest["forall"][-2:] == [{"index": "k_night", "set": "shift", "where": [{"attr": "id", "op": "=", "value": "night"}]},
                                   {"index": "k_morning", "set": "shift", "where": [{"attr": "id", "op": "=", "value": "morning"}]}]
    # A goal term naming one record is summed over that one record.
    goal = {"version": 2, "sets": ["shift"], "variables": {"x": {"index": ["shift"], "domain": "binary"}},
            "objective": {"sense": "minimize", "terms": [{"id": "o", "weight": 1, "expression": {"var": "x", "index": ["night"]}}]}}
    core.bind_literal_keys(goal)
    assert goal["objective"]["terms"][0]["expression"]["over"][0]["index"] == "k_night"
    # And the whole roster, written that way, builds and solves to the reference.
    client = TestClient(app)
    files = [client.post("/api/v1/agent/files", files={"file": (n, body, "text/csv")}, headers=tenants["b"]).json()
             for n, body in (("nurses.csv", NURSES_CSV), ("cover.csv", COVER_CSV), ("requests_off.csv", REQUESTS_CSV))]
    spec["ir"] = ir
    spec["seed"] = agent_files.expand(spec["seed"], files)
    built = client.post("/api/v1/problems/from-spec", json=spec, headers=tenants["b"])
    assert built.status_code in (200, 201), built.text
    run = client.post(f"/api/v1/scenarios/{built.json()['scenario_id']}/runs", json={}, headers=tenants["b"]).json()
    for _ in range(5):
        if work_once(db) is None:
            break
    text = client.get(f"/api/v1/agent/result/{run['id']}", headers=tenants["b"]).json()["text"]
    assert "o_requests_broken = 2" in text and "o_wage_cost = 37,650" in text, text


def test_data_no_rule_or_goal_reads_is_refused():
    """The roster plan loaded the days off asked for, and its goal never read them."""
    spec = _roster_spec("unused")
    spec["seed"] = agent_files.expand(spec["seed"], _roster_files())
    assert core._empty_parameters(spec) == []
    goal = spec["ir"]["objective"]["terms"][0]
    goal["expression"] = {"sum": {"var": "work", "index": ["n", "d", "s"]},
                          "over": [{"index": "n", "set": "nurse"}, {"index": "d", "set": "day"}, {"index": "s", "set": "shift"}]}
    faults = core._empty_parameters(spec)
    assert len(faults) == 1 and faults[0].startswith('Parameter "asked_off" holds data (8 cells) but no rule or goal reads it')


def test_old_specs_are_shortened_and_a_too_long_prompt_is_asked_again(tenants, monkeypatch):
    """The roster test overflowed 32k with four 10,000-character specs in the history, and the turn ended."""
    big = json.dumps({"spec": _roster_spec("big")})
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "go"}]
    for i in range(4):
        msgs += [{"role": "assistant", "content": None, "tool_calls": [
                     {"id": f"c{i}", "type": "function", "function": {"name": "check_spec", "arguments": big}}]},
                 {"role": "tool", "tool_call_id": f"c{i}", "name": "check_spec", "content": "Not valid yet"}]
    fitted = core.fit(msgs, core.Settings(), 8192)
    kept = [c["function"]["arguments"] for m in fitted for c in m.get("tool_calls") or []]
    assert kept[-1] == big and all("superseded" in k for k in kept[:-1])

    monkeypatch.setattr(agent_api, "make_caller", _in_process_caller)
    seen = []

    def llm(settings, messages, native, tools=None, max_tokens=None):
        seen.append(max_tokens)
        if len(seen) == 1:
            raise core.LlmError(400, '{"error":{"message":"This model\'s maximum context length is 32768 tokens. '
                                     'However, you requested 4096 output tokens and your prompt contains at least '
                                     '29000 input tokens, for a total of at least 33096 tokens."}}')
        return {"role": "assistant", "content": "Fine.", "_finish": "stop"}, True

    monkeypatch.setattr(core, "llm_chat", llm)
    events = _chat(tenants["b"], text="hello")
    assert events[-2]["text"] == "Fine." and seen[1] < seen[0]


def test_a_rule_missing_its_right_key_is_put_right_and_a_taken_domain_name_says_so(tenants, monkeypatch):
    """The roster test, run 3: "relation": "<=", {"mul": ...} twice; then Postgres' own words for a taken name."""
    from app.agent import toolcall

    good = json.dumps({"spec": _roster_spec("right")})
    bad = good.replace('"relation": "<=", "right": ', '"relation": "<=", ', 1)
    assert json.loads(toolcall.fix_spec(bad)) == json.loads(good)
    client = TestClient(app)
    spec = _warehouse_spec("taken")
    spec["seed"] = agent_files.expand(spec["seed"], _files(client, tenants["b"]))
    assert client.post("/api/v1/problems/from-spec", json=spec, headers=tenants["b"]).status_code in (200, 201)
    again = client.post("/api/v1/problems/from-spec", json={**spec, "dry_run": True}, headers=tenants["b"])
    assert again.status_code == 422 and "already exists (id " in again.text and "domain_id" in again.text


def test_read_result_names_the_cells_behind_each_goal(tenants, db):
    """The roster report put Eman's broken request on Saturday; she asked for Friday."""
    from app.worker import work_once

    client = TestClient(app)
    files = [client.post("/api/v1/agent/files", files={"file": (n, body, "text/csv")}, headers=tenants["b"]).json()
             for n, body in (("nurses.csv", NURSES_CSV), ("cover.csv", COVER_CSV), ("requests_off.csv", REQUESTS_CSV))]
    spec = _roster_spec("cells")
    spec["seed"] = agent_files.expand(spec["seed"], files)
    built = client.post("/api/v1/problems/from-spec", json=spec, headers=tenants["b"]).json()
    run = client.post(f"/api/v1/scenarios/{built['scenario_id']}/runs", json={}, headers=tenants["b"]).json()
    for _ in range(5):
        if work_once(db) is None:
            break
    text = client.get(f"/api/v1/agent/result/{run['id']}", headers=tenants["b"]).json()["text"]
    line = next(x for x in text.splitlines() if x.startswith("o_requests_broken comes from: "))
    assert line.count("work[") == 2 and line.count(", Fri, ") == 2, line


def test_a_spec_slip_is_put_right_in_a_call_written_as_text_too():
    """The retest: the dropped "right" key came in a <tool_call> block in the reply, not a native call."""
    from app.agent import toolcall

    good = {"spec": _roster_spec("text")}
    bad = json.dumps({"name": "check_spec", "arguments": good}).replace('"relation": "<=", "right": ', '"relation": "<=", ', 1)
    calls, _, errors = toolcall.extract_tool_calls("<tool_call>\n" + bad + "\n</tool_call>", {"check_spec"})
    assert calls and calls[0]["arguments"] == json.loads(json.dumps(good)) and any("slip" in e for e in errors)
    xml = ("<function=check_spec><parameter=spec>" + json.dumps(good["spec"]).replace(
        '"relation": "<=", "right": ', '"relation": "<=", ', 1) + "</parameter></function>")
    calls, _, errors = toolcall.extract_tool_calls(xml, {"check_spec"})
    assert calls and isinstance(calls[0]["arguments"]["spec"], dict) and any("slip" in e for e in errors)
    # A broken spec that cannot be put right is an error, never passed on as a string.
    calls, _, errors = toolcall.extract_tool_calls("<function=check_spec><parameter=spec>{\"ir\": {\"a\" 1}}</parameter></function>",
                                                   {"check_spec"})
    assert not calls and errors


def test_records_from_a_sheet_that_repeats_their_key_are_made_once():
    """The retest: days loaded from cover.csv, which has a row per day and shift."""
    seed = agent_files.expand({"entities_from_file": [{"file": "cover.csv", "type": "day", "key": "day"}]}, _roster_files())
    assert [e["key"] for e in seed["entities"]] == DAYS
    with pytest.raises(agent_files.FileRefused, match="twice with different fields"):
        agent_files.expand({"entities_from_file": [{"file": "cover.csv", "type": "day", "key": "day",
                                                    "attrs": {"need": "nurses_needed"}}]}, _roster_files())


def test_the_read_back_shows_what_will_be_built_not_what_was_meant(tenants, monkeypatch):
    """The retest's roster plan said "1.3x night premium" and "no morning after a night"; it built one
    multiplier for every shift and a rule against a morning followed by a night. The read-back shows that."""
    from app.agent import readback

    spec = _roster_spec("readback")
    spec["seed"] = agent_files.expand(spec["seed"], _roster_files())
    text = readback.readback(spec)
    assert "- pay_factor[shift]: 1 cells given, every other cell 1" in text
    assert "- asked_off[nurse, day]: 8 cells given, every other cell 0" in text
    assert "link next_day (day → day): 6 links: Sun → Mon" in text
    assert "d2 ∈ day that d links to by next_day (d → d2)" in text
    assert "s1 ∈ shift where id = \"night\"" in text
    assert "1. o_requests_broken: Σ over n ∈ nurse, d ∈ day, s ∈ shift of (asked_off[n, d] × work[n, d, s])" in text
    # The retest's slip: one number for every shift reads as exactly that.
    wrong = json.loads(json.dumps(spec))
    wrong["seed"]["parameters"].append({"name": "night_multiplier", "index": [], "default_value": 1.3})
    assert "- night_multiplier: ONE number for the whole problem = 1.3" in readback.readback(wrong)
    # check_spec returns it, with the instruction to compare.
    model = _install(monkeypatch, [("native", "check_spec", json.dumps({"spec": _roster_spec("readback2")})),
                                   ("text", "Checked.")])
    events = _chat(tenants["b"], mode="model", text="check; night pays 1.3 times", files=_roster_files())
    tool_msg = next(m for m in model.requests[-1]["messages"] if m["role"] == "tool")
    assert tool_msg["content"].startswith("SPEC_OK") and "AS BUILT" in tool_msg["content"]
    assert "compare EVERY line of AS BUILT" in tool_msg["content"]
    del events


# -- the camp-bed evaluation (October 2026): data first, local metres, no endless loop ------------------------


def _no_data_spec(name: str) -> dict:
    return {"domain_name": f"Camp {name}", "problem_name": "Beds",
            "seed": {"entity_types": [{"name": "zone", "role": "location", "attributes": [
                {"name": "max_beds", "data_type": "integer"}]}]},
            "ir": {"version": 2, "sets": ["zone"], "parameters": {},
                   "variables": {"beds": {"index": ["zone"], "domain": "integer", "lower": 0, "upper": 100}},
                   "constraints": [{"id": "c_cap", "forall": [{"index": "z", "set": "zone"}],
                                    "left": {"var": "beds", "index": ["z"]}, "relation": "<=",
                                    "right": {"attr": {"of": "z", "name": "max_beds"}}, "severity": "hard"}],
                   "objective": {"sense": "maximize", "terms": [{"id": "o_beds", "weight": 1, "expression": {
                       "sum": {"var": "beds", "index": ["z"]}, "over": [{"index": "z", "set": "zone"}]}}]}}}


def test_a_plan_whose_set_has_no_data_source_is_refused(tenants, monkeypatch):
    """The camp-bed plan built "zone" and "door" with no records; the solve failed and it looped 24 times."""
    model = _install(monkeypatch, [("native", "check_spec", json.dumps({"spec": _no_data_spec("empty")})),
                                   ("text", "I need the zones' data.")])
    events = _chat(tenants["b"], mode="model", text="check")
    result = next(e for e in events if e["type"] == "result" and e["name"] == "check_spec")
    assert not result["ok"] and 'Set "zone" would have NO records' in result["preview"]
    del model
    # Typed records count as a source.
    spec = _no_data_spec("typed")
    spec["seed"]["entities"] = [{"type": "zone", "key": "z1", "attrs": {"max_beds": 3}}]
    assert core._sets_without_data(spec, {}) == []
    # So do records already in the domain.
    assert core._sets_without_data({**_no_data_spec("there"), "domain_id": 1}, {"zone": 4}) == []


def test_an_empty_set_the_decisions_range_over_blocks_solve(tenants, db):
    client = TestClient(app)
    built = client.post("/api/v1/problems/from-spec", json=_no_data_spec("block"), headers=tenants["b"])
    assert built.status_code in (200, 201), built.text
    run = client.post(f"/api/v1/scenarios/{built.json()['scenario_id']}/runs", json={}, headers=tenants["b"])
    assert run.status_code == 422 and "zone has no records" in run.text, run.text
    ready = client.get(f"/api/v1/problems/{built.json()['problem_id']}/readiness", headers=tenants["b"]).json()
    assert ready["check"]["ready"] is False
    assert any(f["code"] == "set_empty" and f["kind"] == "blocker" for f in ready["check"]["findings"])


def test_a_drawing_with_no_coordinate_system_is_local_metres_and_refuses_degrees(tenants, monkeypatch):
    from tests.test_agent import _utm_drawing

    client = TestClient(app)
    drawing = client.post("/api/v1/agent/files", headers=tenants["b"],
                          files={"file": ("camp.dxf", _utm_drawing(), "application/dxf")}).json()
    assert drawing["spatial"]["local_metres"] is True
    outline = agent_files.outline([drawing])
    assert "LOCAL METRES" in outline and "never use EPSG:4326" in outline and '"kind": "local"' in outline
    model = _install(monkeypatch, [("native", "place_file", json.dumps({"file": "camp.dxf", "epsg": 4326})),
                                   ("text", "Kept in local metres.")])
    events = _chat(tenants["b"], mode="model", text="place it", files=[drawing])
    refused = next(e for e in events if e["type"] == "result" and e["name"] == "place_file")
    assert refused["preview"].startswith("Refused: EPSG:4326 is longitude/latitude in degrees")
    del model


def test_a_drawing_far_too_big_for_metres_gets_a_scale_check():
    import io
    import ezdxf

    doc = ezdxf.new()  # no $INSUNITS, numbers of a millimetre drawing: 88,000 x 64,000
    doc.modelspace().add_lwpolyline([(0, 0), (88_000, 0), (88_000, 64_000), (0, 64_000)], close=True,
                                    dxfattribs={"layer": "BOUNDARY"})
    buffer = io.StringIO()
    doc.write(buffer)
    parsed = agent_files.parse_spatial("site.dxf", buffer.getvalue().encode())
    assert any(n.startswith("SCALE CHECK") and "88.0 km" in n for n in parsed["spatial"]["notes"])


def test_the_same_refusal_three_times_stops_the_turn_and_shows_the_error(tenants, monkeypatch):
    bad = _roster_spec("stuck")
    bad["ir"]["constraints"][0]["relation"] = "=<"
    model = _install(monkeypatch, [("native", "check_spec", json.dumps({"spec": bad}))] * 5 + [("text", "never")])
    events = _chat(tenants["b"], mode="model", text="check; night pays 1.3", files=_roster_files())
    answer = next(e for e in events if e["type"] == "answer")["text"]
    assert answer.startswith("I could not get the model past the platform's check")
    assert "**The check says:**" in answer and "**The part of the plan it is about:**" in answer
    assert sum(1 for e in events if e["type"] == "tool" and e["name"] == "check_spec") == core.MAX_SAME_ERROR
    # Only the latest attempt stays whole in the history.
    history = events[-1]["messages"]
    specs = [c["function"]["arguments"] for m in history for c in m.get("tool_calls") or []]
    assert sum("superseded by a later attempt" in a for a in specs) == len(specs) - 1
    del model


def test_the_reply_gets_the_room_the_prompt_leaves_and_the_server_size_is_read(monkeypatch):
    seen = {}

    class Reply:
        def __init__(self, body):
            self.body = body

        def read(self):
            return self.body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(core.urllib.request, "urlopen", lambda req, timeout=0: Reply(json.dumps(
        {"data": [{"id": "qwen3.5", "max_model_len": 65536}]}).encode()))
    core._SERVER_CONTEXT.clear()
    settings = core.Settings()
    assert core.server_context(settings) == 65536

    def silent(req, timeout=0):
        raise OSError("no server")

    monkeypatch.setattr(core.urllib.request, "urlopen", silent)
    core._SERVER_CONTEXT.clear()

    def llm(settings, messages, native, tools=None, max_tokens=None):
        seen["max_tokens"] = max_tokens
        return {"role": "assistant", "content": "ok", "_finish": "stop"}, True

    monkeypatch.setattr(core, "llm_chat", llm)
    agent = core.Agent(replace_settings(context=12000), agent_api._index, lambda *a, **k: {}, core.Context("x", mode="model"))
    history = [{"role": "user", "content": "x" * 18000}]  # 9,000 tokens of a 12,000 context
    agent._complete({"role": "system", "content": "s"}, history, True, agent.s)
    assert seen["max_tokens"] < agent.reply_tokens and seen["max_tokens"] >= 1024


def replace_settings(**kw):
    from dataclasses import replace

    return replace(core.Settings(), **kw)


def test_data_preparation_is_allowed_in_describe_mode(tenants, monkeypatch):
    model = _install(monkeypatch, [("native", "call_api", json.dumps(
        {"method": "POST", "path": "/api/domain/", "body": {"name": "Camp data first"}})), ("text", "Made.")])
    events = _chat(tenants["b"], mode="model", text="make the domain for the drawing")
    result = next(e for e in events if e["type"] == "result" and e["name"] == "call_api")
    assert result["ok"] and '"status": 201' in result["preview"]
    assert core.DATA_POST.match("/api/v1/gis/datasets") and core.DATA_POST.match("/api/v1/domains/3/distances")
    assert not core.DATA_POST.match("/api/v1/problems")
    del model


def test_run_python_works_where_network_namespaces_are_refused(monkeypatch, tmp_path):
    """Docker's default profile refuses unshare(CLONE_NEWNET); the probe raised, and every run_python failed
    with "Exception occurred in preexec_fn" on the live platform (camp-bed retest)."""
    from app.agent import sandbox

    def refuse(flags):
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(sandbox.os, "unshare", refuse, raising=False)
    monkeypatch.setattr(sandbox, "_NET_ISOLATION", None)
    assert sandbox._can_isolate_network() is False
    # The model is told each sheet's file name in the folder.
    outline = agent_files.outline(_roster_files())
    assert 'run_python file "nurses.csv"' in outline


def test_trimming_never_drops_the_problem_statement():
    """The camp-bed retest: trimming cut the brief, and the model asked "What decision are you making?"."""
    brief = {"role": "user", "content": "Maximise sofabeds of 1.5 x 0.5 m in the camps."}
    msgs = [{"role": "system", "content": "s"}, brief]
    for i in range(12):
        msgs += [{"role": "assistant", "content": None, "tool_calls": [{"id": f"c{i}", "type": "function", "function": {
                     "name": "run_python", "arguments": json.dumps({"code": "x = 1\n" * 1500})}}]},
                 {"role": "tool", "tool_call_id": f"c{i}", "name": "run_python", "content": "y" * 3000},
                 {"role": "assistant", "content": "Next step."},
                 {"role": "user", "content": f"go on {i}"}]
    fitted = core.fit(msgs, replace_settings(context=12000), 4096)
    assert fitted[1] == brief and fitted[-1]["content"] == "go on 11"
    assert len(json.dumps(fitted)) < len(json.dumps(msgs)) / 3
    ids = {c["id"] for m in fitted for c in m.get("tool_calls") or []}
    assert all(m.get("tool_call_id") in ids for m in fitted if m["role"] == "tool")


def test_a_large_generated_file_loads_whole_and_builds(tenants, db, monkeypatch, tmp_path):
    """The camp-bed retest generated more candidates than an attachment carries (5,000 rows) and than a plan
    could hold (2,000 records). Generated files are read whole from the working folder; a plan holds 50,000."""
    import time

    from app.agent import sandbox

    monkeypatch.setenv("AGENT_SANDBOX_ROOT", str(tmp_path))
    ctx = core.Context("x", mode="model", user_id="u1", conversation_id="big", can_run_python=True)
    folder = sandbox.workdir("u1", "big")
    import os

    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "candidates.csv"), "w") as fh:
        fh.write("cand,x_m,y_m\n" + "".join(f"c{i},{i % 200 * 0.5},{i // 200 * 0.5}\n" for i in range(20_000)))
    agent = core.Agent(core.Settings(), agent_api._index, lambda *a, **k: {}, ctx)
    spec = {"domain_name": "Camp big", "problem_name": "Beds",
            "seed": {"entity_types": [{"name": "cand", "role": "location", "attributes": [
                         {"name": "x_m", "data_type": "number"}, {"name": "y_m", "data_type": "number"}]}],
                     "entities_from_file": [{"file": "candidates.csv", "type": "cand", "key": "cand",
                                             "attrs": {"x_m": "x_m", "y_m": "y_m"}}]},
            "ir": {"version": 2, "sets": ["cand"], "parameters": {},
                   "variables": {"pick": {"index": ["cand"], "domain": "binary"}},
                   "constraints": [{"id": "c_some", "left": {"sum": {"var": "pick", "index": ["c"]},
                                                              "over": [{"index": "c", "set": "cand"}]},
                                    "relation": "<=", "right": {"const": 10}, "severity": "hard"}],
                   "objective": {"sense": "maximize", "terms": [{"id": "o", "weight": 1, "expression": {
                       "sum": {"var": "pick", "index": ["c"]}, "over": [{"index": "c", "set": "cand"}]}}]}}}
    expanded = agent._spec({"spec": spec})
    assert len(expanded["seed"]["entities"]) == 20_000
    started = time.monotonic()
    built = TestClient(app).post("/api/v1/problems/from-spec", json=expanded, headers=tenants["b"])
    assert built.status_code in (200, 201), built.text[:500]
    assert time.monotonic() - started < 120


def test_the_layout_pattern_builds_and_solves(tenants, db):
    """The prompt's layout pattern, as written there: candidates, cells, occupies links, one rule per cell."""
    from app.worker import work_once

    # A 2 m x 1 m room on a 0.5 m grid (8 cells); beds 1.0 x 0.5 m, horizontal or vertical, at every position.
    cells = [(f"k{i}{j}", i * 0.5, j * 0.5) for i in range(4) for j in range(2)]
    cands, occ = [], []
    for i in range(4):
        for j in range(2):
            for w, h, rot in ((2, 1, 0), (1, 2, 90)):
                if i + w <= 4 and j + h <= 2:
                    name = f"b{i}{j}r{rot}"
                    cands.append((name, i * 0.5, j * 0.5, rot))
                    occ += [(name, f"k{i + a}{j + b}") for a in range(w) for b in range(h)]
    files = [agent_files.parse("candidates.csv", _csv(["cand", "x_m", "y_m", "rot"], cands).encode()),
             agent_files.parse("cells.csv", _csv(["cell", "x_m", "y_m"], cells).encode()),
             agent_files.parse("occupies.csv", _csv(["cand", "cell"], occ).encode())]
    c, k = {"index": "c", "set": "cand"}, {"index": "k", "set": "cell"}
    spec = {"domain_name": "Layout pattern", "problem_name": "Beds",
            "seed": {"entity_types": [{"name": "cand", "role": "resource", "attributes": [
                         {"name": "x_m", "data_type": "number"}, {"name": "y_m", "data_type": "number"},
                         {"name": "rot", "data_type": "integer"}]},
                                      {"name": "cell", "role": "location", "attributes": [
                         {"name": "x_m", "data_type": "number"}, {"name": "y_m", "data_type": "number"}]}],
                     "relationship_types": [{"name": "occupies", "from": "cand", "to": "cell", "cardinality": "many_to_many"}],
                     "entities_from_file": [{"file": "candidates.csv", "type": "cand", "key": "cand",
                                             "attrs": {"x_m": "x_m", "y_m": "y_m", "rot": "rot"}},
                                            {"file": "cells.csv", "type": "cell", "key": "cell",
                                             "attrs": {"x_m": "x_m", "y_m": "y_m"}}],
                     "relationships_from_file": [{"file": "occupies.csv", "type": "occupies",
                                                  "from": ["cand", "cand"], "to": ["cell", "cell"]}]},
            "ir": {"version": 2, "sets": ["cand", "cell"], "relationships": ["occupies"], "parameters": {},
                   "variables": {"pick": {"index": ["cand"], "domain": "binary"}},
                   "constraints": [{"id": "c_no_overlap", "forall": [k], "left": {"sum": {"var": "pick", "index": ["c"]},
                                    "over": [{"index": "c", "set": "cand", "via": {"rel": "occupies", "to": "k"}}]},
                                    "relation": "<=", "right": {"const": 1}, "severity": "hard"}],
                   "objective": {"sense": "maximize", "terms": [{"id": "o_beds", "weight": 1, "expression": {
                       "sum": {"var": "pick", "index": ["c"]}, "over": [c]}}]}}}
    client = TestClient(app)
    spec["seed"] = agent_files.expand(spec["seed"], files)
    built = client.post("/api/v1/problems/from-spec", json=spec, headers=tenants["b"])
    assert built.status_code in (200, 201), built.text
    run = client.post(f"/api/v1/scenarios/{built.json()['scenario_id']}/runs", json={}, headers=tenants["b"]).json()
    for _ in range(5):
        if work_once(db) is None:
            break
    answer = client.get(f"/api/v1/runs/{run['id']}", headers=tenants["b"]).json()
    assert answer["status"] == "optimal" and round(float(answer["objective"])) == 4  # 8 cells / 2 cells a bed


def test_a_generated_file_is_never_overwritten_by_its_cut_attachment(tmp_path):
    from app.agent import sandbox

    folder = str(tmp_path)
    whole = "cell,x\n" + "".join(f"k{i},{i}\n" for i in range(7000))
    (tmp_path / "cells.csv").write_text(whole)
    attached = agent_files.parse("cells.csv", whole.encode())
    assert attached["sheets"][0]["truncated"]
    sandbox.write_attachments(folder, [attached])
    assert (tmp_path / "cells.csv").read_text() == whole


# -- the platform's order (camp-bed evaluation, second look) -------------------------------------------------


def test_made_up_values_are_refused_and_given_ones_pass():
    """Qwen's camp plan had bed_length 1.5, bed_width 0.5, corridor_width 0.35 (all given by the user) and
    max_door_distance 100, space_factor 1.25 (made up)."""
    spec = _no_data_spec("values")
    spec["seed"]["entities"] = [{"type": "zone", "key": "z1", "attrs": {"max_beds": 3}}]
    spec["seed"]["parameters"] = [{"name": n, "index": [], "default_value": v} for n, v in
                                  (("bed_length", 1.5), ("bed_width", 0.5), ("corridor_width", 0.35),
                                   ("max_door_distance", 100), ("space_factor", 1.25))]
    known = core.numbers_in("sofabeds of 1.5 m x 0.5 m, corridors at least 0.35 m wide")
    faults = core._platform_order_faults(spec, None, [], known)
    assert len(faults) == 1 and faults[0].startswith("STEP 4, DATA VALUES")
    assert "max_door_distance = 100" in faults[0] and "space_factor = 1.25" in faults[0] and "bed_length" not in faults[0]
    # A number a calculation printed counts as data.
    assert core._platform_order_faults(spec, None, [], known | core.numbers_in("door reach 100 m; factor 1.25")) == []
    assert core.numbers_in("a 5% margin") >= {5.0, 0.05}


def test_a_relationship_the_model_walks_needs_links_before_the_plan_and_before_solve(tenants, db):
    spec = _roster_spec("nolinks")
    spec["seed"] = agent_files.expand(spec["seed"], _roster_files())
    spec["seed"]["relationships"] = []
    faults = core._platform_order_faults(spec, None, [], core.numbers_in("night pays 1.3"))
    assert any(f.startswith('STEP 3, RELATIONSHIPS: "next_day" has NO links') for f in faults)
    client = TestClient(app)
    built = client.post("/api/v1/problems/from-spec", json=spec, headers=tenants["b"])
    assert built.status_code in (200, 201), built.text
    run = client.post(f"/api/v1/scenarios/{built.json()['scenario_id']}/runs", json={}, headers=tenants["b"])
    assert run.status_code == 422 and "next_day" in run.text and "no links" in run.text
    ready = client.get(f"/api/v1/problems/{built.json()['problem_id']}/readiness", headers=tenants["b"]).json()
    assert ready["check"]["ready"] is False
    assert any(f["code"] == "relationship_empty" for f in ready["check"]["findings"])
