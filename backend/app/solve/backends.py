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
from typing import Any, Literal, Callable, Protocol

from app.solve.classify import Classification
from app.solve.compile import Compiled
from app.solve.result import Solution

# True means the caller has asked this solve to give up. Backends that can
# interrupt do; the rest return as soon as their current call does.
ShouldStop = Callable[[], bool]

# Told of progress while a backend solves: ("incumbent" | "bound", payload)
# with `t` (seconds into the solve), `objective` (the best answer so far,
# or None) and `bound` (the best proven limit, or None). Backends that have
# no callback never call it; a failure in it must not stop the solve.
ProgressFn = Callable[[str, dict], None]


class SolveFn(Protocol):
    def __call__(
        self,
        compiled: Compiled,
        *,
        time_limit: float,
        workers: int,
        should_stop: ShouldStop | None = None,
        seed: int | None = None,
        gap_rel: float = 0.0,
        on_progress: "ProgressFn | None" = None,
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
    #: A third, `approximate` (migration 0051): optimal to a stated tolerance,
    #: not proven -- a first-order method such as PDLP.
    proves: Literal["global", "local", "approximate"]
    #: Whether this build actually has it.
    is_available: Callable[[], bool] = field(default=lambda: True)
    note: str = ""
    #: One sentence the Model editor shows instead of this backend's name.
    #: A picker is a different capability; the editor never offers one.
    planner_choice: str = ""
    #: `built-in`, or `adapter` -- added from a manifest (queue R41, `app.solve.adapters`).
    origin: str = "built-in"
    #: Whether the rules may choose it unasked. An adapter is not, until the conformance kit
    #: (queue R43) has passed it: until then it runs only when asked for by name.
    automatic: bool = True
    #: An adapter's manifest (`app.solve.adapters.Manifest`); None for a built-in.
    manifest: object = None


def _cpsat_solve(
    compiled: Compiled,
    *,
    time_limit: float,
    workers: int,
    should_stop: ShouldStop | None = None,
    seed: int | None = None,
    gap_rel: float = 0.0,
    on_progress=None,
    hint: dict | None = None,
    solver_params: dict | None = None,
) -> Solution:
    from app.solve import cpsat

    return cpsat.solve(
        compiled, time_limit=time_limit, workers=workers, should_stop=should_stop, seed=seed,
        gap_rel=gap_rel,
        on_progress=on_progress,
        hint=hint,
        solver_params=solver_params,
    )


def _milp_solve(
    compiled: Compiled,
    *,
    time_limit: float,
    workers: int,
    should_stop: ShouldStop | None = None,
    seed: int | None = None,
    gap_rel: float = 0.0,
    on_progress=None,
    hint: dict | None = None,
    solver_params: dict | None = None,
) -> Solution:
    from app.solve import milp

    return milp.solve(
        compiled, time_limit=time_limit, workers=workers, should_stop=should_stop, seed=seed,
        gap_rel=gap_rel,
        on_progress=on_progress,
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
    seed: int | None = None,
    gap_rel: float = 0.0,
    on_progress=None,
    hint: dict | None = None,
    solver_params: dict | None = None,
) -> Solution:
    from app.solve import lp

    return lp.solve(
        compiled, time_limit=time_limit, workers=workers, should_stop=should_stop, seed=seed,
        gap_rel=gap_rel,
        on_progress=on_progress,
    )


def _lp_available() -> bool:
    from app.solve import lp

    return lp.available()


def _pdlp_solve(
    compiled: Compiled,
    *,
    time_limit: float,
    workers: int,
    should_stop: ShouldStop | None = None,
    seed: int | None = None,
    gap_rel: float = 0.0,
    on_progress=None,
    hint: dict | None = None,
    solver_params: dict | None = None,
) -> Solution:
    from app.solve import lp

    return lp.solve(
        compiled, time_limit=time_limit, workers=workers, should_stop=should_stop, seed=seed,
        gap_rel=gap_rel, on_progress=on_progress, engine=lp.PDLP,
    )


def _pdlp_available() -> bool:
    from app.solve import lp

    return lp.available(lp.PDLP)


def _highs_solve(
    compiled: Compiled,
    *,
    time_limit: float,
    workers: int,
    should_stop: ShouldStop | None = None,
    seed: int | None = None,
    gap_rel: float = 0.0,
    on_progress=None,
    hint: dict | None = None,
    solver_params: dict | None = None,
) -> Solution:
    from app.solve import highs

    return highs.solve(
        compiled, time_limit=time_limit, workers=workers, should_stop=should_stop, seed=seed,
        gap_rel=gap_rel,
        on_progress=on_progress,
        hint=hint,
        solver_params=solver_params,
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
    seed: int | None = None,
    gap_rel: float = 0.0,
    on_progress=None,
    hint: dict | None = None,
    solver_params: dict | None = None,
) -> Solution:
    from app.solve import scip

    return scip.solve(
        compiled, time_limit=time_limit, workers=workers, should_stop=should_stop, seed=seed,
        gap_rel=gap_rel,
        on_progress=on_progress,
        hint=hint,
        solver_params=solver_params,
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
    # MIQP and MIQCQP here mean all-integer quadratic models: CP-SAT has no
    # continuous variables, so a mixed one is kept away by `continuous`.
    classes=frozenset({"IP", "MIQP", "MIQCQP", "trivial"}),
    # `quadratic`, `quadratic-constraints` and `nonconvex`: products of whole
    # numbers are held exactly, in a goal or a rule, so the optimum is the
    # global one whatever the curvature.
    provides=frozenset(
        {
            "linear",
            "connected",
            "route",
            "integral",
            "soft-constraints",
            "quadratic",
            "quadratic-constraints",
            "nonconvex",
            # Fractional data made whole exactly (`scaling.py`), which is only
            # a need at all when `solve.cpsat_scaling` admits the model.
            "scaled-fractional-data",
            # A conditional rule (`when`) as an enforcement literal: the rule
            # is switched, not approximated with a big number.
            "indicator",
            "indicator-bounded",
            # A piecewise curve of a whole number, as a table (AddElement).
            "pwl",
            "pwl-convex",
            "pwl-native",
            # Intervals, NoOverlap and Cumulative.
            "scheduling",
            # A product of a yes-or-no decision, held as a product.
            "bilinear-binary",
            # Cone rules, as the products they are, searched exactly.
            "socp",
        }
    ),
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
    provides=frozenset(
        {
            "linear",
            "continuous",
            "fractional-data",
            "scaled-fractional-data",
            "soft-constraints",
            # Only a curve an epigraph can hold: the rest need binaries.
            "pwl-convex",
        }
    ),
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
        {
            "linear",
            "connected",
            "route",
            "integral",
            "continuous",
            "fractional-data",
            "scaled-fractional-data",
            "soft-constraints",
            "quadratic",
            # A conditional rule over declared bounds, rewritten with a tight
            # big-M (app.solve.reformulate) -- never over a guard ceiling.
            "indicator-bounded",
            # Piecewise curves, rewritten: epigraph or incremental.
            "pwl",
            "pwl-convex",
            # A product of a yes-or-no decision, written exactly (McCormick).
            "bilinear-binary",
        }
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
        {
            "linear",
            "connected",
            "route",
            "integral",
            "continuous",
            "fractional-data",
            "scaled-fractional-data",
            "soft-constraints",
            "indicator-bounded",
            "pwl",
            "pwl-convex",
            "bilinear-binary",
        }
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
    # And the linear classes, for one reason: a conditional rule over a model
    # with continuous decisions, which CP-SAT cannot hold and the linear
    # backends have no indicator for. Rank 2 keeps every other linear model
    # with the backends above.
    # NLP and MINLP: a catalogue function of a decision, which SCIP holds as
    # its own nonlinear expression and nothing else here holds at all.
    classes=frozenset({"QP", "MIQP", "QCQP", "MIQCQP", "IP", "MILP", "LP", "NLP", "MINLP"}),
    # `nonconvex` and a mix of `integral` and `continuous` together: the two
    # cases stage 2 refused. Spatial branch-and-bound bounds each product on
    # every branch, so nonconvexity costs time, never correctness.
    provides=frozenset(
        {
            "linear",
            "connected",
            "route",
            "integral",
            "continuous",
            "fractional-data",
            "scaled-fractional-data",
            "soft-constraints",
            "quadratic",
            "quadratic-constraints",
            "nonconvex",
            # `when`, as SCIP's own indicator constraints.
            "indicator",
            "indicator-bounded",
            # A piecewise curve as SOS2.
            "pwl",
            "pwl-convex",
            "pwl-native",
            # exp, log, sqrt, abs, sin and cos of a linear argument.
            "functions",
            "bilinear-binary",
            # Second-order cones: SCIP detects and holds them as cones.
            "socp",
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

PDLP = Backend(
    name="pdlp",
    classes=frozenset({"LP"}),
    # What GLOP takes, and `large-scale`: the need `app.solve.pdlp` adds to a
    # linear program past its size threshold when `solve.pdlp` is on -- the
    # one need only this backend provides, so nothing else is chosen then.
    provides=frozenset(
        {"linear", "continuous", "fractional-data", "scaled-fractional-data", "soft-constraints", "pwl-convex", "large-scale"}
    ),
    # Last: an ordinary linear program goes to the simplex or interior-point
    # solvers, whose optimum is proven.
    rank=3,
    solve=_pdlp_solve,
    proves="approximate",
    is_available=_pdlp_available,
    note="a first-order method for very large linear programs; optimal to a tolerance, not proven",
    planner_choice="A solver for very large linear programs will take this; its answer is optimal to a small tolerance.",
)

def _ipopt_solve(
    compiled: Compiled,
    *,
    time_limit: float,
    workers: int,
    should_stop: ShouldStop | None = None,
    seed: int | None = None,
    gap_rel: float = 0.0,
    on_progress=None,
    hint: dict | None = None,
    solver_params: dict | None = None,
) -> Solution:
    from app.solve import ipopt

    return ipopt.solve(compiled, time_limit=time_limit, workers=workers, should_stop=should_stop, seed=seed,
                       gap_rel=gap_rel, on_progress=on_progress, hint=hint, solver_params=solver_params)


def _ipopt_available() -> bool:
    from app.solve import ipopt

    return ipopt.available()


IPOPT = Backend(
    name="ipopt",
    # Continuous nonlinear and quadratic models: an interior-point method
    # needs a slope everywhere, so nothing whole-numbered and no corners.
    classes=frozenset({"NLP", "QP", "QCQP"}),
    provides=frozenset(
        {"linear", "continuous", "fractional-data", "scaled-fractional-data", "soft-constraints", "quadratic",
         "quadratic-constraints", "nonconvex", "functions"}
    ),
    # Last: whatever a global solver can take goes there first. IPOPT is asked
    # for by name, or takes over when SCIP ends with nothing (`solve.local_fallback`).
    rank=4,
    solve=_ipopt_solve,
    # The best answer nearby, and nothing about elsewhere: a local optimum.
    proves="local",
    is_available=_ipopt_available,
    note="IPOPT (interior point); the best answer near where it starts -- a local optimum, never proven best",
    planner_choice="A local nonlinear solver will take this; its answer is the best nearby, not proven the best.",
)

def _benders_solve(
    compiled: Compiled,
    *,
    time_limit: float,
    workers: int,
    should_stop: ShouldStop | None = None,
    seed: int | None = None,
    gap_rel: float = 0.0,
    on_progress=None,
    hint: dict | None = None,
    solver_params: dict | None = None,
) -> Solution:
    from app.solve import benders

    return benders.solve(compiled, time_limit=time_limit, workers=workers, should_stop=should_stop, seed=seed,
                         gap_rel=gap_rel, on_progress=on_progress, solver_params=solver_params)


BENDERS = Backend(
    name="benders",
    # A mixed model only: the whole-number decisions go to the master, the
    # continuous ones to the subproblem (`app.solve.benders`). Curves and
    # conditional rules arrive as linear rows (`solve_compiled` rewrites them).
    classes=frozenset({"MILP"}),
    provides=frozenset(
        {"linear", "integral", "continuous", "fractional-data", "scaled-fractional-data", "soft-constraints",
         "indicator-bounded", "pwl", "pwl-convex"}
    ),
    rank=8,
    solve=_benders_solve,
    # The loop ends when the master's bound meets the best answer: a global optimum.
    proves="global",
    is_available=_highs_available,
    note="Benders decomposition over HiGHS; for a mixed model whose continuous part is large and easy once the "
         "whole-number decisions are fixed",
    planner_choice="A decomposition solver will take this; asked for by name.",
    # By name only: on most mixed models HiGHS's own branch and cut is faster.
    automatic=False,
)


def _colgen_solve(
    compiled: Compiled,
    *,
    time_limit: float,
    workers: int,
    should_stop: ShouldStop | None = None,
    seed: int | None = None,
    gap_rel: float = 0.0,
    on_progress=None,
    hint: dict | None = None,
    solver_params: dict | None = None,
) -> Solution:
    from app.solve import colgen

    return colgen.solve(compiled, time_limit=time_limit, workers=workers, should_stop=should_stop, seed=seed,
                        gap_rel=gap_rel, on_progress=on_progress)


COLGEN = Backend(
    name="colgen",
    # A linear model with many more decisions than rules (a candidate list, every pairing, every pattern): a
    # small master over the columns that matter, the rest priced from the rule matrix (`app.solve.colgen`).
    classes=frozenset({"LP", "MILP"}),
    provides=frozenset(
        {"linear", "integral", "continuous", "fractional-data", "scaled-fractional-data", "soft-constraints"}
    ),
    rank=9,
    solve=_colgen_solve,
    # The bound is the Lagrangian of every column at the master's prices; an answer meeting it is proven best.
    proves="global",
    is_available=_highs_available,
    note="column generation over HiGHS; for a linear model with many more decisions than rules -- the answer is "
         "proven best only when it meets the bound over every column",
    planner_choice="A column generation solver will take this; asked for by name.",
    # By name only: it pays on models with far more decisions than rules.
    automatic=False,
)


def _evolve(method: str):
    def run(compiled: Compiled, *, time_limit: float, workers: int, should_stop: ShouldStop | None = None,
            seed: int | None = None, gap_rel: float = 0.0, on_progress=None, hint: dict | None = None,
            solver_params: dict | None = None) -> Solution:
        from app.solve import evolve

        return evolve.solve(compiled, method=method, time_limit=time_limit, workers=workers, should_stop=should_stop,
                            seed=seed, on_progress=on_progress, hint=hint)

    return run


# What a search over whole answers can be handed: every row it can evaluate.
_SEARCHED = frozenset({"linear", "continuous", "fractional-data", "scaled-fractional-data", "soft-constraints",
                       "quadratic", "quadratic-constraints", "nonconvex", "functions"})
_CONTINUOUS_CLASSES = frozenset({"LP", "QP", "QCQP", "NLP"})
#: The metaheuristic lane (queue R14): registered `local` like IPOPT, so the
#: rules never choose them and memory, the race and the portfolio (which
#: compare proofs) never enter them. Asked for by name, or after an exact
#: solver ended with nothing (setting `solve.metaheuristic`). They never say
#: `optimal`: an answer is `feasible`, with no bound.
CMA_ES = Backend(
    name="cma-es",
    classes=_CONTINUOUS_CLASSES,
    provides=_SEARCHED,
    rank=5,
    solve=_evolve("cma-es"),
    proves="local",
    note="CMA-ES (evolution strategy); searches continuous decisions without slopes -- an answer, never proven best",
    planner_choice="A search over whole answers will take this; its answer keeps every rule but is not proven the best.",
)
PSO = Backend(
    name="pso",
    classes=_CONTINUOUS_CLASSES,
    provides=_SEARCHED,
    rank=6,
    solve=_evolve("pso"),
    proves="local",
    note="particle swarm; searches continuous decisions -- an answer, never proven best",
    planner_choice="A search over whole answers will take this; its answer keeps every rule but is not proven the best.",
)
GA = Backend(
    name="ga",
    classes=_CONTINUOUS_CLASSES | {"IP", "MILP", "MIQP", "MIQCQP", "MINLP"},
    provides=_SEARCHED | {"integral", "connected", "bilinear-binary"},
    rank=7,
    solve=_evolve("ga"),
    proves="local",
    note="genetic algorithm; breeds whole answers, whole-number or continuous -- an answer, never proven best",
    planner_choice="A search over whole answers will take this; its answer keeps every rule but is not proven the best.",
)

def _networkx_solve(
    compiled: Compiled,
    *,
    time_limit: float,
    workers: int,
    should_stop: ShouldStop | None = None,
    seed: int | None = None,
    gap_rel: float = 0.0,
    on_progress=None,
    hint: dict | None = None,
    solver_params: dict | None = None,
) -> Solution:
    from app.solve import network
    from app.solve.compile import Unsupported

    why = network.applies(compiled, ceilings=True)
    if why is not None:
        from app.solve import matching

        # Not a network, but a pairing any record may join (not two-sided): Edmonds' blossom, proven.
        if matching.applies(compiled) is None:
            return matching.solve(compiled).solution
        # Its class fits (a linear model), its shape does not: said, never answered as something else.
        raise Unsupported(
            "networkx solves a network -- every rule flow in less flow out (each coefficient +1 or -1, "
            "each decision in at most two rules), every number whole: transport, assignment, shortest "
            f"path, maximum flow -- or a matching (each record in at most, or exactly, one pair). This model is "
            f"neither: {why}. Leave the solver unset and the rules choose one that takes it.")
    return network.solve(compiled, engine="networkx", ceilings=True).solution


def _networkx_available() -> bool:
    from app.solve import network

    return network.networkx_available()


NETWORKX = Backend(
    name="networkx",
    # A network model is linear; its class is whatever its decisions are. The shape (flow in less flow
    # out) is checked on the compiled model, and anything else is refused with the reason.
    classes=frozenset({"IP", "LP", "MILP", "trivial"}),
    provides=frozenset({"linear", "integral", "continuous"}),
    # After the general solvers: it runs when asked for by name (`automatic=False`) -- the class alone
    # cannot tell a network from any other linear model. Network models reach it unasked through the
    # network lane (`solve.network`, engine `solve.network_engine`).
    rank=3,
    solve=_networkx_solve,
    # Network simplex is exact on whole numbers: the optimum it proves is the global one, and a
    # totally unimodular model's LP optimum is whole, so continuous and whole agree.
    proves="global",
    is_available=_networkx_available,
    automatic=False,
    note="NetworkX (BSD licence): network simplex for network models -- transport, assignment, shortest path, "
         "maximum flow -- and Edmonds' blossom for pairings any record may join; proven optimal, with shadow "
         "prices for networks",
    planner_choice="A network solver will take this: min-cost flow, proven optimal.",
)

def _layout_solve(compiled: Compiled, *, time_limit: float, workers: int, should_stop: ShouldStop | None = None,
                  seed: int | None = None, gap_rel: float = 0.0, on_progress=None, hint: dict | None = None,
                  solver_params: dict | None = None) -> Solution:
    from app.solve import placement

    return placement.solve(compiled, time_limit=time_limit, workers=workers, should_stop=should_stop, seed=seed,
                           gap_rel=gap_rel, on_progress=on_progress)


LAYOUT = Backend(
    name="layout",
    # A place rule's decisions: chosen (yes or no), where (whole cells), turned and aisle side.
    classes=frozenset({"placement"}),
    provides=frozenset({"placement", "integral", "linear"}),
    # Last: only a model with a place rule needs what it alone provides; every other model has better solvers.
    rank=99,
    solve=_layout_solve,
    # It says optimal only when its answer meets the area bound, which no layout can pass.
    proves="global",
    note="Placement on a drawing's free area without a list of positions (app.solve.placement): greedy from "
         "coarse to fine grids, then windows solved exactly by CP-SAT; bounded by the free area",
    planner_choice="The placement solver will lay the items out on the drawing's grid, without listing positions.",
)

BUILT_IN: tuple[Backend, ...] = (CP_SAT, GLOP, HIGHS, MILP, SCIP, PDLP, IPOPT, CMA_ES, PSO, GA, BENDERS, COLGEN,
                                 NETWORKX, LAYOUT)


def _with_adapters() -> tuple[Backend, ...]:
    """The built-ins and every solver added from a manifest (queue R41). An adapter that cannot
    be loaded is skipped with its reason (`app.solve.adapters.SKIPPED`), never raised here."""
    from app.solve import adapters

    return BUILT_IN + adapters.load(BUILT_IN)


REGISTRY: tuple[Backend, ...] = _with_adapters()
#: The searches: they never say `optimal`, `infeasible` or `unbounded` -- an answer, or none.
SEARCHES = frozenset({CMA_ES.name, PSO.name, GA.name})


class NoBackend(Exception):
    """No available backend can take this model."""


def by_name(name: str) -> Backend | None:
    return next((b for b in REGISTRY if b.name == name), None)


def available_names() -> list[str]:
    return [b.name for b in REGISTRY if b.is_available()]


def is_automatic(backend: "Backend") -> bool:
    """Whether the rules may choose it unasked: a built-in, or an added solver whose current
    version passed the conformance kit (queue R43, `app.solve.adapters.VERIFIED`)."""
    # Remote GPU trials remain explicit until model-family benchmarks exist.
    if backend.name == "cuopt-remote":
        return False
    if backend.automatic:
        return True
    from app.solve.adapters import VERIFIED

    return backend.origin == "adapter" and backend.name in VERIFIED


def allows(backend: "Backend", allowed: set[str] | None, denied: set[str] | None) -> str | None:
    """Why an organization's settings keep this backend from solving (queue R42), or None."""
    if denied and backend.name in denied:
        return f"{backend.name} is denied here (setting solve.denied_solvers)"
    if allowed and backend.name not in allowed:
        return f"{backend.name} is not among the solvers allowed here (setting solve.allowed_solvers)"
    return None


def choose(found: Classification, requested: str | None = None, *, allowed: set[str] | None = None,
           denied: set[str] | None = None) -> tuple[Backend, str]:
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
        kept_out = allows(backend, allowed, denied)
        if kept_out:
            raise NoBackend(kept_out)
        missing = found.needs - backend.provides
        if found.model_class not in backend.classes or missing:
            raise NoBackend(
                f"{requested} cannot take a {found.model_class} model"
                + (f" needing {', '.join(sorted(missing))}" if missing else "")
                + "".join(f": {found.refusals[need]}" for need in sorted(missing) if need in found.refusals)
            )
        return backend, f"asked for {backend.name}"

    # A local solver is never the rules' choice: its optimum may not be the
    # best, so it runs only when asked for by name or as a fallback that says
    # so (`solve.local_fallback`) -- a model nothing global takes is refused.
    fits = [
        b
        for b in sorted(REGISTRY, key=lambda b: b.rank)
        if b.proves != "local" and is_automatic(b) and allows(b, allowed, denied) is None
        and b.is_available() and found.model_class in b.classes and not (found.needs - b.provides)
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


#: A whole-number model with at least this many yes/no decisions and a weighted capacity row is "knapsack-shaped".
KNAPSACK_DECISIONS = 500


def knapsack_shaped(numbers: dict[str, Any] | None) -> bool:
    """Many yes/no decisions under weighted capacity rows (`a·x <= b`, whole weights), and nothing only a
    constraint-programming solver takes (schedules, intervals, networks, switched or quadratic rows): a
    branch-and-bound MIP solver's LP bound settles these at once, where CP-SAT searched (the evaluation, October
    2026: a 2,000-item knapsack took CP-SAT 15.7 s; HiGHS solves the family in 0.08-1.7 s)."""
    if not numbers:
        return False
    return (numbers.get("rows_knapsack", 0) >= 1 and numbers.get("binary", 0) >= KNAPSACK_DECISIONS
            and numbers.get("coef_max", 0) >= 10
            and not any(numbers.get(k, 0) for k in ("rows_scheduling", "rows_connectivity", "rows_conditional",
                                                     "rows_quadratic", "intervals", "curves", "functions"))
            and numbers.get("objective_degree", 1) <= 1)


def prefer_for_shape(found: Classification, numbers: dict[str, Any] | None, chosen: "Backend", why: str, *,
                     allowed: set[str] | None = None, denied: set[str] | None = None) -> tuple["Backend", str]:
    """The rules' choice, or a MIP solver for a knapsack-shaped model the rank would give CP-SAT."""
    if chosen.name != "cp-sat" or not knapsack_shaped(numbers):
        return chosen, why
    for name in ("highs", "scip"):
        try:
            backend, _ = choose(found, name, allowed=allowed, denied=denied)
        except NoBackend:
            continue
        return backend, (f"{name}: the model is knapsack-shaped ({numbers.get('binary')} yes/no decisions under "
                         f"weighted capacity rows), which a MIP solver's bound settles faster than CP-SAT's search; "
                         + why)
    return chosen, why

def fit(found: Classification, *, allowed: set[str] | None = None, denied: set[str] | None = None) -> list[dict]:
    """Every solver in the registry against this model (Epic UX, U-5): whether it can take it,
    whether the rules would choose it unasked, and -- when it cannot -- why, in words.

    The same tests `choose()` makes, one solver at a time, so a planner sees before a run
    which solvers fit and what keeps the others out. `chosen` marks the one `choose()` picks.
    """
    try:
        picked = choose(found, allowed=allowed, denied=denied)[0].name
    except NoBackend:
        picked = None
    rows = []
    for backend in sorted(REGISTRY, key=lambda b: b.rank):
        missing = sorted(found.needs - backend.provides)
        if not backend.is_available():
            why = "not installed in this build"
        elif (kept_out := allows(backend, allowed, denied)) is not None:
            why = kept_out
        elif found.model_class not in backend.classes:
            why = f"takes {', '.join(sorted(backend.classes))} models, not a {found.model_class} model"
        elif missing:
            why = "cannot hold what this model needs: " + ", ".join(
                found.refusals.get(need, need) for need in missing)
        else:
            why = None
        fits = why is None
        by_name_only = fits and (backend.proves == "local" or not is_automatic(backend))
        rows.append({
            "name": backend.name,
            "fits": fits,
            "automatic": fits and not by_name_only,
            "chosen": backend.name == picked,
            "proves": backend.proves,
            "why": why if not fits else (
                "the rules' choice for this model" if backend.name == picked
                else "fits; used only when asked for by name" + (" (its answer is the best nearby, not proven best)"
                                                                 if backend.proves == "local" else "")
                if by_name_only else "fits; ranked below the rules' choice"),
            "note": backend.note,
        })
    return rows


def _why_nothing_fits(found: Classification) -> str:
    """The quadratic dead ends, in words. Both are refusals on purpose: the
    alternative is solving with a method that may return an answer that is
    not the best and cannot say so."""
    if "quadratic-constraints" in found.needs:
        return (
            ". A rule multiplies decisions together, and this build has no global "
            "nonlinear solver: a local one could stop at an answer that is only the "
            "best nearby and report it as optimal. Making every decision a whole "
            "number lets the exact integer solver take it"
        )
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
