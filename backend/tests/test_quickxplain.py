"""Epic engine, E-5: QuickXplain in the conflict filter.

The filter is judged by an oracle here, not a solver: a set of candidates is
"infeasible" exactly when it contains every member of some hidden conflict.
That is what the filter's probes answer, and it makes irreducibility and the
probe count exact to check.
"""

from __future__ import annotations

import random

import pytest

from app.solve.diagnose import QUICK_ABOVE, _delete, _filter, _quick


def _oracle(conflicts: list[set[int]], log: list[int]):
    def still_infeasible(subset: list[int]) -> bool:
        log.append(1)
        present = set(subset)
        return any(conflict <= present for conflict in conflicts)

    return still_infeasible


def _irreducible(found: list[int], conflicts: list[set[int]]) -> bool:
    present = set(found)
    holds = any(c <= present for c in conflicts)
    each_needed = all(not any(c <= present - {x} for c in conflicts) for x in found)
    return holds and each_needed


@pytest.mark.parametrize("seed", range(20))
def test_quickxplain_finds_an_irreducible_conflict_among_many(seed):
    rng = random.Random(seed)
    n = rng.randint(QUICK_ABOVE + 1, 400)
    conflicts = [set(rng.sample(range(n), rng.randint(1, 5))) for _ in range(rng.randint(1, 3))]
    found, stopped = _quick(list(range(n)), _oracle(conflicts, []))
    assert not stopped
    assert _irreducible(found, conflicts)


def test_it_asks_far_fewer_probes_than_one_at_a_time():
    n, conflict = 300, [{17, 150, 299}]
    quick, slow = [], []
    a, _ = _quick(list(range(n)), _oracle(conflict, quick))
    b, _ = _delete(list(range(n)), _oracle(conflict, slow))
    assert sorted(a) == sorted(b) == [17, 150, 299]
    assert len(slow) == n
    assert len(quick) < n / 5


def test_the_filter_picks_quickxplain_only_above_the_threshold():
    small, large = [], []
    _filter(list(range(QUICK_ABOVE)), _oracle([{3}], small))
    _filter(list(range(200)), _oracle([{3}], large))
    assert len(small) == QUICK_ABOVE  # one probe per candidate: the deletion filter
    assert len(large) < 40


def test_a_probe_that_cannot_decide_stops_it_and_says_so():
    calls = []

    def undecided(subset):
        calls.append(1)
        return None if len(calls) == 3 else len(subset) > 50

    found, stopped = _quick(list(range(100)), undecided)
    assert stopped and found == list(range(100))


def test_equal_candidates_are_told_apart_by_position():
    # Two instances that compare equal: only one of them is needed.
    items = ["same"] * 20

    def needs_one(subset):
        return len(subset) >= 1

    found, stopped = _quick(items, needs_one)
    assert not stopped and found == ["same"]
