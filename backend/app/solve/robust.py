"""Robust solving: an answer that holds however the uncertain data turns out.

A parameter may declare that its values may be off by up to a fraction of
themselves (IR version 2, `uncertainty: {kind: interval, deviation, gamma}`).
A rule that reads it then has coefficients that may move -- each by its
deviation `a_hat_j` -- and the answer should hold for any `gamma` of them
moving at once (Bertsimas and Sim's budget; all of them when absent, which
is Soyster's fully protected rule).

**The rewrite is exact and linear** (Bertsimas & Sim, "The Price of
Robustness", 2004). For a rule `sum a_j x_j <= b` with budget G, the worst
case adds `max over |S| <= G of sum_{j in S} a_hat_j |x_j|` to the left.
By duality that maximum is the least of `G z + sum p_j` subject to
`z + p_j >= a_hat_j |x_j|`, `z, p_j >= 0`; so the robust rule is

    sum a_j x_j + G z + sum p_j <= b,   z + p_j >= a_hat_j y_j,   y_j >= |x_j|

with `y_j` replaced by `x_j` itself when `x_j` cannot go below zero. A
`>=` rule is the same on the negated row; a moving right-hand side is a
coefficient on a constant 1. A fractional G is exact too.

**Where the deviations come from.** The model is compiled once more for
each uncertain parameter with that parameter's values raised by their
deviation; the change in each row's coefficients is exactly how far each
may move (the compiler is linear in a parameter's values). Rows line up
because compiling is deterministic in everything but the values.

**What it refuses.** An equality rule whose coefficients may move -- it
cannot hold for every deviation -- and a quadratic rule that reads an
uncertain parameter. The goal is left nominal: uncertainty is in the rules.

Target roadmap Phase 15; the run reports the price of robustness -- the
robust goal against the nominal one.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Any

from app.solve.compile import Compiled, Constraint, Linear, Variable, compile_model

_ID_Z, _ID_P, _ID_Y = "__robust_z", "__robust_p", "__robust_y"


class NotRobust(ValueError):
    """A rule that cannot be made robust, named."""


@dataclass
class RowDeviation:
    #: variable -> how far its coefficient may move (always >= 0)
    coefficients: dict = field(default_factory=dict)
    #: how far the rule's constant may move
    constant: Decimal = Decimal(0)
    #: the budget: how many of these may move at once
    gamma: Decimal = Decimal(0)


def uncertain_parameters(ir: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        name: spec["uncertainty"]
        for name, spec in (ir.get("parameters") or {}).items()
        if isinstance(spec, dict) and (spec.get("uncertainty") or {}).get("kind") == "interval"
    }


def deviations(ir: dict[str, Any], data: dict[str, Any], compiled: Compiled) -> dict[int, RowDeviation]:
    """Per row (by position in `compiled.constraints`), how far it may move."""
    found: dict[int, RowDeviation] = {}
    for name, spec in uncertain_parameters(ir).items():
        share = Decimal(str(spec["deviation"]))
        if share == 0:
            continue
        raised = copy.deepcopy(data)
        for row in raised.get("parameters", {}).get(name, []):
            row["value"] = float(Decimal(str(row["value"])) * (1 + share))
        if name in raised.get("parameter_defaults", {}):
            raised["parameter_defaults"][name] = float(Decimal(str(raised["parameter_defaults"][name])) * (1 + share))
        other = compile_model(ir, raised)
        if len(other.constraints) != len(compiled.constraints):  # pragma: no cover -- deterministic compile
            raise NotRobust(f"raising {name!r} changed the rules themselves, not only their numbers")
        for i, (a, b) in enumerate(zip(compiled.constraints, other.constraints, strict=True)):
            moved = _moved(a, b)
            if not moved[0] and not moved[1]:
                continue
            if a.quadratic or b.quadratic:
                raise NotRobust(f"the rule {a.id!r} multiplies decisions and reads the uncertain {name!r}")
            if a.relation in ("=", "=="):
                raise NotRobust(
                    f"the rule {a.id!r} is an equality that reads the uncertain {name!r}: it cannot hold "
                    "for every value the data may take -- make it an inequality, or the data exact"
                )
            row = found.setdefault(i, RowDeviation())
            for key, amount in moved[0].items():
                row.coefficients[key] = row.coefficients.get(key, Decimal(0)) + amount
            row.constant += moved[1]
            gamma = spec.get("gamma")
            row.gamma = max(row.gamma, Decimal(str(gamma)) if gamma is not None else Decimal("Infinity"))
    for row in found.values():
        count = len(row.coefficients) + (1 if row.constant else 0)
        row.gamma = min(row.gamma, Decimal(count))
    return found


def _moved(a: Constraint, b: Constraint) -> tuple[dict, Decimal]:
    """How far each coefficient of `left - right` moved, and the constant."""
    def net(c: Constraint) -> tuple[dict, Decimal]:
        coeffs = dict(c.left.coeffs)
        for key, value in c.right.coeffs.items():
            coeffs[key] = coeffs.get(key, Decimal(0)) - value
        return coeffs, c.right.const - c.left.const

    (ca, ka), (cb, kb) = net(a), net(b)
    moved = {key: abs(cb.get(key, Decimal(0)) - ca.get(key, Decimal(0))) for key in set(ca) | set(cb)}
    return {k: v for k, v in moved.items() if v}, abs(kb - ka)


def rewrite(compiled: Compiled, rows: dict[int, RowDeviation]) -> tuple[Compiled, list[dict[str, Any]]]:
    """The robust counterpart of every row that may move, exactly."""
    variables = dict(compiled.variables)
    constraints = list(compiled.constraints)
    record = []
    for i, dev in sorted(rows.items()):
        c = compiled.constraints[i]
        # As `expr <= b`: a `>=` rule is the same on its negation.
        sign = Decimal(-1) if c.relation in (">=", ">") else Decimal(1)
        left = Linear().add(c.left, factor=sign).add(c.right, factor=-sign)
        z = (_ID_Z, (str(i),))
        variables[z] = Variable(z, "continuous", Decimal(0), Decimal("1e12"))
        protection = Linear(coeffs={z: dev.gamma})
        extra: list[Constraint] = []
        for n, (key, amount) in enumerate(sorted(dev.coefficients.items(), key=lambda kv: repr(kv[0]))):
            p = (_ID_P, (str(i), str(n)))
            variables[p] = Variable(p, "continuous", Decimal(0), Decimal("1e12"))
            protection.add(Linear(coeffs={p: Decimal(1)}))
            spec = compiled.variables[key]
            if spec.lower >= 0:
                size = Linear(coeffs={key: amount})
            else:
                y = (_ID_Y, (str(i), str(n)))
                variables[y] = Variable(y, "continuous", Decimal(0), max(abs(spec.lower), abs(spec.upper)))
                extra.append(Constraint(c.id, dict(c.index), Linear(coeffs={y: Decimal(1), key: Decimal(-1)}), ">=", Linear()))
                extra.append(Constraint(c.id, dict(c.index), Linear(coeffs={y: Decimal(1), key: Decimal(1)}), ">=", Linear()))
                size = Linear(coeffs={y: amount})
            # z + p_j >= a_hat_j |x_j|
            extra.append(Constraint(c.id, dict(c.index), Linear(coeffs={z: Decimal(1), p: Decimal(1)}).add(size, factor=-1), ">=", Linear()))
        if dev.constant:
            # The right-hand side moves too: a coefficient on a constant 1.
            p = (_ID_P, (str(i), "rhs"))
            variables[p] = Variable(p, "continuous", Decimal(0), Decimal("1e12"))
            protection.add(Linear(coeffs={p: Decimal(1)}))
            extra.append(Constraint(c.id, dict(c.index), Linear(coeffs={z: Decimal(1), p: Decimal(1)}), ">=", Linear(const=dev.constant)))
        constraints[i] = Constraint(c.id, dict(c.index), left.add(protection), "<=", Linear(), when=c.when)
        constraints += extra
        record.append({"rule": c.id, "index": [str(v) for v in c.index.values()], "moving": len(dev.coefficients) + (1 if dev.constant else 0), "gamma": float(dev.gamma)})
    return replace(compiled, variables=variables, constraints=constraints), record
