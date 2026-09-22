"""The benchmark harness (target roadmap Phase 6.1): its generators, its
wrong-answer check, its report arithmetic and its MPS reader."""

from __future__ import annotations

import math

import pytest
from sqlalchemy import text

from app.ir.validate import check_shape
from bench import mps
from bench.families import FAMILIES, generate
from bench.report import markdown, sgm, summarise
from bench.run import Technique, mark_wrong, run, store
from tests.test_v1_problem_run import db  # noqa: F401


@pytest.mark.parametrize("family", sorted(FAMILIES))
def test_every_family_generates_a_model_the_contract_accepts(family):
    instance = generate(family, "S")
    assert check_shape(instance.ir) is None


@pytest.mark.parametrize("family", sorted(FAMILIES))
def test_an_instance_is_the_same_every_time(family):
    assert generate(family, "M", 3).data == generate(family, "M", 3).data
    assert generate(family, "M", 3).data != generate(family, "M", 4).data


def test_the_small_sizes_solve_on_every_backend_that_takes_them_and_agree():
    rows = run(sorted(FAMILIES), ["S"], time_limit=20)

    assert {row["family"] for row in rows} == set(FAMILIES)
    assert all(row["status"] == "optimal" for row in rows), [
        (row["instance"], row["backend"], row["status"]) for row in rows if row["status"] != "optimal"
    ]
    assert not any(row["wrong"] for row in rows)
    # Every family is solved by more than one backend, or "agree" means nothing.
    for family in FAMILIES:
        assert len({row["backend"] for row in rows if row["family"] == family}) >= 2, family


def _row(instance, backend, status, objective, value=None, solve_s=1.0, seed=1, family="f", gap=0.0):
    return {
        "family": family,
        "size": "S",
        "instance": instance,
        "class": "IP",
        "backend": backend,
        "technique": "workers" if value is not None else None,
        "value": value,
        "seed": seed,
        "status": status,
        "objective": objective,
        "bound": objective,
        "gap": gap,
        "compile_s": 0.0,
        "solve_s": solve_s,
        "time_limit": 30.0,
    }


def test_a_backend_that_disagrees_with_the_proven_answer_is_marked_wrong():
    rows = [
        _row("i", "a", "optimal", 17.0),
        _row("i", "b", "optimal", 17.0000000001),
        _row("i", "c", "optimal", 18.0),
        _row("i", "d", "infeasible", None),
        # An unproven answer claims nothing, so it cannot contradict anyone.
        _row("i", "e", "feasible", 30.0),
    ]
    mark_wrong(rows)
    assert [row["wrong"] for row in rows] == [False, False, True, True, False]


def test_the_shifted_geometric_mean():
    assert sgm([0.0, 0.0]) == pytest.approx(0.0)
    assert sgm([10.0]) == pytest.approx(10.0)
    # exp(mean(log(t + 10))) - 10 for 1 s and 100 s.
    assert sgm([1.0, 100.0]) == pytest.approx(math.sqrt(11 * 110) - 10)


def test_the_enable_rule_needs_two_families_no_regression_and_no_wrong_answer():
    rows = []
    for family in ("f1", "f2"):
        for seed in (1, 2):
            rows.append(_row(f"{family}-i", "a", "optimal", 1.0, value=1, solve_s=4.0, seed=seed, family=family))
            rows.append(_row(f"{family}-i", "a", "optimal", 1.0, value=8, solve_s=1.0, seed=seed, family=family))
    mark_wrong(rows)
    (verdict,) = summarise(rows)["comparisons"]
    assert verdict["improved_families"] == ["f1", "f2"]
    assert verdict["enable"] is True

    rows.append(_row("f3-i", "a", "optimal", 1.0, value=1, solve_s=1.0, family="f3"))
    rows.append(_row("f3-i", "a", "optimal", 1.0, value=8, solve_s=5.0, family="f3"))
    (verdict,) = summarise(rows)["comparisons"]
    assert verdict["regressions"] and verdict["enable"] is False
    assert "enable by default: no" in markdown(rows, "t")


def test_a_technique_value_is_passed_to_the_solver():
    rows = run(["feed_blend"], ["S"], technique=Technique("gap_rel", [0.0, 0.05]), backends=["highs"], time_limit=20)
    assert [row["value"] for row in rows] == [0.0, 0.05]


# -- MPS ------------------------------------------------------------------------------

# max 3x + 2y + 4z  (written as min of the negation)
#   x + y + 2z <= 4          (c1)
#   2 <= x + 3y <= 5         (c2: G row with a range of 3)
#   z binary, y integer in [-1, 3] (UP 3, LO -1), x >= 0 with no upper bound (PL)
# Optimum by hand. With z = 1: x + y <= 2; y = 0, x = 2 gives 6 + 4 = 10.
# With z = 0: x + y <= 4 and 2 <= x + 3y <= 5; y = -1 lets x reach 5
# (x - 3 = 2), for 15 - 2 = 13 -- the best. Stated as a minimisation: -13.
TINY = """NAME          TINY
ROWS
 N  obj
 L  c1
 G  c2
COLUMNS
    x         obj       -3             c1        1
    x         c2        1
    MARKER    'MARKER'  'INTORG'
    y         obj       -2             c1        1
    y         c2        3
    z         obj       -4             c1        2
    MARKER    'MARKER'  'INTEND'
RHS
    RHS       c1        4              c2        2
RANGES
    RNG       c2        3
BOUNDS
 LO BND       x         0
 PL BND       x
 UP BND       y         3
 LO BND       y         -1
 BV BND       z
ENDATA
"""


def test_mps_is_read_with_ranges_integers_and_bounds():
    compiled = mps.parse(TINY)

    kinds = {key[1][0]: spec.domain for key, spec in compiled.variables.items()}
    assert kinds == {"x": "continuous", "y": "integer", "z": "binary"}
    y = compiled.variables[("x", ("y",))]
    assert (y.lower, y.upper) == (-1, 3)
    assert compiled.variables[("x", ("x",))].upper == mps.INF
    # The ranged row became two, at 2 and 5.
    ranged = [c for c in compiled.constraints if c.id == "c2"]
    assert sorted((c.relation, c.right.const) for c in ranged) == [("<=", 5), (">=", 2)]
    assert mps.classify_compiled(compiled).model_class == "MILP"


@pytest.mark.parametrize("backend", mps.MPS_BACKENDS)
def test_an_mps_model_solves_to_its_hand_worked_optimum(backend):
    from app.solve.backends import by_name
    from app.solve.service import solve_compiled

    result, _ = solve_compiled(by_name(backend), mps.parse(TINY), time_limit=10)

    assert result.status == "optimal"
    assert result.objective == pytest.approx(-13)


def test_results_are_stored_for_the_history(db):
    rows = [_row("i", "a", "optimal", 1.0)]
    mark_wrong(rows)
    store(rows)
    try:
        stored = db.execute(text("SELECT backend, status, wrong FROM bench_result WHERE instance = 'i'")).all()
        assert [tuple(r) for r in stored] == [("a", "optimal", False)]
    finally:
        db.execute(text("DELETE FROM bench_result WHERE instance = 'i'"))
        db.commit()


# -- the nightly job --------------------------------------------------------


def _row(instance="rota-L-0", backend="cp-sat", seed=1, status="optimal", objective=10.0,
         solve_s=1.0, wrong=False):
    return {"instance": instance, "backend": backend, "seed": seed, "status": status,
            "objective": objective, "solve_s": solve_s, "wrong": wrong}


def test_nightly_finds_nothing_when_nothing_changed():
    from bench.nightly import compare

    night = [_row(), _row(backend="highs", solve_s=1.4)]
    assert compare(night, [dict(r) for r in night]) == []


def test_nightly_reports_each_kind_of_worse():
    from bench.nightly import compare

    before = [
        _row(instance="a", objective=10.0),
        _row(instance="b", status="optimal", objective=5.0),
        _row(instance="c", solve_s=1.0),
    ]
    tonight = [
        _row(instance="a", objective=11.0),                      # the optimum moved
        _row(instance="b", status="feasible", objective=6.0),    # proof lost
        _row(instance="c", solve_s=4.5),                         # (4.5+1)/(1+1) = 2.75x
        _row(instance="d", status="error", objective=None),
        _row(instance="e", wrong=True),
    ]
    problems = compare(before, tonight)
    assert any(p.startswith("optimum moved: a was 10.0, now 11.0") for p in problems)
    assert any(p.startswith("proof lost: b on cp-sat") for p in problems)
    assert any(p.startswith("2x slower: c on cp-sat") for p in problems)
    assert any(p.startswith("error: d on cp-sat") for p in problems)
    assert any(p.startswith("wrong: e on cp-sat") for p in problems)
    assert len(problems) == 5


def test_nightly_does_not_call_noise_on_a_fast_solve_a_regression():
    """20 ms to 90 ms is 4.5x raw, but (0.09+1)/(0.02+1) = 1.07 shifted."""
    from bench.nightly import compare

    assert compare([_row(solve_s=0.02)], [_row(solve_s=0.09)]) == []


def test_nightly_first_night_only_checks_tonight():
    from bench.nightly import compare

    assert compare(None, [_row()]) == []
    assert compare(None, [_row(wrong=True)]) != []


def test_nightly_runs_end_to_end_and_compares_with_the_night_before(tmp_path):
    """Two nights on the small instances: the second compares with the first
    and finds nothing; a doctored first night makes it fail."""
    import json

    from bench.nightly import main

    common = ["--out-dir", str(tmp_path), "--sizes", "S", "--instances", "1", "--seeds", "1",
              "--time-limit", "10", "--no-store"]
    assert main([*common, "--night", "2026-01-01"]) == 0
    assert main([*common, "--night", "2026-01-02"]) == 0
    summary = (tmp_path / "2026-01-02.md").read_text()
    assert "compared with 2026-01-01" in summary
    assert "Nothing got worse" in summary

    first = json.loads((tmp_path / "2026-01-01.json").read_text())
    for row in first:
        if row["status"] == "optimal":
            row["objective"] = row["objective"] + 1
    (tmp_path / "2026-01-01.json").write_text(json.dumps(first))
    (tmp_path / "2026-01-02.json").unlink()
    assert main([*common, "--night", "2026-01-02"]) == 1
    assert "optimum moved" in (tmp_path / "2026-01-02.md").read_text()
