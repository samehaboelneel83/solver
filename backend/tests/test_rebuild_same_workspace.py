"""Building a model again into a workspace that already holds its records (camp retest, October 2026).

The layout was rebuilt into its old workspace: the cells kept yesterday's fields (no `entrance`) and the
old candidates' links, and the run said "optimal" with no bed. A missing field is now filled in, differing
values or links are refused before the build, and a sourced `connected` rule with no source stops with a
reason instead of an empty "optimal" answer."""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.solve.compile import Unsupported, compile_model
from tests.test_quadratic import empty_queue  # noqa: F401
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


def _spec(cells, links, *, domain_id=None, name="Reach", entrance=True):
    attrs = [{"name": "x_m", "data_type": "number"}]
    if entrance:
        attrs.append({"name": "entrance", "data_type": "integer"})
    k = {"index": "k", "set": "cell"}
    rules = [{"id": "c_access", "severity": "hard", "connected": {
        "assign": {"var": "way", "index": ["k"]}, "units": k, "via": "next_to", "sources": "entrance"}}] if entrance else []
    spec = {
        "problem_name": name,
        "seed": {
            "entity_types": [{"name": "cell", "attributes": attrs}],
            "relationship_types": [{"name": "next_to", "from": "cell", "to": "cell"}],
            "entities": [{"type": "cell", "key": key, "attrs": a} for key, a in cells],
            "relationships": [{"type": "next_to", "from": ["cell", a], "to": ["cell", b]} for a, b in links],
        },
        "ir": {"version": 2, "sets": ["cell"], "relationships": ["next_to"], "parameters": {},
               "variables": {"way": {"index": ["cell"], "domain": "binary"}},
               "constraints": rules,
               "objective": {"sense": "maximize", "terms": [{"id": "o", "weight": 1, "expression": {
                   "sum": {"var": "way", "index": ["k"]}, "over": [k]}}]}},
    }
    if domain_id is None:
        spec["domain_name"] = name
    else:
        spec["domain_id"] = domain_id
    return spec


def _cells(x=0.0, entrance=True):
    return [(f"k{i}", {"x_m": x + i, **({"entrance": 1 if i == 0 else 0} if entrance else {})}) for i in range(3)]


LINKS = [("k0", "k1"), ("k1", "k2")]


def test_a_rebuild_fills_a_field_the_old_records_lack(tenants, db):
    client = TestClient(app)
    first = client.post("/api/v1/problems/from-spec", json=_spec(_cells(entrance=False), LINKS, entrance=False,
                                                                 name="Old"), headers=tenants["b"])
    assert first.status_code == 200, first.text
    domain = first.json()["domain_id"]
    again = client.post("/api/v1/problems/from-spec", json=_spec(_cells(), LINKS, domain_id=domain, name="New"),
                        headers=tenants["b"])
    assert again.status_code == 200, again.text
    types = client.get(f"/api/v1/entity-types?domain_id={domain}", headers=tenants["b"]).json()
    cell = next(t for t in (types.get("items") if isinstance(types, dict) else types) if t["name"] == "cell")
    rows = client.get(f"/api/v1/entities?entity_type_id={cell['id']}&limit=10", headers=tenants["b"]).json()
    rows = rows.get("items") if isinstance(rows, dict) else rows
    assert {r["key"]: r["attrs"].get("entrance") for r in rows} == {"k0": 1, "k1": 0, "k2": 0}


def test_differing_values_or_links_are_refused_before_the_build(tenants, db):
    client = TestClient(app)
    first = client.post("/api/v1/problems/from-spec", json=_spec(_cells(), LINKS, name="Layout A"),
                        headers=tenants["b"])
    assert first.status_code == 200, first.text
    domain = first.json()["domain_id"]
    moved = client.post("/api/v1/problems/from-spec",
                        json={**_spec(_cells(x=0.5), LINKS, domain_id=domain, name="Layout B"), "dry_run": True},
                        headers=tenants["b"])
    assert moved.status_code == 422
    msg = " ".join(d["msg"] for d in moved.json()["detail"])
    assert "3 cell record(s) are already in this workspace with other values" in msg
    assert "new workspace" in msg
    relinked = client.post("/api/v1/problems/from-spec",
                           json=_spec(_cells(), [("k0", "k2")], domain_id=domain, name="Layout C"),
                           headers=tenants["b"])
    assert relinked.status_code == 422
    assert "next_to link(s) already in this workspace" in relinked.text
    same = client.post("/api/v1/problems/from-spec", json=_spec(_cells(), LINKS, domain_id=domain, name="Layout D"),
                       headers=tenants["b"])
    assert same.status_code == 200, same.text


def test_a_sourced_rule_with_no_source_says_so():
    k = {"index": "k", "set": "cell"}
    ir = _spec(_cells(), LINKS)["ir"]
    data = {"sets": {"cell": [{"id": f"k{i}", "entrance": 0} for i in range(3)]}, "parameters": {},
            "parameter_defaults": {}, "relationships": {"next_to": [{"from": a, "to": b} for a, b in LINKS]}}
    with pytest.raises(Unsupported, match='no cell record is a source \("entrance"\)'):
        compile_model(ir, data)
    data["sets"]["cell"][0]["entrance"] = 1
    assert compile_model(ir, data) is not None
    assert k


def test_the_probe_race_gets_the_start_the_solve_would_get(tenants, db, monkeypatch):
    """Camp retest: the probes ran without the reach start, CP-SAT "found no answer" in 5 s, and HiGHS -- which
    takes no start -- was chosen and never beat it. A solver that takes a start now gets it in its probe too."""
    from sqlalchemy import text

    from app.solve import race, sandbox
    from app.worker import work_once

    monkeypatch.setattr(race, "FLOOR_DECISIONS", 0)
    monkeypatch.setattr(race, "FLOOR_ROWS", 0)
    client = TestClient(app)
    built = client.post("/api/v1/problems/from-spec", json=_spec(_cells(), LINKS, name="Probe start"),
                        headers=tenants["b"])
    assert built.status_code == 200, built.text
    db.execute(text("INSERT INTO setting (scope, scope_id, key, value) VALUES "
                    "('problem', :p, 'solve.probe', CAST('true' AS jsonb)),"
                    " ('problem', :p, 'solve.memory', CAST('false' AS jsonb))"), {"p": built.json()["problem_id"]})
    db.commit()
    seen: list[tuple[str, bool]] = []
    real = sandbox.run

    def spy(target, payload, **kw):
        if target.endswith("solve_in_child"):
            seen.append((payload["backend"], bool(payload.get("hint"))))
        return real(target, payload, **kw)

    monkeypatch.setattr(sandbox, "run", spy)
    run = client.post(f"/api/v1/scenarios/{built.json()['scenario_id']}/runs", json={"time_limit_s": 20},
                      headers=tenants["b"]).json()
    for _ in range(5):
        if work_once(db) is None:
            break
    answer = client.get(f"/api/v1/runs/{run['id']}", headers=tenants["b"]).json()
    assert answer["params"].get("reach_start_run", {}).get("used"), answer["params"]
    assert ("cp-sat", True) in seen, seen
    assert answer["objective"] == 3


def test_sources_picked_by_a_where_list_build_and_a_wrong_field_is_refused(tenants, db):
    client = TestClient(app)
    spec = _spec(_cells(), LINKS, name="Fibre where")
    spec["seed"]["entity_types"][0]["attributes"].append({"name": "kind", "data_type": "text"})
    for e in spec["seed"]["entities"]:
        e["attrs"]["kind"] = "exchange" if e["key"] == "k0" else "village"
    rule = spec["ir"]["constraints"][0]["connected"]
    rule["sources"] = [{"attr": "kind", "op": "=", "value": "exchange"}]
    ok = client.post("/api/v1/problems/from-spec", json={**spec, "dry_run": True}, headers=tenants["b"])
    assert ok.status_code == 200, ok.text
    rule["sources"] = [{"attr": "type", "op": "=", "value": "exchange"}]
    bad = client.post("/api/v1/problems/from-spec", json={**spec, "dry_run": True}, headers=tenants["b"])
    assert bad.status_code == 422 and "sources" in bad.text, bad.text


def _newsvendor_spec(name):
    ir = {"version": 2, "sets": [], "parameters": {"demand": {"index": [], "uncertainty": {"kind": "interval", "deviation": 0.5}}},
          "variables": {"order": {"index": [], "domain": "continuous", "lower": 0, "upper": 300, "stage": 1},
                        "sell": {"index": [], "domain": "continuous", "lower": 0, "upper": 300, "stage": 2}},
          "constraints": [{"id": "c_stock", "left": {"var": "sell", "index": []}, "relation": "<=",
                           "right": {"var": "order", "index": []}, "severity": "hard"},
                          {"id": "c_dem", "left": {"var": "sell", "index": []}, "relation": "<=",
                           "right": {"par": "demand", "index": []}, "severity": "hard"}],
          "objective": {"sense": "maximize", "terms": [{"id": "o_sell", "weight": 3, "expression": {"var": "sell", "index": []}},
                                                       {"id": "o_buy", "weight": -1, "expression": {"var": "order", "index": []}}]}}
    return {"domain_name": name, "problem_name": name,
            "seed": {"parameters": [{"name": "demand", "index": [], "default_value": 100}]}, "ir": ir}


def test_a_sampled_two_stage_run_is_never_served_from_a_plain_one_and_a_plain_one_says_so(tenants, db):
    """Evaluation battery: 50 futures asked for, the average-demand answer of an earlier run came back."""
    from sqlalchemy import text

    from app.worker import work_once

    client = TestClient(app)

    def solve(name, samples):
        built = client.post("/api/v1/problems/from-spec", json=_newsvendor_spec(name), headers=tenants["b"]).json()
        if samples:
            db.execute(text("INSERT INTO setting (scope, scope_id, key, value) VALUES ('problem', :p, "
                            "'solve.stochastic_samples', CAST(:v AS jsonb))"), {"p": built["problem_id"], "v": str(samples)})
            db.commit()
        run = client.post(f"/api/v1/scenarios/{built['scenario_id']}/runs", json={}, headers=tenants["b"]).json()
        for _ in range(5):
            if work_once(db) is None:
                break
        return client.get(f"/api/v1/runs/{run['id']}", headers=tenants["b"]).json()

    plain = solve(f"news plain {uuid.uuid4().hex[:6]}", 0)
    assert plain["objective"] == pytest.approx(200)
    assert "solve.stochastic_samples is 0" in plain["params"]["stochastic"]["skipped"]
    sampled = solve(f"news sampled {uuid.uuid4().hex[:6]}", 30)
    assert sampled["reused_from"] is None
    assert sampled["params"]["stochastic"]["samples"] == 30 and sampled["objective"] < 200


def test_a_run_may_ask_for_futures_itself(tenants, db):
    """Evaluation: stochastic solving was reachable only through a setting the Assistant could not set. A run --
    and so a what-if -- may now ask for its own number of futures."""
    from app.worker import work_once

    client = TestClient(app)
    built = client.post("/api/v1/problems/from-spec", json=_newsvendor_spec(f"news run {uuid.uuid4().hex[:6]}"),
                        headers=tenants["b"]).json()
    run = client.post(f"/api/v1/scenarios/{built['scenario_id']}/runs", json={"futures": 30},
                      headers=tenants["b"]).json()
    for _ in range(5):
        if work_once(db) is None:
            break
    answer = client.get(f"/api/v1/runs/{run['id']}", headers=tenants["b"]).json()
    assert answer["params"]["stochastic"]["samples"] == 30 and answer["objective"] < 200
    too_many = client.post(f"/api/v1/scenarios/{built['scenario_id']}/runs", json={"futures": 5000},
                           headers=tenants["b"])
    assert too_many.status_code == 422
