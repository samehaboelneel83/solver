"""Per-problem memory: the solver that proved this problem fastest before (queue 17a).

Most runs re-solve a problem already solved -- new data, the same shape. So
before the rules pick a solver, this asks the problem's own history: of its
recent runs proven optimal, which admissible solver proved them in the least
time? That one is used, and `why_solver` quotes the evidence.

Conservative on purpose: only proven runs count (a fast "feasible" is not a
proof); a solver needs `MIN_RUNS` of them (one lucky run decides nothing);
only solvers the rules admit for *this* model are candidates (history never
routes a model to a backend that cannot take it); a solver named on the run
or by the `solve.solver` setting overrides it. Behind the setting
`solve.memory`, whose default the bench decides.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median

#: How far back a problem remembers, in settled runs.
RECENT = 20
#: Proven runs a solver needs before its median means anything.
MIN_RUNS = 2


@dataclass(frozen=True)
class Recalled:
    solver: str
    #: The sentence `why_solver` records.
    evidence: str


def recall(history: list[tuple[str, float]], admissible: set[str]) -> Recalled | None:
    """`history`: (solver, seconds) of the problem's recent proven runs, newest
    first. The admissible solver with the least median time over at least
    `MIN_RUNS` of them, or None."""
    times: dict[str, list[float]] = {}
    for solver, seconds in history[:RECENT]:
        if solver in admissible and seconds is not None:
            times.setdefault(solver, []).append(float(seconds))
    proven = {s: t for s, t in times.items() if len(t) >= MIN_RUNS}
    if not proven:
        return None
    ranked = sorted(proven, key=lambda s: (median(proven[s]), s))
    best = ranked[0]
    said = [f"{best} proved {len(proven[best])} of this problem's recent runs in a median {_seconds(median(proven[best]))}"]
    said += [f"{s} {len(proven[s])} in {_seconds(median(proven[s]))}" for s in ranked[1:]]
    return Recalled(best, "remembered: " + "; ".join(said))


def _seconds(value: float) -> str:
    """Three figures, in milliseconds under a second: "0 s" says nothing."""
    return f"{value * 1000:.3g} ms" if value < 1 else f"{value:.3g} s"

