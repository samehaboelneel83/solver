"""Relax-and-fix over a time horizon (queue R9, target roadmap Phase 13).

A model laid out over time -- a rota over days, a plan over weeks -- can be
too large to solve whole but easy a stretch at a time. Relax-and-fix walks
the horizon in windows: window k's whole-number decisions are kept whole,
every later period's are relaxed to fractions (so the future still pulls on
today's choices), every earlier period is held at what was already decided;
solve, fix window k, move on. The last window leaves nothing relaxed, so its
answer is an answer to the whole model.

**Which set is time.** The domain says so: a set whose entity type has the
role `time`. Its members come in the frozen data's own order (sort order,
then key) -- the order periods follow.

**What it claims.** A heuristic: each window is decided without the later
ones' whole-number truth, so the answer is `feasible` and claims nothing
about being best (`optimality = none`). A window with no answer leaves the
run with none, and says which window.

Decisions not indexed by time are kept whole in every window and decided
with the last. A backend that holds no fractions (CP-SAT) solves the windows
on HiGHS instead, and the run says so.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any, Callable

from app.solve.compile import Compiled, VarKey

#: Windows the horizon is cut into.
WINDOWS = 4
#: Fewer periods than this per window, and the model is small enough to solve whole.
MIN_PERIODS = 2


def time_positions(compiled: Compiled, time_set: str) -> dict[str, int]:
    """variable name -> the position of the time set in its index."""
    return {name: index.index(time_set) for name, index in compiled.var_index_sets.items() if time_set in index}


def applies(compiled: Compiled, time_set: str | None, periods: list[str]) -> str | None:
    """None when relax-and-fix applies, else why not (recorded on the run)."""
    if time_set is None:
        return "no set in this model is time (an entity type with the role time)"
    if not any(var.is_integral for var in compiled.variables.values()):
        return "nothing is a whole number: there is nothing to relax"
    if not time_positions(compiled, time_set):
        return f"no decision is indexed by {time_set}"
    if len(periods) < MIN_PERIODS * 2:
        return f"{time_set} has {len(periods)} periods: too few to cut into windows"
    if compiled.objective_mode != "weighted":
        return "a goal in order of importance is solved stage by stage"
    return None


def windows(periods: list[str], count: int = WINDOWS) -> list[list[str]]:
    """The periods cut into `count` consecutive windows, as even as they go."""
    count = max(1, min(count, len(periods) // MIN_PERIODS))
    size = math.ceil(len(periods) / count)
    return [periods[i:i + size] for i in range(0, len(periods), size)]


def _period(key: VarKey, positions: dict[str, int]) -> str | None:
    position = positions.get(key[0])
    return key[1][position] if position is not None and len(key[1]) > position else None


def step(compiled: Compiled, positions: dict[str, int], window: set[str], later: set[str],
         fixed: dict[VarKey, Any]) -> Compiled:
    """One window's model: earlier periods held, this one whole, later ones relaxed."""
    variables = dict(compiled.variables)
    for key, var in compiled.variables.items():
        if key in fixed:
            value = Decimal(str(round(float(fixed[key]))))
            variables[key] = replace(var, lower=value, upper=value)
        elif var.is_integral and _period(key, positions) in later:
            variables[key] = replace(var, domain="continuous")
    return replace(compiled, variables=variables)


@dataclass
class Rolled:
    solution: Any
    record: dict[str, Any]


def solve(compiled: Compiled, time_set: str, periods: list[str], run: Callable[[Compiled, float], Any], *,
          time_limit: float, should_stop: Callable[[], bool] | None = None, clock=time.monotonic) -> Rolled:
    """`run(model, seconds) -> Solution`. Every window gets an equal share of the time."""
    started = clock()
    positions = time_positions(compiled, time_set)
    cut = windows(periods)
    fixed: dict[VarKey, Any] = {}
    steps: list[dict[str, Any]] = []
    solution = None
    for k, window in enumerate(cut):
        if should_stop and should_stop():
            break
        later = {p for w in cut[k + 1:] for p in w}
        left = time_limit - (clock() - started)
        share = max(0.5, left / (len(cut) - k))
        solution = run(step(compiled, positions, set(window), later, fixed), share)
        steps.append({"window": [window[0], window[-1]], "status": solution.status, "objective": solution.objective})
        if solution.objective is None:
            record = {"time_set": time_set, "windows": len(cut), "steps": steps,
                      "why": f"the window {window[0]}..{window[-1]} has no answer with the earlier windows held"}
            return Rolled(replace(solution, status="unknown", optimal=False, objective=None, assignments={}), record)
        for key, var in compiled.variables.items():
            if var.is_integral and _period(key, positions) in window:
                fixed[key] = solution.assignments.get(key, 0)
    assert solution is not None
    record = {"time_set": time_set, "windows": len(cut), "steps": steps}
    # The last window relaxed nothing: its answer answers the whole model -- a heuristic's, never proven best.
    return Rolled(replace(solution, status="feasible", optimal=False, best_bound=None,
                          wall_seconds=round(clock() - started, 3)), record)
