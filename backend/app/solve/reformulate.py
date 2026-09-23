"""Conditional rules for the backends that have no indicator: a big-M, as tight as the bounds allow.

CP-SAT and SCIP hold a `when` natively (an enforcement literal, an
indicator constraint). HiGHS and the MILP wrapper have no such thing, so a
conditional rule reaches them rewritten: for `expr <= rhs` switched on by a
literal `L` (the switch, or `1 - switch` when `is` is 0),

    expr <= rhs + M (1 - L)

holds whatever L is when L = 0 -- provided M is at least the most `expr` can
exceed `rhs` by. That most is computed from the variables' **declared**
bounds: `M = max(expr) - rhs` over the box, the tightest M that is still
correct (a larger one weakens the relaxation, a smaller one cuts off
answers). `>=` is the mirror image, `=` both halves. A rule whose M comes
out <= 0 can never be violated and needs no row at all; a rule with nothing
left to decide that cannot hold forbids its switch instead.

**A bound the model never set is not a bound.** An integer or continuous
variable without an `upper` gets the compiler's guard ceiling
(`DEFAULT_UPPER`, marked `default_upper`); an M derived from it would be a
million, and the rewrite would quietly depend on a number nobody chose.
`admit` refuses that, naming the variable, and leaves the model to the
backends that take the rule as it is.

Target roadmap Phase 10, "big-M from declared bounds"; D9's marking is what
makes the refusal possible.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Any

from app.solve.classify import Classification
from app.solve.compile import Compiled, Constraint, Linear

INDICATOR = "indicator"
#: What a model with conditional rules needs once every variable those
#: rules touch has declared bounds: a big-M can then be derived exactly, so
#: a backend without native indicators may take it too.
INDICATOR_BOUNDED = "indicator-bounded"


def _rows_of(c: Constraint) -> tuple[dict, Decimal]:
    """`left - right` as coefficients, and the constant moved to the right."""
    coeffs: dict = dict(c.left.coeffs)
    for key, coeff in c.right.coeffs.items():
        coeffs[key] = coeffs.get(key, Decimal(0)) - coeff
    return {k: v for k, v in coeffs.items() if v}, c.right.const - c.left.const


def unbounded_in(compiled: Compiled) -> tuple[str, str] | None:
    """The first (rule id, variable) whose ceiling is only the compiler's guard."""
    for c in compiled.constraints:
        if c.when is None:
            continue
        coeffs, _ = _rows_of(c)
        for key in coeffs:
            if compiled.variables[key].default_upper:
                name = key[0] + (f"[{','.join(key[1])}]" if key[1] else "")
                return c.id, name
    return None


def admit(found: Classification, compiled: Compiled) -> Classification:
    """With every conditional rule over declared bounds, the model needs
    `indicator-bounded` -- which the big-M backends provide too; otherwise
    it keeps `indicator`, and the reason a big-M backend may not take it."""
    if INDICATOR not in found.needs:
        return found
    blocked = unbounded_in(compiled)
    if blocked is not None:
        rule, variable = blocked
        return replace(
            found,
            refusals={
                **found.refusals,
                INDICATOR: (
                    f"the conditional rule {rule!r} uses {variable}, which has no declared upper "
                    "bound, so no big-M can be derived from it -- declare one, or let a solver "
                    "that holds the rule natively (CP-SAT, SCIP) take it"
                ),
            },
        )
    return replace(
        found,
        needs=(found.needs - {INDICATOR}) | {INDICATOR_BOUNDED},
        reasons=[
            *found.reasons,
            "every decision a conditional rule touches has declared bounds, so the rule can "
            "also be written with a big-M derived from them",
        ],
    )


def bigm(compiled: Compiled) -> tuple[Compiled, list[dict[str, Any]]]:
    """The model with every conditional rule rewritten; and, per rule, how
    many rows it became and the largest M used (for the run's record)."""
    rows: list[Constraint] = []
    record: dict[str, dict[str, Any]] = {}
    for c in compiled.constraints:
        if c.when is None:
            rows.append(c)
            continue
        entry = record.setdefault(c.id, {"rule": c.id, "kind": "big-m", "rows": 0, "largest_m": 0.0})
        for row in _rewrite(compiled, c):
            rows.append(row)
            entry["rows"] += 1
            entry["largest_m"] = max(entry["largest_m"], float(row._big_m))  # type: ignore[attr-defined]
    return replace(compiled, constraints=rows), list(record.values())


def _rewrite(compiled: Compiled, c: Constraint) -> list[Constraint]:
    if c.quadratic:  # pragma: no cover -- the validator refuses `when_on_product`
        raise ValueError(f"{c.id!r} is conditional and quadratic")
    switch, value = c.when
    coeffs, rhs = _rows_of(c)
    if c.relation == "<":
        rhs, relation = rhs - 1, "<="
    elif c.relation == ">":
        rhs, relation = rhs + 1, ">="
    else:
        relation = "=" if c.relation == "==" else c.relation

    if not coeffs:
        holds = {"<=": 0 <= rhs, ">=": 0 >= rhs, "=": rhs == 0}[relation]
        if holds:
            return []
        # It can never hold, so it may never be switched on.
        forbid = Linear(coeffs={switch: Decimal(1)})
        return [_row(c, forbid, "<=" if value == 1 else ">=", Decimal(0) if value == 1 else Decimal(1), Decimal(0))]

    highest = sum(a * (compiled.variables[k].upper if a > 0 else compiled.variables[k].lower) for k, a in coeffs.items())
    lowest = sum(a * (compiled.variables[k].lower if a > 0 else compiled.variables[k].upper) for k, a in coeffs.items())
    out: list[Constraint] = []
    if relation in ("<=", "="):
        m = highest - rhs
        if m > 0:
            out.append(_relaxed(c, coeffs, "<=", rhs, m, switch, value))
    if relation in (">=", "="):
        m = rhs - lowest
        if m > 0:
            out.append(_relaxed(c, coeffs, ">=", rhs, m, switch, value))
    return out


def _relaxed(c: Constraint, coeffs: dict, relation: str, rhs: Decimal, m: Decimal, switch, value: int) -> Constraint:
    """`expr <= rhs + M (1 - L)` or `expr >= rhs - M (1 - L)`, with L the
    switch (value 1) or 1 - switch (value 0), rearranged to one linear row."""
    left = dict(coeffs)
    sign = 1 if relation == "<=" else -1
    if value == 1:
        # expr + sign*M*s  rel  rhs + sign*M
        left[switch] = left.get(switch, Decimal(0)) + sign * m
        bound = rhs + sign * m
    else:
        # expr - sign*M*s  rel  rhs
        left[switch] = left.get(switch, Decimal(0)) - sign * m
        bound = rhs
    return _row(c, Linear(coeffs=left), relation, bound, m)


def _row(c: Constraint, left: Linear, relation: str, bound: Decimal, m: Decimal) -> Constraint:
    row = Constraint(c.id, dict(c.index), left, relation, Linear(const=bound))
    row._big_m = m  # type: ignore[attr-defined]
    return row
