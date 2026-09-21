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
from typing import Callable, Protocol

from app.solve.classify import Classification
from app.solve.compile import Compiled
from app.solve.result import Solution


class SolveFn(Protocol):
    def __call__(self, compiled: Compiled, *, time_limit: float, workers: int) -> Solution: ...


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
    #: Whether this build actually has it.
    is_available: Callable[[], bool] = field(default=lambda: True)
    note: str = ""


def _cpsat_solve(compiled: Compiled, *, time_limit: float, workers: int) -> Solution:
    from app.solve import cpsat

    return cpsat.solve(compiled, time_limit=time_limit, workers=workers)


def _milp_solve(compiled: Compiled, *, time_limit: float, workers: int) -> Solution:
    from app.solve import milp

    return milp.solve(compiled, time_limit=time_limit, workers=workers)


def _milp_available() -> bool:
    from app.solve import milp

    return milp.available() is not None


CP_SAT = Backend(
    name="cp-sat",
    classes=frozenset({"IP", "trivial"}),
    provides=frozenset({"linear", "integral", "soft-constraints"}),
    rank=0,
    solve=_cpsat_solve,
    note="constraint programming; strongest on tightly constrained combinatorial models",
)

MILP = Backend(
    name="milp",
    classes=frozenset({"IP", "trivial"}),
    provides=frozenset({"linear", "integral", "soft-constraints"}),
    rank=1,
    solve=_milp_solve,
    is_available=_milp_available,
    note="branch and cut over a linear relaxation; strongest where the linear structure is",
)

REGISTRY: tuple[Backend, ...] = (CP_SAT, MILP)


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
            f"{', '.join(sorted(found.needs))}"
        )
    chosen = fits[0]
    others = [b.name for b in fits[1:]]
    reason = f"{chosen.name} is the highest-ranked solver for a {found.model_class} model"
    if others:
        reason += f"; {', '.join(others)} could also take it"
    return chosen, reason
