"""Camp Layout Optimization Engine.

    from camp_layout import solve, examples, export
    run = solve(examples.complex_camp(), solver="cpsat")
    export.write(run, "out/")

See docs/MODEL.md for the mathematical model.
"""
from . import examples, export
from .pipeline import Run, solve

__all__ = ["Run", "examples", "export", "solve"]
