"""A connected, balanced start (queue R13): feasible for every compiled row, and the solve still optimal from it."""

from __future__ import annotations

from collections import deque

import pytest

from app.solve import compile_model, partition
from app.solve.backends import by_name
from app.solve.stochastic import _holds
from bench.families import generate
from tests.test_quadratic import empty_queue  # noqa: F401
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


def _case(size: str, instance: int):
    case = generate("districting", size, instance)
    return case, compile_model(case.ir, case.data)


@pytest.mark.parametrize(("size", "instance"), [("S", 0), ("S", 1), ("M", 0), ("M", 1), ("L", 0), ("L", 1)])
def test_the_start_holds_every_row(size, instance):
    """Assignments, roots and flows together: every compiled row holds, the flow rows included."""
    case, compiled = _case(size, instance)
    hint, record = partition.start(case.ir, case.data, compiled, seconds=10)
    assert record["feasible"] and record["breach"] == 0
    assert set(hint) == set(compiled.variables)  # complete: HiGHS takes a whole start or none
    broken = [c.id for c in compiled.constraints if not _holds(c, hint)]
    assert broken == []


def test_the_start_is_found_past_the_flows_reach():
    """1,600 cells in 12 zones, where the exact flow found nothing in two minutes."""
    case, compiled = _case("XL", 0)
    hint, record = partition.start(case.ir, case.data, compiled, seconds=10)
    assert record["feasible"], record
    assert record["seconds"] < 10
    assert all(_holds(c, hint) for c in compiled.constraints)


def test_every_zone_is_one_piece_and_none_is_empty():
    case, compiled = _case("L", 0)
    hint, _ = partition.start(case.ir, case.data, compiled, seconds=10)
    neighbours: dict[str, set[str]] = {}
    for edge in case.data["relationships"]["adjacent"]:
        neighbours.setdefault(edge["from"], set()).add(edge["to"])
        neighbours.setdefault(edge["to"], set()).add(edge["from"])
    zones: dict[str, set[str]] = {}
    for (name, (cell, zone)), value in ((k, v) for k, v in hint.items() if k[0] == "assign"):
        if value:
            zones.setdefault(zone, set()).add(cell)
    assert len(zones) == len(case.data["sets"]["zone"])
    for cells in zones.values():
        first = next(iter(cells))
        seen, queue = {first}, deque([first])
        while queue:
            for v in neighbours.get(queue.popleft(), ()):
                if v in cells and v not in seen:
                    seen.add(v)
                    queue.append(v)
        assert seen == cells


def test_from_the_start_the_solver_still_proves_the_optimum():
    """The start is not optimal (1260 against 610); the solve from it must be."""
    case, compiled = _case("S", 0)
    hint, record = partition.start(case.ir, case.data, compiled, seconds=10)
    assert record["objective"] > 610
    result = by_name("cp-sat").solve(compiled, time_limit=60, seed=1, workers=8, gap_rel=0.0, hint=hint)
    assert result.status == "optimal"
    assert float(result.objective) == pytest.approx(610)


def test_it_applies_to_one_connected_rule_only():
    case, _ = _case("S", 0)
    assert partition.applies(case.ir) is None
    no_rule = {**case.ir, "constraints": [c for c in case.ir["constraints"] if "connected" not in c]}
    assert "no connected rule" in partition.applies(no_rule)
    rule = next(c for c in case.ir["constraints"] if "connected" in c)
    nested = {**case.ir, "constraints": [*case.ir["constraints"], {**rule, "id": "c_again"}]}
    assert "more than one" in partition.applies(nested)


def test_a_run_records_why_a_nested_partition_starts_from_nothing(tenants, db, empty_queue):  # noqa: F811
    """The region template has zones and sub-zones, two connected rules: the solver is left to it, and the run says so."""
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    from app.main import app
    from app.regions import REGION_PARTITIONING
    from app.showcase import ensure_showcase_templates
    from app.worker import work_once

    client = TestClient(app)
    template_id = ensure_showcase_templates(db)[REGION_PARTITIONING]
    applied = client.post(f"/api/v1/templates/{template_id}/apply", json={"domain_name": "regions start"},
                          headers=tenants["a"]).json()
    db.execute(text("INSERT INTO setting (scope, scope_id, key, value) VALUES ('problem', :p, 'solve.connected_start',"
                    " CAST('true' AS jsonb))"), {"p": applied["problem_id"]})
    db.commit()
    run_id = client.post(f"/api/v1/scenarios/{applied['scenario_id']}/runs", json={"time_limit_s": 10, "reuse": False},
                         headers=tenants["a"]).json()["id"]
    for _ in range(5):
        if db.execute(text("SELECT status FROM run WHERE id = :r"), {"r": run_id}).scalar_one() not in ("queued", "running"):
            break
        work_once(db)
    params = client.get(f"/api/v1/runs/{run_id}", headers=tenants["a"]).json()["params"]
    assert params["connected_start"] is True
    assert params["connected_start_run"] == {"used": False, "why": partition.applies(
        {"constraints": [{"connected": {}}, {"connected": {}}]})}
    db.execute(text("DELETE FROM setting WHERE key = 'solve.connected_start'"))
    db.commit()


def test_the_start_as_an_answer_keeps_every_rule_and_claims_nothing():
    """When the solver ends with nothing (HiGHS at 400 cells in two minutes), the run keeps the start."""
    case, compiled = _case("L", 0)
    hint, record = partition.start(case.ir, case.data, compiled, seconds=10)
    answer = partition.as_answer(compiled, hint, "highs", 1.5)
    assert answer.status == "feasible" and not answer.optimal and answer.best_bound is None
    assert answer.objective == pytest.approx(record["objective"])
    assert all(_holds(c, answer.assignments) for c in compiled.constraints)


def test_highs_takes_the_start():
    """HiGHS dropped a start given before its objective and ended with nothing at 400 cells (found by R13's bench)."""
    case, compiled = _case("L", 0)
    hint, record = partition.start(case.ir, case.data, compiled, seconds=10)
    result = by_name("highs").solve(compiled, time_limit=5, seed=1, workers=4, gap_rel=0.0, hint=hint)
    assert result.status == "feasible"
    assert float(result.objective) <= record["objective"]


def test_the_start_is_the_same_in_every_process():
    """Ties broken by name, not by set order: string hashing differs per process (R13's bench saw two starts)."""
    import os
    import subprocess
    import sys

    script = ("from bench.families import generate\nfrom app.solve import compile_model, partition\n"
              "c = generate('districting', 'M', 0)\n"
              "print(partition.start(c.ir, c.data, compile_model(c.ir, c.data), seconds=10)[1]['objective'])")
    seen = {subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=True,
                           env={**os.environ, "PYTHONHASHSEED": seed}).stdout.strip() for seed in ("1", "2", "3")}
    assert len(seen) == 1, seen
