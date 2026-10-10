"""What the goal is made of (benchmark, October 2026, G5a): each goal term's value and its share of
the total, and within each term the records it comes from -- "transport 61 %, opening 30 %,
shortage 9 %; most of the transport is from Giza" -- so an answer can be explained, not only read."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.solve.compile import Compiled, number, quadratic_at

#: Records listed per term; the rest are summed as one line.
TOP = 15


CELLS = 25  # the cells that make a goal, largest first, kept with the run


def objective_breakdown(ir: dict[str, Any], compiled: Compiled, assignments: dict[Any, Any], top: int = TOP) -> dict[str, Any] | None:
    if not assignments or not compiled.objective_terms:
        return None
    weights = {str(t.get("id")): number(t.get("weight", 1)) for t in ((ir.get("objective") or {}).get("terms") or [])}
    terms = []
    # One per term; a model whose terms were rewritten after compiling (a lex stage, a why-not probe)
    # may carry fewer -- those terms have no product of decisions to count.
    known = compiled.objective_term_quadratics
    squares = [known[i] if i < len(known) and len(known) == len(compiled.objective_terms) else {}
               for i in range(len(compiled.objective_terms))]
    for term_id, linear, square in zip(compiled.objective_term_ids, compiled.objective_terms, squares, strict=True):
        weight = weights.get(term_id, Decimal(1))
        # Its products of decisions count too (benchmark round 4: irr * amount showed 0, and the terms
        # did not add up to the goal).
        value = linear.evaluated_at(assignments) + (quadratic_at(square, assignments) if square else Decimal(0))
        by_record: dict[tuple[str, str], Decimal] = {}
        # And by cell, whole index: a person asks WHICH requests were broken -- "Basma, Fri" -- and a record
        # alone cannot say (the roster field test reported Eman's broken request on the wrong day).
        by_cell: dict[tuple[str, tuple], Decimal] = {}

        def count(key_var: Any, amount: Decimal) -> None:
            name, index = key_var
            kind = (compiled.var_index_sets.get(name) or [""])[0] if index else ""
            key = (kind, index[0] if index else "")
            by_record[key] = by_record.get(key, Decimal(0)) + amount

        for (name, index), coeff in linear.coeffs.items():
            got = assignments.get((name, index))
            if got is None or coeff * number(got) == 0:
                continue
            count((name, index), coeff * number(got))
            by_cell[(name, tuple(index))] = by_cell.get((name, tuple(index)), Decimal(0)) + coeff * number(got)
        for (a, b), coeff in square.items():
            x, y = assignments.get(a), assignments.get(b)
            if x is None or y is None or coeff * number(x) * number(y) == 0:
                continue
            count(a, coeff * number(x) * number(y))
        cells = sorted(((k, v) for k, v in by_cell.items() if v != 0), key=lambda kv: (-abs(kv[1]), str(kv[0])))
        # And by decision, over every cell: one goal term is often several costs -- changeovers, holding,
        # overtime (the production-planning trace: with 54 cells, more than are kept, the Assistant split the
        # total itself and reported holding as 0 where it was 16,440).
        by_var: dict[str, Decimal] = {}
        for (name, _index), v in by_cell.items():
            by_var[name] = by_var.get(name, Decimal(0)) + v
        for (a, b), coeff in square.items():
            x, y = assignments.get(a), assignments.get(b)
            if x is not None and y is not None and coeff * number(x) * number(y) != 0:
                key = f"{a[0]} x {b[0]}"
                by_var[key] = by_var.get(key, Decimal(0)) + coeff * number(x) * number(y)
        ranked = sorted(by_record.items(), key=lambda kv: -abs(kv[1]))
        rest = sum((v for _, v in ranked[top:]), Decimal(0))
        terms.append({
            "id": term_id, "weight": float(weight), "value": float(value), "contribution": float(weight * value),
            "records": [{"kind": k, "key": r, "value": float(v)} for (k, r), v in ranked[:top]],
            **({"rest": {"records": len(ranked) - top, "value": float(rest)}} if len(ranked) > top else {}),
            "cells": [{"var": n, "index": [str(i) for i in ix], "value": float(v)} for (n, ix), v in cells[:CELLS]],
            "cell_count": len(cells),
            "decisions": [{"var": n, "value": float(v)} for n, v in sorted(by_var.items(), key=lambda kv: -abs(kv[1]))
                          if v != 0],
        })
    penalties = float(compiled.penalty_objective.evaluated_at(assignments)) if compiled.penalty_objective.coeffs else 0.0
    whole = sum(abs(t["contribution"]) for t in terms) + abs(penalties)
    for t in terms:
        # Goals solved in order are not one sum: no share of one in another (benchmark round 4: a count
        # of people and a cost in pounds were put together as 23.9 % and 76.1 %).
        t["share"] = None if compiled.objective_mode == "lex" else round(abs(t["contribution"]) / whole, 4) if whole else 0.0
    return {"sense": compiled.sense, "mode": compiled.objective_mode, "terms": terms,
            **({"soft_rules": penalties} if penalties else {})}
