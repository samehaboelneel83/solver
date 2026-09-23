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

**A core first, when there is one** (target roadmap Phase 11, native IIS).
Deletion filtering over the whole model costs a probe per rule and then one
per instance of the rules kept -- hundreds of solves on a large model. For a
linear model HiGHS can name an irreducible infeasible subset of the linear
relaxation in one call (`highs.iis`). That set is only a *core* here: it is
confirmed infeasible with the run's own backend (one probe), then shrunk by
deletion filtering **on the core alone** with that backend, so the verdicts
are still the run's and the result is still provably irreducible. When
there is no core -- the relaxation is feasible and only the whole-number
model is not, or HiGHS cannot take the model -- the full search runs, as it
always did.

**The honest part.** Each probe is a solve, so this is bounded by a budget,
and a probe can time out without deciding. Either way the search stops early
and reports what it has with `minimal = False`: a *superset* of a conflict,
still true, but not proven irreducible. Reporting a truncated search as
though it were minimal would be a lie of exactly the kind this module exists
to prevent -- the caller must be able to tell "any of these removed fixes it"
from "somewhere in here".
"""

from __future__ import annotations

import time
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
    #: How it was found: the name of the core it was shrunk from ("cp-sat",
    #: "iis") or "deletion" (the whole model filtered), and what it cost.
    method: str = "deletion"
    probes: int = 0
    seconds: float = 0.0

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
    cores: list[tuple[str, Callable[[Compiled], list[int] | None]]] = (),
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

    started = time.monotonic()

    def done(needed: list[Constraint], stopped: bool, method: str) -> Conflict:
        return Conflict(
            items=[{"constraint_id": c.id, "instance": _instance(c)} for c in needed],
            minimal=not stopped,
            note=_note(stopped, purse),
            method=method,
            probes=purse.spent,
            seconds=round(time.monotonic() - started, 3),
        )

    # -- a core, confirmed and shrunk with the run's own backend -----------
    # The first one offered that the backend confirms; one it does not is a
    # candidate that failed, and the next is tried.
    for name, core in cores:
        found = core(compiled)
        if not found:
            continue
        candidates = [compiled.constraints[i] for i in found]
        if infeasible(candidates):
            needed, stopped = _filter(candidates, lambda keep: infeasible(keep))
            return done(needed, stopped, name)

    # -- pass 1: which rules are involved ---------------------------------
    rules = list(dict.fromkeys(c.id for c in compiled.constraints))
    needed_rules, stopped = _filter(rules, lambda keep: infeasible(_by_rule(compiled, keep)))

    # -- pass 2: which instances of them ----------------------------------
    instances = [c for c in compiled.constraints if c.id in needed_rules]
    if not stopped:
        needed, stopped = _filter(instances, lambda keep: infeasible(keep))
    else:
        needed = instances

    return done(needed, stopped, "deletion")


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
    return replace(compiled, constraints=list(constraints), objective=Linear(), objective_quadratic={})


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
