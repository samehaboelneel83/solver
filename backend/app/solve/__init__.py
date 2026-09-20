"""Turning a model and a dataset into an answer.

`compile` resolves the IR against the frozen dataset, `classify` says what
kind of model it is, `cpsat` solves it. The split is what lets Phase 2 add a
second backend without rewriting the compiler.
"""

from app.solve.classify import Classification, classify
from app.solve.compile import Compiled, Unsupported, compile_model
from app.solve.cpsat import Solution, solve

__all__ = [
    "Classification",
    "Compiled",
    "Solution",
    "Unsupported",
    "classify",
    "compile_model",
    "solve",
]
