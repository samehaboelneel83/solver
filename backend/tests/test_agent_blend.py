"""The third field test (October 2026): a feed blend, a continuous LP, told in plain words.

Reference (scipy/HiGHS, worked out separately): 1,000 kg at 13,813.55 EGP -- corn 241.56, soybean meal 107.54,
wheat bran 234.48, sunflower meal 0, corn gluten feed 300 (all of it), barley 116.42; protein, fat and fiber all
tight. At 8 % fiber: 13,408.34 (a saving of 405.21), although the fiber shadow price alone (-1.018 per kg-%)
"predicts" 1,018 -- it holds only up to 7.142 %.

What went wrong, and is checked here:
- the sum was written with `over` inside its body four times; the turn gave up and showed the person JSON;
- an empty forall and a bound given as a field name were refused;
- a fiber change sent with a run was dropped, and the run was answered from the earlier one;
- read_result had no shadow prices, and the model misread them by 100x, then extrapolated past their range;
- the answer was shown with "Wait, let's re-verify..." in it.
"""

from __future__ import annotations

import copy
import uuid
import json

from fastapi.testclient import TestClient

from app.agent import core
from app.agent import files as agent_files
from app.agent import repair
from app.api import agent as agent_api
from app.main import app
from tests.test_agent import _chat
from tests.test_agent_field_test import _install, _platform
from tests.test_quadratic import empty_queue  # noqa: F401
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401

INGREDIENTS_CSV = """ingredient,cost_egp_per_kg,protein_pct,fat_pct,fiber_pct,available_kg
Yellow corn,14.5,8.5,3.8,2.2,700
Soybean meal,27.0,44.0,1.5,6.5,400
Wheat bran,9.0,15.5,4.0,11.0,250
Sunflower meal,16.0,32.0,1.2,22.0,200
Corn gluten feed,13.0,21.0,2.5,8.5,300
Barley,12.0,11.0,2.0,5.5,350
"""
REFERENCE = 13813.553905
AT_8_PERCENT_FIBER = 13408.343473


def _share(field: str, nested_over: bool = False) -> dict:
    body = {"mul": [{"attr": {"of": "i", "name": field}}, {"var": "amount", "index": ["i"]}]}
    over = [{"index": "i", "set": "ingredient"}]
    return {"sum": {"body": body, "over": over}} if nested_over else {"sum": body, "over": over}


def _blend_spec(name: str, as_qwen_wrote_it: bool = False) -> dict:
    """The model as the Assistant built it; `as_qwen_wrote_it` puts back the three shapes it was refused for."""
    rules = [
        {"id": "c_batch_total", "severity": "hard", "note": "exactly the batch", "left": {"sum": {"var": "amount", "index": ["i"]},
         "over": [{"index": "i", "set": "ingredient"}]}, "relation": "=", "right": {"par": "batch_size", "index": []}},
        {"id": "c_protein_min", "severity": "hard", "note": "protein", "left": _share("protein_pct", as_qwen_wrote_it), "relation": ">=",
         "right": {"mul": [{"par": "min_protein", "index": []}, {"par": "batch_size", "index": []}]}},
        {"id": "c_fat_min", "severity": "hard", "note": "fat", "left": _share("fat_pct"), "relation": ">=",
         "right": {"mul": [{"par": "min_fat", "index": []}, {"par": "batch_size", "index": []}]}},
        {"id": "c_fiber_max", "severity": "hard", "note": "fiber", "left": _share("fiber_pct"), "relation": "<=",
         "right": {"mul": [{"par": "max_fiber", "index": []}, {"par": "batch_size", "index": []}]}},
    ]
    variable = {"index": ["ingredient"], "domain": "continuous", "lower": 0}
    if as_qwen_wrote_it:
        variable["upper"] = "available_kg"
        rules[0]["forall"] = []
    else:
        rules.append({"id": "c_availability", "severity": "hard", "note": "stock", "forall": [{"index": "i", "set": "ingredient"}],
                      "left": {"var": "amount", "index": ["i"]}, "relation": "<=",
                      "right": {"attr": {"of": "i", "name": "available_kg"}}})
    return {
        "domain_name": f"Feed blend {name}", "problem_name": "Cheapest 1000 kg batch", "note": "blend",
        "seed": {
            "entity_types": [{"name": "ingredient", "role": "resource", "attributes": [
                {"name": n, "data_type": "number", "required": True} for n in
                ("cost_egp_per_kg", "protein_pct", "fat_pct", "fiber_pct", "available_kg")]}],
            "parameters": [{"name": n, "index": [], "default_value": v} for n, v in
                           (("batch_size", 1000), ("min_protein", 18), ("min_fat", 3), ("max_fiber", 7))],
            "entities_from_file": [{"file": "ingredients.csv", "type": "ingredient", "key": "ingredient",
                                    "attrs": {n: n for n in ("cost_egp_per_kg", "protein_pct", "fat_pct",
                                                             "fiber_pct", "available_kg")}}],
        },
        "ir": {
            "version": 2, "sets": ["ingredient"],
            "parameters": {n: {"index": []} for n in ("batch_size", "min_protein", "min_fat", "max_fiber")},
            "variables": {"amount": variable},
            "constraints": rules,
            "objective": {"sense": "minimize", "mode": "weighted", "terms": [{"id": "o_cost", "weight": 1,
                          "expression": {"sum": {"mul": [{"attr": {"of": "i", "name": "cost_egp_per_kg"}},
                                                         {"var": "amount", "index": ["i"]}]},
                                         "over": [{"index": "i", "set": "ingredient"}]}}]},
        },
    }


def _file(client, headers) -> list[dict]:
    return [client.post("/api/v1/agent/files", files={"file": ("ingredients.csv", INGREDIENTS_CSV, "text/csv")},
                        headers=headers).json()]


def _solve(client, headers, db, scenario_id: int, body: dict | None = None) -> dict:
    from app.worker import work_once

    run = client.post(f"/api/v1/scenarios/{scenario_id}/runs", json=body or {}, headers=headers)
    assert run.status_code == 201, run.text
    for _ in range(5):
        if work_once(db) is None:
            break
    return client.get(f"/api/v1/runs/{run.json()['id']}", headers=headers).json()


def _build(client, headers, name: str) -> dict:
    spec = _blend_spec(name)
    spec["seed"] = agent_files.expand(spec["seed"], [agent_files.parse("ingredients.csv", INGREDIENTS_CSV.encode())])
    built = client.post("/api/v1/problems/from-spec", json=spec, headers=headers)
    assert built.status_code in (200, 201), built.text
    return built.json()


# -- the model as Qwen wrote it ---------------------------------------------------------------------------


def test_the_three_refused_shapes_are_put_right_and_the_model_told():
    spec = _blend_spec("repair", as_qwen_wrote_it=True)
    notes = repair.repair(spec)
    rules = {c["id"]: c for c in spec["ir"]["constraints"]}
    assert rules["c_protein_min"]["left"] == _share("protein_pct")  # over moved beside the sum
    assert "forall" not in rules["c_batch_total"]
    assert "upper" not in spec["ir"]["variables"]["amount"]
    stock = rules["amount_upper_available_kg"]
    assert stock["forall"] == [{"index": "i", "set": "ingredient"}] and stock["relation"] == "<="
    assert stock["right"] == {"attr": {"of": "i", "name": "available_kg"}}
    assert any("inside its body was moved" in n for n in notes)
    assert any("empty \"forall\"" in n for n in notes) and any("became the rule" in n for n in notes)
    # Nothing to repair: nothing changes, nothing said.
    clean = _blend_spec("clean")
    before = copy.deepcopy(clean)
    assert repair.repair(clean) == [] and clean == before


def test_other_ways_of_naming_a_sums_range_are_taken_as_its_over():
    for written in ({"sum": {"var": "x", "index": ["i"]}, "index": "i", "set": "s"},
                    {"sum": {"var": "x", "index": ["i"]}, "for": [{"index": "i", "set": "s"}]},
                    {"sum": {"over": {"index": "i", "set": "s"}, "term": {"var": "x", "index": ["i"]}}}):
        spec = {"ir": {"constraints": [{"id": "c", "left": copy.deepcopy(written), "relation": "<=",
                                        "right": {"const": 1}}]}}
        assert repair.repair(spec)
        assert spec["ir"]["constraints"][0]["left"] == {"sum": {"var": "x", "index": ["i"]},
                                                        "over": [{"index": "i", "set": "s"}]}


def test_the_validator_says_where_over_goes_and_how_a_varying_bound_is_written():
    from app.ir.validate import check_shape

    ir = _blend_spec("messages", as_qwen_wrote_it=True)["ir"]
    ir["constraints"][0].pop("forall")
    bound = check_shape(copy.deepcopy(ir))
    assert bound is not None and "one number for every cell" in bound.message and "available_kg" in bound.message
    ir["variables"]["amount"].pop("upper")
    nested = check_shape(ir)
    assert nested is not None and 'BESIDE "sum"' in nested.message and "INSIDE the sum's body" in nested.message


def test_qwens_blend_passes_check_spec_after_repair(tenants, monkeypatch):
    client = TestClient(app)
    files = _file(client, tenants["b"])
    model = _install(monkeypatch, [("native", "check_spec", json.dumps({"spec": _blend_spec("qwen", True)})),
                                   ("text", "Checked.")])
    events = _chat(tenants["b"], text="One batch of exactly 1000 kg; protein at least 18%, fat at least 3%, fiber at "
                   "most 7%; no more of an ingredient than available. Check it.", mode="model", files=files)
    result = next(e for e in events if e["type"] == "result" and e["name"] == "check_spec")
    assert result["ok"], result
    told = "\n".join(_platform(model))
    assert "moved beside" in told and "became the rule" in told


def test_a_repeated_refusal_is_flagged_as_the_same_one():
    calls = []

    def call(method, path, query=None, body=None, *a, **k):
        calls.append(path)
        return {"ok": False, "status": 422, "body": {"detail": [{"loc": ["ir", "objective"], "msg": "bad goal"}]}}

    agent = core.Agent(core.Settings(), agent_api._index, call, core.Context("x", mode="model"))
    first = agent._check_spec({"domain_name": "d", "ir": {"version": 2}})
    second = agent._check_spec({"domain_name": "d", "ir": {"version": 2}})
    assert "SAME refusal" not in first and "SAME refusal" in second


# -- solving, sensitivity, what-ifs ------------------------------------------------------------------------


def test_the_blend_solves_to_the_reference_and_read_result_explains_the_limits(tenants, db):
    client = TestClient(app)
    built = _build(client, tenants["b"], "solve")
    run = _solve(client, tenants["b"], db, built["scenario_id"])
    assert run["status"] == "optimal" and abs(float(run["objective"]) - REFERENCE) < 0.01
    text = client.get(f"/api/v1/agent/result/{run['id']}", headers=tenants["b"]).json()["text"]
    assert "Yellow corn" in text and "241.56" in text and "Corn gluten feed" in text
    for rule in ("c_protein_min", "c_fat_min", "c_fiber_max"):
        assert f"- {rule} (hard): held, tight (no room left)" in text, text
    line = next(ln for ln in text.splitlines() if ln.startswith("- c_availability (hard)"))
    assert "held, tight (no room left on 1 of " in line and "Corn gluten feed" in line, line
    assert "SENSITIVITY" in text
    # Fiber: -1.018 per kg-%, i.e. -1,018 per +1 on max_fiber, and only up to max_fiber 7.142.
    assert "per +1 on max_fiber (now 7): limit +1,000, goal -1,018.09" in text, text
    assert "holds for max_fiber from 4.855 to 7.142 (only 0.142 of room above 7, so +1 is OUTSIDE it" in text
    assert "batch_size is in 4 rules: a change to it moves them all together -- use what_if." in text
    assert "- c_fiber_max (hard): held, tight (no room left); uses 7,000 of 7,000, room left 0\n" in text
    assert "Not used (at 0)" in text and "amount[Sunflower meal] 10.702" in text


def test_a_run_refuses_a_field_it_does_not_know_instead_of_dropping_it(tenants, db):
    client = TestClient(app)
    built = _build(client, tenants["b"], "fields")
    refused = client.post(f"/api/v1/scenarios/{built['scenario_id']}/runs",
                          json={"parameter_overrides": {"max_fiber": 8}}, headers=tenants["b"])
    assert refused.status_code == 422 and "parameter_overrides" in refused.text
    agent = core.Agent(core.Settings(), agent_api._index, lambda *a, **k: {"ok": True, "body": {}}, core.Context("x"))
    said = agent.run_tool("call_api", {"method": "POST", "path": f"/api/v1/scenarios/{built['scenario_id']}/runs",
                                       "body": {"overrides": {"max_fiber": 8}}})
    assert said.startswith("Refused: a run takes only") and "what_if" in said
    from app.api.runs import RunRequest

    assert core.RUN_FIELDS == set(RunRequest.model_fields)


def test_what_if_solves_the_change_and_gives_the_exact_difference(tenants, db, monkeypatch):
    from tests.test_agent import _in_process_caller
    import threading
    from app.worker import work_once

    client = TestClient(app)
    built = _build(client, tenants["b"], "whatif")
    _solve(client, tenants["b"], db, built["scenario_id"])
    token = tenants["b"]["Authorization"].split(" ", 1)[1]
    agent = core.Agent(core.Settings(), agent_api._index, _in_process_caller(core.Settings(), token),
                       core.Context("x", mode="model"))
    stop = threading.Event()

    def worker():  # the platform's worker, solving what what_if queues
        while not stop.is_set():
            if work_once(db) is None:
                stop.wait(0.3)

    monkeypatch.setattr(core, "WHATIF_WAIT_S", 60)
    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    try:
        said = agent.run_tool("what_if", {"scenario_id": built["scenario_id"], "name": "fiber 8%",
                                          "set_param": [{"param": "max_fiber", "value": 8}]})
    finally:
        stop.set()
        thread.join(5)
    assert "WHAT-IF 'fiber 8%'" in said, said
    assert "BASE goal 13,813.55" in said and "WHAT-IF goal 13,408.34" in said and "difference -405.21" in said
    # The base scenario is untouched.
    base = client.get(f"/api/v1/scenarios/{built['scenario_id']}", headers=tenants["b"]).json()
    assert base["patch"] == {}
    assert "what_if" in {t["function"]["name"] for t in core.MODEL_TOOLS}


def test_a_settled_run_read_through_call_api_comes_back_as_read_result(tenants, db):
    from tests.test_agent import _in_process_caller

    client = TestClient(app)
    built = _build(client, tenants["b"], "auto")
    run = _solve(client, tenants["b"], db, built["scenario_id"])
    token = tenants["b"]["Authorization"].split(" ", 1)[1]
    agent = core.Agent(core.Settings(), agent_api._index, _in_process_caller(core.Settings(), token),
                       core.Context("x", mode="model"))
    said = agent.run_tool("call_api", {"method": "GET", "path": f"/api/v1/runs/{run['id']}"})
    assert said.startswith(f"Run {run['id']} has settled (optimal). This is read_result") and "SENSITIVITY" in said


# -- the conversation -------------------------------------------------------------------------------------


def test_an_answer_with_second_thoughts_is_not_shown(tenants, monkeypatch):
    model = _install(monkeypatch, [
        ("text", "You would save about 10.2 EGP.\n\nWait, let's re-verify the scaling. Actually it is 1,018 EGP."),
        ("text", "Allowing 8% fiber saves 405.21 EGP per batch (13,813.55 -> 13,408.34)."),
    ])
    events = _chat(tenants["b"], text="what if fiber were 8%?", mode="model")
    answers = [e["text"] for e in events if e["type"] == "answer"]
    assert answers == ["Allowing 8% fiber saves 405.21 EGP per batch (13,813.55 -> 13,408.34)."]
    assert any("second thoughts" in p for p in _platform(model))


def test_creating_the_domain_with_call_api_is_refused_with_where_it_goes():
    agent = core.Agent(core.Settings(), agent_api._index, lambda *a, **k: {"ok": True, "body": {}},
                       core.Context("x", mode="model"))
    said = agent.run_tool("call_api", {"method": "POST", "path": "/api/v1/domains", "body": {"name": "Feed"}})
    assert "Put domain_name in the spec" in said
    said = agent.run_tool("call_api", {"method": "POST", "path": "/api/v1/scenarios", "body": {}})
    assert "what_if" in said


def test_the_prompt_keeps_unrelated_problems_out_of_the_selected_domain_and_has_the_blend_pattern():
    prompt = core.model_prompt(core.Context("x", mode="model", domain_id=31))
    assert "never put an unrelated problem into the selected domain" in prompt
    assert "a MIX or BLEND" in prompt and "BESIDE" in prompt
    assert "call what_if" in prompt and "never extrapolate" in prompt


def test_the_read_back_shows_a_decisions_bounds():
    from app.agent.readback import readback

    text = readback(_blend_spec("readback"))
    assert "decision amount[ingredient]: continuous, 0 ≤ amount ≤ the platform ceiling" in text
    spec = _blend_spec("readback")
    spec["ir"]["variables"]["amount"] = {"index": ["ingredient"], "domain": "continuous", "upper": 1000}
    assert "continuous, 0 ≤ amount ≤ 1000" in readback(spec)


def test_a_turn_runs_on_when_the_browser_leaves_and_can_be_picked_up(tenants, monkeypatch):
    """The blend test: changing page lost a turn minutes into writing the model."""
    _install(monkeypatch, [("text", "Here is my answer.")])
    events = _chat(tenants["b"], text="hello", mode="model", conversation_id="resume1", server_history=True)
    assert events[-1]["type"] == "state"
    client = TestClient(app)
    turn = client.get("/api/v1/agent/conversations/resume1/turn", headers=tenants["b"]).json()
    assert turn["known"] and not turn["running"]
    assert [e["type"] for e in turn["events"]][-2:] == ["answer", "state"]
    assert client.get("/api/v1/agent/conversations/resume1/turn?after=1", headers=tenants["b"]).json()["count"] == turn["count"]
    # Someone else's conversation is not theirs to read.
    other = client.get("/api/v1/agent/conversations/resume1/turn", headers=tenants["a"]).json()
    assert other == {"running": False, "known": False, "events": [], "count": 0}
    assert client.post("/api/v1/agent/conversations/resume1/stop", headers=tenants["b"]).status_code == 204


def test_a_small_attached_sheet_is_shown_to_the_model_whole():
    """The blend retest: 3 of 6 ingredients shown, and the person was asked to name the rest."""
    parsed = agent_files.parse("ingredients.csv", INGREDIENTS_CSV.encode())
    text = agent_files.outline([parsed])
    assert all(name in text for name in ("Yellow corn", "Sunflower meal", "Corn gluten feed", "Barley"))
    assert "(every row is shown above)" in text
    big = agent_files.parse("big.csv", ("k,v\n" + "".join(f"r{i},{i}\n" for i in range(300))).encode())
    assert "...297 more rows: read_file / query_file, never ask the user for them" in agent_files.outline([big])
    # Fibre test: 30 places x 6 columns showed 3 rows, and the model asked whether the exchange was in the file.
    narrow = agent_files.parse("places.csv", ("place,kind,a,b,c,d\n" + "".join(
        f"p{i},village,1,2,3,4\n" for i in range(30))).encode())
    assert "p29" in agent_files.outline([narrow]) and "(every row is shown above)" in agent_files.outline([narrow])
    wide = agent_files.parse("places.csv", ("place,kind,a,b,c,d\n" + "".join(
        f"p{i},village,1,2,3,4\n" for i in range(120))).encode())
    assert 'every "place": ["p0", "p1"' in agent_files.outline([wide]) and "p119" in agent_files.outline([wide])


PRODUCTS_CSV = """product,profit_egp,cutting_h,assembly_h,finishing_h,max_demand
Table,1200,3,2,4,15
Chair,450,1,2,1,60
Bookshelf,900,2,3,2,25
Cabinet,1600,4,4,3,10
"""


def test_read_result_says_how_much_of_each_limit_is_used(tenants, db):
    """The furniture retest (integer): the base report was exact, but after a what-if the model wrote usage
    figures of its own ("154/154 hours, tight" for 151 used). The platform now gives them."""
    def share(field):
        return {"sum": {"mul": [{"attr": {"of": "p", "name": field}}, {"var": "make", "index": ["p"]}]},
                "over": [{"index": "p", "set": "product"}]}

    spec = {
        "domain_name": "Furniture usage", "problem_name": "Weekly plan", "note": "plan",
        "seed": {
            "entity_types": [{"name": "product", "role": "task", "attributes": [
                {"name": n, "data_type": "number", "required": True} for n in
                ("profit_egp", "cutting_h", "assembly_h", "finishing_h", "max_demand")]}],
            "parameters": [{"name": n, "index": [], "default_value": v} for n, v in
                           (("cutting_hours", 120), ("assembly_hours", 140), ("finishing_hours", 110))],
            "entities_from_file": [{"file": "products.csv", "type": "product", "key": "product",
                                    "attrs": {n: n for n in ("profit_egp", "cutting_h", "assembly_h", "finishing_h",
                                                             "max_demand")}}],
        },
        "ir": {
            "version": 2, "sets": ["product"],
            "parameters": {n: {"index": []} for n in ("cutting_hours", "assembly_hours", "finishing_hours")},
            "variables": {"make": {"index": ["product"], "domain": "integer", "lower": 0, "upper": 100}},
            "constraints": [
                {"id": "c_cutting", "severity": "hard", "left": share("cutting_h"), "relation": "<=",
                 "right": {"par": "cutting_hours", "index": []}},
                {"id": "c_assembly", "severity": "hard", "left": share("assembly_h"), "relation": "<=",
                 "right": {"par": "assembly_hours", "index": []}},
                {"id": "c_finishing", "severity": "hard", "left": share("finishing_h"), "relation": "<=",
                 "right": {"par": "finishing_hours", "index": []}},
                {"id": "c_demand", "severity": "hard", "forall": [{"index": "p", "set": "product"}],
                 "left": {"var": "make", "index": ["p"]}, "relation": "<=",
                 "right": {"attr": {"of": "p", "name": "max_demand"}}},
            ],
            "objective": {"sense": "maximize", "mode": "weighted", "terms": [
                {"id": "o_profit", "weight": 1, "expression": share("profit_egp")}]},
        },
    }
    client = TestClient(app)
    spec["seed"] = agent_files.expand(spec["seed"], [agent_files.parse("products.csv", PRODUCTS_CSV.encode())])
    built = client.post("/api/v1/problems/from-spec", json=spec, headers=tenants["b"])
    assert built.status_code in (200, 201), built.text
    run = _solve(client, tenants["b"], db, built.json()["scenario_id"])
    assert run["status"] == "optimal" and round(float(run["objective"])) == 48_400
    text = client.get(f"/api/v1/agent/result/{run['id']}", headers=tenants["b"]).json()["text"]
    made = {k[0] if isinstance(k, list) else k: 1 for k in []}
    del made
    amounts = {a["index"][0]: a["value"] for a in run["amounts"]["make"]}
    used = {f: sum(amounts.get(p, 0) * h for p, h in zip(("Table", "Chair", "Bookshelf", "Cabinet"), hours))
            for f, hours in (("cutting", (3, 1, 2, 4)), ("assembly", (2, 2, 3, 4)), ("finishing", (4, 1, 2, 3)))}
    for name, limit in (("cutting", 120), ("assembly", 140), ("finishing", 110)):
        assert f"- c_{name} (hard): held" in text
        assert f"uses {used[name]:,.0f} of {limit}, room left {limit - used[name]:,.0f}" in text, text
    assert "c_demand (hard): held" in text and "least room left on any one record 0" in text
    assert "Each product's field x make:" in text
    totals = next(line for line in text.splitlines() if line.startswith("Totals of field x make: "))
    for part in ("profit_egp 48,400", f"cutting_h {used['cutting']:,.0f}", f"assembly_h {used['assembly']:,.0f}",
                 f"finishing_h {used['finishing']:,.0f}"):
        assert part in totals, totals


def test_read_result_of_a_what_if_reads_its_changed_numbers(tenants, db, monkeypatch):
    """The furniture retest: finishing raised from 110 to 120 by a what-if was read back as 110."""
    client = TestClient(app)
    built = _build(client, tenants["b"], "whatif-readback")
    base = client.get(f"/api/v1/scenarios/{built['scenario_id']}", headers=tenants["b"]).json()
    made = client.post("/api/v1/scenarios", json={
        "problem_id": base["problem_id"], "model_version_id": base["model_version_id"], "name": "fiber 8",
        "patch": {"set_param": [{"param": "max_fiber", "index": [], "value": 8}]}}, headers=tenants["b"])
    assert made.status_code == 201, made.text
    run = _solve(client, tenants["b"], db, made.json()["id"])
    assert abs(float(run["objective"]) - AT_8_PERCENT_FIBER) < 0.01
    text = client.get(f"/api/v1/agent/result/{run['id']}", headers=tenants["b"]).json()["text"]
    assert "c_fiber_max (hard): held, tight (no room left); uses 8,000 of 8,000" in text, text
    assert "per +1 on max_fiber (now 8)" in text


def test_a_problem_asked_in_the_ask_tab_is_handed_to_describe_with_its_files(tenants, monkeypatch):
    """The camp test (October 2026): asked in the Ask tab, the Assistant spent 16 minutes making kinds of record and
    typing 16 records one by one, then said to switch tabs. It hands the problem over at once now."""
    client = TestClient(app)
    files = _file(client, tenants["b"])
    model = _install(monkeypatch, [("native", "hand_to_describe", json.dumps({"reason": "A feed blend to optimise."}))])
    events = _chat(tenants["b"], text="Cheapest feed mix from the attached ingredients please", mode="assistant",
                   files=files, conversation_id="ask1", server_history=True)
    kinds = [e["type"] for e in events]
    assert "handover" in kinds and kinds[-1] == "state"
    answer = next(e["text"] for e in events if e["type"] == "answer")
    assert answer.startswith("A feed blend to optimise.") and "Describe a problem" in answer
    assert len(model.requests) == 1  # nothing else was tried
    moved = client.post("/api/v1/agent/conversations/ask1/handover", headers=tenants["b"]).json()
    assert moved["text"] == "Cheapest feed mix from the attached ingredients please"
    assert [f["name"] for f in moved["files"]] == ["ingredients.csv"] and moved["files"][0]["sheets"][0]["rows"] == []
    # The new Describe conversation already holds the file's rows.
    _install(monkeypatch, [("native", "read_file", json.dumps({"file": "ingredients.csv"})), ("text", "Read it.")])
    events = _chat(tenants["b"], text=moved["text"], mode="model", conversation_id=moved["conversation_id"],
                   server_history=True, keep_files=["ingredients.csv"])
    read = next(e for e in events if e["type"] == "result" and e["name"] == "read_file")
    assert read["ok"] and "Sunflower meal" in read["preview"]
    # Only in Ask mode; someone else's conversation is not theirs.
    assert "hand_to_describe" not in {t["function"]["name"] for t in core.MODEL_TOOLS}
    assert client.post("/api/v1/agent/conversations/ask1/handover", headers=tenants["a"]).status_code == 404


def test_building_a_problem_from_the_ask_tab_hands_it_over_too(tenants, monkeypatch):
    _install(monkeypatch, [("native", "call_api", json.dumps({"method": "POST", "path": "/api/v1/problems/from-spec",
                                                              "body": {}}))])
    events = _chat(tenants["b"], text="build it", mode="assistant")
    assert any(e["type"] == "handover" for e in events)


def test_a_layout_step_the_model_chose_that_is_too_fine_points_to_the_one_that_fits(monkeypatch):
    """The camp retest: a 0.5 m step the model chose gave 384k links; leaving it out gives 1 m and fits."""
    from app.agent import layout

    calls = []

    def fake(files, folder, *, step=None, **kw):
        calls.append(step)
        if step == 0.5:
            raise layout.LayoutRefused("this layout needs 383,808 occupies links")
        return {"grid_step_m": 1.0, "candidates": 12008, "upper_bound": {"items": 828}, "files": [], "spec": {}}

    monkeypatch.setattr(layout, "make", fake)
    agent = core.Agent(core.Settings(), agent_api._index, lambda *a, **k: {"ok": True}, core.Context("x", mode="model"))
    said = agent._make_layout({"area_layers": ["BOUNDARY"], "items": [{"name": "bed", "length": 2, "width": 1}],
                               "aisle": 1, "step": 0.5})
    assert said.startswith("Could not lay it out: this layout needs 383,808")
    assert "LEAVING step OUT works: the platform's exact step is 1 m, giving 12,008 candidate positions" in said
    assert calls == [0.5, None]


def test_quotes_left_unescaped_in_a_plans_text_are_put_right(tenants, monkeypatch):
    """The camp retest: 'The "keeps_free" cells...' in a plan's summary, refused twice, 7 minutes."""
    from app.agent import toolcall

    raw = ('{"summary": "* The "keeps_free" cells model the 1m aisle; the "zone" rule is a pre-filter.", '
           '"spec": {"domain_name": "d", "ir": {"version": 2}}}')
    fixed = json.loads(toolcall.fix_spec(raw))
    assert fixed["summary"] == '* The "keeps_free" cells model the 1m aisle; the "zone" rule is a pre-filter.'
    assert fixed["spec"]["ir"] == {"version": 2}
    assert toolcall.escape_inner_quotes('{"a": 1 "b": 2}') is None  # a missing comma is not a quote in a text
    # Through the loop: the call runs (its check refuses the toy spec, but it is not "NOT run").
    model = _install(monkeypatch, [("native", "check_spec", raw.replace('"summary"', '"note"', 1)), ("text", "ok")])
    events = _chat(tenants["b"], text="check", mode="model")
    assert any(e["type"] == "tool" and e["name"] == "check_spec" for e in events)
    assert not any("NOT run" in p for p in _platform(model))


def test_a_run_the_assistant_starts_gets_two_minutes_not_the_platform_default():
    sent = []

    def call(method, path, query=None, body=None, *a, **k):
        sent.append((method, path, body))
        return {"ok": True, "status": 201, "body": {"id": 1, "status": "queued"}}

    agent = core.Agent(core.Settings(), agent_api._index, call, core.Context("x", mode="model"))
    agent.built = {"built": True}
    agent.run_tool("call_api", {"method": "POST", "path": "/api/v1/scenarios/7/runs", "body": {}})
    agent.run_tool("call_api", {"method": "POST", "path": "/api/v1/scenarios/8/runs",
                                "body": {"time_limit_s": 900}})
    runs = [b for m, p, b in sent if p.endswith("/runs")]
    assert runs == [{"time_limit_s": core.AGENT_RUN_SECONDS}, {"time_limit_s": 900}] and core.AGENT_RUN_SECONDS == 120


def test_a_feasible_answer_is_never_reported_as_optimal_and_exports_are_listed():
    from app.agent import result

    rec = {"id": 69, "status": "feasible", "objective": 638, "best_bound": 808.0, "solver": "milp", "params": {},
           "ir": {"objective": {"sense": "maximize"}, "variables": {}, "constraints": []},
           "data": {"sets": {"item": [{"id": "b1", "x_m": 1}]}}, "assignments": {}, "amounts": {}, "results": []}
    rec["ir"]["relationships"] = ["occupies"]
    text = result.summary(rec)
    assert "NOT PROVEN OPTIMAL" in text and "at most 808, so it is 21.0% short of that bound (a bound, not an answer found" in text
    assert "MAP: GeoJSON /api/v1/runs/69/export?format=geojson" in text and "format=dxf" in text


def test_questions_after_go_ahead_are_not_shown_and_the_plan_is_made(tenants, monkeypatch):
    """The blend and camp tests: "nothing else, go ahead" was followed by "exactly 1000 kg? Shall I proceed?"."""
    model = _install(monkeypatch, [
        ("text", "**Open questions:**\\n1. Is it exactly 1000 kg?\\n\\nShall I proceed?"),
        ("native", "check_spec", json.dumps({"spec": {"domain_name": "d", "ir": {"version": 2}}})),
        ("text", "Checked; here is what I will build."),
    ])
    events = _chat(tenants["b"], text="Exactly 1000 kg, nothing else. Go ahead.", mode="model")
    answers = [e["text"] for e in events if e["type"] == "answer"]
    assert answers == ["Checked; here is what I will build."]
    assert any("already said to go ahead" in p for p in _platform(model))
    # Without a go-ahead, questions are fine.
    model = _install(monkeypatch, [("text", "How many kg is a batch?")])
    events = _chat(tenants["b"], text="We mix feed.", mode="model")
    assert [e["text"] for e in events if e["type"] == "answer"] == ["How many kg is a batch?"]


def test_a_new_workspace_asked_for_is_made_not_the_selected_one_reused():
    """Camp retest: "in new workspace" was ignored and the selected workspace's old records offered for reuse."""
    agent = core.Agent(core.Settings(), agent_api._index, lambda *a, **k: {"ok": True, "body": {}},
                       core.Context("x", mode="model", domain_id=31))
    agent.messages = [{"role": "user", "content": "in new workspace. Place as many beds as fit."}]
    assert agent._order_faults({"domain_id": 31, "seed": {}, "ir": {}}) == [core.NEW_WORKSPACE_ASKED]
    assert agent._order_faults({"domain_name": "Camp 2", "seed": {}, "ir": {}}) != [core.NEW_WORKSPACE_ASKED]
    agent.messages.append({"role": "user", "content": "actually, use the existing workspace"})
    assert not agent._asked_new_workspace()
    agent.messages = [{"role": "user", "content": "Place as many beds as fit."}]
    assert not agent._asked_new_workspace()
    assert "When the user asks for a new workspace, ALWAYS make one" in core.model_prompt(agent.ctx)
    # Bakery test: the workspace this conversation made may take a corrected model.
    agent.messages = [{"role": "user", "content": "Use a new workspace \"Bakery\"."},
                      {"role": "tool", "name": "propose_plan", "content":
                       'BUILT {"ok": true, "dry_run": false, "domain_id": 98, "domain_created": true, "problem_id": 1}'}]
    assert agent._order_faults({"domain_id": 98, "seed": {}, "ir": {}}) != [core.NEW_WORKSPACE_ASKED]
    assert agent._order_faults({"domain_id": 31, "seed": {}, "ir": {}}) == [core.NEW_WORKSPACE_ASKED]


def test_a_drawing_whose_upload_is_used_up_is_copied_into_the_new_workspace():
    """Camp retest: the new workspace got no map -- the drawing's upload went into the first workspace."""
    calls = []

    def call(method, path, params=None, body=None):
        calls.append((method, path, body))
        if path == "/api/v1/agent/workspace":
            return {"ok": True, "body": {"map_data": []}}
        if path == "/api/v1/gis/datasets":
            return {"ok": False, "body": {"detail": "That upload is gone"}}
        return {"ok": True, "body": {"id": 9}}

    spatial = {"upload_id": "u1", "placement": {"kind": "local"}, "sha256": "ab" * 32, "extent": [0, 0, 10, 5]}
    agent = core.Agent(core.Settings(), agent_api._index, call,
                       core.Context("x", mode="model", files=[{"name": "camp.dxf", "spatial": spatial}]))
    said = agent._import_drawings(58)
    assert "is now on the domain's map" in said
    method, path, body = calls[-1]
    assert path == "/api/v1/gis/domains/58/datasets/same-drawing"
    assert body == {"name": "camp.dxf", "sha256": "ab" * 32, "filename": "camp.dxf", "extent": [0, 0, 10, 5]}


def test_an_answer_placed_by_metres_offers_no_empty_map():
    from app.agent import result as agent_result

    rec = {"id": 7, "status": "feasible", "objective": 3, "assignments": {}, "params": {},
           "ir": {"sets": ["item"], "relationships": ["occupies"], "variables": {}, "constraints": [],
                  "objective": {"sense": "maximize", "terms": []}},
           "data": {"sets": {"item": [{"id": "a", "x_m": 1.0}]}}}
    placed = agent_result.summary({**rec, "map_placed": True})
    assert "format=geojson" in placed and "format=dxf" in placed and "NO MAP" not in placed
    unplaced = agent_result.summary({**rec, "map_placed": False})
    assert "format=geojson" not in unplaced and "format=dxf" in unplaced and "NO MAP" in unplaced


def test_the_prompt_teaches_a_network_from_a_source_as_one_connected_rule():
    """Fibre test: the model wrote "a picked place touches a used road" (islands pass) and made roads records."""
    prompt = core.model_prompt(core.Context("x", mode="model"))
    assert "NETWORK FROM A SOURCE" in prompt and '"sources":[{"attr":"kind"' in prompt
    assert "relationships_from_file" in prompt and "cut-off islands" in prompt


def test_seed_and_model_parts_written_beside_seed_are_moved_where_they_belong():
    """Fibre test: entities_from_file, relationships_from_file and parameters at the top, and no ir."""
    spec = {"domain_name": "F", "seed": {"entity_types": [{"name": "place"}]},
            "entities_from_file": [{"file": "places.csv"}], "relationships_from_file": [{"file": "roads.csv"}],
            "parameters": [{"name": "budget", "index": [], "default_value": 300000}],
            "sets": ["place"], "variables": {"pick": {"index": ["place"], "domain": "binary"}}, "constraints": [],
            "objective": {"sense": "maximize", "terms": []}}
    notes = repair.misplaced(spec)
    assert set(spec) == {"domain_name", "seed", "ir"}
    assert spec["seed"]["entities_from_file"] == [{"file": "places.csv"}] and spec["seed"]["parameters"][0]["name"] == "budget"
    assert spec["ir"]["version"] == 2 and "pick" in spec["ir"]["variables"]
    assert any("moved into seed" in n for n in notes) and any("moved into ir" in n for n in notes)
    agent = core.Agent(core.Settings(), agent_api._index, lambda *a, **k: {"ok": True, "body": {}},
                       core.Context("x", mode="model"))
    said = agent.run_tool("check_spec", {"spec": {"domain_name": "F", "seed": {}}})
    assert 'the spec has no "ir"' in said, said


def test_a_rule_without_a_severity_is_made_hard_and_the_model_told():
    spec = {"ir": {"constraints": [{"id": "c_reach", "connected": {}}, {"id": "c_soft", "weight": 2},
                                   {"id": "c_null", "severity": None, "left": {"const": 1}}]}, "seed": {}}
    notes = repair.repair(spec)
    rules = {c["id"]: c for c in spec["ir"]["constraints"]}
    assert rules["c_reach"]["severity"] == "hard" and rules["c_null"]["severity"] == "hard"
    assert "severity" not in rules["c_soft"]
    assert any('c_reach had no severity and was made "hard"' in n for n in notes)


def test_a_product_of_three_factors_is_nested_into_pairs():
    term = {"mul": [{"const": 500}, {"attr": {"of": "p", "name": "households"}}, {"var": "pick", "index": ["p"]}]}
    spec = {"ir": {"constraints": [], "objective": {"terms": [{"id": "o", "expression": {
        "sum": term, "over": [{"index": "p", "set": "place"}]}}]}}, "seed": {}}
    notes = repair.repair(spec)
    got = spec["ir"]["objective"]["terms"][0]["expression"]["sum"]
    assert got == {"mul": [{"const": 500}, {"mul": [{"attr": {"of": "p", "name": "households"}},
                                                    {"var": "pick", "index": ["p"]}]}]}
    assert "a product of 3 factors was nested into pairs" in notes


def test_the_read_back_says_a_network_rule_in_words_and_lists_a_parameter_once():
    """Fibre test: "rule c_connectivity: null None null", and both parameters twice."""
    from app.agent import readback

    spec = {"seed": {"parameters": [{"name": "budget", "index": [], "default_value": 300000}]},
            "parameters": [{"name": "budget", "index": [], "default_value": 300000}],
            "ir": {"constraints": [{"id": "c_reach", "severity": "hard", "connected": {
                "assign": {"var": "pick", "index": ["p"]}, "units": {"index": "p", "set": "place"},
                "via": "connects", "sources": [{"attr": "kind", "op": "=", "value": "exchange"}]}}]}}
    repair.misplaced(spec)
    text = readback.readback(spec)
    assert text.count("budget: ONE number") == 1
    assert ('rule c_reach: every place with pick = 1 is joined along connects to a place where kind = "exchange", '
            "through others with pick = 1 (hard)") in text


def test_read_result_adds_up_the_chosen_and_says_a_network_rule_in_words():
    """Fibre test: 1,770 households written for 1,870; the network rule read "held, tight (no room left)"."""
    from app.agent import result as agent_result

    places = [{"id": "a", "cost_egp": 0, "households": 0}, {"id": "b", "cost_egp": 30000, "households": 260},
              {"id": "c", "cost_egp": 26000, "households": 40}, {"id": "d", "cost_egp": 22000, "households": 60}]
    rec = {"id": 74, "status": "optimal", "objective": 1, "params": {},
           "assignments": {"pick": [["a"], ["b"], ["c"]]}, "amounts": None,
           "ir": {"sets": ["place"], "variables": {"pick": {"index": ["place"], "domain": "binary"}},
                  "constraints": [{"id": "c_reach", "severity": "hard", "connected": {
                      "assign": {"var": "pick", "index": ["p"]}, "units": {"index": "p", "set": "place"},
                      "via": "road", "sources": [{"attr": "kind", "op": "=", "value": "exchange"}]}}],
                  "objective": {"sense": "maximize", "terms": []}},
           "data": {"sets": {"place": places}},
           "results": [{"constraint_id": "c_reach", "satisfied": True, "hard": True, "slack": 0}]}
    text = agent_result.summary(rec)
    assert "Totals over the 3 chosen: cost_egp 56,000, households 300" in text
    assert "- c_reach (hard): held: every chosen one joined to a source along road" in text
    assert "tight" not in text.split("RULES:")[1]


def test_a_what_if_says_which_choices_it_added_and_removed_and_the_base_totals():
    """Fibre test: "keeping the previous 12 places" when Ayyat was dropped; the base total from memory."""
    runs = {74: {"assignments": {"pick": [["Saft"], ["Ayyat"], ["Waraq"]]}},
            75: {"assignments": {"pick": [["Saft"], ["Waraq"], ["Imbaba"], ["Kerdasa"]]}}}

    def call(method, path, params=None, body=None):
        if path.startswith("/api/v1/runs/"):
            return {"ok": True, "body": runs[int(path.rsplit("/", 1)[1])]}
        if path == "/api/v1/agent/result/74":
            return {"ok": True, "body": {"text": "RUN 74\nTotals over the 3 chosen: households 1,870\n"
                                                 "- c_budget (hard): held; uses 291,000 of 300,000, room left 9,000"}}
        return {"ok": False}

    agent = core.Agent(core.Settings(), agent_api._index, call, core.Context("x", mode="model"))
    lines = agent._what_changed(74, 75)
    assert "CHANGED pick: 3 chosen -> 4; added 2: Imbaba, Kerdasa; removed 1: Ayyat." in lines
    assert "BASE Totals over the 3 chosen: households 1,870" in lines
    assert any(l.startswith("BASE - c_budget") and "room left 9,000" in l for l in lines)


def test_the_what_if_tells_the_model_to_take_base_numbers_from_it_not_from_memory():
    import inspect

    assert "never from your earlier" in inspect.getsource(core.Agent) and "BASE ..., CHANGED ..." in inspect.getsource(core.Agent)


def test_a_total_the_tools_do_not_say_is_caught_and_differences_are_not():
    """Fibre test: 1,770 households repeated from an earlier reply although every result said 1,870."""
    tools = ["Totals over the 12 chosen: cost_egp 291,000, households 1,870\n"
             "BASE Totals over the 12 chosen: cost_egp 291,000, households 1,870"]
    wrong = "| **Total Households** | **1,770** |\nall 1,770 households now pay more; budget used 291,000 EGP"
    assert core.stale_totals(wrong, tools) == [("1,770", "1,870", "households")]
    fine = "Total households: 1,870 (+210 households; 580 gained households, 470 lost households)"
    assert core.stale_totals(fine, tools) == []
    assert core.stale_totals(wrong, ["no totals here"]) == []


OPERATIONS_CSV = """job,step,machine,minutes
Gear,1,Lathe,25
Gear,2,Grinder,41
Gear,3,Drill,11
Gear,4,Mill,12
Shaft,1,Lathe,43
Shaft,2,Mill,40
Shaft,3,Drill,33
Shaft,4,Grinder,10
Bracket,1,Mill,22
Bracket,2,Drill,28
Bracket,3,Lathe,22
Bracket,4,Grinder,38
Housing,1,Lathe,43
Housing,2,Mill,17
Housing,3,Grinder,20
Housing,4,Drill,38
Flange,1,Lathe,45
Flange,2,Mill,32
Flange,3,Grinder,24
Flange,4,Drill,20
"""


def test_a_job_shop_from_one_file_with_joined_keys_and_steps_in_order_solves_to_the_reference(tenants, db):
    """Job-shop field test: no key column, no "next step" in the file. Reference (own CP-SAT): 231 minutes."""
    from app.worker import work_once

    client = TestClient(app)
    ops = client.post("/api/v1/agent/files", files={"file": ("operations.csv", OPERATIONS_CSV, "text/csv")},
                      headers=tenants["b"]).json()
    key = ["job", "step"]
    seed = {"entity_types": [{"name": "op", "attributes": [{"name": "job", "data_type": "text"},
                                                            {"name": "step", "data_type": "integer"}]},
                             {"name": "machine"}],
            "relationship_types": [{"name": "then", "from": "op", "to": "op"}, {"name": "on", "from": "op", "to": "machine"}],
            "parameters": [{"name": "minutes", "index": ["op"], "default_value": 0}],
            "entities_from_file": [{"file": "operations.csv", "type": "op", "key": key, "attrs": {"job": "job", "step": "step"}},
                                   {"file": "operations.csv", "type": "machine", "key": "machine"}],
            "relationships_from_file": [{"file": "operations.csv", "type": "on", "from": ["op", key], "to": ["machine", "machine"]}],
            "relationships_in_order": [{"type": "then", "of": "op", "by": "step", "within": "job"}],
            "parameter_values_from_file": [{"file": "operations.csv", "parameter": "minutes", "entities": [["op", key]],
                                            "value": "minutes"}]}
    expanded = agent_files.expand(seed, [ops])
    then = [r for r in expanded["relationships"] if r["type"] == "then"]
    assert len(then) == 15 and {"type": "then", "from": ["op", "Gear-1"], "to": ["op", "Gear-2"]} in then
    op = {"index": ["op"]}
    ir = {"version": 2, "sets": ["op", "machine"], "relationships": ["then", "on"], "parameters": {"minutes": {"index": ["op"]}},
          "variables": {"begin": {**op, "domain": "integer", "lower": 0, "upper": 1000},
                        "finish": {**op, "domain": "integer", "lower": 0, "upper": 1000},
                        "makespan": {"index": [], "domain": "integer", "lower": 0, "upper": 1000},
                        "task": {**op, "domain": "interval", "start": "begin", "end": "finish", "size": "minutes"}},
          "constraints": [
              {"id": "c_machine", "forall": [{"index": "m", "set": "machine"}], "severity": "hard",
               "no_overlap": {"interval": {"var": "task", "index": ["o"]},
                              "over": [{"index": "o", "set": "op", "via": {"rel": "on", "to": "m"}}]}},
              {"id": "c_order", "forall": [{"index": "a", "set": "op"}, {"index": "b", "set": "op", "via": {"rel": "then", "from": "a"}}],
               "left": {"var": "finish", "index": ["a"]}, "relation": "<=", "right": {"var": "begin", "index": ["b"]}, "severity": "hard"},
              {"id": "c_span", "forall": [{"index": "o", "set": "op"}], "left": {"var": "finish", "index": ["o"]},
               "relation": "<=", "right": {"var": "makespan", "index": []}, "severity": "hard"}],
          "objective": {"sense": "minimize", "terms": [{"id": "o", "weight": 1, "expression": {"var": "makespan", "index": []}}]}}
    spec = {"domain_name": "Workshop js test", "problem_name": "Earliest finish", "seed": expanded, "ir": ir}
    built = client.post("/api/v1/problems/from-spec", json=spec, headers=tenants["b"])
    assert built.status_code == 200, built.text
    run = client.post(f"/api/v1/scenarios/{built.json()['scenario_id']}/runs", json={}, headers=tenants["b"]).json()
    for _ in range(5):
        if work_once(db) is None:
            break
    got = client.get(f"/api/v1/runs/{run['id']}", headers=tenants["b"]).json()
    assert got["status"] == "optimal" and got["objective"] == 231
    # The reply then said the drill had no idle time: each machine's busy time and gaps are now given exactly.
    text = client.get(f"/api/v1/agent/result/{run['id']}", headers=tenants["b"]).json()["text"]
    assert "RESOURCES (c_machine" in text and "the answer ends at 231" in text
    lines = {ln.split(":")[0][2:]: ln for ln in text.splitlines() if ln.startswith("- ") and " tasks, busy " in ln}
    assert set(lines) == {"Lathe", "Mill", "Drill", "Grinder"}
    busy = {"Lathe": 178, "Mill": 123, "Drill": 130, "Grinder": 133}
    for m, minutes in busy.items():
        assert f"5 tasks, busy {minutes} " in lines[m], lines[m]


def test_relationships_in_order_through_the_build_api_and_wrapping():
    from app.seed import order_links

    seed = {"entities": [{"type": "day", "key": d, "attrs": {"n": n}} for n, d in enumerate(["Sun", "Mon", "Tue"])],
            "relationships_in_order": [{"type": "next_day", "of": "day", "by": "n", "wrap": True}]}
    out = order_links(seed)
    assert [(r["from"][1], r["to"][1]) for r in out["relationships"]] == [("Sun", "Mon"), ("Mon", "Tue"), ("Tue", "Sun")]
    assert "relationships_in_order" not in out


def test_an_unloaded_link_between_records_of_one_kind_points_to_relationships_in_order():
    """Job-shop retest: "then" (op -> op) declared but never loaded; the message only named files."""
    spec = {"seed": {"relationship_types": [{"name": "then", "from": "op", "to": "op"}]},
            "ir": {"relationships": ["then"], "constraints": []}}
    said = " ".join(core._platform_order_faults(spec, None, [], set(), 0))
    assert '"relationships_in_order": [{"type": "then", "of": "op"' in said


CUSTOMERS_CSV = """place,x_km,y_km,demand_crates
Depot,0,0,0
Heliopolis,-20,10,2
Nasr City,5,-11,2
Maadi,-12,-13,6
Zamalek,-6,-12,3
Dokki,-18,-17,3
Shubra,-6,14,5
Giza,13,6,3
Mokattam,17,-15,2
"""


def test_routing_from_coordinate_columns_solves_to_the_exact_reference(tenants, db):
    """Evaluation: a routing model from x/y columns needed run_python for its distances. Reference (Held-Karp
    over every split): 154.965 km with 2 of the 3 trucks."""
    from app.worker import work_once

    client = TestClient(app)
    places = client.post("/api/v1/agent/files", files={"file": ("customers.csv", CUSTOMERS_CSV, "text/csv")},
                         headers=tenants["b"]).json()
    seed = {"entity_types": [{"name": "place", "attributes": [{"name": "x_km", "data_type": "number"},
                                                              {"name": "y_km", "data_type": "number"},
                                                              {"name": "demand_crates", "data_type": "number"}]},
                             {"name": "truck", "attributes": [{"name": "capacity", "data_type": "number"}]}],
            "entities": [{"type": "truck", "key": f"truck{k}", "attrs": {"capacity": 15}} for k in (1, 2, 3)],
            "entities_from_file": [{"file": "customers.csv", "type": "place", "key": "place",
                                    "attrs": {"x_km": "x_km", "y_km": "y_km", "demand_crates": "demand_crates"}}],
            "distances_from_fields": [{"name": "distance", "of": "place", "x": "x_km", "y": "y_km"}]}
    expanded = agent_files.expand(seed, [places])
    assert sum(1 for c in expanded["parameter_values"] if c["parameter"] == "distance") == 81
    visit = {"var": "visit", "index": ["v", "i", "j"]}
    ir = {"version": 2, "sets": ["truck", "place"], "parameters": {"distance": {"index": ["place", "place"]}},
          "variables": {"visit": {"index": ["truck", "place", "place"], "domain": "binary"}},
          "constraints": [{"id": "c_routes", "severity": "hard", "route": {
              "visit": visit, "vehicles": {"index": "v", "set": "truck"}, "stops": {"index": "i", "set": "place"},
              "depot": "Depot", "demand": "demand_crates", "capacity": "capacity"}}],
          "objective": {"sense": "minimize", "terms": [{"id": "o_km", "weight": 1, "expression": {
              "sum": {"mul": [{"par": "distance", "index": ["i", "j"]}, visit]},
              "over": [{"index": "v", "set": "truck"}, {"index": "i", "set": "place"}, {"index": "j", "set": "place"}]}}]}}
    built = client.post("/api/v1/problems/from-spec", json={"domain_name": "Routes test", "problem_name": "Deliveries",
                                                             "seed": expanded, "ir": ir}, headers=tenants["b"])
    assert built.status_code == 200, built.text
    run = client.post(f"/api/v1/scenarios/{built.json()['scenario_id']}/runs", json={"time_limit_s": 60},
                      headers=tenants["b"]).json()
    for _ in range(5):
        if work_once(db) is None:
            break
    got = client.get(f"/api/v1/runs/{run['id']}", headers=tenants["b"]).json()
    assert got["status"] == "optimal" and abs(float(got["objective"]) - 154.965) < 0.01, got["objective"]


def test_two_indices_from_one_column_are_refused_and_point_to_distances_from_fields():
    """Evaluation routing test: distance[place, place] read ["place","place"] twice -- 9 of 81 cells, the rest 999,999."""
    sheet = agent_files.parse("customers.csv", CUSTOMERS_CSV.encode())
    seed = {"parameter_values_from_file": [{"file": "customers.csv", "parameter": "distance",
                                            "entities": [["place", "place"], ["place", "place"]], "value": 1}]}
    try:
        agent_files.expand(seed, [sheet])
    except agent_files.FileRefused as e:
        assert "same column" in str(e) and '"distances_from_fields"' in str(e)
    else:
        raise AssertionError("not refused")


def test_a_go_ahead_in_the_first_message_lets_the_plan_through_without_a_question():
    """Evaluation routing test: "you decide the rest and go ahead" -- the plan was refused for no discussion, and
    the go-ahead guard forbade asking: a deadlock."""
    agent = core.Agent(core.Settings(), agent_api._index, lambda *a, **k: {"ok": True, "body": {}},
                       core.Context("x", mode="model"))
    agent.messages = [{"role": "user", "content": "Plan the routes. Nothing else, you decide the rest and go ahead."}]
    assert "not discussed" not in agent._check_plan({"summary": "x", "spec": {}})
    agent.messages = [{"role": "user", "content": "Plan the routes."}]
    assert "not discussed" in agent._check_plan({"summary": "x", "spec": {}})


def test_read_result_gives_each_route_as_a_sequence_with_its_load_and_km():
    """Evaluation routing test: the model computed each truck's km itself (103.60 for 103.65)."""
    from app.agent import result as agent_result

    arcs = [["truck1", "Depot", "Maadi"], ["truck1", "Maadi", "Dokki"], ["truck1", "Dokki", "Depot"],
            ["truck2", "Depot", "Giza"], ["truck2", "Giza", "Depot"]]
    km = {("truck1", "Depot", "Maadi"): 17.69, ("truck1", "Maadi", "Dokki"): 7.21, ("truck1", "Dokki", "Depot"): 24.76,
          ("truck2", "Depot", "Giza"): 14.32, ("truck2", "Giza", "Depot"): 14.32}
    rec = {"id": 78, "status": "optimal", "objective": 78.3, "amounts": None, "assignments": {"visit": arcs},
           "params": {"objective_breakdown": {"terms": [{"id": "o_km", "value": 78.3, "cell_count": 5, "cells": [
               {"var": "visit", "index": list(k), "value": v} for k, v in km.items()]}]}},
           "ir": {"sets": ["truck", "place"], "variables": {"visit": {"index": ["truck", "place", "place"], "domain": "binary"}},
                  "constraints": [{"id": "c_route", "severity": "hard", "route": {
                      "visit": {"var": "visit", "index": ["v", "i", "j"]}, "vehicles": {"index": "v", "set": "truck"},
                      "stops": {"index": "i", "set": "place"}, "depot": "Depot", "demand": "crates", "capacity": "capacity"}}],
                  "objective": {"sense": "minimize", "terms": []}},
           "data": {"sets": {"truck": [{"id": f"truck{k}", "capacity": 15} for k in (1, 2, 3)],
                             "place": [{"id": "Depot", "crates": 0}, {"id": "Maadi", "crates": 6}, {"id": "Dokki", "crates": 3},
                                       {"id": "Giza", "crates": 3}]}}}
    text = agent_result.summary(rec)
    assert "- truck1: Depot -> Maadi -> Dokki -> Depot (2 stops); load 9 of 15 (room left 6); goal part 49.66" in text
    assert "- truck3: not used" in text and "goal (minimize) = 78.30" in text


def test_the_read_back_says_route_and_scheduling_rules_in_words():
    """Evaluation routing test: "rule c_route: null None null" in the plan the person approves."""
    from app.agent import readback

    spec = {"seed": {}, "ir": {"constraints": [
        {"id": "c_route", "severity": "hard", "route": {
            "visit": {"var": "visit", "index": ["v", "i", "j"]}, "vehicles": {"index": "v", "set": "truck"},
            "stops": {"index": "i", "set": "place"}, "depot": "Depot", "demand": "crates", "capacity": "capacity"}},
        {"id": "c_machine", "severity": "hard", "forall": [{"index": "m", "set": "machine"}],
         "no_overlap": {"interval": {"var": "task", "index": ["o"]},
                        "over": [{"index": "o", "set": "op", "via": {"rel": "on", "to": "m"}}]}}]}}
    text = readback.readback(spec)
    assert "rule c_route: routes of truck from and back to 'Depot'; every other place visited exactly once" in text
    assert "each truck's load of place.crates <= its capacity" in text
    assert "rule c_machine: for every m ∈ machine: task[o] for o ∈ op" in text and "never overlap" in text
    assert "null None null" not in text


def test_an_order_link_on_a_field_that_was_not_loaded_says_which_field_and_how():
    """Job-shop retest: "within": "job" with job only the label -- "then has NO links" three times, then it gave up."""
    sheet = agent_files.parse("operations.csv", OPERATIONS_CSV.encode())
    seed = {"entities_from_file": [{"file": "operations.csv", "type": "operation", "key": ["job", "step"], "label": "job",
                                    "attrs": {"duration": "minutes", "step": "step"}}],
            "relationships_in_order": [{"type": "then", "of": "operation", "by": "step", "within": "job"}]}
    try:
        agent_files.expand(seed, [sheet])
    except agent_files.FileRefused as e:
        assert 'the operation records have no field "job" (their fields: duration, step)' in str(e)
        assert "a label is not a field" in str(e)
    else:
        raise AssertionError("not refused")


def test_a_record_named_by_a_list_of_key_parts_is_the_joined_key():
    """Job-shop retest: links typed as ["operation", ["Gear", 1]] -> "no record"."""
    spec = {"seed": {"relationships": [{"type": "then", "from": ["operation", ["Gear", 1]], "to": ["operation", ["Gear", 2.0]]}],
                     "parameter_values": [{"parameter": "minutes", "entities": [["operation", ["Gear", 1]]], "value": 25}]}}
    notes = repair.joined_keys(spec)
    assert spec["seed"]["relationships"][0]["from"] == ["operation", "Gear-1"]
    assert spec["seed"]["relationships"][0]["to"] == ["operation", "Gear-2"]
    assert spec["seed"]["parameter_values"][0]["entities"] == [["operation", "Gear-1"]]
    assert notes and "joined" in notes[0]


def test_a_decision_without_an_index_is_one_number():
    spec = {"ir": {"variables": {"makespan": {"domain": "integer", "lower": 0}}, "constraints": []}, "seed": {}}
    notes = repair.repair(spec)
    assert spec["ir"]["variables"]["makespan"]["index"] == [] and any("makespan" in n for n in notes)


MONTHS_CSV = """month,demand_units,capacity_units,cost_per_unit_egp
Jan,420,500,90
Feb,610,500,90
Mar,380,550,95
Apr,700,550,95
May,820,600,100
Jun,450,650,100
"""


def test_stock_over_periods_with_backorders_solves_to_the_reference(tenants, db):
    """Production-plan field test (October 2026): months named Jan..Jun, start stock 80, holding 6, lateness 25 a
    month, all delivered by June. The pattern in the prompt -- one balance rule through the "next" link, owed
    subtracted on both sides, the starting stock as a parameter given only for the first month -- builds from the
    file and solves to the reference (scipy linprog: 321,250 EGP, 150 units late in May)."""
    from app.worker import work_once

    client = TestClient(app)
    f = client.post("/api/v1/agent/files", files={"file": ("months.csv", MONTHS_CSV, "text/csv")},
                    headers=tenants["b"]).json()
    seed = {"entity_types": [{"name": "month", "attributes": [
                {"name": "name", "data_type": "text"}, {"name": "demand", "data_type": "number"},
                {"name": "capacity", "data_type": "number"}, {"name": "cost", "data_type": "number"}]}],
            "relationship_types": [{"name": "next", "from": "month", "to": "month"}],
            "entities_from_file": [{"file": "months.csv", "type": "month", "key": "month", "attrs": {
                "name": "month", "demand": "demand_units", "capacity": "capacity_units", "cost": "cost_per_unit_egp"}}],
            "relationships_in_order": [{"type": "next", "of": "month", "by": "#row"}],
            "parameters": [{"name": "opening", "index": ["month"], "default_value": 0},
                           {"name": "hold", "index": [], "default_value": 6},
                           {"name": "late", "index": [], "default_value": 25}],
            "parameter_values": [{"parameter": "opening", "entities": [["month", "Jan"]], "value": 80}]}
    expanded = agent_files.expand(seed, [f])
    assert [(r["from"][1], r["to"][1]) for r in expanded["relationships"]] == [
        ("Jan", "Feb"), ("Feb", "Mar"), ("Mar", "Apr"), ("Apr", "May"), ("May", "Jun")]
    p, q = {"index": "p", "set": "month"}, {"index": "q", "set": "month", "via": {"rel": "next", "to": "p"}}

    def v(name, i="p"):
        return {"var": name, "index": [i]}

    def total(expr):
        return {"sum": expr, "over": [p]}

    def minus(a, b):
        return {"add": [a, {"mul": [{"const": -1}, b]}]}

    ir = {"version": 2, "sets": ["month"], "relationships": ["next"],
          "parameters": {"opening": {"index": ["month"]}, "hold": {"index": []}, "late": {"index": []}},
          "variables": {n: {"index": ["month"], "domain": "continuous", "lower": 0} for n in ("make", "stock", "owed")},
          "constraints": [
              {"id": "c_cap", "forall": [p], "left": v("make"), "relation": "<=",
               "right": {"attr": {"of": "p", "name": "capacity"}}, "severity": "hard"},
              {"id": "c_balance", "forall": [p], "severity": "hard", "relation": "=",
               "left": {"add": [{"sum": minus(v("stock", "q"), v("owed", "q")), "over": [q]},
                                {"par": "opening", "index": ["p"]}, v("make")]},
               "right": {"add": [{"attr": {"of": "p", "name": "demand"}}, minus(v("stock"), v("owed"))]}},
              {"id": "c_all_by_june", "forall": [{**p, "where": [{"attr": "name", "op": "=", "value": "Jun"}]}],
               "left": v("owed"), "relation": "=", "right": {"const": 0}, "severity": "hard"}],
          "objective": {"sense": "minimize", "terms": [{"id": "o_cost", "weight": 1, "expression": {"add": [
              total({"mul": [{"attr": {"of": "p", "name": "cost"}}, v("make")]}),
              total({"mul": [{"par": "hold", "index": []}, v("stock")]}),
              total({"mul": [{"par": "late", "index": []}, v("owed")]})]}}]}}
    built = client.post("/api/v1/problems/from-spec", json={"domain_name": "Plan H1 test", "problem_name": "H1",
                                                            "seed": expanded, "ir": ir}, headers=tenants["b"])
    assert built.status_code == 200, built.text
    run = client.post(f"/api/v1/scenarios/{built.json()['scenario_id']}/runs", json={}, headers=tenants["b"]).json()
    for _ in range(5):
        if work_once(db) is None:
            break
    got = client.get(f"/api/v1/runs/{run['id']}", headers=tenants["b"]).json()
    assert got["status"] == "optimal" and abs(float(got["objective"]) - 321250) < 1e-3, got
    # One cost of three parts: each part exact (the reply split it as 4,650 + 2,100 for 3,000 + 3,750), and no
    # product the model never makes (demand x stock).
    text = client.get(f"/api/v1/agent/result/{run['id']}", headers=tenants["b"]).json()["text"]
    assert "o_cost by decision (exact" in text and "make 314,500" in text and "owed 3,750" in text \
        and "stock 3,000" in text, text
    assert "field x stock" not in text and "field x make" in text
    cap = next(ln for ln in text.splitlines() if ln.startswith("- c_cap (hard)"))
    assert "tight (no room left on 5 of 6: " in cap and "room left on the others: Jun 50" in cap, cap


def test_subtraction_written_as_sub_is_repaired():
    from app.agent.repair import repair

    spec = {"ir": {"constraints": [{"id": "c", "left": {"sub": [{"var": "a", "index": []}, {"var": "b", "index": []}]},
                                    "relation": "=", "right": {"neg": {"var": "c", "index": []}}},
                                   {"id": "d", "left": {"add": [2, {"var": "a", "index": []}]}, "relation": "<=", "right": 5}]}}
    notes = repair(spec)
    c = spec["ir"]["constraints"][0]
    assert c["left"] == {"add": [{"var": "a", "index": []}, {"mul": [{"const": -1}, {"var": "b", "index": []}]}]}
    assert c["right"] == {"mul": [{"const": -1}, {"var": "c", "index": []}]}
    assert any('"sub"' in n for n in notes)
    d = spec["ir"]["constraints"][1]
    assert d["right"] == {"const": 5} and d["left"]["add"][0] == {"const": 2}


ORDERS_CSV = "width_cm,pieces\n45,97\n36,610\n31,395\n14,211\n"


def test_cutting_stock_from_patterns_that_fit_solves_to_the_reference(tenants, db):
    """Paper-cutting field test (October 2026): rolls of 100 cm, four ordered widths. The patterns come from
    `patterns_that_fit` (37 ways to cut a roll); the model decides how often to use each. Reference (scipy milp over
    the same enumeration, independently written): 453 rolls (LP bound 452.25)."""
    from app.worker import work_once

    client = TestClient(app)
    f = client.post("/api/v1/agent/files", files={"file": ("orders.csv", ORDERS_CSV, "text/csv")},
                    headers=tenants["b"]).json()
    seed = {"entity_types": [{"name": "width", "attributes": [{"name": "cm", "data_type": "number"},
                                                              {"name": "pieces", "data_type": "integer"}]}],
            "entities_from_file": [{"file": "orders.csv", "type": "width", "key": "width_cm",
                                    "attrs": {"cm": "width_cm", "pieces": "pieces"}}],
            "patterns_that_fit": [{"type": "pattern", "of": "width", "size": "cm", "capacity": 100, "count": "cuts"}]}
    expanded = agent_files.expand(seed, [f])
    assert sum(e["type"] == "pattern" for e in expanded["entities"]) == 37
    w, p = {"index": "w", "set": "width"}, {"index": "p", "set": "pattern"}
    ir = {"version": 2, "sets": ["width", "pattern"], "parameters": {"cuts": {"index": ["pattern", "width"]}},
          "variables": {"uses": {"index": ["pattern"], "domain": "integer", "lower": 0, "upper": 1000}},
          "constraints": [{"id": "c_orders", "forall": [w], "severity": "hard", "relation": ">=",
                           "left": {"sum": {"mul": [{"par": "cuts", "index": ["p", "w"]}, {"var": "uses", "index": ["p"]}]},
                                    "over": [p]},
                           "right": {"attr": {"of": "w", "name": "pieces"}}}],
          "objective": {"sense": "minimize", "terms": [{"id": "o_rolls", "weight": 1, "expression": {
              "sum": {"var": "uses", "index": ["p"]}, "over": [p]}}]}}
    built = client.post("/api/v1/problems/from-spec", json={"domain_name": "Paper test", "problem_name": "Rolls",
                                                            "seed": expanded, "ir": ir}, headers=tenants["b"])
    assert built.status_code == 200, built.text
    run = client.post(f"/api/v1/scenarios/{built.json()['scenario_id']}/runs", json={"time_limit_s": 60},
                      headers=tenants["b"]).json()
    for _ in range(5):
        if work_once(db) is None:
            break
    got = client.get(f"/api/v1/runs/{run['id']}", headers=tenants["b"]).json()
    assert got["status"] == "optimal" and got["objective"] == 453, got
    # Live test: "all demand rules tight, no surplus" -- the room per width is read from the model itself.
    text = client.get(f"/api/v1/agent/result/{run['id']}", headers=tenants["b"]).json()["text"]
    line = next(ln for ln in text.splitlines() if ln.startswith("- c_orders (hard)"))
    import re as _re

    rooms = dict(_re.findall(r"(\d+) (\d+(?:\.\d+)?)(?=,|$)", line.split("room left on the others: ")[1]))
    assert "tight (no room left on " in line and "36" in line.split("others")[0] and rooms.get("14"), line
    assert all(float(v) > 0 for v in rooms.values()) and "-" not in line[2:], line
    # The same through the build API itself, unexpanded, and a wrong size field said in words.
    direct = {"domain_name": "Paper test 2", "problem_name": "Rolls", "dry_run": True, "ir": ir, "seed": {
        **{k: v for k, v in seed.items() if k != "entities_from_file"},
        "entities": [e for e in expanded["entities"] if e["type"] == "width"]}}
    assert client.post("/api/v1/problems/from-spec", json=direct, headers=tenants["b"]).status_code == 200
    direct["seed"]["patterns_that_fit"] = [{"type": "pattern", "of": "width", "size": "width", "capacity": 100,
                                            "count": "cuts"}]
    bad = client.post("/api/v1/problems/from-spec", json=direct, headers=tenants["b"])
    assert bad.status_code == 422 and 'no number field "width"' in bad.json()["detail"][0]["msg"], bad.text


def test_a_null_bound_is_left_out():
    from app.agent.repair import repair

    spec = {"ir": {"variables": {"uses": {"index": ["p"], "domain": "integer", "lower": 0, "upper": None}}}}
    notes = repair(spec)
    assert spec["ir"]["variables"]["uses"] == {"index": ["p"], "domain": "integer", "lower": 0}
    assert any('"upper": null' in n for n in notes)


PROJECTS_CSV = """project,cost_kegp,benefit_points,co2_tonnes
Solar farm,239,52,45
Bus depot,283,108,83
Ring road,215,23,59
Water plant,278,51,83
Clinic,93,40,14
School wing,175,80,31
Bridge repair,177,89,13
Park,226,51,1
Fibre link,267,47,52
Market hall,151,43,49
Flood wall,120,117,9
Bike lanes,115,99,79
"""
#: The exact front (benefit, co2) by enumerating all 4,096 portfolios within 1,000 kEGP.
COUNCIL_FRONT = {(0, 0), (51, 1), (117, 9), (168, 10), (206, 22), (257, 23), (297, 37), (337, 54), (377, 68),
                 (389, 99), (396, 116), (420, 117), (436, 133), (445, 137), (476, 147), (479, 182), (493, 215),
                 (533, 229)}


def test_a_trade_off_front_is_read_back_point_by_point(tenants, db):
    """Council field test (October 2026): "show us the trade-off between benefit and CO2". A front run's points are
    each on the exact front, and read_result lists them with the projects each one funds."""
    from app.worker import work_once

    client = TestClient(app)
    f = client.post("/api/v1/agent/files", files={"file": ("projects.csv", PROJECTS_CSV, "text/csv")},
                    headers=tenants["b"]).json()
    seed = {"entity_types": [{"name": "project", "attributes": [{"name": n, "data_type": "number"}
                                                                for n in ("cost", "benefit", "co2")]}],
            "entities_from_file": [{"file": "projects.csv", "type": "project", "key": "project",
                                    "attrs": {"cost": "cost_kegp", "benefit": "benefit_points", "co2": "co2_tonnes"}}]}
    expanded = agent_files.expand(seed, [f])
    p = {"index": "p", "set": "project"}

    def total(field):
        return {"sum": {"mul": [{"attr": {"of": "p", "name": field}}, {"var": "fund", "index": ["p"]}]}, "over": [p]}

    ir = {"version": 2, "sets": ["project"], "parameters": {},
          "variables": {"fund": {"index": ["project"], "domain": "binary"}},
          "constraints": [{"id": "c_budget", "left": total("cost"), "relation": "<=", "right": {"const": 1000},
                           "severity": "hard"}],
          "objective": {"sense": "maximize", "terms": [{"id": "o_benefit", "weight": 1, "expression": total("benefit")},
                                                       {"id": "o_co2", "weight": -1, "expression": total("co2")}]}}
    built = client.post("/api/v1/problems/from-spec", json={"domain_name": "Council test", "problem_name": "Front",
                                                            "seed": expanded, "ir": ir}, headers=tenants["b"])
    assert built.status_code == 200, built.text
    run = client.post(f"/api/v1/scenarios/{built.json()['scenario_id']}/runs", json={"pareto_steps": 10},
                      headers=tenants["b"]).json()
    for _ in range(30):
        if work_once(db) is None:
            break
    got = client.get(f"/api/v1/runs/{run['id']}", headers=tenants["b"]).json()
    assert got["pareto"], got
    text = client.get(f"/api/v1/agent/result/{run['id']}", headers=tenants["b"]).json()["text"]
    assert "TRADE-OFF FRONT (" in text, text
    lines = [ln for ln in text.splitlines() if ln.startswith("- point ")]
    assert len(lines) == len(got["pareto"]) >= 5
    for pt in got["pareto"]:
        assert (round(abs(pt["first"])), round(abs(pt["second"]))) in COUNCIL_FRONT, pt
    assert "chooses fund: " in lines[-1] or "chooses fund: " in lines[0]
    top = next(ln for ln in lines if "o_benefit 533" in ln)
    assert "totals of the chosen: " in top and all(x in top for x in ("cost 963", "benefit 533", "co2 229")), top
    print("\n".join(lines))


def test_bakery_planned_for_its_futures_lands_near_the_newsvendor_answer(tenants, db):
    """Bakery field test (October 2026): bake before demand is known; demand 100-300 evenly; cost 3, price 8,
    leftovers 1. The exact answer (newsvendor critical ratio 5/7) is 242.9 loaves and 857.1 EGP a day on average.
    Planned over sampled futures, the platform's plan lands near it; on the middle value alone it would be 200."""
    from app.worker import work_once

    client = TestClient(app)
    one = {"index": []}
    ir = {"version": 2, "sets": [], "parameters": {"demand": {"index": [], "uncertainty": {"kind": "interval",
                                                                                           "deviation": 0.5}}},
          "variables": {"bake": {**one, "domain": "continuous", "lower": 0, "upper": 400, "stage": 1},
                        "sell": {**one, "domain": "continuous", "lower": 0, "upper": 400, "stage": 2}},
          "constraints": [{"id": "c_baked", "left": {"var": "sell", "index": []}, "relation": "<=",
                           "right": {"var": "bake", "index": []}, "severity": "hard"},
                          {"id": "c_demand", "left": {"var": "sell", "index": []}, "relation": "<=",
                           "right": {"par": "demand", "index": []}, "severity": "hard"}],
          "objective": {"sense": "maximize", "terms": [
              {"id": "o_sales", "weight": 7, "expression": {"var": "sell", "index": []}},
              {"id": "o_baking", "weight": -2, "expression": {"var": "bake", "index": []}}]}}
    built = client.post("/api/v1/problems/from-spec", json={
        "domain_name": f"Bakery {uuid.uuid4().hex[:6]}", "problem_name": "Loaves", "ir": ir,
        "seed": {"parameters": [{"name": "demand", "index": [], "default_value": 200}]}}, headers=tenants["b"])
    assert built.status_code == 200, built.text
    run = client.post(f"/api/v1/scenarios/{built.json()['scenario_id']}/runs", json={"futures": 200},
                      headers=tenants["b"]).json()
    for _ in range(5):
        if work_once(db) is None:
            break
    got = client.get(f"/api/v1/runs/{run['id']}", headers=tenants["b"]).json()
    bake = next(a["value"] for a in got["amounts"]["bake"])
    assert 225 <= float(bake) <= 262, bake
    assert 800 <= float(got["objective"]) <= 915, got["objective"]
    text = client.get(f"/api/v1/agent/result/{run['id']}", headers=tenants["b"]).json()["text"]
    assert "UNCERTAINTY PLANNED FOR: 50 sampled futures" in text and "fresh futures it averages" in text, text
    assert "DECISION sell" not in text and "o_sales = 0" not in text and "DECISION bake" in text, text


def test_futures_asked_for_a_model_with_no_later_decision_say_they_were_not_planned_for(tenants, db):
    """Bakery test: no decision marked stage 2, so the 50-futures what-if was the plain run again (bake 200,
    profit 1,000), and the reply called it the average. The run and read_result now say it was not planned for."""
    from app.worker import work_once

    client = TestClient(app)
    ir = {"version": 2, "sets": [], "parameters": {"demand": {"index": [], "uncertainty": {"kind": "interval",
                                                                                           "deviation": 0.5}}},
          "variables": {"bake": {"index": [], "domain": "continuous", "lower": 0, "upper": 400},
                        "sell": {"index": [], "domain": "continuous", "lower": 0, "upper": 400}},
          "constraints": [{"id": "c_baked", "left": {"var": "sell", "index": []}, "relation": "<=",
                           "right": {"var": "bake", "index": []}, "severity": "hard"},
                          {"id": "c_demand", "left": {"var": "sell", "index": []}, "relation": "<=",
                           "right": {"par": "demand", "index": []}, "severity": "hard"}],
          "objective": {"sense": "maximize", "terms": [
              {"id": "o_sales", "weight": 7, "expression": {"var": "sell", "index": []}},
              {"id": "o_baking", "weight": -2, "expression": {"var": "bake", "index": []}}]}}
    built = client.post("/api/v1/problems/from-spec", json={
        "domain_name": f"Bakery flat {uuid.uuid4().hex[:6]}", "problem_name": "Loaves", "ir": ir,
        "seed": {"parameters": [{"name": "demand", "index": [], "default_value": 200}]}}, headers=tenants["b"])
    run = client.post(f"/api/v1/scenarios/{built.json()['scenario_id']}/runs", json={"futures": 50},
                      headers=tenants["b"]).json()
    for _ in range(5):
        if work_once(db) is None:
            break
    text = client.get(f"/api/v1/agent/result/{run['id']}", headers=tenants["b"]).json()["text"]
    assert "UNCERTAINTY NOT SOLVED: 50 futures were asked for, but no decision waits for the data" in text, text
    assert "NOT an average over futures" in text


def test_seed_data_written_inside_the_ir_is_moved_to_the_seed():
    from app.agent.repair import misplaced

    spec = {"seed": {}, "ir": {"sets": ["pattern"], "patterns_that_fit": [{"type": "pattern", "of": "width",
                                                                          "size": "cm", "capacity": 100, "count": "cuts"}]}}
    notes = misplaced(spec)
    assert "patterns_that_fit" not in spec["ir"] and spec["seed"]["patterns_that_fit"][0]["capacity"] == 100
    assert any("inside ir" in n for n in notes)


def test_room_per_record_reads_a_limit_held_in_a_parameter(tenants, db):
    """Live production test: capacity[m] as a parameter gave "-600 room left" for every month."""
    from app.worker import work_once

    client = TestClient(app)
    m = {"index": "m", "set": "month"}
    seed = {"entity_types": [{"name": "month"}],
            "entities": [{"type": "month", "key": k} for k in ("Jan", "Feb", "Mar")],
            "parameters": [{"name": "cap", "index": ["month"], "default_value": 0}],
            "parameter_values": [{"parameter": "cap", "entities": [["month", k]], "value": v}
                                 for k, v in (("Jan", 500), ("Feb", 500), ("Mar", 650))]}
    ir = {"version": 2, "sets": ["month"], "parameters": {"cap": {"index": ["month"]}},
          "variables": {"make": {"index": ["month"], "domain": "continuous", "lower": 0, "upper": 600}},
          "constraints": [{"id": "c_cap", "forall": [m], "left": {"var": "make", "index": ["m"]}, "relation": "<=",
                           "right": {"par": "cap", "index": ["m"]}, "severity": "hard"}],
          "objective": {"sense": "maximize", "terms": [{"id": "o", "weight": 1, "expression": {
              "sum": {"var": "make", "index": ["m"]}, "over": [m]}}]}}
    built = client.post("/api/v1/problems/from-spec", json={"domain_name": f"Cap {uuid.uuid4().hex[:6]}",
                                                            "problem_name": "Cap", "seed": seed, "ir": ir},
                        headers=tenants["b"])
    assert built.status_code == 200, built.text
    run = client.post(f"/api/v1/scenarios/{built.json()['scenario_id']}/runs", json={}, headers=tenants["b"]).json()
    for _ in range(5):
        if work_once(db) is None:
            break
    text = client.get(f"/api/v1/agent/result/{run['id']}", headers=tenants["b"]).json()["text"]
    line = next(ln for ln in text.splitlines() if ln.startswith("- c_cap (hard)"))
    assert "no room left on 2 of 3" in line and "Mar 50" in line and "-" not in line[2:], line


def test_an_interval_part_written_as_a_term_is_reduced_to_its_name():
    from app.agent.repair import repair

    spec = {"ir": {"sets": ["op"], "variables": {"task": {"index": ["op"], "domain": "interval",
                                                          "start": {"var": "begin", "index": ["op"]}, "end": "finish",
                                                          "size": {"par": "duration", "index": ["op"]}}}}}
    repair(spec)
    task = spec["ir"]["variables"]["task"]
    assert task["start"] == "begin" and task["size"] == "duration" and task["end"] == "finish"


def test_a_one_number_decision_read_with_an_index_is_read_with_none():
    from app.agent.repair import repair

    spec = {"ir": {"sets": ["op"], "variables": {"makespan": {"index": [], "domain": "integer"},
                                                "finish": {"index": ["op"], "domain": "integer"}},
                   "constraints": [{"id": "c", "forall": [{"index": "o", "set": "op"}], "relation": "<=",
                                    "left": {"var": "finish", "index": ["o"]},
                                    "right": {"var": "makespan", "index": ["o"]}, "severity": "hard"}]}}
    notes = repair(spec)
    c = spec["ir"]["constraints"][0]
    assert c["right"]["index"] == [] and c["left"]["index"] == ["o"] and any("makespan" in n for n in notes)


def test_repeated_labels_read_back_as_keys():
    from app.agent.readback import readback

    text = readback({"seed": {"entities": [{"type": "op", "key": f"Gear-{i}", "label": "Gear"} for i in (1, 2)]},
                     "ir": {}})
    assert "records op: 2: Gear-1, Gear-2" in text


JOB_RESULT = """RUN 102: optimal; goal (minimize) = 231; solver cp-sat.
RULES:
- c_cap (hard): held, tight (no room left on 5 of 6: Jan, Feb, Mar, Apr, May); least room left on any one record 0; room left on the others: Jun 50

DECISION begin[operation]: 18 of 20 cells non-zero.
operation | operation.job | operation.step | operation.machine_name | operation.duration_min | value
Flange-1 (Flange) | Flange | 1 | Lathe | 45 | 68
Gear-2 (Gear) | Gear | 2 | Grinder | 41 | 68
Bracket-3 (Bracket) | Bracket | 3 | Lathe | 22 | 156
Bracket-1 (Bracket) | Bracket | 1 | Mill | 22 | 0

DECISION finish[operation]: 20 of 20 cells non-zero.
operation | operation.job | operation.step | operation.machine_name | operation.duration_min | value
Flange-1 (Flange) | Flange | 1 | Lathe | 45 | 113
"""


def test_a_reply_the_results_contradict_is_caught():
    """Live tests (October 2026): "capacity is fully used every month" with June 50 spare; a schedule row giving
    Flange step 1 the Grinder although the results put it on the Lathe."""
    bad = ("Capacity is fully used every month.\n\nPart\tStep\tMachine\tStart\tFinish\tDuration\n"
           "Flange\t1\tGrinder\t68\t113\t45\nBracket\t3\tLathe\t156\t178\t22\n")
    wrong = core.reply_contradictions(bad, [JOB_RESULT])
    assert any("room left on 1 of 6: Jun 50" in w for w in wrong), wrong
    assert any("Grinder" in w and "Lathe for that record" in w for w in wrong), wrong
    assert len(wrong) == 2, wrong
    good = ("Capacity is used fully from January to May; June has 50 units spare.\n\n"
            "| Part | Step | Machine | Start | Finish |\n|---|---|---|---|---|\n| Flange | 1 | Lathe | 68 | 113 |\n"
            "| Gear | 2 | Grinder | 68 | 109 |\n| Bracket | 3 | Lathe | 156 | 178 |")
    assert core.reply_contradictions(good, [JOB_RESULT]) == []


def test_a_contradicted_reply_is_not_shown_and_is_asked_again(tenants, monkeypatch):
    from tests.test_agent import _chat

    replies = [
        ({"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {
            "name": "read_result", "arguments": json.dumps({"run_id": 1})}}]}, True),
        ({"role": "assistant", "content": "Capacity is fully used every month.", "_finish": "stop"}, True),
        ({"role": "assistant", "content": "Capacity is full from January to May; June has 50 spare.",
          "_finish": "stop"}, True),
    ]
    monkeypatch.setattr(core, "llm_chat", lambda *a, **k: replies.pop(0))
    monkeypatch.setattr(core.Agent, "run_tool", lambda self, name, args: JOB_RESULT)
    events = _chat(tenants["b"], mode="model", text="how full is the factory?")
    assert any(e["type"] == "note" and "contradict" in e["text"] for e in events), events
    assert next(e for e in events if e["type"] == "answer")["text"].startswith("Capacity is full from January")


RESOURCE_RESULT = """RUN 102: optimal; goal (minimize) = 231; solver cp-sat.

RESOURCES (c_machine; exact, from the answer -- quote these, never judge idle time yourself; the answer ends at 231):
- Grinder: 5 tasks, busy 133 from 68 to 231; idle before 68; in order: Gear-2 68-109, Shaft-4 116-126, Flange-3 145-169, Housing-3 173-193, Bracket-4 193-231
- Lathe: 5 tasks, busy 178 from 0 to 178; idle after 178; in order: Shaft-1 0-43, Gear-1 43-68, Flange-1 68-113, Housing-1 113-156, Bracket-3 156-178
"""


def test_a_task_put_on_the_wrong_resource_is_caught():
    """Live job-shop test: the machine was a link, not a field, and the reply put Flange step 1 on the Grinder."""
    bad = "| Part | Step | Machine | Start | Finish |\n|---|---|---|---|---|\n| Flange | 1 | Grinder | 68 | 113 |\n" \
          "| Gear | 2 | Grinder | 68 | 109 |"
    wrong = core.reply_contradictions(bad, [RESOURCE_RESULT])
    assert len(wrong) == 1 and "puts Flange-1 (68-113) on Grinder, but the results put it on Lathe" in wrong[0], wrong
    assert core.reply_contradictions(bad.replace("| Flange | 1 | Grinder", "| Flange | 1 | Lathe"),
                                     [RESOURCE_RESULT]) == []


def test_an_answer_from_memory_is_checked_against_the_last_results(tenants, monkeypatch):
    """Live job-shop retest: asked again, the model re-typed the schedule without reading the results, with the
    same wrong machine. With no tool in the turn, the conversation's latest run results are the basis."""
    from tests.test_agent import _chat

    first = [({"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {
                 "name": "read_result", "arguments": json.dumps({"run_id": 102})}}]}, True),
             ({"role": "assistant", "content": "Done: 231 minutes.", "_finish": "stop"}, True)]
    monkeypatch.setattr(core, "llm_chat", lambda *a, **k: first.pop(0))
    monkeypatch.setattr(core.Agent, "run_tool", lambda self, name, args: RESOURCE_RESULT)
    events = _chat(tenants["b"], mode="model", text="solve it", conversation_id="memo1", server_history=True)
    later = [({"role": "assistant", "content": "| Flange | 1 | Grinder | 68 | 113 |", "_finish": "stop"}, True),
             ({"role": "assistant", "content": "| Flange | 1 | Lathe | 68 | 113 |", "_finish": "stop"}, True)]
    monkeypatch.setattr(core, "llm_chat", lambda *a, **k: later.pop(0))
    real_call = core.Agent.__init__

    def init(self, *a, **k):
        real_call(self, *a, **k)
        inner = self.call
        self.call = lambda method, path, *r, **kw: ({"ok": True, "body": {"text": RESOURCE_RESULT}}
                                                    if path == "/api/v1/agent/result/102" else inner(method, path, *r, **kw))

    monkeypatch.setattr(core.Agent, "__init__", init)
    events = _chat(tenants["b"], mode="model", text="the table again?", conversation_id="memo1", server_history=True)
    assert any(e["type"] == "note" and "contradict" in e["text"] for e in events), events
    assert next(e for e in events if e["type"] == "answer")["text"] == "| Flange | 1 | Lathe | 68 | 113 |"


def test_check_spec_runs_a_trial_solve_and_says_it(tenants, db):
    """A plan is solved once on its real data during the check (nothing kept): its status, goal and what is used
    come back with the read-back; a plan with no answer is flagged."""
    client = TestClient(app)
    f = client.post("/api/v1/agent/files", files={"file": ("months.csv", MONTHS_CSV, "text/csv")},
                    headers=tenants["b"]).json()
    m = {"index": "m", "set": "month"}
    seed = {"entity_types": [{"name": "month", "attributes": [{"name": "name", "data_type": "text"},
                                                              {"name": "demand", "data_type": "number"},
                                                              {"name": "capacity", "data_type": "number"}]}],
            "entities_from_file": [{"file": "months.csv", "type": "month", "key": "month", "attrs": {
                "name": "month", "demand": "demand_units", "capacity": "capacity_units"}}]}
    expanded = agent_files.expand(seed, [f])
    ir = {"version": 2, "sets": ["month"], "parameters": {},
          "variables": {"make": {"index": ["month"], "domain": "continuous", "lower": 0}},
          "constraints": [{"id": "c_cap", "forall": [m], "left": {"var": "make", "index": ["m"]}, "relation": "<=",
                           "right": {"attr": {"of": "m", "name": "capacity"}}, "severity": "hard"},
                          {"id": "c_dem", "forall": [m], "left": {"var": "make", "index": ["m"]}, "relation": ">=",
                           "right": {"attr": {"of": "m", "name": "demand"}}, "severity": "hard"}],
          "objective": {"sense": "minimize", "terms": [{"id": "o", "weight": 1, "expression": {
              "sum": {"var": "make", "index": ["m"]}, "over": [m]}}]}}
    spec = {"domain_name": f"Trial {uuid.uuid4().hex[:6]}", "problem_name": "T", "seed": expanded, "ir": ir,
            "dry_run": True, "trial": True}
    got = client.post("/api/v1/problems/from-spec", json=spec, headers=tenants["b"])
    assert got.status_code == 200, got.text
    trial = got.json()["trial"]
    assert trial["status"] == "infeasible", trial  # Feb, Apr, May demand above capacity
    said = core.trial_said(trial)
    assert "NO answer on this data" in said
    ir["constraints"].pop(1)
    trial = client.post("/api/v1/problems/from-spec", json=spec, headers=tenants["b"]).json()["trial"]
    assert trial["status"] == "optimal" and core.trial_said(trial).count("every decision is 0") == 1
    assert "TRIAL on your data (solved once, nothing kept): optimal, goal 0; make used in 0 of 6 -- it chooses or " \
           "makes nothing" in core.trial_for_person(trial)
    # Nothing was kept.
    assert client.post("/api/v1/problems/from-spec", json=spec, headers=tenants["b"]).status_code == 200
