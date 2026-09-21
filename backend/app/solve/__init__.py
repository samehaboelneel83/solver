"""Turning a model and a dataset into an answer.

`compile` resolves the IR against the frozen dataset, `classify` says what
kind of model it is, `cpsat` solves it. The split is what lets Phase 2 add a
second backend without rewriting the compiler.

This package stays free of `ortools` and `highspy` on import. Those two
ship the same `libHighs` and cannot load in one process; HiGHS therefore
runs in a child interpreter (`highs_worker`).
"""

from app.solve.classify import Classification, classify
from app.solve.compile import Compiled, Unsupported, compile_model
from app.solve.result import Solution

__all__ = [
    "Classification",
    "Compiled",
    "Solution",
    "Unsupported",
    "classify",
    "compile_model",
    "solve",
]


def __getattr__(name: str):
    if name == "solve":
        from app.solve.cpsat import solve as _solve

        return _solve
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
