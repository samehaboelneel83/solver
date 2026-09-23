"""Solver options behind the benchmark gate (app.solve.params).

Only whitelisted options, with whitelisted values, ever reach a solver; the
enabled ones (the bench's winners) reach every solve of their backend; and
none of them may change an answer -- only how fast it comes.
"""

from __future__ import annotations

import pytest

from app.solve import params
from app.solve.backends import by_name
from app.solve.service import solve_compiled
from tests.test_warm_start import _knapsack


def test_only_whitelisted_options_and_values_pass():
    assert params.check("cp-sat", {"linearization_level": 2}) == {"linearization_level": 2}
    with pytest.raises(ValueError, match="not a whitelisted option"):
        params.check("cp-sat", {"max_time_in_seconds": 1})
    with pytest.raises(ValueError, match="not a whitelisted value"):
        params.check("highs", {"presolve": "maybe"})
    # A backend with no whitelist takes none.
    with pytest.raises(ValueError):
        params.check("glop", {"presolve": "off"})
    assert params.check("glop", None) == {}


def test_enabled_options_apply_unless_a_request_overrides_them(monkeypatch):
    monkeypatch.setattr(params, "ENABLED", {"highs": {"presolve": "on"}})
    assert params.check("highs", None) == {"presolve": "on"}
    assert params.check("highs", {"presolve": "off"}) == {"presolve": "off"}
    assert params.check("scip", None) == {}


def test_a_command_line_value_is_read_as_the_whitelist_types_it():
    assert params.parse("highs", "mip_heuristic_effort", "0.3") == 0.3
    assert params.parse("cp-sat", "symmetry_level", "4") == 4
    assert params.parse("scip", "presolving", "fast") == "fast"
    with pytest.raises(ValueError):
        params.parse("cp-sat", "symmetry_level", "7")


CASES = [
    ("cp-sat", {"linearization_level": 0}),
    ("cp-sat", {"linearization_level": 2, "symmetry_level": 0}),
    ("highs", {"presolve": "off"}),
    ("highs", {"mip_heuristic_effort": 0.3}),
    ("scip", {"presolving": "fast"}),
    ("scip", {"heuristics": "aggressive"}),
]


@pytest.mark.parametrize("backend_name, options", CASES, ids=[f"{b}-{sorted(o)}" for b, o in CASES])
def test_an_option_changes_how_fast_not_what(backend_name, options):
    backend = by_name(backend_name)
    if not backend.is_available():
        pytest.skip(f"{backend_name} is not in this build")
    result, _ = solve_compiled(backend, _knapsack(), time_limit=10, seed=1, solver_params=options)
    assert (result.status, result.objective) == ("optimal", 17)


@pytest.mark.parametrize("backend_name", ["cp-sat", "highs", "scip"])
def test_an_option_nobody_measured_is_refused_before_any_solve(backend_name):
    backend = by_name(backend_name)
    if not backend.is_available():
        pytest.skip(f"{backend_name} is not in this build")
    with pytest.raises(ValueError, match="not a whitelisted option"):
        solve_compiled(backend, _knapsack(), time_limit=10, seed=1, solver_params={"threads": 64})


def test_the_bench_measures_an_option_on_its_own_solver_default_first():
    from bench.run import parse_technique

    technique = parse_technique("highs.presolve=choose,off")
    assert (technique.name, technique.values) == ("highs.presolve", ["choose", "off"])
    with pytest.raises(SystemExit):
        parse_technique("highs.threads=1,2")
    with pytest.raises(SystemExit):
        parse_technique("cp-sat.symmetry_level=2,9")


def test_scips_fast_presolve_is_the_one_winner_enabled():
    """The gate's verdict, pinned: a change to it is a change to a measured
    default, and belongs with a new report."""
    assert params.ENABLED == {"scip": {"presolving": "fast"}}
    assert params.check("scip", None) == {"presolving": "fast"}
    assert params.check("highs", None) == {} and params.check("cp-sat", None) == {}
