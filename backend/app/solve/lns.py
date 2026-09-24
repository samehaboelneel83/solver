"""Large-neighbourhood search: fix most of the answer, solve the rest again (queue R3).

For an integer model the chosen solver has not proved within a share of the
time (`FIRST_SHARE`) -- a solve that has stalled -- the rest of the time goes
to improving the answer it has: most integer decisions are held at their
value, the rest ("the neighbourhood") are freed, and the same solver solves
that smaller model from the answer it has, over and over. A better answer is
kept. Which decisions to free is decided by the model's own structure, not
by variable number:

- `entity` -- everything that touches a few entities (one nurse's week, one
  depot's items);
- `rule` -- the decisions a few rule instances share, and so the ones that
  trade off against each other;
- `window` -- a run of consecutive members of one index (a stretch of days);
- `random` -- a random share, for diversity.

Each operator's weight grows with the improvements it finds and shrinks when
it finds none (adaptive LNS); a neighbourhood solved to its own optimum with
nothing better found grows, since the answer is locally best at that size.

**What the answer claims.** The first solve's proven bound still holds for
the whole model, so the gap is honest; unless the answer meets it, the run
is `feasible` -- a heuristic's answer, never called optimal. CP-SAT runs its
own LNS inside, so this is for HiGHS and the MILP wrapper.
"""

from __future__ import annotations

import random as random_module
import time
from dataclasses import dataclass, replace
from typing import Any, Callable

from app.solve.compile import Compiled, VarKey

#: The share of the time the solver gets alone before LNS takes over.
FIRST_SHARE = 0.3
#: Each neighbourhood's solve: a twentieth of the time, at least a second.
SUB_SHARE, SUB_MIN_S = 0.05, 1.0
#: The share of integer decisions a neighbourhood frees, and how far it may grow.
START_FREE, MAX_FREE = 0.2, 0.6
OPERATORS = ("entity", "rule", "window", "random")
#: The backends this helps: CP-SAT has its own LNS.
FOR = frozenset({"highs", "milp"})

Run = Callable[[Compiled, float, dict | None], Any]


def applies(backend: str, compiled: Compiled) -> str | None:
    """None when LNS may be used, else why not (recorded on the run)."""
    if backend not in FOR:
        return f"{backend} searches neighbourhoods itself" if backend == "cp-sat" else f"not for {backend}"
    if not _decisions(compiled):
        return "the model has no integer decisions to fix"
    if compiled.objective_mode != "weighted":
        return "a goal in order of importance is solved stage by stage"
    return None


def _decisions(compiled: Compiled) -> list[VarKey]:
    """Integer decisions of the model itself -- not the compiler's own auxiliaries (`__…`)."""
    return [key for key, var in compiled.variables.items() if var.is_integral and not key[0].startswith("__")]


def _better(a, b, sense: str) -> bool:
    if a is None:
        return False
    if b is None:
        return True
    tolerance = 1e-9 * max(1.0, abs(float(b)))
    return float(a) < float(b) - tolerance if sense == "minimize" else float(a) > float(b) + tolerance


# -- the neighbourhoods -------------------------------------------------------------------------


def neighbourhood(operator: str, compiled: Compiled, decisions: list[VarKey], share: float,
                  rng: random_module.Random) -> set[VarKey]:
    """The decisions to free this round: about `share` of them, chosen by `operator`."""
    target = max(1, int(round(share * len(decisions))))
    wanted = set(decisions)
    free: set[VarKey] = set()
    if operator == "random":
        return set(rng.sample(decisions, min(target, len(decisions))))
    if operator == "entity":
        members = sorted({member for _, index in decisions for member in index})
        rng.shuffle(members)
        by_member: dict[str, list[VarKey]] = {}
        for key in decisions:
            for member in key[1]:
                by_member.setdefault(member, []).append(key)
        for member in members:
            if len(free) >= target:
                break
            free.update(by_member.get(member, ()))
        return free
    if operator == "rule":
        rules = list(compiled.constraints)
        rng.shuffle(rules)
        for rule in rules:
            if len(free) >= target:
                break
            free.update(k for k in (*rule.left.coeffs, *rule.right.coeffs) if k in wanted)
        return free
    if operator == "window":
        # One index position of one decision, its members in order, a run of them.
        shaped = sorted({(key[0], position) for key in decisions for position in range(len(key[1]))})
        if not shaped:
            return set(rng.sample(decisions, min(target, len(decisions))))
        name, position = rng.choice(shaped)
        order = sorted({key[1][position] for key in decisions if key[0] == name and len(key[1]) > position})
        start = rng.randrange(len(order))
        for member in order[start:] + order[:start]:
            if len(free) >= target:
                break
            free.update(key for key in decisions if len(key[1]) > position and key[1][position] == member)
        return free
    raise ValueError(f"unknown operator {operator!r}")


def fixed(compiled: Compiled, incumbent: dict[VarKey, Any], free: set[VarKey]) -> Compiled:
    """The model with every integer decision outside `free` held at its value in `incumbent`."""
    variables = dict(compiled.variables)
    for key in _decisions(compiled):
        if key in free or key not in incumbent:
            continue
        value = type(variables[key].lower)(str(round(float(incumbent[key]))))
        variables[key] = replace(variables[key], lower=value, upper=value)
    return replace(compiled, variables=variables)


# -- the search -------------------------------------------------------------------------------


@dataclass
class Searched:
    solution: Any
    #: What happened, for the run's record.
    record: dict[str, Any]


def search(compiled: Compiled, run: Run, *, time_limit: float, seed: int | None = None,
           should_stop: Callable[[], bool] | None = None, clock=time.monotonic) -> Searched:
    """`run(model, seconds, hint) -> Solution` solves with the chosen solver. The first solve gets
    `FIRST_SHARE` of the time; unless it settled the model, neighbourhoods get the rest."""
    from app.solve.service import OPTIMAL_GAP, gap_of

    started = clock()
    first = run(compiled, max(SUB_MIN_S, FIRST_SHARE * time_limit), None)
    if first.status != "feasible" or first.objective is None:
        # Proved, proved there is none, or found nothing to improve: nothing for LNS to do.
        return Searched(first, {"used": False, "why": f"the first solve ended {first.status}"})

    rng = random_module.Random(seed if seed is not None else 0)
    decisions = _decisions(compiled)
    weights = {op: 1.0 for op in OPERATORS}
    share = START_FREE
    best, bound = first, first.best_bound
    rounds, improvements, by_operator = 0, 0, {op: 0 for op in OPERATORS}
    while not (should_stop and should_stop()):
        left = time_limit - (clock() - started)
        if left < SUB_MIN_S:
            break
        operator = rng.choices(OPERATORS, weights=[weights[op] for op in OPERATORS])[0]
        free = neighbourhood(operator, compiled, decisions, share, rng)
        rounds += 1
        sub = run(fixed(compiled, best.assignments, free), min(left, max(SUB_MIN_S, SUB_SHARE * time_limit)),
                  best.assignments)
        if sub.objective is not None and _better(sub.objective, best.objective, compiled.sense):
            best = sub
            improvements += 1
            by_operator[operator] += 1
            weights[operator] += 1.0
        else:
            weights[operator] = max(0.1, weights[operator] * 0.8)
            if sub.status == "optimal":
                # This size of neighbourhood is exhausted around the answer: look wider.
                share = min(MAX_FREE, share * 1.25)

    gap = gap_of(best.objective, bound)
    proven = gap is not None and gap <= OPTIMAL_GAP
    solution = replace(best, status="optimal" if proven else "feasible", optimal=proven, best_bound=bound,
                       wall_seconds=round(clock() - started, 3), solver=first.solver)
    return Searched(solution, {
        "used": True, "first_status": first.status, "first_objective": first.objective, "rounds": rounds,
        "improvements": improvements, "by_operator": by_operator, "final_share": round(share, 3),
        "first_share_s": round(max(SUB_MIN_S, FIRST_SHARE * time_limit), 3),
    })
