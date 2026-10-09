"""Pairings any record may join, solved by Edmonds' blossom (NetworkX): proven, and the same as a MIP solver's."""
from __future__ import annotations

import random

import pytest

from app.solve import compile_model, matching, network
from app.solve.backends import by_name
from app.solve.service import solve_compiled

NO_DATA = {"sets": {}, "parameters": {}, "parameter_defaults": {}, "relationships": {}}


def _pairing(n: int, seed: int, *, perfect: bool = False, sense: str = "maximize", density: float = 0.6) -> dict:
    """n records, a yes-or-no decision per allowed pair, each record in at most (or exactly) one pair."""
    rnd = random.Random(seed)
    pairs = [(a, b) for a in range(n) for b in range(a + 1, n) if rnd.random() < density]
    variables = {f"p{a}_{b}": {"index": [], "domain": "binary"} for a, b in pairs}
    x = lambda v: {"var": v, "index": []}  # noqa: E731
    constraints = []
    for r in range(n):
        mine = [x(f"p{a}_{b}") for a, b in pairs if r in (a, b)]
        if len(mine) >= 2:
            constraints.append({"id": f"r{r}", "left": {"add": mine}, "relation": "=" if perfect else "<=",
                                "right": {"const": 1}, "severity": "hard"})
    terms = [{"id": f"o{a}_{b}", "weight": rnd.randint(-3, 20) / (2 if seed % 2 else 1), "expression": x(f"p{a}_{b}")}
             for a, b in pairs]
    return {"version": 2, "sets": [], "parameters": {}, "variables": variables, "constraints": constraints,
            "objective": {"sense": sense, "terms": terms}}


def _mip(compiled):
    result, _ = solve_compiled(by_name("highs"), compiled, time_limit=30, seed=1)
    return result


@pytest.mark.parametrize("seed", range(8))
def test_a_pairing_with_odd_cycles_is_no_network_but_a_matching_that_agrees_with_a_mip(seed):
    compiled = compile_model(_pairing(9, seed), NO_DATA)
    assert network.applies(compiled) is not None  # odd cycles: not a network
    assert matching.applies(compiled) is None
    ours, theirs = matching.solve(compiled).solution, _mip(compiled)
    assert ours.status == theirs.status == "optimal"
    assert float(ours.objective) == pytest.approx(float(theirs.objective))
    for c in compiled.constraints:
        assert float(c.left.evaluated_at(ours.assignments)) <= 1 + 1e-9


@pytest.mark.parametrize("seed", range(6))
def test_a_perfect_pairing_at_least_cost_agrees_with_a_mip_or_is_proven_impossible(seed):
    compiled = compile_model(_pairing(8 + (seed % 2), seed, perfect=True, sense="minimize", density=0.7), NO_DATA)
    if matching.applies(compiled) is not None:
        pytest.skip("a record with fewer than two possible partners")
    ours, theirs = matching.solve(compiled).solution, _mip(compiled)
    assert ours.status == theirs.status
    if ours.status == "optimal":
        assert float(ours.objective) == pytest.approx(float(theirs.objective))
        assert all(float(c.left.evaluated_at(ours.assignments)) == 1 for c in compiled.constraints)


def test_nine_records_cannot_all_be_paired():
    compiled = compile_model(_pairing(9, 3, perfect=True, sense="minimize", density=1.0), NO_DATA)
    assert matching.applies(compiled) is None
    assert matching.solve(compiled).solution.status == "infeasible"


def test_the_networkx_solver_takes_a_matching_by_name_and_refuses_what_is_neither():
    compiled = compile_model(_pairing(7, 1), NO_DATA)
    result, _ = solve_compiled(by_name("networkx"), compiled, time_limit=10, seed=1)
    assert result.status == "optimal" and "blossom" in result.solver
    ir = _pairing(7, 1)
    ir["constraints"][0]["right"] = {"const": 2}  # a record in two pairs: no longer a matching
    from app.solve.compile import Unsupported

    with pytest.raises(Unsupported, match="matching"):
        solve_compiled(by_name("networkx"), compile_model(ir, NO_DATA), time_limit=10, seed=1)


def test_what_is_not_a_matching_is_said():
    ir = _pairing(6, 2)
    ir["variables"]["p0_1"] = {"index": [], "domain": "integer", "lower": 0, "upper": 3}
    assert "yes-or-no" in matching.applies(compile_model(ir, NO_DATA))


def test_a_run_of_a_pairing_is_solved_by_blossom_and_proven(db, empty_queue):  # noqa: F811
    """With `solve.network` at its default, a pairing run is answered by Edmonds' blossom, recorded, global; and a
    whole-number network run now carries its shadow prices."""
    from sqlalchemy import text

    from tests.test_run_events import _run

    ir = _pairing(9, 4)
    run_id = _run(db, ir, "pairing run")
    row = db.execute(text("SELECT status, optimality, objective, solver_version, params FROM run WHERE id = :r"),
                     {"r": run_id}).mappings().one()
    assert row["status"] == "optimal" and row["optimality"] == "global"
    assert row["solver_version"].startswith("matching") and row["params"]["network_run"]["kind"] == "matching"
    assert float(row["objective"]) == pytest.approx(float(matching.solve(compile_model(ir, NO_DATA)).solution.objective))


from tests.test_quadratic import empty_queue  # noqa: E402,F401
from tests.test_v1_problem_run import db  # noqa: E402,F401
