"""B-E. The mathematical model, independent of any solver.

A small algebra: variables with bounds and a kind, linear expressions,
constraints (each tagged with the group it belongs to, so a report can say
"4 312 non-overlap rows"), and named objective expressions with a sense.
Adapters translate this into CP-SAT, HiGHS, or anything else; nothing here
imports a solver.

`relaxable` marks an integer variable whose integrality the model does not
need (network flows: integral optimal flows exist when every demand is
integral). A MILP adapter may make it continuous, which is far cheaper; a CP
adapter keeps it integer, which it must.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Literal

Kind = Literal["binary", "integer", "continuous"]
Sense = Literal["<=", ">=", "=="]


@dataclass
class Var:
    index: int
    name: str
    lb: float
    ub: float
    kind: Kind
    relaxable: bool = False


class Expr:
    """Σ coef·var + constant, with vars by index."""

    __slots__ = ("terms", "constant")

    def __init__(self, terms: dict[int, float] | None = None, constant: float = 0.0):
        self.terms = terms or {}
        self.constant = constant

    @staticmethod
    def of(pairs, constant: float = 0.0) -> "Expr":
        e = Expr(constant=constant)
        for var, coef in pairs:
            e.add(var, coef)
        return e

    def add(self, var: Var | int, coef: float = 1.0) -> "Expr":
        k = var.index if isinstance(var, Var) else var
        v = self.terms.get(k, 0.0) + coef
        if v == 0.0:
            self.terms.pop(k, None)
        else:
            self.terms[k] = v
        return self

    def plus(self, other: "Expr", factor: float = 1.0) -> "Expr":
        out = Expr(dict(self.terms), self.constant + other.constant * factor)
        for k, c in other.terms.items():
            out.add(k, c * factor)
        return out

    def scaled(self, factor: float) -> "Expr":
        return Expr({k: c * factor for k, c in self.terms.items()}, self.constant * factor)

    def value(self, values) -> float:
        return self.constant + sum(c * values[k] for k, c in self.terms.items())


@dataclass
class Constraint:
    expr: Expr
    sense: Sense
    rhs: float
    group: str


@dataclass
class Objective:
    name: str
    expr: Expr
    sense: Literal["max", "min"]
    scale: float  # a typical size, for normalisation in weighted mode
    unit: str


@dataclass
class MathematicalModel:
    vars: list[Var] = field(default_factory=list)
    constraints: list[Constraint] = field(default_factory=list)
    objectives: dict[str, Objective] = field(default_factory=dict)
    hint: dict[int, float] = field(default_factory=dict)

    def var(self, name: str, lb: float = 0.0, ub: float = 1.0, kind: Kind = "binary", relaxable: bool = False) -> Var:
        v = Var(len(self.vars), name, lb, ub, kind, relaxable)
        self.vars.append(v)
        return v

    def add(self, expr: Expr, sense: Sense, rhs: float, group: str) -> None:
        # Move the constant across: expr.terms (sense) rhs - constant.
        self.constraints.append(Constraint(Expr(expr.terms), sense, rhs - expr.constant, group))

    def size(self) -> dict[str, object]:
        kinds = Counter(v.kind for v in self.vars)
        return {"variables": len(self.vars), "by_kind": dict(kinds),
                "constraints": len(self.constraints), "by_group": dict(Counter(c.group for c in self.constraints)),
                "nonzeros": sum(len(c.expr.terms) for c in self.constraints)}


def violations(model: MathematicalModel, values, tol: float = 1e-6) -> list[str]:
    """Rows and bounds a set of values breaks -- for checking a start or a result."""
    out = []
    for v in model.vars:
        x = values[v.index]
        if x < v.lb - tol or x > v.ub + tol:
            out.append(f"{v.name}={x} outside [{v.lb}, {v.ub}]")
    for c in model.constraints:
        lhs = sum(coef * values[k] for k, coef in c.expr.terms.items())
        bad = (c.sense == "<=" and lhs > c.rhs + tol) or (c.sense == ">=" and lhs < c.rhs - tol) or \
              (c.sense == "==" and abs(lhs - c.rhs) > tol)
        if bad:
            names = ", ".join(f"{coef:g}*{model.vars[k].name}" for k, coef in list(c.expr.terms.items())[:6])
            out.append(f"{c.group}: {names} {c.sense} {c.rhs} (is {lhs:g})")
    return out
