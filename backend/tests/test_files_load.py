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
