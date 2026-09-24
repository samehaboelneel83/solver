"""Solver parameters, behind the benchmark gate (target roadmap Phase 13).

A backend's own options can change how fast it answers, and nothing else:
the whitelist below is every option the platform will set, with the values
it may take -- the solver's default first. The bench measures each against
that default (`python -m bench.run --technique cp-sat.linearization_level=1,0,2`,
`bench.report`'s enable rule: at least 10% better on two families, nothing
2x slower, no wrong answer), and only a winner is **enabled**: listed in
`ENABLED`, which every solve of that backend then applies. Anything not on
the whitelist is refused -- a run's options must be ones someone measured.

One option is enabled today, SCIP's `presolving=fast`; every other one
measured lost or tied (bench/results/2026-09-23-solver-params-*.md).
"""

from __future__ import annotations

from typing import Any

#: backend -> option -> the values it may take, the solver's default first.
WHITELIST: dict[str, dict[str, tuple[Any, ...]]] = {
    "cp-sat": {
        # How much of the model CP-SAT also keeps as an LP relaxation.
        "linearization_level": (1, 0, 2),
        # How hard it looks for and uses symmetry (2 is its default).
        "symmetry_level": (2, 0, 4),
    },
    "highs": {
        # The share of MIP effort spent on primal heuristics.
        "mip_heuristic_effort": (0.05, 0.3),
        "presolve": ("choose", "on", "off"),
    },
    "scip": {
        # SCIP's own emphasis settings for presolve and for heuristics.
        "presolving": ("default", "aggressive", "fast"),
        "heuristics": ("default", "aggressive", "fast"),
    },
}

#: Winners of the benchmark gate, applied to every solve of the backend.
ENABLED: dict[str, dict[str, Any]] = {
    # 29 wins, 2 losses, 17 ties over 96 runs (4 families x M/L x 3
    # instances x 2 seeds), every family at least 10% faster, nothing 2x
    # slower, no wrong answer: SCIP's own "fast" presolve emphasis
    # (bench/results/2026-09-23-solver-params-scip-presolving-confirm.md).
    "scip": {"presolving": "fast"},
}


def check(backend: str, params: dict[str, Any] | None) -> dict[str, Any]:
    """The options to apply: the enabled ones, overridden by `params`, each
    one whitelisted for `backend` with a whitelisted value."""
    chosen = {**ENABLED.get(backend, {}), **(params or {})}
    allowed = WHITELIST.get(backend, {})
    for name, value in chosen.items():
        if name not in allowed:
            raise ValueError(f"{name!r} is not a whitelisted option for {backend}")
        if value not in allowed[name]:
            raise ValueError(f"{value!r} is not a whitelisted value of {backend}'s {name!r}: {allowed[name]}")
    return chosen


def parse(backend: str, name: str, text: str) -> Any:
    """A value as the bench's command line gives it, cast like the whitelist."""
    if name not in WHITELIST.get(backend, {}):
        raise ValueError(f"{name!r} is not a whitelisted option for {backend}: "
                         f"{', '.join(sorted(WHITELIST.get(backend, {}))) or 'it has none'}")
    for value in WHITELIST.get(backend, {}).get(name, ()):
        if str(value) == text:
            return value
    raise ValueError(f"{text!r} is not a whitelisted value of {backend}'s {name!r}")


def parse_setting(text: str | None) -> dict[str, dict[str, Any]]:
    """`solve.solver_params` (queue R10): "cp-sat.symmetry_level=0, highs.presolve=off" -> per backend,
    each option whitelisted with a whitelisted value. Empty text is no override. Raises ValueError, naming
    the part it cannot read."""
    chosen: dict[str, dict[str, Any]] = {}
    for part in (p.strip() for p in (text or "").split(",")):
        if not part:
            continue
        head, _, value = part.partition("=")
        backend, _, name = head.strip().partition(".")
        if not value or not name:
            raise ValueError(f"{part!r} is not backend.option=value")
        if backend not in WHITELIST:
            raise ValueError(f"{backend!r} has no whitelisted options")
        chosen.setdefault(backend, {})[name.strip()] = parse(backend, name.strip(), value.strip())
    for backend, options in chosen.items():
        check(backend, options)
    return chosen
