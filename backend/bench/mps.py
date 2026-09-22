"""The MIPLIB lane: MPS files read straight into `Compiled`.

MIPLIB instances are published models with known optimal values, so they
measure what the generated families cannot: solver settings on problems
built by other people, at sizes and shapes this platform does not generate.
They skip the IR entirely -- there is no IR for them -- so this lane can only
compare *solver-parameter* techniques (gap, threads, seeds), never an IR-level
rewrite. `python -m bench.download_miplib` fetches them; they are not
committed.

The reader takes free-format MPS -- NAME, ROWS, COLUMNS (with integer
markers), RHS, RANGES, BOUNDS, ENDATA -- which is what MIPLIB 2017 ships.
An infinite bound is kept as `Decimal("Infinity")`: only HiGHS and the
pywraplp wrapper are run on this lane, and both take one. CP-SAT, which
needs finite bounds, is not offered MPS instances.
"""

from __future__ import annotations

import gzip
from decimal import Decimal
from pathlib import Path

from app.solve.classify import Classification
from app.solve.compile import Compiled, Constraint, Linear, Variable

INF = Decimal("Infinity")

# Backends this lane runs: the two that take infinite bounds.
MPS_BACKENDS = ("highs", "milp")

#: What `bench.download_miplib` saves MIPLIB's solution file as.
SOLU_FILE = "miplib2017.solu"


def known_optima(directory: str) -> dict[str, float | str]:
    """The published answer per instance, from MIPLIB's solution file in
    `directory`: a proven optimal value, or "infeasible". Lines marked
    `=best=` (an incumbent nobody has proven) are not answers and are left
    out. Empty when the file is absent."""
    import os

    path = os.path.join(directory, SOLU_FILE)
    if not os.path.exists(path):
        return {}
    found: dict[str, float | str] = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            parts = line.split()
            if len(parts) >= 3 and parts[0] == "=opt=":
                found[parts[1]] = float(parts[2])
            elif len(parts) >= 2 and parts[0] == "=inf=":
                found[parts[1]] = "infeasible"
    return found


def read(path: str | Path) -> Compiled:
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8", errors="replace") as handle:
        return parse(handle.read())


def parse(text: str) -> Compiled:
    section = None
    objective_row: str | None = None
    row_kind: dict[str, str] = {}
    row_order: list[str] = []
    coeffs: dict[str, dict[tuple, Decimal]] = {}
    objective: dict[tuple, Decimal] = {}
    rhs: dict[str, Decimal] = {}
    ranges: dict[str, Decimal] = {}
    columns: list[str] = []
    integer: set[str] = set()
    lower: dict[str, Decimal] = {}
    upper: dict[str, Decimal] = {}
    in_integer = False
    sense = "minimize"
    objective_const = Decimal(0)

    for raw in text.splitlines():
        if not raw.strip() or raw.startswith("*"):
            continue
        if not raw[0].isspace():
            head = raw.split()
            section = head[0].upper()
            if section == "OBJSENSE" and len(head) > 1:
                sense = "maximize" if head[1].upper().startswith("MAX") else "minimize"
            continue
        fields = raw.split()
        if section == "OBJSENSE":
            sense = "maximize" if fields[0].upper().startswith("MAX") else "minimize"
        elif section == "ROWS":
            kind, name = fields[0].upper(), fields[1]
            if kind == "N":
                objective_row = objective_row or name
            else:
                row_kind[name] = kind
                row_order.append(name)
                coeffs[name] = {}
        elif section == "COLUMNS":
            if len(fields) >= 3 and fields[1].strip("'").upper() == "MARKER":
                marker = fields[2].strip("'").upper()
                in_integer = marker == "INTORG"
                continue
            column = fields[0]
            if not columns or columns[-1] != column:
                columns.append(column)
            if in_integer:
                integer.add(column)
            key = ("x", (column,))
            for row, value in zip(fields[1::2], fields[2::2]):
                if row == objective_row:
                    objective[key] = objective.get(key, Decimal(0)) + Decimal(value)
                elif row in coeffs:
                    coeffs[row][key] = coeffs[row].get(key, Decimal(0)) + Decimal(value)
        elif section == "RHS":
            pairs = fields[1:] if len(fields) % 2 == 1 else fields
            for row, value in zip(pairs[0::2], pairs[1::2]):
                if row == objective_row:
                    objective_const = -Decimal(value)
                else:
                    rhs[row] = Decimal(value)
        elif section == "RANGES":
            pairs = fields[1:] if len(fields) % 2 == 1 else fields
            for row, value in zip(pairs[0::2], pairs[1::2]):
                ranges[row] = Decimal(value)
        elif section == "BOUNDS":
            kind, column = fields[0].upper(), fields[2]
            value = Decimal(fields[3]) if len(fields) > 3 else None
            if kind == "UP":
                upper[column] = value
                # MPS: an upper bound below zero with no lower bound set
                # makes the lower bound minus infinity.
                if value < 0 and column not in lower:
                    lower[column] = -INF
            elif kind == "LO":
                lower[column] = value
            elif kind == "FX":
                lower[column] = upper[column] = value
            elif kind == "FR":
                lower[column], upper[column] = -INF, INF
            elif kind == "MI":
                lower[column] = -INF
            elif kind == "PL":
                upper[column] = INF
            elif kind == "BV":
                integer.add(column)
                lower[column], upper[column] = Decimal(0), Decimal(1)
            elif kind in ("LI", "UI"):
                integer.add(column)
                (lower if kind == "LI" else upper)[column] = value
        elif section == "ENDATA":
            break

    variables = {}
    for column in columns:
        key = ("x", (column,))
        is_int = column in integer
        low = lower.get(column, Decimal(0))
        # An integer column with no upper bound is binary in MPS's oldest
        # convention only when it was declared by marker without bounds; the
        # MIPLIB 2017 files state bounds, so infinity is the reading here.
        high = upper.get(column, INF)
        domain = "binary" if is_int and low == 0 and high == 1 else ("integer" if is_int else "continuous")
        variables[key] = Variable(key, domain, low, high)

    constraints: list[Constraint] = []
    for row in row_order:
        left = Linear(coeffs[row])
        value = rhs.get(row, Decimal(0))
        kind = row_kind[row]
        span = ranges.get(row)
        if span is None:
            relation = {"L": "<=", "G": ">=", "E": "="}[kind]
            constraints.append(Constraint(row, {}, left, relation, Linear(const=value)))
            continue
        if kind == "L":
            low, high = value - abs(span), value
        elif kind == "G":
            low, high = value, value + abs(span)
        else:
            low, high = (value, value + span) if span > 0 else (value + span, value)
        constraints.append(Constraint(row, {"range": "low"}, left, ">=", Linear(const=low)))
        constraints.append(Constraint(row, {"range": "high"}, Linear(dict(left.coeffs)), "<=", Linear(const=high)))

    return Compiled(
        variables=variables,
        constraints=constraints,
        objective=Linear(objective, objective_const),
        sense=sense,
        var_index_sets={"x": []},
    )


def classify_compiled(compiled: Compiled) -> Classification:
    """The class an MPS model would have had: there is no IR to classify."""
    integral = any(v.is_integral for v in compiled.variables.values())
    continuous = any(not v.is_integral for v in compiled.variables.values())
    needs = {"linear"}
    if integral:
        needs.add("integral")
    if continuous:
        needs.add("continuous")
    if not compiled.is_integral:
        needs.add("fractional-data")
    model_class = "MILP" if integral and continuous else ("IP" if integral else "LP")
    return Classification(model_class, ["read from MPS"], needs)
