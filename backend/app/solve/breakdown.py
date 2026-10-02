"""What the goal is made of (benchmark, October 2026, G5a): each goal term's value and its share of
the total, and within each term the records it comes from -- "transport 61 %, opening 30 %,
shortage 9 %; most of the transport is from Giza" -- so an answer can be explained, not only read."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.solve.compile import Compiled, number

#: Records listed per term; the rest are summed as one line.
TOP = 15


def objective_breakdown(ir: dict[str, Any], compiled: Compiled, assignments: dict[Any, Any], top: int = TOP) -> dict[str, Any] | None:
    if not assignments or not compiled.objective_terms:
        return None
    weights = {str(t.get("id")): number(t.get("weight", 1)) for t in ((ir.get("objective") or {}).get("terms") or [])}
    terms = []
    for term_id, linear in zip(compiled.objective_term_ids, compiled.objective_terms, strict=True):
        weight = weights.get(term_id, Decimal(1))
        value = linear.evaluated_at(assignments)
        by_record: dict[tuple[str, str], Decimal] = {}
        for (name, index), coeff in linear.coeffs.items():
            got = assignments.get((name, index))
            if got is None or coeff * number(got) == 0:
                continue
            kind = (compiled.var_index_sets.get(name) or [""])[0] if index else ""
            key = (kind, index[0] if index else "")
            by_record[key] = by_record.get(key, Decimal(0)) + coeff * number(got)
        ranked = sorted(by_record.items(), key=lambda kv: -abs(kv[1]))
        rest = sum((v for _, v in ranked[top:]), Decimal(0))
        terms.append({
            "id": term_id, "weight": float(weight), "value": float(value), "contribution": float(weight * value),
            "records": [{"kind": k, "key": r, "value": float(v)} for (k, r), v in ranked[:top]],
            **({"rest": {"records": len(ranked) - top, "value": float(rest)}} if len(ranked) > top else {}),
        })
    penalties = float(compiled.penalty_objective.evaluated_at(assignments)) if compiled.penalty_objective.coeffs else 0.0
    whole = sum(abs(t["contribution"]) for t in terms) + abs(penalties)
    for t in terms:
        t["share"] = round(abs(t["contribution"]) / whole, 4) if whole else 0.0
    return {"sense": compiled.sense, "mode": compiled.objective_mode, "terms": terms,
            **({"soft_rules": penalties} if penalties else {})}
