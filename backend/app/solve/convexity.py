"""Is a quadratic objective convex? Decided, not assumed.

This is what makes quadratic programs the right first nonlinear class. For a
general nonlinear model, convexity is undecidable, and a solver's "optimal"
may be only the best nearby answer. For a quadratic objective it is a
question with an exact answer: `x'Qx` is convex exactly when the matrix `Q`
is positive semidefinite -- none of its eigenvalues is negative.

When it is convex (for a minimisation; concave for a maximisation), any
optimum a QP solver finds is the global one, and the platform may say so.
When it is not, a continuous solver could stop at a local optimum and
present it as the answer -- so the model is refused rather than solved, and
the refusal says why. An all-integer model does not need this check at all:
CP-SAT searches it exactly, convex or not.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.solve.classify import Classification, with_convexity
from app.solve.compile import Compiled

# Above this many variables in the quadratic part, the dense eigenvalue check
# stops being cheap. Rather than guess, the model is reported as unchecked,
# which the policy treats as "not proven convex".
MAX_CHECKED_VARIABLES = 2000

# Numerical noise in a matrix of exact decimals turned into floats: an
# eigenvalue this far below zero, relative to the largest, is zero.
_TOLERANCE = 1e-9


@dataclass(frozen=True)
class Convexity:
    #: True, False, or None when the model was too large to check.
    convex: bool | None
    reason: str


def objective_convexity(compiled: Compiled) -> Convexity:
    """Whether the objective's quadratic part curves the way the sense needs:
    upward for a minimisation, downward for a maximisation."""
    quadratic = compiled.objective_quadratic
    if not quadratic:
        return Convexity(True, "the objective is linear")

    keys = sorted({key for pair in quadratic for key in pair})
    if len(keys) > MAX_CHECKED_VARIABLES:
        return Convexity(
            None,
            f"its quadratic part involves {len(keys)} variables, more than the "
            f"{MAX_CHECKED_VARIABLES} the convexity check covers, so it is not proven convex",
        )

    import numpy as np

    position = {key: i for i, key in enumerate(keys)}
    # f(x) = sum c_ij x_i x_j = x'Mx with M symmetric: the diagonal holds c_ii
    # and each off-diagonal pair shares c_ij half and half. f is convex
    # exactly when M is positive semidefinite.
    matrix = np.zeros((len(keys), len(keys)))
    for (a, b), coeff in quadratic.items():
        i, j = position[a], position[b]
        if i == j:
            matrix[i, i] += float(coeff)
        else:
            matrix[i, j] += float(coeff) / 2
            matrix[j, i] += float(coeff) / 2
    if compiled.sense != "minimize":
        # Maximising f is minimising -f.
        matrix = -matrix

    eigenvalues = np.linalg.eigvalsh(matrix)
    scale = max(1.0, float(np.max(np.abs(eigenvalues))))
    lowest = float(eigenvalues.min())
    if lowest >= -_TOLERANCE * scale:
        return Convexity(
            True,
            "its quadratic objective is "
            + ("convex" if compiled.sense == "minimize" else "concave")
            + ", so any optimum is the best overall",
        )
    return Convexity(
        False,
        "its quadratic objective is not "
        + ("convex" if compiled.sense == "minimize" else "concave")
        + " (it curves the wrong way somewhere), so a continuous solver could stop at an "
        "answer that is only the best nearby",
    )


def refine(found: Classification, compiled: Compiled) -> Classification:
    """The classification, with what the compiled numbers say about convexity.

    The one place this is decided, so the Model editor's "which solver would
    take this" and the run that actually solves cannot disagree. Only a
    continuous quadratic model depends on convexity: an all-integer one is
    searched exactly whatever its curvature, so it is not checked.
    """
    if not compiled.objective_quadratic or all(v.is_integral for v in compiled.variables.values()):
        return found
    convexity = objective_convexity(compiled)
    return with_convexity(found, convexity.convex, convexity.reason)
