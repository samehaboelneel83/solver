"""Neutral data handling (neutrality plan, step 4): any table shape loads, and the plan card says what was stored
against what the file holds."""

from __future__ import annotations

import pytest

from app.agent import files
from app.agent.readback import readback


def _file(name, columns, rows):
    return {"name": name, "sheets": [{"name": name.rsplit(".", 1)[0], "columns": columns, "rows": rows,
                                      "total_rows": len(rows), "truncated": False}]}


def _seed(**extra):
    return {"entity_types": [{"name": "plant", "attributes": [{"name": "cap", "data_type": "number"}]},
                             {"name": "customer", "attributes": []}],
            "entities": [{"type": "customer", "key": k} for k in ("C1", "C2", "C3")],
            "parameters": [{"name": "cost", "index": ["plant", "customer"], "default_value": 0}], **extra}


def test_a_wide_table_loads_one_cell_per_row_and_customer_column():
    f = _file("cost.csv", ["plant", "C1", "C2", "C3", "note"],
              [["P1", 4, "$5", 6, "x"], ["P2", 7, None, "1,200", "y"]])
    seed = _seed(parameter_values_from_file=[{"file": "cost.csv", "parameter": "cost",
                                              "entities": [["plant", "plant"], ["customer", "*"]]}])
    report: list[str] = []
    out = files.expand(seed, [f], report)
    got = {(c["entities"][0][1], c["entities"][1][1]): c["value"] for c in out["parameter_values"]}
    assert got == {("P1", "C1"): 4, ("P1", "C2"): 5, ("P1", "C3"): 6, ("P2", "C1"): 7, ("P2", "C3"): 1200}
    assert all(c["entities"][0][0] == "plant" and c["entities"][1][0] == "customer" for c in out["parameter_values"])
    line = report[0]
    assert "columns ['note'] are not customer keys" in line and "3 columns of customer" in line
    assert "1 skipped: the value empty" in line and "1 numbers read without their unit" in line and "5 stored" in line


def test_the_wide_index_can_come_first_and_value_is_refused():
    f = _file("cost.csv", ["customer", "P1"], [["C1", 3]])
    seed = _seed(parameter_values_from_file=[{"file": "cost.csv", "parameter": "cost",
                                              "entities": [["plant", "*"], ["customer", "customer"]]}])
    seed["entities"].append({"type": "plant", "key": "P1"})
    out = files.expand(seed, [f])
    assert out["parameter_values"] == [{"parameter": "cost", "entities": [["plant", "P1"], ["customer", "C1"]], "value": 3}]
    seed["parameter_values_from_file"][0]["value"] = "P1"
    with pytest.raises(files.FileRefused, match='leave "value" out'):
        files.expand(seed, [f])


def test_units_percent_and_yes_no_where_a_number_belongs():
    assert files._numeric("$1,200") == (1200, "unit")
    assert files._numeric("12.5 kg") == (12.5, "unit")
    assert files._numeric("EGP 45") == (45, "unit")
    assert files._numeric("35%") == (0.35, "percent")
    assert files._numeric("yes") == (1, "yes/no")
    assert files._numeric("north") == ("north", None)
    assert files._numeric("2026-10-11") == ("2026-10-11", None)


def test_the_load_report_counts_the_filter_and_the_skipped_rows_and_reaches_the_card():
    f = _file("routes.csv", ["plant", "customer", "open", "cost"],
              [["P1", "C1", "yes", 4], ["P1", "C2", "no", 5], ["P2", "C1", "yes", None], [None, "C3", "yes", 9]])
    seed = _seed(parameter_values_from_file=[{"file": "routes.csv", "parameter": "cost",
                                              "entities": [["plant", "plant"], ["customer", "customer"]],
                                              "value": "cost", "where": [{"column": "open", "value": "yes"}]}])
    report: list[str] = []
    out = files.expand(seed, [f], report)
    assert len(out["parameter_values"]) == 1
    assert report == ['parameter "cost" from "routes.csv": 4 rows; 3 kept by the filter '
                      '[{"column": "open", "value": "yes"}]; 1 skipped: a key cell empty; 1 skipped: the value empty; '
                      '1 stored']
    text = readback({"seed": out, "ir": {}}, report)
    assert "- loaded " + report[0] in text


def test_records_report_repeated_keys_and_numbers_read():
    f = _file("plants.csv", ["id", "cap"], [["P1", "10 t"], ["P1", "10 t"], ["P2", "yes"]])
    seed = _seed(entities_from_file=[{"file": "plants.csv", "type": "plant", "key": "id", "attrs": {"cap": "cap"}}])
    report: list[str] = []
    out = files.expand(seed, [f], report)
    assert [e["attrs"] for e in out["entities"] if e["type"] == "plant"] == [{"cap": 10}, {"cap": 1}]
    assert report == ['records "plant" from "plants.csv": 3 rows; 1 repeated keys counted once; '
                      '2 numbers read without their unit or currency; 1 yes/no read as 1/0; 2 stored']


def test_a_complete_list_on_a_default_of_the_same_value_gets_the_opposite_default_a_partial_one_a_note():
    """11 October 2026: a list naming one customer of eight was flipped, and every other customer became
    unservable (infeasible); a list naming every record is the complete case, and is flipped."""
    seed = _seed(parameters=[{"name": "allowed", "index": ["customer", "plant"], "default_value": 1}],
                 parameter_values_from_file=[{"file": "approved.csv", "parameter": "allowed", "value": 1,
                                              "entities": [["customer", "customer"], ["plant", "plant"]]}])
    partial = _file("approved.csv", ["customer", "plant"], [["C1", "P2"]])
    report: list[str] = []
    out = files.expand(seed, [partial], report)
    assert out["parameters"][0]["default_value"] == 1
    assert "names 1 of 3 records: as loaded it changes nothing" in report[0] and "listed[r]" in report[0]
    complete = _file("approved.csv", ["customer", "plant"], [["C1", "P2"], ["C2", "P1"], ["C3", "P1"]])
    report = []
    out = files.expand(seed, [complete], report)
    assert out["parameters"][0]["default_value"] == 0 and seed["parameters"][0]["default_value"] == 1
    assert "names every record: every pair it does not name is now 0" in report[0]


def test_a_typed_list_of_ones_on_a_default_of_one_is_flipped_only_when_complete():
    from app.agent import repair

    spec = {"seed": {"entities": [{"type": "c", "key": k} for k in ("C4", "C5")],
                     "parameters": [{"name": "allowed", "index": ["c", "w"], "default_value": 1},
                                    {"name": "share", "index": ["c"], "default_value": 1}],
                     "parameter_values": [{"parameter": "allowed", "entities": [["c", "C4"], ["w", "W3"]], "value": 1},
                                          {"parameter": "share", "entities": [["c", "C4"]], "value": 0.5}]},
            "ir": {"version": 2}}
    notes = repair.repair(spec)
    assert [p["default_value"] for p in spec["seed"]["parameters"]] == [1, 1]
    assert any("names 1 of 2 c" in n and "listed[r]" in n for n in notes)
    spec["seed"]["parameter_values"].append({"parameter": "allowed", "entities": [["c", "C5"], ["w", "W1"]], "value": 1})
    notes = repair.repair(spec)
    assert spec["seed"]["parameters"][0]["default_value"] == 0 and any("names every c" in n for n in notes)


def test_one_number_declared_in_the_seed_is_read_with_no_index_however_written():
    from app.agent import repair

    spec = {"seed": {"parameters": [{"name": "rate", "default_value": 2}, {"name": "cost", "index": ["w"]}]},
            "ir": {"version": 2, "parameters": {"cost": {"index": ["w"]}},
                   "constraints": [{"id": "c", "left": {"mul": [{"par": "rate"}, {"par": "rate", "index": ["w"]}]},
                                    "relation": "<=", "right": {"par": "cost", "index": ["w"]}}]}}
    notes = repair.repair(spec)
    left = spec["ir"]["constraints"][0]["left"]["mul"]
    assert left == [{"par": "rate", "index": []}, {"par": "rate", "index": []}]
    assert spec["ir"]["constraints"][0]["right"] == {"par": "cost", "index": ["w"]}
    assert any("rate hold one number" in n for n in notes)


PASTED = """Please plan this.

Candidate stations (coordinates in km):
id,x_km,y_km,bays
ST001,4.72,7.98,2
ST002,8.58,11.83,3

Road travel time from each station to each zone (minutes):
station,zone,road_minutes
ST001,Z001,12
ST001,Z002,30
ST002,Z001,7

Pairs:
a,b

Rules: open at most 3 stations, costs 1,200 a day, and say which, why, and how."""


def test_tables_pasted_into_a_message_are_read_as_files():
    found = files.pasted_tables(PASTED)
    assert [n for n, _ in found] == ["candidate_stations.csv", "road_travel_time_from.csv"]
    assert found[1][1].splitlines()[0] == "station,zone,road_minutes" and len(found[1][1].splitlines()) == 4


def test_the_assistant_attaches_pasted_tables_once_and_says_so():
    from app.api import agent as agent_api
    from app.agent import core

    agent = core.Agent(core.Settings(), agent_api._index, lambda *a, **k: {"ok": True, "body": {}}, core.Context("x"))
    messages = [{"role": "user", "content": PASTED}]
    said = agent._attach_pasted(messages)
    assert said == ["candidate_stations.csv (2 rows)", "road_travel_time_from.csv (3 rows)"]
    assert [f["name"] for f in agent.ctx.files] == ["candidate_stations.csv", "road_travel_time_from.csv"]
    assert agent._attach_pasted(messages) == [] and len(agent.ctx.files) == 2


def test_pasted_tables_survive_the_conversation_being_summarized():
    """11 October 2026: after the first message was summarized, the Assistant asked for files it had been given."""
    from app.agent import compact as agent_compact
    from app.agent import core
    from app.api import agent as agent_api

    messages = [{"role": "user", "content": PASTED}] + [
        {"role": m, "content": "x" * 400} for m in ("assistant", "user", "assistant", "user", "assistant")]
    done = agent_compact.compact(messages, summarize=lambda piece, notes: "notes", keep_chars=1, piece_chars=100_000,
                                 numbers=lambda ms: set(), force=True)
    assert done and agent_compact.is_summary(messages[0])
    assert [n for n, _ in messages[0]["pasted"]] == ["candidate_stations.csv", "road_travel_time_from.csv"]
    agent = core.Agent(core.Settings(), agent_api._index, lambda *a, **k: {"ok": True, "body": {}}, core.Context("x"))
    agent._attach_pasted(messages)
    assert [f["name"] for f in agent.ctx.files] == ["candidate_stations.csv", "road_travel_time_from.csv"]
    assert all("pasted" not in m and "_finish" not in m for m in core.to_wire(messages + [{"role": "assistant", "content": "k", "_finish": "stop"}], True))


def test_an_approved_plan_builds_with_the_pasted_tables_attached():
    """11 October 2026: on the approval turn the build ran before the tables were attached, and the Assistant
    asked for the files it had been given."""
    from app.agent import core
    from app.api import agent as agent_api

    agent = core.Agent(core.Settings(), agent_api._index, lambda *a, **k: {"ok": True, "body": {}}, core.Context("x"))
    seen: list[list[str]] = []

    def fake_execute(pending, messages, allow):
        seen.append([f["name"] for f in agent.ctx.files])
        yield {"type": "answer", "text": "done"}

    agent._execute = fake_execute
    agent.wrote = False  # run() sets it; _run is called directly here
    messages = [{"role": "user", "content": PASTED},
                {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {
                    "name": "propose_plan", "arguments": "{}"}}]}]
    first = next(agent._run(messages, allow=True))
    assert first["type"] == "answer"
    assert seen == [["candidate_stations.csv", "road_travel_time_from.csv"]]


def test_a_term_with_over_and_no_sum_is_read_as_a_sum_over_the_binding():
    """11 October 2026: {"add": [...], "over": [b]} was refused six times running, and the Assistant gave up."""
    from app.agent import repair

    b = {"index": "r", "set": "record"}
    spec = {"seed": {}, "ir": {"version": 2, "constraints": [
        {"id": "c", "left": {"var": "x", "index": []}, "relation": "<=",
         "right": {"add": [{"var": "y", "index": ["r"]}, {"par": "p", "index": ["r"]}], "over": [b]}},
        {"id": "d", "left": {"sum": {"var": "y", "index": ["r"]}, "over": [b]}, "relation": "<=", "right": {"const": 1}}]}}
    notes = repair.repair(spec)
    right = spec["ir"]["constraints"][0]["right"]
    assert right == {"sum": {"add": [{"var": "y", "index": ["r"]}, {"par": "p", "index": ["r"]}]}, "over": [b]}
    assert spec["ir"]["constraints"][1]["left"] == {"sum": {"var": "y", "index": ["r"]}, "over": [b]}
    assert any('written with "over" and no "sum"' in n for n in notes)
