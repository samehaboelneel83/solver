"""Which quadratic rules are convex, and which of those are second-order cones.

A quadratic rule `x'Qx + l'x <= c` (a `>=` rule is the same on its negation)
bounds a convex region in exactly two cases this module recognises:

- **Q is positive semidefinite** -- an ellipsoid or a paraboloid, e.g.
  `x^2 + y^2 <= 25`. Every such rule is a second-order cone in disguise
  (factor Q = F'F: `||F x||^2 + l'x <= c`).
- **A cone.** Q has exactly one negative eigenvalue, there is no linear part
  and the right-hand side is zero -- `x^2 + y^2 <= t^2`, or the rotated
  `x^2 <= y z` -- and the decisions' bounds keep them on one nappe: along the
  negative eigenvector `v`, `v'x` never changes sign over the box (t >= 0;
  y + z >= 0). `{x'Qx <= 0}` is then one convex cone, not the two that meet
  at the origin.

Anything else is not proven convex: `x^2 - y^2 <= 1`, `x y >= 1` without a
sign, an equality with a product. Rules of any kind go to a solver that
proves a global optimum regardless (SCIP, or CP-SAT when every decision is
whole); a model whose quadratic rules are all convex, and whose goal is,
additionally needs `socp` -- what SCIP provides now, and what a conic solver
would provide later -- and is recorded as convex. Target roadmap Phase 16.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.solve.compile import Compiled, Constraint, VarKey

CONVEX, CONE, NOT_CONVEX = "convex quadratic", "second-order cone", "not proven convex"
_TOLERANCE = 1e-9


@dataclass(frozen=True)
class RuleShape:
    rule: str
    index: tuple[str, ...]
    kind: str
    why: str


def _oriented(c: Constraint) -> tuple[dict, dict, Decimal] | None:
    """`x'Qx + l'x <= c` for this rule, or None for an equality."""
    if c.relation in ("=", "=="):
        return None
    sign = Decimal(-1) if c.relation in (">=", ">") else Decimal(1)
    linear: dict[VarKey, Decimal] = {}
    for key, coeff in c.left.coeffs.items():
        linear[key] = linear.get(key, Decimal(0)) + coeff * sign
    for key, coeff in c.right.coeffs.items():
        linear[key] = linear.get(key, Decimal(0)) - coeff * sign
    quadratic = {pair: coeff * sign for pair, coeff in c.quadratic.items()}
    return quadratic, {k: v for k, v in linear.items() if v}, (c.right.const - c.left.const) * sign


def shape_of(compiled: Compiled, c: Constraint) -> RuleShape:
    import numpy as np

    index = tuple(str(v) for v in c.index.values())
    oriented = _oriented(c)
    if oriented is None:
        return RuleShape(c.id, index, NOT_CONVEX, "an equality with a product in it bounds a curved surface, not a region")
    quadratic, linear, rhs = oriented
    keys = sorted({key for pair in quadratic for key in pair})
    position = {key: i for i, key in enumerate(keys)}
    matrix = np.zeros((len(keys), len(keys)))
    for (a, b), coeff in quadratic.items():
        i, j = position[a], position[b]
        if i == j:
            matrix[i, i] += float(coeff)
        else:
            matrix[i, j] += float(coeff) / 2
            matrix[j, i] += float(coeff) / 2
    values, vectors = np.linalg.eigh(matrix)
    scale = max(1.0, float(np.max(np.abs(values))))
    negative = [i for i, value in enumerate(values) if value < -_TOLERANCE * scale]
    if not negative:
        return RuleShape(c.id, index, CONVEX, "its products curve upward in every direction")
    if len(negative) > 1:
        return RuleShape(c.id, index, NOT_CONVEX, "its products curve downward in more than one direction")
    if linear or rhs != 0:
        return RuleShape(
            c.id, index, NOT_CONVEX,
            "its products curve downward in one direction and it is not a cone (it has a linear part or a "
            "non-zero right-hand side)",
        )
    v = vectors[:, negative[0]]
    lowest = highest = 0.0
    for key, weight in zip(keys, v):
        spec = compiled.variables[key]
        low, high = float(weight) * float(spec.lower), float(weight) * float(spec.upper)
        lowest, highest = lowest + min(low, high), highest + max(low, high)
    if lowest >= -_TOLERANCE * scale or highest <= _TOLERANCE * scale:
        return RuleShape(c.id, index, CONE, "it is a cone, and the decisions' bounds keep it to one side of its tip")
    return RuleShape(
        c.id, index, NOT_CONVEX,
        "it is a double cone: the decisions' bounds let it reach both sides of its tip",
    )


def rule_shapes(compiled: Compiled) -> list[RuleShape]:
    """One shape per quadratic rule instance."""
    return [shape_of(compiled, c) for c in compiled.constraints if c.quadratic]


def summary(shapes: list[RuleShape]) -> dict[str, RuleShape]:
    """Per rule id, its least convex instance."""
    order = {CONVEX: 0, CONE: 1, NOT_CONVEX: 2}
    worst: dict[str, RuleShape] = {}
    for shape in shapes:
        if shape.rule not in worst or order[shape.kind] > order[worst[shape.rule].kind]:
            worst[shape.rule] = shape
    return worst


#: What a model whose quadratic rules and goal are all convex needs beyond
#: `quadratic-constraints`: a solver that takes a conic program.
SOCP = "socp"


def admit(found, compiled: Compiled):
    """The classification, told which quadratic rules are convex or cones --
    and, when all are and the goal is too, that the model is a convex
    (second-order cone) program."""
    from dataclasses import replace

    from app.solve.convexity import objective_convexity

    if "quadratic-constraints" not in found.needs:
        return found
    worst = summary(rule_shapes(compiled))
    if not worst:
        return found
    reasons = [*found.reasons]
    for kind in (CONE, CONVEX):
        rules = sorted(rule for rule, shape in worst.items() if shape.kind == kind)
        if rules:
            reasons.append(f"{', '.join(rules)} {'is a ' + kind if len(rules) == 1 else 'are ' + kind + 's'}")
    for rule, shape in sorted(worst.items()):
        if shape.kind == NOT_CONVEX:
            reasons.append(f"{rule} is not proven convex: {shape.why}")
    goal = objective_convexity(compiled)
    convex = all(shape.kind != NOT_CONVEX for shape in worst.values()) and goal.convex is True
    relaxed = (
        " (its continuous relaxation, as some decisions are whole)"
        if any(v.is_integral for v in compiled.variables.values())
        else ""
    )
    if convex:
        reasons.append(
            f"the model is convex{relaxed}: every quadratic rule bounds a convex region and the goal curves the "
            "right way, so it is a second-order cone program"
        )
        planner = [*found.planner, "every curved rule bounds one convex region, so the best answer nearby is the best overall"]
        return replace(found, reasons=reasons, planner=planner, needs=found.needs | {SOCP}, convex=True)
    reasons.append(f"the model is not proven convex{relaxed}, so the solver searches it globally")
    return replace(found, reasons=reasons, convex=False)
