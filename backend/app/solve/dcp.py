"""Curvature by composition: is each term convex, concave, affine -- or unknown?

Disciplined convex programming (Grant, Boyd & Ye, 2006) decides curvature
from the shape of an expression, never from its numbers alone: every leaf
has a known curvature, and each operation has a rule for what it makes of
its operands' curvature. When no rule applies, the answer is "unknown" --
not "nonconvex": the rules are sufficient, not necessary.

The leaves: a number, a parameter and an attribute are constants (with a
sign, read from the data when there is data); a decision is affine; a
piecewise curve is convex when its slopes rise, concave when they fall.
The operations:

- a sum of convex parts is convex, of concave parts concave; a sum that
  mixes the two is unknown;
- a convex or concave part times a constant keeps its curvature when the
  constant is at least zero and flips it when at most zero -- and is
  unknown when the constant's sign is not known;
- a product of two parts that both hold decisions is left to the
  eigenvalue check (`app.solve.convexity`) and is unknown here;
- a function from the catalogue (`contract.json` `functions`), applied to
  g: convex when f is convex and g affine, or f convex and rising and g
  convex (or f convex and falling and g concave); concave likewise; else
  unknown. A function neither convex nor concave is unknown of anything
  but a constant.

A model is convex when every `<=` rule's left minus right is convex, every
`>=` rule's is concave, every `=` rule's is affine, and the goal is convex
to minimise or concave to maximise. Then the best answer nearby is the best
overall -- for a model with whole-number decisions, of its continuous
relaxation. Target roadmap Phase 16.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.ir.contract import FUNCTIONS

CONSTANT, AFFINE, CONVEX, CONCAVE, UNKNOWN = "constant", "affine", "convex", "concave", "unknown"
NONNEG, NONPOS, ANY_SIGN = "nonneg", "nonpos", "any"

#: The sign of a function of a constant, where it has one.
_SIGN_OF = {"exp": NONNEG, "sqrt": NONNEG, "abs": NONNEG}


@dataclass(frozen=True)
class Shape:
    curvature: str
    #: For a constant only: whether it is at least zero, at most zero, or either.
    sign: str = ANY_SIGN
    #: For an unknown: the first place a rule failed, in words.
    why: str | None = None

    @property
    def is_convex(self) -> bool:
        return self.curvature in (CONSTANT, AFFINE, CONVEX)

    @property
    def is_concave(self) -> bool:
        return self.curvature in (CONSTANT, AFFINE, CONCAVE)


def _unknown(why: str) -> Shape:
    return Shape(UNKNOWN, why=why)


def _flip(curvature: str) -> str:
    return {CONVEX: CONCAVE, CONCAVE: CONVEX}.get(curvature, curvature)


def _sign_of_number(value: Any) -> str:
    number = Decimal(str(value))
    if number == 0:
        return "zero"
    return NONNEG if number > 0 else NONPOS


def _joint_sign(signs: list[str]) -> str:
    """The sign every one of these numbers shares, or `any`."""
    kinds = {s for s in signs if s != "zero"}
    if not kinds:
        return "zero"
    return kinds.pop() if len(kinds) == 1 else ANY_SIGN


def add(a: Shape, b: Shape) -> Shape:
    for side in (a, b):
        if side.curvature == UNKNOWN:
            return side
    if a.curvature == CONSTANT and b.curvature == CONSTANT:
        return Shape(CONSTANT, _joint_sign([a.sign, b.sign]))
    curvatures = {a.curvature, b.curvature} - {CONSTANT}
    if curvatures <= {AFFINE}:
        return Shape(AFFINE)
    if curvatures <= {AFFINE, CONVEX}:
        return Shape(CONVEX)
    if curvatures <= {AFFINE, CONCAVE}:
        return Shape(CONCAVE)
    return _unknown("it adds a convex part to a concave one")


def scale(shape: Shape, factor: Shape) -> Shape:
    """`shape` times `factor`, a constant."""
    if shape.curvature == UNKNOWN:
        return shape
    if shape.curvature == CONSTANT:
        signs = {shape.sign, factor.sign}
        if "zero" in signs:
            return Shape(CONSTANT, "zero")
        if ANY_SIGN in signs:
            return Shape(CONSTANT)
        return Shape(CONSTANT, NONNEG if shape.sign == factor.sign else NONPOS)
    if shape.curvature == AFFINE or factor.sign == "zero":
        return Shape(AFFINE)
    if factor.sign == NONNEG:
        return shape
    if factor.sign == NONPOS:
        return Shape(_flip(shape.curvature))
    return _unknown(f"a {shape.curvature} part is multiplied by a number that may be negative or positive")


def negate(shape: Shape) -> Shape:
    return scale(shape, Shape(CONSTANT, NONPOS))


def compose(name: str, argument: Shape) -> Shape:
    """The catalogue function `name` of an argument of this shape."""
    if argument.curvature == UNKNOWN:
        return argument
    if argument.curvature == CONSTANT:
        return Shape(CONSTANT, _SIGN_OF.get(name, ANY_SIGN))
    spec = FUNCTIONS[name]
    kind, monotone = spec["convexity"], spec["monotone"]
    if kind == "neither":
        return _unknown(f"{name} is neither convex nor concave")
    if argument.curvature == AFFINE:
        return Shape(kind)
    # Rising: the function keeps the argument's bend if it bends the same way.
    # Falling: if it bends the other way.
    same = argument.curvature == kind
    if (monotone == "increasing" and same) or (monotone == "decreasing" and not same):
        return Shape(kind)
    return _unknown(f"{name} is {kind}, and its argument is {argument.curvature}")


class _Shapes:
    """The shape of each term of one model, with its data's signs."""

    def __init__(self, data: dict[str, Any] | None) -> None:
        self.data = data
        self._par_signs: dict[str, str] = {}

    def of(self, term: Any, scope: dict[str, str]) -> Shape:
        if not isinstance(term, dict):
            return _unknown("a part of it is not a term")
        if "const" in term:
            return Shape(CONSTANT, _sign_of_number(term["const"]))
        if "par" in term:
            return Shape(CONSTANT, self._parameter_sign(term["par"]))
        if "attr" in term:
            return Shape(CONSTANT, self._attribute_sign(term["attr"], scope))
        if "var" in term:
            return Shape(AFFINE)
        if "pwl" in term:
            return _curve(term["points"])
        if "fn" in term:
            return compose(term["fn"], self.of(term.get("of"), scope))
        if "sum" in term:
            inner = dict(scope)
            for binding in term.get("over") or []:
                inner[binding.get("index")] = binding.get("set")
            body = self.of(term["sum"], inner)
            # Many copies of one shape are that shape (a constant keeps its sign).
            return body
        if "add" in term:
            total = Shape(CONSTANT, "zero")
            for part in term["add"]:
                total = add(total, self.of(part, scope))
            return total
        if "mul" in term:
            a, b = (self.of(factor, scope) for factor in term["mul"])
            if a.curvature == CONSTANT:
                return scale(b, a)
            if b.curvature == CONSTANT:
                return scale(a, b)
            if UNKNOWN in (a.curvature, b.curvature):
                return a if a.curvature == UNKNOWN else b
            return _unknown("it multiplies two parts that hold decisions")
        return _unknown(f"no composition rule covers {sorted(term)}")

    def _parameter_sign(self, name: str) -> str:
        if name not in self._par_signs:
            if self.data is None:
                self._par_signs[name] = ANY_SIGN
            else:
                values = [row.get("value") for row in (self.data.get("parameters") or {}).get(name, [])]
                default = (self.data.get("parameter_defaults") or {}).get(name)
                if default is not None:
                    values.append(default)
                self._par_signs[name] = _joint_sign([_sign_of_number(v) for v in values if v is not None]) if values else ANY_SIGN
        return self._par_signs[name]

    def _attribute_sign(self, reference: dict[str, Any], scope: dict[str, str]) -> str:
        set_name = scope.get(reference.get("of"))
        if self.data is None or set_name is None:
            return ANY_SIGN
        values = [row.get(reference.get("name")) for row in (self.data.get("sets") or {}).get(set_name, [])]
        values = [v for v in values if v is not None]
        return _joint_sign([_sign_of_number(v) for v in values]) if values else ANY_SIGN


def _curve(points: list[list[Any]]) -> Shape:
    slopes = [
        (Decimal(str(y1)) - Decimal(str(y0))) / (Decimal(str(x1)) - Decimal(str(x0)))
        for (x0, y0), (x1, y1) in zip(points, points[1:])
    ]
    if all(a == b for a, b in zip(slopes, slopes[1:])):
        return Shape(AFFINE)
    if all(a <= b for a, b in zip(slopes, slopes[1:])):
        return Shape(CONVEX)
    if all(a >= b for a, b in zip(slopes, slopes[1:])):
        return Shape(CONCAVE)
    return _unknown("a piecewise curve's slopes both rise and fall")


def shape_of(term: Any, data: dict[str, Any] | None = None, scope: dict[str, str] | None = None) -> Shape:
    """The curvature of one term (and its sign, if it is a constant)."""
    return _Shapes(data).of(term, scope or {})


@dataclass(frozen=True)
class Verdict:
    #: True when every rule and the goal bend the way a convex model needs.
    convex: bool
    #: Why, in words: the first rule or goal term that does not, and where.
    reason: str


_NEEDS = {"<=": "convex", ">=": "concave", "=": "affine"}


def model_curvature(ir: dict[str, Any], data: dict[str, Any] | None = None) -> Verdict:
    """Whether the model is convex by composition, and if not, where not."""
    shapes = _Shapes(data)
    for rule in ir.get("constraints") or []:
        if not isinstance(rule, dict) or "left" not in rule:
            continue  # a scheduling rule is combinatorial, not a curve
        scope = {b.get("index"): b.get("set") for b in rule.get("forall") or []}
        shape = add(shapes.of(rule["left"], scope), negate(shapes.of(rule.get("right"), scope)))
        need = _NEEDS.get(rule.get("relation"), "affine")
        ok = shape.curvature in (CONSTANT, AFFINE) or (need == "convex" and shape.is_convex) or (
            need == "concave" and shape.is_concave
        )
        if not ok:
            return Verdict(False, _fails(rule.get("id"), f"a {rule.get('relation')} rule", need, shape))
    objective = ir.get("objective") or {}
    maximize = objective.get("sense") == "maximize"
    need = "concave" if maximize else "convex"
    terms = objective.get("terms") or []
    if objective.get("mode") == "lex":
        parts = [(t.get("id"), shapes.of(t.get("expression"), {})) for t in terms]
    else:
        total = Shape(CONSTANT, "zero")
        for t in terms:
            total = add(total, scale(shapes.of(t.get("expression"), {}), Shape(CONSTANT, _sign_of_number(t.get("weight", 1)))))
        parts = [("the goal", total)]
    for name, shape in parts:
        if not (shape.is_concave if maximize else shape.is_convex):
            return Verdict(False, _fails(name, "the goal to " + ("maximise" if maximize else "minimise"), need, shape))
    return Verdict(True, "every rule and the goal bend the way a convex model needs, by the composition rules")


def _fails(name: Any, what: str, need: str, shape: Shape) -> str:
    found = shape.why if shape.curvature == UNKNOWN else f"it is {shape.curvature}"
    return f"{name} is not proven {need}, as {what} needs to be: {found}"
