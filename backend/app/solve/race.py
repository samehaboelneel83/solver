"""The probe race: a short run of every admissible solver, then the best one goes on (queue 17b).

For a problem with no memory to go on (`app.solve.memory`), which solver
suits it is a guess the rules make from its class alone. A probe asks the
model itself: each admissible solver runs for a few seconds at once, the
threads shared out, and the best of them continues for the rest of the time
-- proven first (fastest), then the smallest gap, then the better answer. A
probe that proves the optimum is the answer; nothing is solved twice.

Skipped for a small model, which the rules' choice settles faster than a
race could start (`should_race`), and for a robust run or a trade-off front,
which solve something other than the model as written. Behind the setting
`solve.probe`, whose default the bench decides. What the probes found is
recorded on the run, and `why_solver` says why the winner won.
"""

from __future__ import annotations

import math
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Callable

PROBE_MAX, PROBE_MIN, PROBE_SHARE = 5.0, 1.0, 0.1
#: Below both, the rules' choice is faster than starting a race.
FLOOR_DECISIONS, FLOOR_ROWS = 200, 100


def probe_seconds(time_limit: float) -> float:
    """A tenth of the time allowed, between one and five seconds."""
    return min(PROBE_MAX, max(PROBE_MIN, PROBE_SHARE * float(time_limit)))


def should_race(fingerprint: dict[str, Any] | None, candidates: list[str], time_limit: float) -> str | None:
    """None when a race is worth running, else why not (recorded on the run)."""
    if not candidates:
        return "no solver that proves its answer takes this model"
    if len(candidates) < 2:
        return "only one solver takes this model"
    if time_limit < 3 * probe_seconds(time_limit):
        return "the time allowed is too short to share with probes"
    if fingerprint and fingerprint.get("variables", 0) < FLOOR_DECISIONS and fingerprint.get("rows", 0) < FLOOR_ROWS:
        return "the model is small enough for the rules' choice to settle it at once"
    return None


@dataclass(frozen=True)
class Raced:
    winner: str
    #: The winner's probe when it proved the optimum: the run's answer as it stands.
    answer: Any | None
    evidence: str
    record: list[dict[str, Any]]
    probe_s: float


def _gap(solution) -> float | None:
    objective, bound = solution.objective, solution.best_bound
    if objective is None or bound is None:
        return None
    objective, bound = float(objective), float(bound)
    return 0.0 if objective == bound else abs(objective - bound) / max(abs(objective), 1e-9)


def _key(solution, sense: str) -> tuple:
    proven = solution.status == "optimal"
    gap = _gap(solution)
    objective = solution.objective
    better = math.inf if objective is None else (float(objective) if sense == "minimize" else -float(objective))
    return (
        0 if proven else 1,
        solution.wall_seconds if proven else 0.0,
        math.inf if gap is None else gap,
        better,
    )


def _said(name: str, solution) -> str:
    if solution.status == "optimal":
        return f"{name} proved it in {solution.wall_seconds:.3g} s"
    gap = _gap(solution)
    if solution.objective is None:
        return f"{name} found no answer"
    return f"{name} {'gap ' + format(gap * 100, '.3g') + '%' if gap is not None else 'had an answer, no bound'}"


def run_race(candidates: list[str], run_one: Callable[[str, float, int, Callable[[], bool]], Any], *, workers: int,
             time_limit: float, sense: str, rule: str) -> Raced:
    """`run_one(solver, seconds, workers, should_stop) -> Solution`; the probes run at once with their share of
    threads, and the first proof stops the others -- a race is never slower than its fastest proof."""
    seconds = probe_seconds(time_limit)
    share = max(1, workers // len(candidates))
    proved = threading.Event()
    results: dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=len(candidates)) as pool:
        futures = {pool.submit(run_one, name, seconds, share, proved.is_set): name for name in candidates}
        for future in as_completed(futures):
            results[futures[future]] = future.result()
            if results[futures[future]].status == "optimal":
                proved.set()
    results = {name: results[name] for name in candidates}
    record = [
        {"solver": name, "status": s.status, "objective": s.objective, "bound": s.best_bound,
         "gap": _gap(s), "seconds": round(s.wall_seconds, 3)}
        for name, s in results.items()
    ]
    answered = [name for name, s in results.items() if s.objective is not None]
    if not answered:
        return Raced(rule, None, f"probe race ({seconds:.3g} s each): no probe found an answer; the rules' choice, "
                                 f"{rule}, continues", record, seconds)
    winner = min(answered, key=lambda name: _key(results[name], sense))
    others = "; ".join(_said(n, results[n]) for n in candidates if n != winner)
    evidence = f"probe race ({seconds:.3g} s each): {_said(winner, results[winner])}" + (f"; {others}" if others else "")
    proven = results[winner].status == "optimal"
    return Raced(winner, results[winner] if proven else None,
                 evidence + ("" if proven else f" -- {winner} continues"), record, seconds)
