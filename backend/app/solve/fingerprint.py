"""What a model looks like to a solver: a fixed set of numbers, computed on every run.

Phase 17's learned selector trains on these (target roadmap: "counts by var
type, nnz, row types, coefficient range and integrality, bound tightness,
indicator/scheduling counts, block count, density, objective degree"), and
they are what an analyst groups runs by in `run_fact`. Computed from the
compiled model -- after every `forall` is expanded -- because that is what a
solver is given.

**Row types** follow the MIPLIB-style classes, on the row as written (`left -
right`), all decisions yes-or-no and every coefficient 1 unless said:

- `partition`  -- sum = 1
- `cover`      -- sum >= 1
- `packing`    -- sum <= 1
- `cardinality`-- sum <= k, >= k or = k for a whole k > 1
- `knapsack`   -- yes-or-no decisions, non-negative whole coefficients, <= a bound
- `general`    -- anything else linear
- `quadratic`, `conditional`, `scheduling` -- a product, a `when`, a scheduling rule
- `connectivity` -- a row of a `connected` rule's flow (version 2 of this vector)

`VERSION` changes whenever a field is added or its meaning changes, so a
model trained on one version is never fed another's numbers unknowingly.
"""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Any

from app.solve.compile import Compiled, Constraint

VERSION = 2


def _net(c: Constraint) -> tuple[dict, Decimal]:
    coeffs: dict = dict(c.left.coeffs)
    for key, value in c.right.coeffs.items():
        coeffs[key] = coeffs.get(key, Decimal(0)) - value
    return {k: v for k, v in coeffs.items() if v}, c.right.const - c.left.const


def row_type(compiled: Compiled, c: Constraint) -> str:
    if c.id in compiled.connectivity:
        return "connectivity"
    if c.schedule is not None:
        return "scheduling"
    if c.quadratic:
        return "quadratic"
    if c.when is not None:
        return "conditional"
    coeffs, rhs = _net(c)
    if not coeffs:
        return "general"
    relation = c.relation
    if all(v < 0 for v in coeffs.values()):
        # `-x - y <= -1` is `x + y >= 1`.
        coeffs, rhs = {k: -v for k, v in coeffs.items()}, -rhs
        relation = {"<=": ">=", ">=": "<=", "<": ">", ">": "<"}.get(relation, relation)
    binary = all(compiled.variables[k].domain == "binary" for k in coeffs)
    if binary and all(v == 1 for v in coeffs.values()) and rhs == rhs.to_integral_value():
        if rhs == 1:
            return {"=": "partition", "==": "partition", ">=": "cover", "<=": "packing"}.get(relation, "general")
        if rhs > 1:
            return "cardinality"
    if binary and relation == "<=" and all(v > 0 and v == v.to_integral_value() for v in coeffs.values()):
        return "knapsack"
    return "general"


def fingerprint(compiled: Compiled) -> dict[str, Any]:
    """The model's numbers, as a flat dict of ints, floats and bools."""
    from app.solve.blocks import blocks

    variables = list(compiled.variables.values())
    decisions = [v for v in variables if not v.key[0].startswith("__")]
    by_domain = {d: sum(v.domain == d for v in decisions) for d in ("binary", "integer", "continuous")}
    rows = compiled.constraints
    types: dict[str, int] = {}
    nnz = 0
    magnitudes: list[float] = []
    integral = True
    for c in rows:
        kind = row_type(compiled, c)
        types[kind] = types.get(kind, 0) + 1
        coeffs, rhs = _net(c)
        nnz += len(coeffs) + len(c.quadratic)
        for value in (*coeffs.values(), *c.quadratic.values()):
            magnitudes.append(abs(float(value)))
            integral = integral and value == value.to_integral_value()
        integral = integral and rhs == rhs.to_integral_value()
    goal = [*compiled.objective.coeffs.values(), *compiled.objective_quadratic.values()]
    integral = integral and all(v == v.to_integral_value() for v in goal)
    bounded = [v for v in decisions if v.domain != "binary"]
    declared = [v for v in bounded if not v.default_upper]
    spans = [float(v.upper - v.lower) for v in declared]
    n_vars, n_rows = len(variables), len(rows)
    return {
        "version": VERSION,
        "variables": n_vars,
        "binary": by_domain["binary"],
        "integer": by_domain["integer"],
        "continuous": by_domain["continuous"],
        "auxiliary": n_vars - len(decisions),
        "rows": n_rows,
        "nnz": nnz,
        "density": round(nnz / (n_vars * n_rows), 6) if n_vars and n_rows else 0.0,
        **{f"rows_{kind}": types.get(kind, 0) for kind in (
            "partition", "cover", "packing", "cardinality", "knapsack", "general",
            "quadratic", "conditional", "scheduling", "connectivity")},
        "coef_min": min(magnitudes) if magnitudes else 0.0,
        "coef_max": max(magnitudes) if magnitudes else 0.0,
        # Orders of magnitude between the smallest and largest coefficient:
        # past about 6, numerical trouble is likely.
        "coef_range_log10": round(math.log10(max(magnitudes) / min(magnitudes)), 3) if magnitudes else 0.0,
        "integral_data": integral,
        # Of the non-binary decisions, the share whose upper bound the model
        # declared (not the compiler's guard), and their median width.
        "bounds_declared": round(len(declared) / len(bounded), 6) if bounded else 1.0,
        "bound_width_median": sorted(spans)[len(spans) // 2] if spans else 0.0,
        "intervals": len(compiled.intervals),
        "curves": len(compiled.pwl),
        "functions": len(compiled.functions),
        "soft_rules": len(compiled.penalty_of),
        "blocks": len(blocks(compiled)),
        "objective_degree": 2 if compiled.objective_quadratic else (1 if compiled.objective.coeffs else 0),
        "objective_terms": len(compiled.objective_terms) or (1 if compiled.objective.coeffs else 0),
        "lexicographic": compiled.objective_mode == "lex",
    }
