"""Start a problem from a spreadsheet: every sheet a kind of record, every
column a field of the type its values read as, a column of another sheet's
keys a link -- proposed first, built as the (edited) proposal says."""
from __future__ import annotations

import io
import json
from datetime import date, time

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import text

from app.api.start import convert, infer, to_name
from app.main import app
from tests.test_api_runs import auth_headers, ensure_admin_seeded  # noqa: F401
from tests.test_v1_problem_run import db, make_domain  # noqa: F401


def _workbook() -> bytes:
    book = Workbook()
    teams = book.active
    teams.title = "Teams"
    teams.append(["Code", "Name"])
    teams.append(["ops", "Operations"])
    teams.append(["dev", "Development"])
    staff = book.create_sheet("Employees")
    staff.append(["ID", "Name", "Team", "Hours", "Rate", "Senior", "Start", "Grade"])
    staff.append([101, "Ahmed", "ops", 40, 12.5, "yes", date(2024, 1, 8), "mid"])
    staff.append([102, "Sara", "dev", 20, 14, "no", date(2023, 5, 2), "senior"])
    staff.append([103, "Omar", "dev", None, 11.25, "no", date(2025, 2, 1), "mid"])
    staff.append([104, "Mona", "ops", 30, 13, "yes", date(2022, 9, 9), "senior"])
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.fixture
def domain(db):  # noqa: F811
    domain_id = make_domain(db, "from-a-sheet")
    db.commit()
    yield domain_id
    db.execute(text("DELETE FROM domain WHERE id = :d"), {"d": domain_id})
    db.commit()


def test_values_read_as_their_type():
    assert infer([1, 2, "3"]) == ("integer", None)
    assert infer([1, 2.5]) == ("number", None)
    assert infer(["yes", "No", True]) == ("boolean", None)
    assert infer([date(2024, 1, 1), "2024-02-01"]) == ("date", None)
    assert infer(["a", "b", "a", "b"]) == ("enum", ["a", "b"])
    assert infer(["06:00", "18:00", time(6, 30)]) == ("time", None)
    assert convert("6:05", "time") == "06:05"
    assert infer(["a", "b", "c"]) == ("text", None)
    assert to_name("Hours per week") == "hours_per_week" and to_name("2nd shift") == "n_2nd_shift"
    assert convert("12", "integer") == 12 and convert(12.0, "integer") == 12
    with pytest.raises(ValueError, match="not a whole number"):
        convert("12.5", "integer")
    with pytest.raises(ValueError, match="not one of mid, senior"):
        convert("junior", "enum", ["mid", "senior"])


def test_a_workbook_is_proposed_then_built(domain, db, auth_headers):  # noqa: F811
    client = TestClient(app)
    files = {"file": ("staff.xlsx", _workbook(), XLSX)}
    response = client.post(f"/api/v1/domains/{domain}/spreadsheet/propose", files=files, headers=auth_headers)
    assert response.status_code == 200, response.text
    kinds = {k["name"]: k for k in response.json()["kinds"]}
    assert set(kinds) == {"team", "employee"}
    assert kinds["team"]["key"] == "Code" and kinds["team"]["rows"] == 2
    employee = kinds["employee"]
    assert employee["key"] == "ID" and employee["rows"] == 4
    assert {f["name"]: f["data_type"] for f in employee["fields"]} == {
        "name": "text", "hours": "integer", "rate": "number", "senior": "boolean", "start": "date", "grade": "enum"}
    assert next(f for f in employee["fields"] if f["name"] == "grade")["enum_values"] == ["mid", "senior"]
    assert employee["links"] == [{"column": "Team", "name": "team", "to": "team", "skip": False}]

    # The person renames the link and keeps the rest.
    proposal = response.json()
    next(k for k in proposal["kinds"] if k["name"] == "employee")["links"][0]["name"] = "works_in"
    response = client.post(f"/api/v1/domains/{domain}/spreadsheet/import", files={"file": ("staff.xlsx", _workbook(), XLSX)},
                           data={"proposal": json.dumps(proposal)}, headers=auth_headers)
    assert response.status_code == 200, response.text
    assert response.json()["made"] == {"kinds": 2, "fields": 7, "records": 6, "link_types": 1, "links": 4}

    rows = db.execute(text(
        "SELECT e.key, e.attrs FROM entity e JOIN entity_type t ON t.id = e.entity_type_id"
        " WHERE t.domain_id = :d AND t.name = 'employee' ORDER BY e.sort_order"), {"d": domain}).all()
    assert [r.key for r in rows] == ["101", "102", "103", "104"]
    assert rows[0].attrs == {"name": "Ahmed", "hours": 40, "rate": 12.5, "senior": True, "start": "2024-01-08", "grade": "mid"}
    assert "hours" not in rows[2].attrs  # a blank cell is no value, not 0
    links = db.execute(text(
        "SELECT a.key, b.key FROM relationship r JOIN relationship_type t ON t.id = r.relationship_type_id"
        " JOIN entity a ON a.id = r.from_entity_id JOIN entity b ON b.id = r.to_entity_id"
        " WHERE t.domain_id = :d AND t.name = 'works_in' ORDER BY a.key"), {"d": domain}).all()
    assert [tuple(r) for r in links] == [("101", "ops"), ("102", "dev"), ("103", "dev"), ("104", "ops")]

    # Importing again makes nothing twice.
    again = client.post(f"/api/v1/domains/{domain}/spreadsheet/import", files={"file": ("staff.xlsx", _workbook(), XLSX)},
                         data={"proposal": json.dumps(proposal)}, headers=auth_headers)
    assert again.status_code == 200, again.text
    assert set(again.json()["made"].values()) == {0}
    assert next(k for k in client.post(f"/api/v1/domains/{domain}/spreadsheet/propose", files={"file": ("staff.xlsx", _workbook(), XLSX)},
                                       headers=auth_headers).json()["kinds"] if k["name"] == "team")["exists"] is True


def test_one_bad_cell_refuses_the_whole_import_and_says_where(domain, db, auth_headers):  # noqa: F811
    client = TestClient(app)
    csv_file = b"key,hours\nahmed,40\nsara,forty\n"
    proposal = client.post(f"/api/v1/domains/{domain}/spreadsheet/propose", files={"file": ("staff.csv", csv_file, "text/csv")},
                           headers=auth_headers).json()
    (kind,) = proposal["kinds"]
    assert kind["name"] == "staff" and kind["key"] == "key" and kind["fields"][0]["data_type"] == "text"
    kind["fields"][0]["data_type"] = "integer"  # the person says hours are whole numbers
    response = client.post(f"/api/v1/domains/{domain}/spreadsheet/import", files={"file": ("staff.csv", csv_file, "text/csv")},
                           data={"proposal": json.dumps(proposal)}, headers=auth_headers)
    assert response.status_code == 422
    assert response.json()["detail"]["faults"] == ["'staff' row 3, column 'hours': 'forty' is not a whole number"]
    assert db.execute(text("SELECT count(*) FROM entity_type WHERE domain_id = :d"), {"d": domain}).scalar_one() == 0

    kind["name"] = "Staff Members"
    response = client.post(f"/api/v1/domains/{domain}/spreadsheet/import", files={"file": ("staff.csv", csv_file, "text/csv")},
                           data={"proposal": json.dumps(proposal)}, headers=auth_headers)
    assert response.status_code == 422
    assert "the kind is named 'Staff Members'" in response.json()["detail"]["faults"][0]
