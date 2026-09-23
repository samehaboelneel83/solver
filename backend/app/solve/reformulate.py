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
from app.solve.compile import Compiled, Constraint, Linear, PwlDef, Variable

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


# -- piecewise-linear curves (IR version 2, `pwl`) -------------------------------------

PWL = "pwl"
#: Every curve is convex where the objective only pushes it down (or concave
#: where it only pushes it up): an epigraph holds it with no binaries, so an
#: LP backend may take it too.
PWL_CONVEX = "pwl-convex"
#: Held by the backend itself: CP-SAT as a table, SCIP as SOS2.
PWL_NATIVE = "pwl-native"


def _pushed_down(compiled: Compiled, curve: PwlDef) -> bool:
    """Can an epigraph stand for this curve? Only if its y appears in no rule
    and nowhere but a weighted objective's linear part, and that objective
    presses y towards the curve from the side the curve bends away from."""
    y = curve.y
    if any(y in c.left.coeffs or y in c.right.coeffs for c in compiled.constraints):
        return False
    if any(y in pair for pair in compiled.objective_quadratic):
        return False
    if compiled.objective_mode == "lex" and any(y in t.coeffs for t in compiled.objective_terms):
        return False
    coeff = compiled.objective.coeffs.get(y, Decimal(0))
    pressure = coeff if compiled.sense == "minimize" else -coeff
    slopes = curve.slopes
    convex = all(b >= a for a, b in zip(slopes, slopes[1:]))
    concave = all(b <= a for a, b in zip(slopes, slopes[1:]))
    return pressure == 0 or (pressure > 0 and convex) or (pressure < 0 and concave)


def admit_pwl(found: Classification, compiled: Compiled) -> Classification:
    """What a model with curves needs once compiled: `pwl-convex` when every
    curve can be an epigraph (any backend, an LP one too), else `pwl`, which
    brings binaries with it on the backends that are not native -- so an LP
    becomes a MILP. A curve whose y is fractional makes the model mixed."""
    if PWL not in found.needs or not compiled.pwl:
        return found
    needs = set(found.needs)
    reasons = list(found.reasons)
    model_class = found.model_class
    if any(not compiled.variables[c.y].is_integral for c in compiled.pwl):
        needs.add("continuous")
        if model_class == "IP":
            model_class = "MILP"
    if all(_pushed_down(compiled, c) for c in compiled.pwl):
        needs = (needs - {PWL}) | {PWL_CONVEX}
        reasons.append(
            "every piecewise curve bends the way the goal pushes it, so it can be held by its "
            "tangent lines alone, with no yes-or-no decisions added"
        )
    else:
        needs.add("integral")
        if model_class == "LP":
            model_class = "MILP"
        reasons.append(
            "a piecewise curve is not convex in the direction the goal pushes it, so choosing "
            "its segment is a yes-or-no decision"
        )
    return replace(found, needs=needs, reasons=reasons, model_class=model_class)


def pwl_rewrite(compiled: Compiled) -> tuple[Compiled, list[dict[str, Any]]]:
    """Every curve as linear rows, for a backend that does not hold it
    natively: an epigraph where `_pushed_down` allows, else the incremental
    formulation (exact, and a stronger relaxation than convex combination)."""
    if not compiled.pwl:
        return compiled, []
    variables = dict(compiled.variables)
    rows = list(compiled.constraints)
    record = []
    for n, curve in enumerate(compiled.pwl):
        if _pushed_down(compiled, curve):
            rows += _epigraph(compiled, curve)
            record.append({"kind": "pwl-epigraph", "x": _name(curve.x), "segments": len(curve.points) - 1})
        else:
            new_vars, new_rows = _incremental(curve, n)
            variables.update(new_vars)
            rows += new_rows
            record.append({"kind": "pwl-incremental", "x": _name(curve.x), "segments": len(curve.points) - 1})
    return replace(compiled, variables=variables, constraints=rows, pwl=[]), record


_ID = "__pwl"


def _name(key) -> str:
    return key[0] + (f"[{','.join(key[1])}]" if key[1] else "")


def _within(curve: PwlDef) -> list[Constraint]:
    """x is kept between the first and last point."""
    (x0, _), (xn, _) = curve.points[0], curve.points[-1]
    x = Linear(coeffs={curve.x: Decimal(1)})
    return [
        Constraint(_ID, {}, x, ">=", Linear(const=x0)),
        Constraint(_ID, {}, Linear(coeffs={curve.x: Decimal(1)}), "<=", Linear(const=xn)),
    ]


def _epigraph(compiled: Compiled, curve: PwlDef) -> list[Constraint]:
    """y >= each segment's line (y <= for a concave curve pushed up): at the
    optimum y sits on the highest line, which for a convex curve is f(x)."""
    coeff = compiled.objective.coeffs.get(curve.y, Decimal(0))
    pressure = coeff if compiled.sense == "minimize" else -coeff
    relation = ">=" if pressure >= 0 else "<="
    rows = _within(curve)
    for (x0, y0), slope in zip(curve.points, curve.slopes):
        # y - slope * x  rel  y0 - slope * x0
        left = Linear(coeffs={curve.y: Decimal(1), curve.x: -slope})
        rows.append(Constraint(_ID, {}, left, relation, Linear(const=y0 - slope * x0)))
    return rows


def _incremental(curve: PwlDef, n: int) -> tuple[dict, list[Constraint]]:
    """x = x0 + sum d_k dx_k, y = y0 + sum d_k dy_k, 0 <= d_k <= 1, and
    d_{k+1} <= z_k <= d_k with z_k binary: segment k+1 is entered only once
    segment k is full."""
    pts = curve.points
    segments = len(pts) - 1
    d = [("__pwl_d", (str(n), str(k))) for k in range(segments)]
    z = [("__pwl_z", (str(n), str(k))) for k in range(segments - 1)]
    variables = {key: Variable(key, "continuous", Decimal(0), Decimal(1)) for key in d}
    variables.update({key: Variable(key, "binary", Decimal(0), Decimal(1)) for key in z})
    x_row = {curve.x: Decimal(1)}
    y_row = {curve.y: Decimal(1)}
    for k in range(segments):
        x_row[d[k]] = -(pts[k + 1][0] - pts[k][0])
        y_row[d[k]] = -(pts[k + 1][1] - pts[k][1])
    rows = [
        Constraint(_ID, {}, Linear(coeffs=x_row), "=", Linear(const=pts[0][0])),
        Constraint(_ID, {}, Linear(coeffs=y_row), "=", Linear(const=pts[0][1])),
    ]
    for k in range(segments - 1):
        rows.append(Constraint(_ID, {}, Linear(coeffs={d[k + 1]: Decimal(1), z[k]: Decimal(-1)}), "<=", Linear()))
        rows.append(Constraint(_ID, {}, Linear(coeffs={z[k]: Decimal(1), d[k]: Decimal(-1)}), "<=", Linear()))
    return variables, rows
