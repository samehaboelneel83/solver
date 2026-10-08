"""A single number given in a plan as a cell with no records is the parameter's value (its default): the
trial and the built model both read it (the database-source test, October 2026: two capacities given that way
were read as their default 0, and the plan made nothing)."""
from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401

PRODUCTS = [("P1", "Chair", 45, 2, 1, 40), ("P2", "Table", 120, 5, 3, 20), ("P3", "Desk", 160, 7, 4, 15),
            ("P4", "Shelf", 60, 3, 1, 30), ("P5", "Stool", 30, 1, 0.5, 60)]


def _spec(dry_run: bool) -> dict:
    fields = ["profit", "assembly_hours", "finishing_hours", "max_demand"]
    seed = {"entity_types": [{"name": "product", "role": "task",
                              "attributes": [{"name": f, "data_type": "number", "required": True} for f in fields]}],
            "parameters": [{"name": "assembly_capacity", "index": [], "default_value": 0},
                           {"name": "finishing_capacity", "index": [], "default_value": 0}],
            "entities": [{"type": "product", "key": k, "label": n, "attrs": dict(zip(fields, rest))}
                         for k, n, *rest in PRODUCTS],
            "parameter_values": [{"parameter": "assembly_capacity", "entities": [], "value": 220},
                                 {"parameter": "finishing_capacity", "entities": [], "value": 120}]}

    def used(field):
        return {"sum": {"mul": [{"attr": {"of": "p", "name": field}}, {"var": "make", "index": ["p"]}]},
                "over": [{"index": "p", "set": "product"}]}
    ir = {"version": 2, "sets": ["product"],
          "parameters": {"assembly_capacity": {"index": []}, "finishing_capacity": {"index": []}},
          "variables": {"make": {"index": ["product"], "domain": "integer", "lower": 0}},
          "constraints": [
              {"id": "assembly", "left": used("assembly_hours"), "relation": "<=",
               "right": {"par": "assembly_capacity", "index": []}, "severity": "hard"},
              {"id": "finishing", "left": used("finishing_hours"), "relation": "<=",
               "right": {"par": "finishing_capacity", "index": []}, "severity": "hard"},
              {"id": "demand", "forall": [{"index": "p", "set": "product"}], "left": {"var": "make", "index": ["p"]},
               "relation": "<=", "right": {"attr": {"of": "p", "name": "max_demand"}}, "severity": "hard"}],
          "objective": {"sense": "maximize", "terms": [{"id": "profit", "weight": 1, "expression": used("profit")}]}}
    return {"domain_name": f"single number {uuid4().hex[:6]}", "problem_name": "mix", "seed": seed, "ir": ir,
            "dry_run": dry_run, "trial": dry_run}


def test_a_cell_with_no_records_is_the_value(tenants, db):  # noqa: F811
    client = TestClient(app)
    checked = client.post("/api/v1/problems/from-spec", json=_spec(True), headers=tenants["a"]).json()
    assert checked["trial"]["status"] == "optimal" and abs(checked["trial"]["objective"] - 5550) < 1e-6, checked
    # The trial names what it chose, so a summary can say it rightly.
    assert sorted(checked["trial"]["used"]["make"]["chosen"]) == ["P1 = 30", "P2 = 20", "P5 = 60"]
    built = client.post("/api/v1/problems/from-spec", json=_spec(False), headers=tenants["a"])
    assert built.status_code == 200, built.text
    rows = db.execute(text("SELECT d.name, d.default_value, (SELECT count(*) FROM parameter_value v"
                           " WHERE v.parameter_def_id = d.id) FROM parameter_def d WHERE d.domain_id = :d ORDER BY 1"),
                      {"d": built.json()["domain_id"]}).all()
    assert [(n, float(v), c) for n, v, c in rows] == [("assembly_capacity", 220.0, 0), ("finishing_capacity", 120.0, 0)]
