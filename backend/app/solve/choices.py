"""On/off choices a run makes before it solves, learnt from the problem's own runs (9 October 2026).

Before a solve the platform may build a start (slope scaling, a spanning tree, a greedy pass ...), add rows a
relaxation breaks, or race two forms. Each helps on some models and only costs time on others, and nothing read
off the model says which in advance. Most runs re-solve a problem already solved -- new data, the same shape --
so each choice is learnt from the problem's own history, the same way for every choice:

1. **On by default.** A choice no run of the problem has tried yet stays as the platform's default.
2. **Tried off, safely.** Once `TRIALS` runs with it on have *proved* their answers (an optimum, or that there is
   none), the next run tries it off -- never earlier, so a problem that needs the choice to find any answer at
   all is never left without one -- until it has `TRIALS` runs each way.
3. **Kept where it is faster.** Each run is scored by the time it took to prove its answer, or -- unproven -- by
   the whole time allowed plus its gap (an unproven run counts as slower than any proven one). The way with the
   lower median is used.
4. **Checked again.** Every `RECHECK` runs the other way is tried once more: the data may have changed which is
   faster.

Each run records its choices (`params.choices`: on or off, and why), so the history is the runs themselves.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Any

#: Runs each way before a choice is decided.
TRIALS = 2
#: Runs on the decided way before the other is tried again.
RECHECK = 10
#: How far back a choice looks.
RECENT = 30


@dataclass(frozen=True)
class Decided:
    on: bool
    evidence: str


def _score(run: dict[str, Any]) -> float:
    """Seconds to prove, or for an unproven run the time allowed times (1 + gap) -- always above a proof."""
    seconds = float(run.get("seconds") or 0.0)
    limit = float(run.get("limit") or seconds or 1.0)
    if run.get("status") in ("optimal", "infeasible", "unbounded"):
        return seconds
    gap = run.get("gap")
    return limit * (2.0 + (float(gap) if gap is not None else 1.0))


def decide(name: str, history: list[dict[str, Any]]) -> Decided:
    """`history`: this problem's recent runs, newest first, each {on, status, seconds, limit, gap} for this
    choice (runs that did not make it are left out)."""
    history = history[:RECENT]
    on = [r for r in history if r.get("on")]
    off = [r for r in history if not r.get("on")]
    proved = ("optimal", "infeasible", "unbounded")
    proven_on = [r for r in on if r.get("status") in proved]
    if len(off) < TRIALS:
        if any(r.get("status") not in proved for r in off) and proven_on:
            return Decided(True, f"{name}: on -- a run without it did not prove its answer, every run with it did")
        if len(proven_on) >= TRIALS:
            return Decided(False, f"{name}: tried off ({len(off) + 1} of {TRIALS}) -- {len(proven_on)} runs with it "
                                  "on proved their answers, so this run can learn whether it is needed")
        return Decided(True, f"{name}: on (the default" + (
            f"; {len(proven_on)} of {TRIALS} proven runs with it on before it is tried off)" if on else ")"))
    if len(on) < TRIALS:
        return Decided(True, f"{name}: on ({len(on) + 1} of {TRIALS} runs each way)")
    med_on = median(_score(r) for r in on[:RECENT])
    med_off = median(_score(r) for r in off[:RECENT])
    better = med_on <= med_off
    # Runs since the last run the other way: time to check it again?
    since = 0
    for r in history:
        if bool(r.get("on")) != better:
            break
        since += 1
    said = (f"{name}: {'on' if better else 'off'} -- median {_seconds(med_on)} with it, {_seconds(med_off)} "
            f"without, over this problem's recent runs")
    if since >= RECHECK:
        return Decided(not better, said + f"; {RECHECK} runs since the other way was tried, so it is tried again")
    return Decided(better, said)


def _seconds(value: float) -> str:
    return f"{value * 1000:.3g} ms" if value < 1 else f"{value:.3g} s"
