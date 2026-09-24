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


#: Families whose S is sized to be hard, not small. districting's S sits
#: where the exact flow starts to strain: CP-SAT proves it in 2-5 s, the
#: MIP backends take up to 78 s (bench/results/2026-09-24-districting.md).
#: That the flow is exact on every backend is pinned by brute force in
#: tests/test_connected.py instead.
_NOT_SMALL = frozenset({"districting"})


def test_the_small_sizes_solve_on_every_backend_that_takes_them_and_agree():
    families = sorted(set(FAMILIES) - _NOT_SMALL)
    rows = run(families, ["S"], time_limit=20)

    assert {row["family"] for row in rows} == set(families)
    assert all(row["status"] == "optimal" for row in rows), [
        (row["instance"], row["backend"], row["status"]) for row in rows if row["status"] != "optimal"
    ]
    assert not any(row["wrong"] for row in rows)
    # Every family is solved by more than one backend, or "agree" means
    # nothing -- except one only CP-SAT holds (intervals), which must agree
    # with its twin formulation on the same data instead.
    twins = {"flow_shop": "flow_shop_timed"}
    for family in families:
        if family in twins:
            continue
        assert len({row["backend"] for row in rows if row["family"] == family}) >= 2, family
    for family, twin in twins.items():
        optima = {
            f: {row["instance"].rsplit("-", 1)[1]: row["objective"] for row in rows if row["family"] == f}
            for f in (family, twin)
        }
        assert optima[family] and optima[family] == optima[twin], optima


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


def _night(instance="rota-L-0", backend="cp-sat", seed=1, status="optimal", objective=10.0,
         solve_s=1.0, wrong=False):
    return {"instance": instance, "backend": backend, "seed": seed, "status": status,
            "objective": objective, "solve_s": solve_s, "wrong": wrong}


def test_nightly_finds_nothing_when_nothing_changed():
    from bench.nightly import compare

    night = [_night(), _night(backend="highs", solve_s=1.4)]
    assert compare(night, [dict(r) for r in night]) == []


def test_nightly_reports_each_kind_of_worse():
    from bench.nightly import compare

    before = [
        _night(instance="a", objective=10.0),
        _night(instance="b", status="optimal", objective=5.0),
        _night(instance="c", solve_s=1.0),
    ]
    tonight = [
        _night(instance="a", objective=11.0),                      # the optimum moved
        _night(instance="b", status="feasible", objective=6.0),    # proof lost
        _night(instance="c", solve_s=4.5),                         # (4.5+1)/(1+1) = 2.75x
        _night(instance="d", status="error", objective=None),
        _night(instance="e", wrong=True),
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

    assert compare([_night(solve_s=0.02)], [_night(solve_s=0.09)]) == []


def test_nightly_first_night_only_checks_tonight():
    from bench.nightly import compare

    assert compare(None, [_night()]) == []
    assert compare(None, [_night(wrong=True)]) != []


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


# -- the primal integral ------------------------------------------------------


def test_primal_gap_is_berthold_s():
    from bench.primal import primal_gap

    assert primal_gap(None, 10) == 1.0          # no answer yet
    assert primal_gap(0, 0) == 0.0
    assert primal_gap(-1, 1) == 1.0             # different signs
    assert primal_gap(20, 10) == 0.5            # |20-10| / 20
    assert primal_gap(8, 10) == 0.2             # |8-10| / 10, the same for maximising


def test_primal_integral_of_a_hand_worked_curve():
    """Minimising, optimum 10, run ends at 8 s. Answers 20 at 1 s, 12 at 3 s,
    10 at 6 s. Area = 1x1 (nothing) + 0.5x2 (20) + (2/12)x3 (12) + 0x2 (10)
    = 1 + 1 + 0.5 = 2.5."""
    from bench.primal import primal_integral

    assert primal_integral([(3, 12), (1, 20), (6, 10)], 10, 8) == pytest.approx(2.5)


def test_primal_integral_maximising_and_ignoring_worse_answers():
    """Maximising, optimum 10, ends at 5 s: 5 at 2 s, 8 at 4 s, then a worse 6
    at 4.5 s. Area = 1x2 + 0.5x2 + 0.2x1 = 3.2."""
    from bench.primal import primal_integral

    points = [(2, 5), (4, 8), (4.5, 6)]
    assert primal_integral(points, 10, 5, minimise=False) == pytest.approx(3.2)


def test_primal_integral_charges_the_whole_run_when_nothing_was_found():
    from bench.primal import primal_integral

    assert primal_integral([], 10, 7.5) == pytest.approx(7.5)
    # An answer after the end is not counted early.
    assert primal_integral([(9, 10)], 10, 7.5) == pytest.approx(7.5)


def test_rows_get_a_primal_integral_against_the_instance_s_proven_optimum():
    from bench.primal import mark_primal_integral

    rows = [
        {"instance": "a", "status": "optimal", "objective": 10.0, "solve_s": 2.0,
         "incumbents": [(1.0, 10.0)], "wrong": False},
        {"instance": "a", "status": "feasible", "objective": 20.0, "solve_s": 4.0,
         "incumbents": [(2.0, 20.0)], "wrong": False},
        {"instance": "b", "status": "infeasible", "objective": None, "solve_s": 0.5,
         "incumbents": [], "wrong": False},
    ]
    mark_primal_integral(rows)
    assert rows[0]["primal_integral"] == pytest.approx(1.0)        # 1x1 then 0
    assert rows[1]["primal_integral"] == pytest.approx(2.0 + 1.0)  # 1x2 then 0.5x2
    assert rows[2]["primal_integral"] is None
    assert all("incumbents" not in row for row in rows)


def test_a_real_run_streams_incumbents_into_its_primal_integral():
    """CP-SAT streams its answers; the integral lies between 0 and the run time."""
    from bench.run import run

    rows = run(["rota"], ["S"], backends=["cp-sat"], time_limit=10.0)
    assert rows and rows[0]["status"] == "optimal"
    integral = rows[0]["primal_integral"]
    assert integral is not None and 0 <= integral <= rows[0]["solve_s"]


def test_the_report_shows_the_primal_integral():
    from bench.report import markdown

    rows = [
        {"family": "f", "size": "S", "instance": "i", "backend": "cp-sat", "technique": None,
         "value": None, "seed": 1, "status": "optimal", "objective": 1.0, "gap": 0.0,
         "solve_s": 2.0, "time_limit": 10.0, "wrong": False, "primal_integral": 0.75},
    ]
    assert "| 0.750 |" in markdown(rows, "x")


# -- MIPLIB's published answers ------------------------------------------------------


def test_the_solution_file_gives_proven_optima_and_infeasibility_only(tmp_path):
    from bench.mps import SOLU_FILE, known_optima

    (tmp_path / SOLU_FILE).write_text(
        "=opt=      pk1                                      11\n"
        "=opt=      glass4                                   1200012599.972384\n"
        "=inf=      bnatt500\n"
        "=best=     some-open-one                            42\n"
    )
    assert known_optima(str(tmp_path)) == {"pk1": 11.0, "glass4": 1200012599.972384, "bnatt500": "infeasible"}
    assert known_optima(str(tmp_path / "nowhere")) == {}


def test_an_answer_the_backends_agree_on_is_still_wrong_if_miplib_says_otherwise():
    """Both backends say 12 for pk1; MIPLIB proved 11. Agreeing is not proof."""
    from bench.run import mark_against_known

    rows = [
        {"instance": "pk1", "status": "optimal", "objective": 12.0, "wrong": False},
        {"instance": "pk1", "status": "optimal", "objective": 12.0, "wrong": False},
        {"instance": "neos5", "status": "optimal", "objective": 15.0000001, "wrong": False},
        {"instance": "neos5", "status": "feasible", "objective": 16.0, "wrong": False},
        {"instance": "bnatt500", "status": "optimal", "objective": 3.0, "wrong": False},
        {"instance": "unknown", "status": "optimal", "objective": 1.0, "wrong": False},
    ]
    mark_against_known(rows, {"pk1": 11.0, "neos5": 15.0, "bnatt500": "infeasible"})
    assert [r["wrong"] for r in rows] == [True, True, False, False, True, False]
    assert rows[0]["known"] == 11.0 and rows[-1]["known"] is None


def test_an_unproven_answer_better_than_the_published_optimum_is_wrong():
    """Minimising pk1 (optimum 11): a feasible 10 is impossible; 14 is just
    unfinished. Maximising the same way round."""
    from bench.run import mark_against_known

    rows = [
        {"instance": "pk1", "status": "feasible", "objective": 10.0, "wrong": False, "sense": "minimize"},
        {"instance": "pk1", "status": "feasible", "objective": 14.0, "wrong": False, "sense": "minimize"},
        {"instance": "m", "status": "feasible", "objective": 101.0, "wrong": False, "sense": "maximize"},
        {"instance": "m", "status": "feasible", "objective": 99.0, "wrong": False, "sense": "maximize"},
    ]
    mark_against_known(rows, {"pk1": 11.0, "m": 100.0})
    assert [r["wrong"] for r in rows] == [True, False, True, False]


# -- flow shop: two formulations of one problem ---------------------------------------


def _johnson(duration: dict, jobs: list[str], machines: list[str]) -> int:
    """The optimal makespan of a two-machine flow shop, by Johnson's rule
    (1954): jobs faster on the first machine go first, shortest first; the
    rest go last, longest second-machine time first. Shares nothing with
    either formulation."""
    first, second = machines
    early = sorted((j for j in jobs if duration[(j, first)] < duration[(j, second)]), key=lambda j: duration[(j, first)])
    late = sorted((j for j in jobs if duration[(j, first)] >= duration[(j, second)]), key=lambda j: -duration[(j, second)])
    a = b = 0
    for j in early + late:
        a += duration[(j, first)]
        b = max(a, b) + duration[(j, second)]
    return b


def _optimum(family: str, size: str, instance: int, backend: str | None = None):
    from app.solve import compile_model
    from app.solve.backends import by_name, choose
    from app.solve.classify import classify
    from app.solve.convexity import refine
    from app.solve.service import solve_compiled

    case = generate(family, size, instance)
    compiled = compile_model(case.ir, case.data)
    chosen, _ = choose(refine(classify(case.ir, case.data), compiled), backend)
    result, _ = solve_compiled(chosen, compiled, time_limit=60, seed=1)
    return chosen.name, result.status, result.objective


@pytest.mark.parametrize("instance", range(3))
def test_both_flow_shop_formulations_find_johnsons_makespan(instance):
    from bench.families import _flow_shop_facts

    jobs, machines, duration, horizon = _flow_shop_facts("S", instance)
    expected = _johnson(duration, jobs, machines)
    assert expected <= horizon
    assert _optimum("flow_shop", "S", instance) == ("cp-sat", "optimal", expected)
    for backend in ("cp-sat", "highs"):
        assert _optimum("flow_shop_timed", "S", instance, backend) == (backend, "optimal", expected)


def test_the_formulations_agree_on_three_machines():
    """No rule gives this one by hand; the two models share only the data."""
    interval = _optimum("flow_shop", "M", 0)
    timed = _optimum("flow_shop_timed", "M", 0)
    assert interval[1] == timed[1] == "optimal"
    assert interval[2] == timed[2]


def test_only_the_time_indexed_model_grows_with_the_horizon():
    from app.solve import compile_model

    sizes = {}
    for family in ("flow_shop", "flow_shop_timed"):
        for size in ("S", "M"):
            case = generate(family, size, 0)
            sizes[family, size] = len(compile_model(case.ir, case.data).variables)
    # Interval: begin and finish per operation, and the makespan.
    assert sizes["flow_shop", "S"] == 2 * 4 * 2 + 1
    # Timed: run and start per operation and slot -- the horizon times more.
    assert sizes["flow_shop_timed", "M"] > 20 * sizes["flow_shop", "M"]


def test_the_nightly_leaves_out_the_comparison_only_families(monkeypatch, tmp_path):
    from bench import nightly
    from bench import run as bench_run
    from bench.families import COMPARISON_ONLY

    seen = {}

    def fake_main(argv):
        seen["family"] = argv[argv.index("--family") + 1].split(",")
        (tmp_path / "2026-01-01.json").write_text("[]")
        return 0

    monkeypatch.setattr(bench_run, "main", fake_main)
    assert nightly.main(["--out-dir", str(tmp_path), "--night", "2026-01-01", "--no-store"]) == 0
    assert "flow_shop" in seen["family"]
    assert not COMPARISON_ONLY & set(seen["family"])


def test_the_iis_bench_measures_both_ways_on_a_planted_conflict():
    from bench.iis import measure

    row = measure("feed_blend", "S", probe_seconds=2.0)
    assert row["status"] == "infeasible"
    assert row["deletion"]["method"] == "deletion" and row["iis"]["method"] == "iis"
    assert row["deletion"]["minimal"] and row["iis"]["minimal"] and row["same_rules"]
    # The batch and the nutrient floor it cannot meet.
    assert row["iis"]["rules"] == ["c_batch", "c_need"]
    assert row["iis"]["probes"] < row["deletion"]["probes"]


def test_the_warm_bench_perturbs_a_small_share_of_the_data_the_same_way_each_time():
    from bench.warm import perturb

    case = generate("rota", "M", 0)
    one, two = perturb(case.data, "seed"), perturb(case.data, "seed")
    assert one == two and one != case.data
    before = [row["value"] for row in case.data["parameters"]["demand"]]
    after = [row["value"] for row in one["parameters"]["demand"]]
    changed = sum(a != b for a, b in zip(before, after))
    assert 0 <= changed <= max(1, round(0.05 * len(before)) + 1)
    # Whole numbers stay whole: a demand of 2.3 people is not a perturbation.
    assert all(isinstance(value, int) for value in after)
