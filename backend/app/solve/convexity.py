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

    # A symmetric matrix is positive semidefinite exactly when each of its
    # blocks is -- the connected pieces of "these two variables share a
    # term". Checked block by block (queue R12's gate found a sum of 5,000
    # squares refused as one 5,000-wide matrix), so only a single block past
    # the limit goes unchecked.
    parent: dict = {}

    def root(key):
        parent.setdefault(key, key)
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    for a, b in quadratic:
        parent[root(a)] = root(b)
    blocks: dict = {}
    for key in {key for pair in quadratic for key in pair}:
        blocks.setdefault(root(key), []).append(key)
    largest = max(len(keys) for keys in blocks.values())
    if largest > MAX_CHECKED_VARIABLES:
        return Convexity(
            None,
            f"its quadratic part ties {largest} variables together, more than the "
            f"{MAX_CHECKED_VARIABLES} the convexity check covers, so it is not proven convex",
        )

    import numpy as np

    lowest, scale = 0.0, 1.0
    by_block: dict = {}
    for (a, b), coeff in quadratic.items():
        by_block.setdefault(root(a), []).append(((a, b), coeff))
    for block_root, members in blocks.items():
        keys = sorted(members)
        position = {key: i for i, key in enumerate(keys)}
        # f(x) = sum c_ij x_i x_j = x'Mx with M symmetric: the diagonal holds c_ii
        # and each off-diagonal pair shares c_ij half and half. f is convex
        # exactly when M is positive semidefinite.
        matrix = np.zeros((len(keys), len(keys)))
        for (a, b), coeff in by_block[block_root]:
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
        scale = max(scale, float(np.max(np.abs(eigenvalues))))
        lowest = min(lowest, float(eigenvalues.min()))

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
    # Conditional rules: whether a big-M backend may take them is a fact
    # about the compiled bounds too (app.solve.reformulate).
    from app.solve.reformulate import admit, admit_pwl

    found = admit_pwl(admit(found, compiled), compiled)
    # Every product of a yes-or-no decision: linear once written exactly
    # (McCormick), so its curvature is no longer the question.
    from app.solve.mccormick import BILINEAR_BINARY, admit as admit_products

    found = admit_products(found, compiled)
    if BILINEAR_BINARY in found.needs:
        return found
    # Quadratic rules: which are convex, which are cones (app.solve.socp).
    from app.solve.socp import admit as admit_cones

    found = admit_cones(found, compiled)
    if not compiled.objective_quadratic or all(v.is_integral for v in compiled.variables.values()):
        return found
    convexity = objective_convexity(compiled)
    return with_convexity(found, convexity.convex, convexity.reason)
