"""Shape a solver answer for storage and the UI (OAAS P2 / service stage).

Turns a ``Compiled`` model and a ``Solution`` into the JSON the ``solution``
row and amount chunks hold: which cells were used, how much each continuous
or whole-number decision took, and non-zero reduced costs.

Kept out of ``service.py`` so recording a run and choosing a solver stay
readable; the worker still enters through ``service.execute_run``.
"""

from __future__ import annotations

from typing import Any

from app.solve.compile import Compiled
from app.solve.result import Solution

#: Past this many used whole or fractional cells, a run keeps amounts in
#: `solution_amount_chunk` instead of the inline `solution.amounts` column
#: (queue R23 / OAAS Phase 5). The roster still says which cells were used;
#: `params.amounts_chunked` records the cell count and chunking.
AMOUNT_CELLS = 200_000

#: Max cells stored in one `solution_amount_chunk` row.
AMOUNT_CHUNK = 50_000

_REDUCED_COST_FLOOR = 1e-8


def assignments(compiled: Compiled, result: Solution) -> dict[str, list[list[str]]]:
    """The answer in the domain's own words: which index tuples each variable
    took. Violation variables are not part of the roster and are reported
    through `constraint_result` instead."""
    out: dict[str, list[list[str]]] = {name: [] for name in compiled.var_index_sets}
    for (name, index), value in sorted(result.assignments.items()):
        # Violations and the auxiliaries a curve stands for are not decisions
        # anyone made; `__` names are the compiler's own.
        if not name.startswith("__") and value:
            out.setdefault(name, []).append(list(index))
    return out


def amounts(compiled: Compiled, result: Solution) -> dict[str, list[dict[str, Any]]]:
    """How much each whole-number or continuous decision took, where it took any
    (queue R17): what a heat matrix, bars or a line are drawn from. A yes-or-no
    decision says all it has to say in ``assignments``."""
    out: dict[str, list[dict[str, Any]]] = {}
    for (name, index), value in sorted(result.assignments.items()):
        variable = compiled.variables.get((name, index))
        if name.startswith("__") or not value or variable is None or variable.domain == "binary":
            continue
        out.setdefault(name, []).append({"index": list(index), "value": json_number(value)})
    return out


def kept_amounts(
    compiled: Compiled,
    result: Solution,
    *,
    cell_limit: int = AMOUNT_CELLS,
    chunk_size: int = AMOUNT_CHUNK,
) -> tuple[dict[str, list[dict[str, Any]]] | None, dict]:
    """Inline amounts when small enough; otherwise metadata for chunk storage."""
    packed = amounts(compiled, result)
    cells = sum(len(rows) for rows in packed.values())
    if cells > cell_limit:
        return None, {"amounts_chunked": {"cells": cells, "chunk_size": chunk_size}}
    return packed, {}


def amount_chunk_rows(
    packed: dict[str, list[dict[str, Any]]], chunk_size: int = AMOUNT_CHUNK
) -> list[tuple[str, int, list[dict[str, Any]], int]]:
    """Split amounts into (variable, chunk_index, rows, cell_count) for storage."""
    out: list[tuple[str, int, list[dict[str, Any]], int]] = []
    for variable, rows in sorted(packed.items()):
        for start in range(0, len(rows), chunk_size):
            piece = rows[start : start + chunk_size]
            out.append((variable, start // chunk_size, piece, len(piece)))
    return out


def reduced_costs(result: Solution) -> dict[str, list[dict[str, Any]]] | None:
    """Non-zero reduced costs, grouped like the roster. None when this
    backend has nothing to say -- not an empty object, which would mean it
    looked and every decision was free."""
    if result.reduced_costs is None:
        return None
    out: dict[str, list[dict[str, Any]]] = {}
    for (name, index), value in sorted(result.reduced_costs.items()):
        if name.startswith("__") or abs(value) < _REDUCED_COST_FLOOR:
            continue
        out.setdefault(name, []).append(
            {"index": list(index), "value": json_number(value)}
        )
    return out


def json_number(value: float) -> int | float:
    rounded = round(value)
    if abs(value - rounded) < _REDUCED_COST_FLOOR:
        return int(rounded)
    return float(value)
