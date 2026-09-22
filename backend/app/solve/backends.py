"""Which solvers exist, what each can do, and how one is chosen.

Capabilities are **data**, not branches spread through the code — the same
discipline the expression catalogue follows (Ruling 37). Adding a backend is
a row here plus a module; the policy does not change.

The policy, in order, and recorded on every run so a result can be
questioned:

1. an explicit choice wins, and is refused if that backend cannot take the
   model — saying "I used something else instead" would make the record a
   lie;
2. otherwise the highest-ranked available backend whose capabilities cover
   the model's class;
3. if none does, the run fails with the reason rather than being handed to a
   solver that will answer badly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Callable, Protocol

from app.solve.classify import Classification
from app.solve.compile import Compiled
from app.solve.result import Solution

# True means the caller has asked this solve to give up. Backends that can
# interrupt do; the rest return as soon as their current call does.
ShouldStop = Callable[[], bool]


class SolveFn(Protocol):
    def __call__(
        self,
        compiled: Compiled,
        *,
        time_limit: float,
        workers: int,
        should_stop: ShouldStop | None = None,
    ) -> Solution: ...


@dataclass(frozen=True)
class Backend:
    name: str
    #: What it solves. The classifier's vocabulary, so the two cannot drift.
    classes: frozenset[str]
    #: What a model may need of it; compared against `Classification.needs`.
    provides: frozenset[str]
    #: Lower runs first when both could take a model.
    rank: int
    solve: SolveFn
    #: What this backend's `optimal` proves (migration 0028): `global` -- the
    #: best of all possible answers -- or `local` -- the best among its
    #: neighbours, with a better one possibly elsewhere. Required, with no
    #: default, so a local solver cannot be registered without saying so: a
    #: local optimum shown as "optimal" looks exactly like the best answer.
    proves: Literal["global", "local"]
    #: Whether this build actually has it.
    is_available: Callable[[], bool] = field(default=lambda: True)
    note: str = ""
    #: One sentence the Model editor shows instead of this backend's name.
    #: A picker is a different capability; the editor never offers one.
    planner_choice: str = ""


def _cpsat_solve(
    compiled: Compiled,
    *,
    time_limit: float,
    workers: int,
    should_stop: ShouldStop | None = None,
) -> Solution:
    from app.solve import cpsat

    return cpsat.solve(
        compiled, time_limit=time_limit, workers=workers, should_stop=should_stop
    )


def _milp_solve(
    compiled: Compiled,
    *,
    time_limit: float,
    workers: int,
    should_stop: ShouldStop | None = None,
) -> Solution:
    from app.solve import milp

    return milp.solve(
        compiled, time_limit=time_limit, workers=workers, should_stop=should_stop
    )


def _milp_available() -> bool:
    from app.solve import milp

    return milp.available() is not None


def _lp_solve(
    compiled: Compiled,
    *,
    time_limit: float,
    workers: int,
    should_stop: ShouldStop | None = None,
) -> Solution:
    from app.solve import lp

    return lp.solve(
        compiled, time_limit=time_limit, workers=workers, should_stop=should_stop
    )


def _lp_available() -> bool:
    from app.solve import lp

    return lp.available()


def _highs_solve(
    compiled: Compiled,
    *,
    time_limit: float,
    workers: int,
    should_stop: ShouldStop | None = None,
) -> Solution:
    from app.solve import highs

    return highs.solve(
        compiled, time_limit=time_limit, workers=workers, should_stop=should_stop
    )


def _highs_available() -> bool:
    from app.solve import highs

    return highs.available()


def _scip_solve(
    compiled: Compiled,
    *,
    time_limit: float,
    workers: int,
    should_stop: ShouldStop | None = None,
) -> Solution:
    from app.solve import scip

    return scip.solve(
        compiled, time_limit=time_limit, workers=workers, should_stop=should_stop
    )


def _scip_available() -> bool:
    from app.solve import scip

    return scip.available()


# Ranks are global, so they encode one ordering across every class. That
# works because the `classes` sets keep each backend out of the comparison
# where it would be the wrong technique: glop and cp-sat both rank 0 and never
# compete, because no model is both an LP and an IP. highs and milp share
# rank 1; highs is listed first so it wins the mixed case when installed.
# milp remains the generalist fallback that ships inside ortools.
CP_SAT = Backend(
    name="cp-sat",
    # MIQP here means an all-integer quadratic model: CP-SAT has no
    # continuous variables, so a mixed one is kept away by `continuous`.
    classes=frozenset({"IP", "MIQP", "trivial"}),
    # `quadratic` and `nonconvex` both: products of whole numbers are searched
    # exactly, so the optimum is the global one whatever the curvature.
    provides=frozenset({"linear", "integral", "soft-constraints", "quadratic", "nonconvex"}),
    rank=0,
    solve=_cpsat_solve,
    # A linear model is convex: every optimum it proves is the global one.
    proves="global",
    note="constraint programming; strongest on tightly constrained combinatorial models",
    planner_choice="A combinatorial solver will take this by default.",
)

GLOP = Backend(
    name="glop",
    classes=frozenset({"LP", "trivial"}),
    provides=frozenset({"linear", "continuous", "fractional-data", "soft-constraints"}),
    rank=0,
    solve=_lp_solve,
    # A linear model is convex: every optimum it proves is the global one.
    proves="global",
    is_available=_lp_available,
    note="the simplex method; the right technique for a model with no discrete decisions",
    planner_choice="A linear solver will take this by default.",
)

HIGHS = Backend(
    name="highs",
    # QP: continuous only -- HiGHS has no integer quadratic search -- and
    # convex only: it provides `quadratic` but not `nonconvex`, because on a
    # nonconvex objective it could stop at an answer that is only the best
    # nearby, and this entry declares `proves="global"`.
    classes=frozenset({"IP", "LP", "MILP", "QP", "trivial"}),
    provides=frozenset(
        {"linear", "integral", "continuous", "fractional-data", "soft-constraints", "quadratic"}
    ),
    rank=1,
    solve=_highs_solve,
    # A linear model is convex: every optimum it proves is the global one.
    proves="global",
    is_available=_highs_available,
    note="HiGHS; LP and MILP under an MIT licence, the mixed-model default when installed",
    planner_choice="A mixed solver will take this by default.",
)

MILP = Backend(
    name="milp",
    classes=frozenset({"IP", "LP", "MILP", "trivial"}),
    provides=frozenset(
        {"linear", "integral", "continuous", "fractional-data", "soft-constraints"}
    ),
    rank=1,
    solve=_milp_solve,
    # A linear model is convex: every optimum it proves is the global one.
    proves="global",
    is_available=_milp_available,
    note="branch and cut over a linear relaxation; the ortools fallback for a mixed model",
    planner_choice="A mixed solver will take this by default.",
)

SCIP = Backend(
    name="scip",
    # Only the quadratic classes: a linear model is better served by every
    # backend above, and rank 2 keeps it that way even if this list grows.
    classes=frozenset({"QP", "MIQP"}),
    # `nonconvex` and a mix of `integral` and `continuous` together: the two
    # cases stage 2 refused. Spatial branch-and-bound bounds each product on
    # every branch, so nonconvexity costs time, never correctness.
    provides=frozenset(
        {
            "linear",
            "integral",
            "continuous",
            "fractional-data",
            "soft-constraints",
            "quadratic",
            "nonconvex",
        }
    ),
    rank=2,
    solve=_scip_solve,
    # Its `optimal` closes the gap between the best answer and a proven bound
    # over the whole space, convex or not: a global optimum.
    proves="global",
    is_available=_scip_available,
    note="SCIP; spatial branch-and-bound, the global solver for quadratic models nothing else takes",
    planner_choice="A global nonlinear solver will take this by default.",
)

REGISTRY: tuple[Backend, ...] = (CP_SAT, GLOP, HIGHS, MILP, SCIP)


class NoBackend(Exception):
    """No available backend can take this model."""


def by_name(name: str) -> Backend | None:
    return next((b for b in REGISTRY if b.name == name), None)


def available_names() -> list[str]:
    return [b.name for b in REGISTRY if b.is_available()]


def choose(found: Classification, requested: str | None = None) -> tuple[Backend, str]:
    """The backend to use and, in words, why.

    The reason is stored on the run. A result whose solver nobody can account
    for is not reproducible, and "why this one" is the first question asked
    when two runs of the same model disagree.
    """
    if requested is not None:
        backend = by_name(requested)
        if backend is None:
            raise NoBackend(f"there is no solver called {requested!r}")
        if not backend.is_available():
            raise NoBackend(f"{requested} is not available in this build")
        missing = found.needs - backend.provides
        if found.model_class not in backend.classes or missing:
            raise NoBackend(
                f"{requested} cannot take a {found.model_class} model"
                + (f" needing {', '.join(sorted(missing))}" if missing else "")
            )
        return backend, f"asked for {backend.name}"

    fits = [
        b
        for b in sorted(REGISTRY, key=lambda b: b.rank)
        if b.is_available() and found.model_class in b.classes and not (found.needs - b.provides)
    ]
    if not fits:
        raise NoBackend(
            f"no available solver takes a {found.model_class} model needing "
            f"{', '.join(sorted(found.needs))}" + _why_nothing_fits(found)
        )
    chosen = fits[0]
    others = [b.name for b in fits[1:]]
    reason = f"{chosen.name} is the highest-ranked solver for a {found.model_class} model"
    if others:
        reason += f"; {', '.join(others)} could also take it"
    return chosen, reason


def _why_nothing_fits(found: Classification) -> str:
    """The quadratic dead ends, in words. Both are refusals on purpose: the
    alternative is solving with a method that may return an answer that is
    not the best and cannot say so."""
    if "quadratic" not in found.needs:
        return ""
    if "nonconvex" in found.needs:
        return (
            ". Its objective is not proven convex, and this build has no global "
            "nonlinear solver: a local one could stop at an answer that is only the "
            "best nearby and report it as optimal, so the model is refused rather "
            "than answered wrongly. Making every decision a whole number lets the "
            "exact integer solver take it"
        )
    if "continuous" in found.needs and "integral" in found.needs:
        return (
            ". A quadratic goal over a mix of whole-number and continuous decisions "
            "needs a mixed-integer quadratic solver, which this build does not have"
        )
    return ""


def planner_choice_for(found: Classification) -> str | None:
    """What the Model editor shows: the chosen backend's planner sentence,
    or None when this platform has nothing that can take the model.

    `choose()` is the one policy; this is only its wording. The editor
    never names the backend and never offers a picker.
    """
    try:
        backend, _why = choose(found)
    except NoBackend:
        return None
    return backend.planner_choice


def optimality_of(backend: Backend, status: str) -> str | None:
    """What a run's answer may claim, from the backend's declaration.

    `optimal` claims whatever the backend proves; `feasible` -- an answer found
    before the clock ran out -- claims nothing about being best; a run with no
    answer makes no claim at all.
    """
    if status == "optimal":
        return backend.proves
    if status == "feasible":
        return "none"
    return None
