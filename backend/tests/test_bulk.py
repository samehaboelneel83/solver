"""Download templates and bulk uploads (queue R21): the right columns, every row checked
first, each fault by row and column, nothing written until the file is clean."""

from __future__ import annotations

import csv
import io

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

from app.main import app
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


@pytest.fixture
def shop(tenants, db):  # noqa: F811
    client, headers, domain = TestClient(app), tenants["a"], tenants["domain_a"]

    def call(method, path, body=None, ok=(200, 201, 204), **kw):
        response = client.request(method, path, json=body, headers=headers, **kw)
        if ok:
            assert response.status_code in ok, response.text
        return response

    def post(path, body):
        return call("POST", path, body).json()

    site = post("/api/v1/entity-types", {"domain_id": domain, "name": "site", "role": "location"})
    post(f"/api/v1/entity-types/{site['id']}/attributes", {"name": "capacity", "data_type": "integer", "required": True})
    post(f"/api/v1/entity-types/{site['id']}/attributes",
         {"name": "tier", "data_type": "enum", "enum_values": ["a", "b"], "default_value": "b"})
    post(f"/api/v1/entity-types/{site['id']}/attributes", {"name": "opens", "data_type": "time"})
    day = post("/api/v1/entity-types", {"domain_id": domain, "name": "day", "role": "time"})
    for k, key in enumerate(["mon", "tue"]):
        post("/api/v1/entities", {"entity_type_id": day["id"], "key": key, "sort_order": k})
    return {"call": call, "post": post, "domain": domain, "site": site, "day": day}


def _csv(rows):
    out = io.StringIO()
    csv.writer(out).writerows(rows)
    return {"file": ("up.csv", out.getvalue().encode(), "text/csv")}


def _upload(shop, path, rows, **params):
    query = "&".join(f"{k}={str(v).lower()}" for k, v in params.items())
    return shop["call"]("POST", f"{path}?{query}", files=_csv(rows)).json()


def test_an_entity_template_names_every_column_and_says_their_types(shop):
    got = shop["call"]("GET", f"/api/v1/entity-types/{shop['site']['id']}/template?format=csv")
    assert got.headers["content-type"].startswith("text/csv")
    assert next(csv.reader(io.StringIO(got.text.lstrip("﻿")))) == ["key", "label", "sort_order", "active", "capacity", "tier", "opens"]
    book = load_workbook(io.BytesIO(shop["call"]("GET", f"/api/v1/entity-types/{shop['site']['id']}/template?format=xlsx").content))
    about = {row[0]: row for row in book["about"].iter_rows(min_row=2, values_only=True)}
    assert about["capacity"][1:3] == ("integer", "yes") and about["tier"][3] == "a, b"


def test_a_file_with_one_bad_row_writes_nothing_and_names_row_and_column(shop):
    path = f"/api/v1/entity-types/{shop['site']['id']}/upload"
    report = _upload(shop, path, [["key", "capacity", "tier", "opens"],
                                  ["north", "10", "a", "08:00"],
                                  ["south", "ten", "c", "8am"],
                                  ["", "3", "", ""]])
    assert not report["ok"] and report["written"] == 0
    assert {(f["row"], f["column"]) for f in report["faults"]} == {(3, "capacity"), (3, "tier"), (3, "opens"), (4, "key")}
    listed = shop["call"]("GET", f"/api/v1/entities?entity_type_id={shop['site']['id']}").json()
    assert listed["total"] == 0


def test_clean_only_writes_the_clean_rows_and_a_second_upload_updates_by_key(shop):
    path = f"/api/v1/entity-types/{shop['site']['id']}/upload"
    report = _upload(shop, path, [["key", "label", "capacity"], ["north", "North", "10"], ["south", "", "x"]], clean_only=True)
    assert report["written"] == 1 and report["skipped"] == 1
    # The database's own rule: capacity is required -- a trigger fault, still by row and column.
    report = _upload(shop, path, [["key", "tier"], ["east", "a"]])
    assert not report["ok"] and report["faults"][0]["row"] == 2 and report["faults"][0]["column"] == "capacity"
    report = _upload(shop, path, [["key", "capacity"], ["north", "25"]])
    assert report["ok"] and report["written"] == 1
    north = shop["call"]("GET", f"/api/v1/entities?entity_type_id={shop['site']['id']}").json()["items"][0]
    assert north["label"] == "North" and north["attrs"] == {"capacity": 25, "tier": "b"}


def test_a_dry_run_checks_and_writes_nothing(shop):
    path = f"/api/v1/entity-types/{shop['site']['id']}/upload"
    report = _upload(shop, path, [["key", "capacity"], ["north", "10"]], dry_run=True)
    assert report["ok"] and report["dry_run"] and report["written"] == 0
    assert shop["call"]("GET", f"/api/v1/entities?entity_type_id={shop['site']['id']}").json()["total"] == 0


def test_an_unknown_column_is_named_on_row_one(shop):
    report = _upload(shop, f"/api/v1/entity-types/{shop['site']['id']}/upload", [["key", "capacity", "colour"], ["n", "1", "red"]])
    assert report["faults"] == [{"row": 1, "column": "colour", "message": "is not a column of this template"}]



def test_add_fields_turns_unknown_columns_into_typed_fields(shop):
    site = shop["site"]["id"]
    path = f"/api/v1/entity-types/{site}/upload"
    rows = [["key", "capacity", "floors", "shift_start", "Bad Name"], ["n", "1", "3", "06:00", "x"], ["s", "2", "5", "18:00", "y"]]
    refused = _upload(shop, path, rows, add_fields=True, dry_run=True)
    assert [f["column"] for f in refused["faults"]] == ["Bad Name"]  # not a name a field may have
    attrs = {a["name"] for a in shop["call"]("GET", f"/api/v1/entity-types/{site}").json()["attributes"]}
    assert "floors" not in attrs  # a dry run leaves the type alone
    report = _upload(shop, path, [r[:4] for r in rows], add_fields=True)
    assert report["ok"] and report["written"] == 2, report
    kinds = {a["name"]: a["data_type"] for a in shop["call"]("GET", f"/api/v1/entity-types/{site}").json()["attributes"]}
    assert kinds["floors"] == "integer" and kinds["shift_start"] == "time"

def test_xlsx_round_trips_the_stored_rows(shop):
    path = f"/api/v1/entity-types/{shop['site']['id']}/upload"
    _upload(shop, path, [["key", "capacity", "opens"], ["north", "10", "08:00"], ["south", "4", ""]])
    content = shop["call"]("GET", f"/api/v1/entity-types/{shop['site']['id']}/template?format=xlsx&rows=true").content
    book = load_workbook(io.BytesIO(content))
    sheet = book["data"]
    sheet["E2"] = 11  # north's capacity, edited in a spreadsheet
    out = io.BytesIO()
    book.save(out)
    report = shop["call"]("POST", f"{path}", files={"file": ("sites.xlsx", out.getvalue(), "application/octet-stream")}).json()
    assert report["ok"] and report["written"] == 2
    items = shop["call"]("GET", f"/api/v1/entities?entity_type_id={shop['site']['id']}").json()["items"]
    assert {e["key"]: e["attrs"]["capacity"] for e in items} == {"north": 11, "south": 4}


def test_relationships_upload_by_keys(shop):
    post = shop["post"]
    for key in ("north", "south"):
        post("/api/v1/entities", {"entity_type_id": shop["site"]["id"], "key": key, "attrs": {"capacity": 1}})
    rel = post("/api/v1/relationship-types", {"domain_id": shop["domain"], "name": "open_on",
                                              "from_type_id": shop["site"]["id"], "to_type_id": shop["day"]["id"]})
    path = f"/api/v1/relationship-types/{rel['id']}/upload"
    bad = _upload(shop, path, [["from", "to"], ["north", "mon"], ["west", "tue"], ["north", "mon"]])
    assert {(f["row"], f["column"]) for f in bad["faults"]} == {(3, "from"), (4, "to")} and bad["written"] == 0
    good = _upload(shop, path, [["from", "to", "valid_from"], ["north", "mon", "2026-01-01"], ["south", "tue", ""]])
    assert good["ok"] and good["written"] == 2
    csv_text = shop["call"]("GET", f"/api/v1/relationship-types/{rel['id']}/template?rows=true").text.lstrip("﻿")
    assert list(csv.reader(io.StringIO(csv_text)))[1:] == [["north", "mon", "2026-01-01", ""], ["south", "tue", "", ""]]


def test_a_parameter_template_lists_every_cell_and_an_upload_fills_them(shop):
    post = shop["post"]
    for key in ("north", "south"):
        post("/api/v1/entities", {"entity_type_id": shop["site"]["id"], "key": key, "attrs": {"capacity": 1}})
    par = post("/api/v1/parameters", {"domain_id": shop["domain"], "name": "demand", "default_value": 1,
                                      "index_type_ids": [shop["site"]["id"], shop["day"]["id"]]})
    listed = shop["call"]("GET", f"/api/v1/parameters/{par['id']}/template").text.lstrip("﻿")
    assert list(csv.reader(io.StringIO(listed))) == [["site", "day", "value"], ["north", "mon", ""], ["north", "tue", ""],
                                                      ["south", "mon", ""], ["south", "tue", ""]]
    path = f"/api/v1/parameters/{par['id']}/upload"
    bad = _upload(shop, path, [["site", "day", "value"], ["north", "mon", "3"], ["north", "sun", "2"], ["south", "tue", "x"]])
    assert {(f["row"], f["column"]) for f in bad["faults"]} == {(3, "day"), (4, "value")}
    good = _upload(shop, path, [["site", "day", "value"], ["north", "mon", "3"], ["south", "tue", "1"], ["south", "mon", "2.5"]])
    assert good["ok"] and good["written"] == 3
    cells = shop["call"]("GET", f"/api/v1/parameters/{par['id']}/values").json()["cells"]
    # The default (1) is not stored: the grid stays sparse.
    assert sorted(c["value"] for c in cells) == [2.5, 3]
