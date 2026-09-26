"""A compiled model as free-format MPS, for a solver that is a program (queue R41's command-line
adapters). Columns are named `v0, v1, ...` and rows `r0, r1, ...` in the compiled model's own
order, so a solution file's names map straight back; the goal row is `obj`.

Written here, not exported through OR-Tools: its exporter renames every column (`auto_v_...`) when
it pleases, and a mapping resting on another program's naming scheme would break unseen. Only a
linear model is written -- a rule the linear translation cannot carry is refused, as the backends
that take MPS would refuse it. The goal's constant is left out: the platform works the objective
out from the values itself.
"""

from __future__ import annotations

import math
from pathlib import Path

from app.solve.compile import Compiled
from app.solve.pywraplp_model import row_bounds


def write(compiled: Compiled, path: Path) -> None:
    if compiled.pwl or compiled.functions or compiled.intervals or compiled.objective_quadratic:
        raise ValueError("only a linear model can be written as MPS")
    keys = list(compiled.variables)
    column = {key: f"v{i}" for i, key in enumerate(keys)}
    lines = ["NAME          model", "OBJSENSE", "    MAX" if compiled.sense != "minimize" else "    MIN", "ROWS",
             " N  obj"]
    entries: dict[str, list[tuple[str, float]]] = {column[k]: [] for k in keys}
    rhs: list[tuple[str, float]] = []
    ranges: list[tuple[str, float]] = []
    for i, c in enumerate(compiled.constraints):
        if c.quadratic or c.when is not None or c.schedule is not None:
            raise ValueError(f"{c.id!r} is not a linear rule, which MPS cannot hold here")
        coeffs, lower, upper = row_bounds(c)
        name = f"r{i}"
        if lower == upper:
            kind, bound = "E", lower
        elif math.isinf(lower) and math.isinf(upper):
            kind, bound = "N", None
        elif math.isinf(lower):
            kind, bound = "L", upper
        elif math.isinf(upper):
            kind, bound = "G", lower
        else:
            kind, bound = "G", lower
            ranges.append((name, upper - lower))
        lines.append(f" {kind}  {name}")
        if bound:
            rhs.append((name, bound))
        for key, coeff in coeffs.items():
            if coeff:
                entries[column[key]].append((name, float(coeff)))
    for key, coeff in compiled.objective.coeffs.items():
        if coeff:
            entries[column[key]].insert(0, ("obj", float(coeff)))

    lines.append("COLUMNS")
    integral = False
    for key in keys:
        name, whole = column[key], compiled.variables[key].is_integral
        if whole != integral:
            lines.append("    MARKER  'MARKER'  'INTORG'" if whole else "    MARKER  'MARKER'  'INTEND'")
            integral = whole
        # A column in no row and not in the goal is still a column: a zero goal entry keeps it.
        for row, coeff in entries[name] or [("obj", 0.0)]:
            lines.append(f"    {name}  {row}  {coeff!r}")
    if integral:
        lines.append("    MARKER  'MARKER'  'INTEND'")
    lines.append("RHS")
    lines.extend(f"    rhs  {row}  {value!r}" for row, value in rhs)
    if ranges:
        lines.append("RANGES")
        lines.extend(f"    rng  {row}  {value!r}" for row, value in ranges)
    lines.append("BOUNDS")
    for key in keys:
        spec, name = compiled.variables[key], column[key]
        if spec.domain == "binary":
            lines.append(f" BV bnd  {name}")
            continue
        lower, upper = float(spec.lower), float(spec.upper)
        if math.isinf(lower) and math.isinf(upper):
            lines.append(f" FR bnd  {name}")
            continue
        lines.append(f" MI bnd  {name}" if math.isinf(lower) else f" LO bnd  {name}  {lower!r}")
        if not math.isinf(upper):
            lines.append(f" UP bnd  {name}  {upper!r}")
    lines.append("ENDATA")
    path.write_text("\n".join(lines) + "\n", encoding="ascii")
