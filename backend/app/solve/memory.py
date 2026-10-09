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



#: Races a form must win in a row (each with a proof) before it is used alone.
FORM_WINS = 3
#: Runs on a remembered form before the forms race again (the data may have changed what is faster).
FORM_RECHECK = 10


@dataclass(frozen=True)
class Form:
    form: str
    evidence: str


def recall_form(history: list[dict]) -> Form | None:
    """`history`: the problem's recent `strengthen_run.forms` records, newest first -- races (`raced`) and runs
    that used a remembered form (`remembered`). The form that won the last `FORM_WINS` races, each by a proof,
    unless `FORM_RECHECK` runs have used it since the last race (then race again); else None."""
    since = 0
    races: list[dict] = []
    for entry in history:
        if entry.get("remembered"):
            if not races:
                since += 1
            continue
        if entry.get("raced"):
            races.append(entry)
        if len(races) >= FORM_WINS:
            break
    if len(races) < FORM_WINS or since >= FORM_RECHECK:
        return None
    winners = {race.get("won") for race in races}
    if len(winners) != 1:
        return None
    won = winners.pop()
    proofs = [next((r for r in race.get("raced", []) if r.get("solver") == won), {}) for race in races]
    if not all(p.get("status") == "optimal" for p in proofs):
        return None
    seconds = [p.get("seconds") for p in proofs if p.get("seconds") is not None]
    evidence = (f"remembered: the model {won} proved the last {len(races)} races between the two forms on this "
                f"problem first" + (f" (in {_seconds(median(seconds))} median)" if seconds else "")
                + f"; races again after {FORM_RECHECK - since} more runs")
    return Form(won, evidence)
