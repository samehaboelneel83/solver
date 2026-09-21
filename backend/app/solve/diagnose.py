"""When there is no answer, say which rules cannot hold at once.

`infeasible` on its own is the least useful true thing the platform can say.
The planner's question is never "is it infeasible" -- they already know, they
cannot build the roster -- it is *which rules are fighting, and over what*.

**Deletion filtering.** Drop a constraint and solve again. If the model is
still infeasible, that constraint was not part of the problem, so leave it
out; if it becomes solvable, the constraint is needed and goes back. What
survives is an *irreducible* infeasible set: every member matters, and
removing any single one makes the model solvable. That last property is the
whole value -- it turns "no answer" into a short list of rules a person can
act on, and it is exactly what the test asserts.

Two passes, because the answer is wanted at two grains. The first narrows to
the **rules** involved, which is the sentence a planner reads. The second
narrows those to the **instances** -- Thursday morning, not "coverage" --
which is what `run.conflict` is shaped for and what makes the sentence
checkable.

**The honest part.** Each probe is a solve, so this is bounded by a budget,
and a probe can time out without deciding. Either way the search stops early
and reports what it has with `minimal = False`: a *superset* of a conflict,
still true, but not proven irreducible. Reporting a truncated search as
though it were minimal would be a lie of exactly the kind this module exists
to prevent -- the caller must be able to tell "any of these removed fixes it"
from "somewhere in here".
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Callable

from app.solve.compile import Compiled, Constraint, Linear
from app.solve.result import Solution

SolveFn = Callable[..., Solution]

#: Probes per diagnosis. A probe is a full solve, so the cost of an
#: explanation is bounded rather than proportional to the model.
DEFAULT_BUDGET = 200

#: Per-probe seconds. A probe only asks "does any answer exist", which is far
#: cheaper than optimising, so it gets a short clock of its own.
DEFAULT_PROBE_SECONDS = 5.0


@dataclass
class Conflict:
    """Rules that cannot hold together, and whether that was proven."""

    #: `[{"constraint_id": "c_cover_demand", "instance": ["mon", "morning"]}]`
    items: list[dict[str, Any]] = field(default_factory=list)
    #: True only when every member was shown to be needed.
    minimal: bool = True
    #: Why the search stopped, when it stopped early.
    note: str = ""

    @property
    def rules(self) -> list[str]:
        return list(dict.fromkeys(item["constraint_id"] for item in self.items))


class _Budget:
    def __init__(self, probes: int) -> None:
        self.left = probes
        self.spent = 0
        self.inconclusive = False

    def take(self) -> bool:
        if self.left <= 0:
            return False
        self.left -= 1
        self.spent += 1
        return True


def explain(
    compiled: Compiled,
    solve: SolveFn,
    *,
    probe_seconds: float = DEFAULT_PROBE_SECONDS,
    budget: int = DEFAULT_BUDGET,
) -> Conflict:
    """An irreducible set of constraint instances that cannot all hold.

    `solve` is the backend that already called this model infeasible; the
    diagnosis is made with the same search, so its verdicts agree with the
    run's.
    """
    purse = _Budget(budget)

    def infeasible(subset: list[Constraint]) -> bool | None:
        """Is the model infeasible with only these constraints? None when the
        probe could not decide -- a timeout is not a verdict."""
        if not purse.take():
            return None
        result = solve(_only(compiled, subset), time_limit=probe_seconds, workers=8)
        if result.status in ("optimal", "feasible"):
            return False
        if result.status == "infeasible":
            return True
        return None

    # -- pass 1: which rules are involved ---------------------------------
    rules = list(dict.fromkeys(c.id for c in compiled.constraints))
    needed_rules, stopped = _filter(rules, lambda keep: infeasible(_by_rule(compiled, keep)))

    # -- pass 2: which instances of them ----------------------------------
    instances = [c for c in compiled.constraints if c.id in needed_rules]
    if not stopped:
        needed, stopped = _filter(instances, lambda keep: infeasible(keep))
    else:
        needed = instances

    return Conflict(
        items=[{"constraint_id": c.id, "instance": _instance(c)} for c in needed],
        minimal=not stopped,
        note=_note(stopped, purse),
    )


def _filter(candidates: list, still_infeasible: Callable[[list], bool | None]) -> tuple[list, bool]:
    """The deletion filter. Returns what survives, and whether the search was
    cut short before proving irreducibility.

    Candidates are dropped **by position**, not by value: two instances of a
    constraint can compare equal (the same rule over two days can compile to
    the same coefficients), and removing by value would take both out at once
    and call a pair irreducible when only one of them was needed.
    """
    keep = list(range(len(candidates)))
    for position in range(len(candidates)):
        trial = [i for i in keep if i != position]
        verdict = still_infeasible([candidates[i] for i in trial])
        if verdict is None:
            return [candidates[i] for i in keep], True
        if verdict:
            # Infeasible without it, so it was never part of the problem.
            keep = trial
    return [candidates[i] for i in keep], False


def _by_rule(compiled: Compiled, rules: list[str]) -> list[Constraint]:
    return [c for c in compiled.constraints if c.id in rules]


def _only(compiled: Compiled, constraints: list[Constraint]) -> Compiled:
    """The same model with a subset of its constraints and **no objective**.

    A probe asks whether any answer exists, not which is best; leaving the
    objective in would spend the probe's clock proving optimality of an answer
    nobody reads.
    """
    return replace(compiled, constraints=list(constraints), objective=Linear())


def _instance(c: Constraint) -> list[str]:
    """The index tuple, in the binding order the constraint was written in --
    `["mon", "morning"]`, which is what names the instance to a person."""
    return [str(value) for _, value in c.index.items()]


def _note(stopped: bool, purse: _Budget) -> str:
    if not stopped:
        return f"every rule listed is needed: removing any one makes the model solvable ({purse.spent} probes)"
    if purse.left <= 0:
        return (
            f"stopped after {purse.spent} probes, so this is a set that conflicts "
            "but may be larger than it needs to be"
        )
    return (
        "a probe ran out of time without deciding, so this is a set that conflicts "
        "but may be larger than it needs to be"
    )
