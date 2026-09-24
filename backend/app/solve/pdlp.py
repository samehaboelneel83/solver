"""When a linear program goes to PDLP (roadmap Phase 14, queue R1).

PDLP is a first-order method: it needs only the constraint matrix's products,
so it reaches linear programs whose factorisation the simplex method or an
interior-point method cannot hold. Its answer is optimal to a tolerance, not
proven (`proves="approximate"`), so it is used only where the others would
not answer: behind the setting `solve.pdlp` (off by default), for a linear
program with more nonzeros than `LARGE_SCALE_NNZ`.

The threshold is the benchmark's (`bench/results/2026-09-24-pdlp.md`): up to
500,000 nonzeros the exact solvers are as fast; at 2,000,000 HiGHS runs out
of the run's memory and PDLP answers first; past 4,500,000 nothing fits.
"""

from __future__ import annotations

from dataclasses import replace

from app.solve.classify import Classification
from app.solve.compile import Compiled

#: Nonzeros in the constraint matrix beyond which a linear program is large-scale.
LARGE_SCALE_NNZ = 1_000_000
LARGE_SCALE = "large-scale"


def nonzeros(compiled: Compiled) -> int:
    return sum(len(c.left.coeffs) + len(c.right.coeffs) for c in compiled.constraints)


def admit(found: Classification, compiled: Compiled, threshold: int | None = None) -> Classification:
    """`found`, needing `large-scale` when it is a linear program past the
    threshold (`LARGE_SCALE_NNZ`, read when called)."""
    threshold = LARGE_SCALE_NNZ if threshold is None else threshold
    if found.model_class != "LP" or nonzeros(compiled) <= threshold:
        return found
    return replace(
        found,
        needs=found.needs | {LARGE_SCALE},
        reasons=[*found.reasons, f"it has {nonzeros(compiled):,} nonzeros, past the {threshold:,} a first-order method is for"],
    )
