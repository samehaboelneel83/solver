"""Symmetry breaking: order interchangeable entities, for the backends that do not.

Two members of a set are **interchangeable** when nothing in the model can
tell them apart: the same attributes (all but the id), the same value in
every parameter cell they index, the same neighbours along every declared
relationship, and no edge between them. The IR names an entity only through
those -- a binding ranges over a set, a filter reads attributes, a
parameter reads its cells, a walk follows edges -- so swapping two such
entities maps every answer to another with the same value. A solver that
does not see this explores each answer once per ordering of the entities.

The rewrite keeps one ordering of each class: for one variable indexed by
the set once, each member's total is at least the next one's,
`sum x[e1, ...] >= sum x[e2, ...] >= ...`. Any answer, its interchangeable
entities sorted by that total, is an answer of the same value that holds --
so the optimum survives and only its mirror images are cut. Applied only
for HiGHS and the MILP wrapper (target roadmap Phase 13): CP-SAT and SCIP
detect symmetry themselves, and rows added to them can only get in the
way. Behind the setting `solve.symmetry` (migration 0044), whose default
is the bench's (bench/results/2026-09-23-symmetry.md).
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Any

from app.solve.compile import Compiled, Constraint, Linear, parameter_index

#: The backends the rows are for.
FOR = frozenset({"highs", "milp"})

_ID = "__symmetry"


def classes(ir: dict[str, Any], data: dict[str, Any]) -> list[tuple[str, tuple[str, ...]]]:
    """Every class of two or more interchangeable members, per set, members
    in the frozen order."""
    parameters = ir.get("parameters") or {}
    found: list[tuple[str, tuple[str, ...]]] = []
    for set_name in ir.get("sets") or []:
        # A parameter indexed by the set twice (a distance matrix) would
        # need a symmetric table too; not attempted.
        if any(spec.get("index", []).count(set_name) > 1 for spec in parameters.values()):
            continue
        rows = data.get("sets", {}).get(set_name, [])
        cells, edges = _by_member(set_name, ir, data)
        signature = {
            row["id"]: (
                tuple(sorted((k, repr(v)) for k, v in row.items() if k != "id")),
                tuple(sorted(cells.get(row["id"], []))),
                tuple(sorted(edges.get(row["id"], []))),
            )
            for row in rows
        }
        groups: dict[Any, list[str]] = {}
        for row in rows:
            groups.setdefault(signature[row["id"]], []).append(row["id"])
        for members in groups.values():
            if len(members) > 1 and not _linked(members, ir, data):
                found.append((set_name, tuple(members)))
    return found


def _by_member(set_name: str, ir: dict[str, Any], data: dict[str, Any]):
    """Each member's parameter cells and incident edges -- what its signature
    compares -- gathered in one pass over the data.

    Once per member used to scan every cell of every parameter: members x
    cells, quadratic, and on every compile (the PDLP bench found it: 14.9 s of
    a 15.6 s compile at 22,500 decisions)."""
    cells: dict[Any, list] = {}
    for name, spec in (ir.get("parameters") or {}).items():
        order = spec.get("index", [])
        if set_name not in order:
            continue
        at = order.index(set_name)
        for cell in data.get("parameters", {}).get(name, []):
            index = parameter_index(cell, order)
            cells.setdefault(index[at], []).append((name, index[:at] + index[at + 1 :], repr(cell["value"])))
    edges: dict[Any, list] = {}
    for rel in ir.get("relationships") or []:
        for edge in data.get("relationships", {}).get(rel, []):
            edges.setdefault(edge["from"], []).append((rel, "to", edge["to"]))
            edges.setdefault(edge["to"], []).append((rel, "from", edge["from"]))
    return cells, edges


def _linked(members: list[str], ir: dict[str, Any], data: dict[str, Any]) -> bool:
    """Whether any edge joins two members: then they are not interchangeable
    (e1 -> e2 is not e2 -> e1)."""
    inside = set(members)
    return any(
        edge["from"] in inside and edge["to"] in inside
        for rel in ir.get("relationships") or []
        for edge in data.get("relationships", {}).get(rel, [])
    )


def order_rows(compiled: Compiled) -> tuple[Compiled, list[dict[str, Any]]]:
    """The model with each class ordered on one variable; and, per class,
    what was done (for the run's record)."""
    rows = list(compiled.constraints)
    record = []
    for set_name, members in compiled.symmetry:
        chosen = next(
            (name for name, sets in compiled.var_index_sets.items() if list(sets).count(set_name) == 1),
            None,
        )
        if chosen is None:
            continue
        position = list(compiled.var_index_sets[chosen]).index(set_name)
        totals: dict[str, dict] = {member: {} for member in members}
        for key in compiled.variables:
            if key[0] == chosen and key[1][position] in totals:
                totals[key[1][position]][key] = Decimal(1)
        for a, b in zip(members, members[1:]):
            rows.append(Constraint(_ID, {}, Linear(coeffs=totals[a]), ">=", Linear(coeffs=totals[b])))
        record.append({"set": set_name, "members": len(members), "variable": chosen, "rows": len(members) - 1})
    return replace(compiled, constraints=rows), record
