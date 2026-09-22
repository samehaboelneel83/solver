"""Whole-number rows from fractional ones, exactly, so CP-SAT can take them.

CP-SAT works in integers. A model whose every variable is whole but whose
data is not -- 7.5-hour shifts, rates to the cent -- used to be routed away
from it (`fractional-data`), because rounding would answer a different
question. Scaling does not round: a rule `7.5 x + 2.25 y <= 30` means the
same as `750 x + 225 y <= 3000`, and dividing by the gcd, `10 x + 3 y <= 40`.
Every coefficient and the bound become whole, and the set of whole-number
solutions is unchanged, because both sides were multiplied by the same
positive number.

A row is scaled by 10^k, k its most decimal places, then divided by the gcd
of the results. The objective is scaled the same way as one row, and its
value and bound are divided back when reported. Two limits keep this
honest, and past either the model is not admitted:

* **at most 4 decimal places** (`MAX_DECIMALS`) -- beyond that the data is
  measured, not counted, and a linear-programming backend is the right tool;
* **no scaled row can reach 2^53** (`LIMIT`) -- the largest activity a
  row can have, |coefficients| times the variables' bounds plus |bound|,
  must stay where every integer is exact.

Behind the setting `solve.cpsat_scaling` (migration 0039), off by default,
and measured to stay so (`bench/results/2026-09-23-cpsat-scaling.md`):
CP-SAT is faster up to L-sized instances and gives the same optima, but on
the XL rota it is more than 2x slower, which the enable-by-default rule
does not allow.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any

from app.solve.classify import Classification
from app.solve.compile import Compiled

MAX_DECIMALS = 4
LIMIT = 2**53

FRACTIONAL = "fractional-data"
#: The need a scalable model has instead of `fractional-data` once scaling is
#: on. CP-SAT provides it; every backend that takes fractional data does too.
SCALED = "scaled-fractional-data"


class NotScalable(Exception):
    """This model's numbers cannot be made whole exactly and safely."""


def decimals(value: Decimal) -> int:
    exponent = value.normalize().as_tuple().exponent
    return max(0, -exponent) if isinstance(exponent, int) else 0


@dataclass(frozen=True)
class ScaledRow:
    """`sum(coeffs) + sum(quadratic) relation rhs`, in whole numbers, and the
    positive factor the original row was multiplied by."""

    coeffs: dict[Any, int]
    quadratic: dict[tuple[Any, Any], int]
    rhs: int
    factor: Decimal


def scale(
    coeffs: dict[Any, Decimal],
    rhs: Decimal,
    quadratic: dict[tuple[Any, Any], Decimal],
    reach: dict[Any, Decimal],
    what: str,
) -> ScaledRow:
    """Scale one row. `reach` is each variable's largest absolute value, for
    the magnitude check; a product's reach is the product of its two."""
    numbers = [*coeffs.values(), *quadratic.values(), rhs]
    places = max((decimals(n) for n in numbers), default=0)
    if places > MAX_DECIMALS:
        raise NotScalable(f"{what} has a number with {places} decimal places; at most {MAX_DECIMALS} are scaled")
    lifted = Decimal(10) ** places
    whole = {k: int(v * lifted) for k, v in coeffs.items()}
    whole_q = {k: int(v * lifted) for k, v in quadratic.items()}
    whole_rhs = int(rhs * lifted)
    divisor = math.gcd(*whole.values(), *whole_q.values(), whole_rhs) or 1
    whole = {k: v // divisor for k, v in whole.items()}
    whole_q = {k: v // divisor for k, v in whole_q.items()}
    whole_rhs //= divisor

    activity = sum(abs(v) * reach[k] for k, v in whole.items())
    activity += sum(abs(v) * reach[a] * reach[b] for (a, b), v in whole_q.items())
    if activity + abs(whole_rhs) >= LIMIT:
        raise NotScalable(f"{what} would reach {activity + abs(whole_rhs):,} once scaled, past 2^53")
    return ScaledRow(whole, whole_q, whole_rhs, lifted / divisor)


def reach_of(compiled: Compiled) -> dict[Any, Decimal]:
    return {
        key: max(abs(spec.lower), abs(spec.upper)) for key, spec in compiled.variables.items()
    }


def check(compiled: Compiled) -> None:
    """Raise NotScalable naming the first rule, or the objective, that cannot
    be scaled. A continuous variable is never scalable: its value is not a
    count, and CP-SAT has no such variable to give it."""
    for key, spec in compiled.variables.items():
        if not spec.is_integral:
            raise NotScalable(f"{key[0]!r} is {spec.domain}, not a whole number")
    reach = reach_of(compiled)
    for c in compiled.constraints:
        coeffs = dict(c.left.coeffs)
        for key, coeff in c.right.coeffs.items():
            coeffs[key] = coeffs.get(key, Decimal(0)) - coeff
        scale(coeffs, c.right.const - c.left.const, c.quadratic, reach, f"rule {c.id!r}")
    scale(
        compiled.objective.coeffs, Decimal(0), compiled.objective_quadratic, reach, "the objective"
    )


def admit(found: Classification, compiled: Compiled) -> Classification:
    """With scaling on: a model that needs `fractional-data` only because its
    data is fractional, and whose rows scale, needs `scaled-fractional-data`
    instead -- which CP-SAT takes. Anything else is returned unchanged."""
    if FRACTIONAL not in found.needs:
        return found
    try:
        check(compiled)
    except NotScalable as exc:
        return replace(found, reasons=[*found.reasons, f"not scaled for CP-SAT: {exc}"])
    return replace(
        found,
        needs=(found.needs - {FRACTIONAL}) | {SCALED},
        reasons=[
            *found.reasons,
            "every number has at most 4 decimal places, so each rule can be multiplied into "
            "whole numbers exactly, and a solver that works in integers can take it",
        ],
    )
