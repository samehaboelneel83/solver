"""Products with a yes-or-no factor, written exactly as linear rows (McCormick).

A product `a * x` of two decisions with bounds `a in [La, Ua]`, `x in [L, U]`
has four McCormick inequalities (McCormick, 1976) on a variable `w` that
stands for it:

    w >= L a + La x - La L        w >= U a + Ua x - Ua U
    w <= U a + La x - La U        w <= L a + Ua x - Ua L

In general they are its convex envelope -- a relaxation: the least and most
`w` may be between them are bounds on `a * x`, not its value. **When `a` is
binary they are exact.** With La = 0 and Ua = 1 they read

    L a <= w <= U a,        x - U (1 - a) <= w <= x - L (1 - a)

so `a = 0` pins `w` to 0 and `a = 1` pins it to `x`: `w` *is* the product,
and a model whose every product has a binary factor is a mixed-integer
linear model, written exactly. That is the one use this platform makes of
the envelope: a backend with no quadratic search (HiGHS, the MILP wrapper)
may then take such a model. `x * x` for a binary `x` is `x` itself.

**Declared bounds only.** `x`'s bounds are what `w` is squeezed between; a
bound the model never set (the compiler's guard ceiling, `default_upper`)
would make the rows rest on a number nobody chose, so `admit` refuses it by
name, as the big-M rewrite does (`app.solve.reformulate`).

**Not the relaxation.** A product of two decisions neither of which is
binary is left to the solvers that search it (SCIP bounds each product with
these same envelopes on every branch, and refines them); the envelope's own
optimum is a bound, never an answer, and no run reports one. Target roadmap
Phase 16.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Any

from app.solve.classify import Classification
from app.solve.compile import Compiled, Constraint, Linear, Variable, VarKey

#: What a model whose every product has a binary factor over declared bounds
#: needs in place of `quadratic` / `quadratic-constraints`.
BILINEAR_BINARY = "bilinear-binary"
#: The backends that take such a model rewritten; the others that provide
#: `bilinear-binary` (CP-SAT, SCIP) hold the products themselves.
FOR = frozenset({"highs", "milp"})

_ID = "__mccormick"


def _products(compiled: Compiled) -> set[tuple[VarKey, VarKey]]:
    pairs = set(compiled.objective_quadratic)
    for c in compiled.constraints:
        pairs |= set(c.quadratic)
    return pairs


def _name(key: VarKey) -> str:
    return key[0] + (f"[{','.join(key[1])}]" if key[1] else "")


def _split(compiled: Compiled, pair: tuple[VarKey, VarKey]) -> tuple[VarKey, VarKey] | str:
    """(the binary factor, the other), or why this product is not exact."""
    a, b = pair
    spec_a, spec_b = compiled.variables[a], compiled.variables[b]
    if spec_b.domain == "binary" and spec_a.domain != "binary":
        a, b, spec_a, spec_b = b, a, spec_b, spec_a
    if spec_a.domain != "binary":
        return f"{_name(a)} * {_name(b)} has no yes-or-no factor"
    if spec_b.default_upper:
        return f"{_name(a)} * {_name(b)}: {_name(b)} has no declared upper bound"
    if spec_b.lower.is_infinite() or spec_b.upper.is_infinite():
        return f"{_name(a)} * {_name(b)}: {_name(b)} is not bounded"
    return a, b


def blocked(compiled: Compiled) -> str | None:
    """The first product that cannot be written exactly, in words, or None."""
    for pair in sorted(_products(compiled)):
        found = _split(compiled, pair)
        if isinstance(found, str):
            return found
    return None


def admit(found: Classification, compiled: Compiled) -> Classification:
    """A quadratic model whose every product has a binary factor over
    declared bounds is a mixed-integer linear model written exactly: it
    needs `bilinear-binary` rather than `quadratic` / `quadratic-constraints`,
    and is classified as what it is once written so."""
    if not ({"quadratic", "quadratic-constraints"} & found.needs) or not _products(compiled):
        return found
    if blocked(compiled) is not None:
        return found
    whole = all(v.is_integral for v in compiled.variables.values())
    model_class = "IP" if whole else "MILP"
    return replace(
        found,
        model_class=model_class,
        needs=(found.needs - {"quadratic", "quadratic-constraints", "nonconvex"}) | {BILINEAR_BINARY},
        reasons=[
            *found.reasons,
            "every product has a yes-or-no factor and a partner with declared bounds, so it is "
            f"written exactly as linear rows (McCormick): the model is {model_class}",
        ],
        planner=[
            *found.planner,
            "each product is of a yes-or-no decision, so it can be written without multiplying",
        ],
    )


def linearise(compiled: Compiled) -> tuple[Compiled, list[dict[str, Any]]]:
    """The model with every product replaced by the variable it equals, and
    four rows holding it there; and, per product, what it became."""
    variables = dict(compiled.variables)
    extra: list[Constraint] = []
    stands: dict[tuple[VarKey, VarKey], VarKey] = {}
    record: list[dict[str, Any]] = []

    def stand_in(pair: tuple[VarKey, VarKey]) -> Linear:
        split = _split(compiled, pair)
        if isinstance(split, str):
            raise ValueError(f"not exact: {split}")  # `admit` routed only exact ones here
        a, x = split
        if a == x:
            return Linear(coeffs={a: Decimal(1)})  # a binary squared is itself
        if pair not in stands:
            low, high = compiled.variables[x].lower, compiled.variables[x].upper
            w: VarKey = (_ID, (str(len(stands)),))
            variables[w] = Variable(w, "continuous", min(Decimal(0), low), max(Decimal(0), high))
            one = Decimal(1)
            rows = [
                (Linear(coeffs={w: one, a: -high}), "<=", Decimal(0)),  # w <= U a
                (Linear(coeffs={w: one, a: -low}), ">=", Decimal(0)),  # w >= L a
                (Linear(coeffs={w: one, x: -one, a: -low}), "<=", -low),  # w <= x - L (1 - a)
                (Linear(coeffs={w: one, x: -one, a: -high}), ">=", -high),  # w >= x - U (1 - a)
            ]
            for left, relation, right in rows:
                left.coeffs = {k: v for k, v in left.coeffs.items() if v}
                extra.append(Constraint(_ID, {}, left, relation, Linear(const=right)))
            stands[pair] = w
            record.append({"product": [_name(a), _name(x)], "bounds": [float(low), float(high)]})
        return Linear(coeffs={stands[pair]: Decimal(1)})

    objective = compiled.objective.copy()
    for pair, coeff in sorted(compiled.objective_quadratic.items()):
        objective.add(stand_in(pair), factor=coeff)
    constraints = []
    for c in compiled.constraints:
        if c.quadratic:
            left = c.left.copy()
            for pair, coeff in sorted(c.quadratic.items()):
                left.add(stand_in(pair), factor=coeff)
            c = replace(c, left=left, quadratic={})
        constraints.append(c)
    return (
        replace(
            compiled,
            variables=variables,
            constraints=constraints + extra,
            objective=objective,
            objective_quadratic={},
        ),
        record,
    )
