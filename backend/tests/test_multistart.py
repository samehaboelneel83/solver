"""Epic engine, E-2: IPOPT from several starting points.

IPOPT follows the slope from where it starts, so on a goal with several peaks
one start finds the nearest. `sin(x) + x/10` over [0, 20] has peaks near 1.7,
7.9 and 14.2 and its best value at the bound x = 20 (about 2.91); from the
middle of the range (x = 10) IPOPT climbs to the peak near 7.9 (about 1.78).
"""

from __future__ import annotations

import math

import pytest

from app.solve import compile_model
from app.solve.backends import IPOPT, by_name
from app.solve.ipopt import spread
from app.solve.params import check, parse_setting
from app.solve.service import solve_compiled
from tests.test_functions import NO_DATA, X, _ir, fn, plus

pytestmark = pytest.mark.skipif(not IPOPT.is_available(), reason="casadi (IPOPT) is not installed in this image")

PEAKS = _ir(plus(fn("sin", X), {"mul": [{"const": 0.1}, X]}), "maximize", x=(0, 20))
BEST = math.sin(20) + 2.0


def _solve(starts: int | None, seed: int = 1):
    params = None if starts is None else {"starts": starts}
    return solve_compiled(by_name("ipopt"), compile_model(PEAKS, NO_DATA), time_limit=20, seed=seed,
                          solver_params=params)[0]


def test_one_start_finds_the_peak_nearest_the_middle():
    result = _solve(None)
    assert result.status == "optimal"
    assert result.objective == pytest.approx(math.sin(7.954) + 0.7954, abs=1e-2)
    assert "starts" not in result.solver


def test_several_starts_find_the_best_peak_and_say_how():
    result = _solve(8)
    assert result.status == "optimal"
    assert result.objective == pytest.approx(BEST, abs=1e-5)
    assert result.assignments[("x", ())] == pytest.approx(20, abs=1e-5)
    assert "from 8 starts" in result.solver


def test_multistart_is_reproducible_from_its_seed():
    a, b = _solve(4, seed=7), _solve(4, seed=7)
    assert a.objective == b.objective and a.assignments == b.assignments


def test_a_multistart_answer_is_still_only_local():
    # Several nearby optima are still nearby optima: the backend proves `local`.
    assert IPOPT.proves == "local"


def test_starts_are_spread_one_per_slice_of_each_range():
    points = spread([0.0, -1.0], [10.0, 1.0], 5, seed=3)
    assert len(points) == 5
    for column, (lo, hi) in zip(zip(*points), [(0.0, 10.0), (-1.0, 1.0)]):
        slices = sorted(int((v - lo) / (hi - lo) * 5) for v in column)
        assert slices == [0, 1, 2, 3, 4]
    assert spread([0.0], [1.0], 0, seed=1) == []


def test_an_unbounded_side_becomes_a_box_around_the_other():
    (point,) = spread([5.0], [float("inf")], 1, seed=1)
    assert 5.0 <= point[0] <= 1005.0


def test_starts_is_a_whitelisted_option_with_whitelisted_values():
    assert check("ipopt", {"starts": 8}) == {"starts": 8}
    assert parse_setting("ipopt.starts=16") == {"ipopt": {"starts": 16}}
    with pytest.raises(ValueError):
        check("ipopt", {"starts": 3})
