"""A run's answer as the Assistant reports it: one compact text, everything joined already.

The field test (October 2026): the answer was right, but the report the model wrote listed demand for
2 of 12 customers ("-" for the rest) and spoke of "255 km slack". It had the run's raw JSON -- keys,
cells, constraint rows -- and had to join it with the records' numbers itself. Here the platform does
the join from the run's own frozen data (never today's): status and goal; what the goal is made of;
each decision's chosen cells with the records' names and their numeric fields; per record of a
decision's first index, how many cells and the sums of the other records' numbers (a warehouse's
customers and their total demand); and each rule held or not, tight or broken, where.
"""

from __future__ import annotations

from typing import Any

from app.api.run_export import _labels, _num, decision_rows

MAX_ROWS = 80
MAX_FIELDS = 4


def _numeric_fields(rows: list[dict[str, Any]]) -> list[str]:
    """A set's number fields, in their order, at most MAX_FIELDS (positions and ids left out)."""
    seen: list[str] = []
    for row in rows[:50]:
        for k, v in row.items():
            if k in ("id", "label", "name", "lon", "lat", "longitude", "latitude") or k in seen:
                continue
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                seen.append(k)
    return seen[:MAX_FIELDS]


def summary(rec: dict[str, Any]) -> str:
    data = rec.get("data") or {}
    sets = {name: {str(r.get("id")): r for r in rows if isinstance(r, dict)}
            for name, rows in (data.get("sets") or {}).items() if isinstance(rows, list)}
    fields = {name: _numeric_fields(list(rows.values())) for name, rows in sets.items()}
    labels = _labels(data)
    ir = rec.get("ir") or {}
    params = rec.get("params") or {}
    out: list[str] = []

    def name(set_name: str, key: str) -> str:
        label = labels.get(set_name, {}).get(key)
        return f"{key} ({label})" if label and label != key else key

    sense = (ir.get("objective") or {}).get("sense", "")
    goal = "none (feasibility)" if rec.get("objective") is None else _num(rec["objective"])
    out.append(f"RUN {rec.get('id')}: {rec.get('status')}; goal ({sense}) = {goal}; solver {rec.get('solver')}.")
    if rec.get("error"):
        out.append(f"ERROR: {rec['error']}")
    made_of = params.get("objective_breakdown") or {}
    if params.get("objective_mode") == "lex" and params.get("objective_terms"):
        out.append("Goals, in order: " + "; ".join(f"{t['id']} = {_num(t['value'])}" for t in params["objective_terms"]))
    elif made_of.get("terms"):
        parts = []
        for t in made_of["terms"]:
            top = ", ".join(f"{r['key']} {_num(r['value'])}" for r in (t.get("records") or [])[:5])
            parts.append(f"{t['id']} = {_num(t.get('contribution', t['value']))}" + (f" (largest: {top})" if top else ""))
        out.append("Goal made of: " + "; ".join(parts))
    for t in made_of.get("terms") or []:
        cells = t.get("cells") or []
        if cells and t.get("cell_count", len(cells)) <= 25:
            # Exactly which cells make a goal's value -- which requests were broken, on which day.
            out.append(f"{t['id']} comes from: " + "; ".join(
                f"{c['var']}[{', '.join(c['index'])}] {_num(c['value'])}" for c in cells))

    if rec.get("assignments") is None and rec.get("amounts") is None:
        out.append("No decisions: the run has no answer.")
    for var, (index, rows) in decision_rows(rec).items():
        spec = (ir.get("variables") or {}).get(var) or {}
        binary = (spec.get("domain") or "binary") == "binary"
        cells = 1
        for s in index:
            cells *= max(1, len(sets.get(s, {})))
        what = "chosen (= 1)" if binary else "non-zero"
        out.append(f"\nDECISION {var}[{', '.join(index)}]: {len(rows)} of {cells} cells {what}.")
        if not rows:
            continue
        header = []
        for s in index:
            header += [s] + [f"{s}.{f}" for f in fields.get(s, [])]
        if not binary:
            header.append("value")
        out.append(" | ".join(header))
        for row in rows[:MAX_ROWS]:
            line: list[str] = []
            for s, key in zip(index, row[:-1]):
                record = sets.get(s, {}).get(str(key), {})
                line += [name(s, str(key))] + [_num(record[f]) if f in record and record[f] is not None else ""
                                               for f in fields.get(s, [])]
            if not binary:
                line.append(_num(row[-1]))
            out.append(" | ".join(line))
        if len(rows) > MAX_ROWS:
            out.append(f"...[{len(rows) - MAX_ROWS} more cells; the run's export has them all]")
        if len(index) >= 2:
            # Per record of the first index: how many cells, and the sums of the others' numbers.
            first, others = index[0], index[1:]
            groups: dict[str, list[list[Any]]] = {}
            for row in rows:
                groups.setdefault(str(row[0]), []).append(row)
            lines = []
            for key, members in groups.items():
                sums = []
                for pos, s in enumerate(others, start=1):
                    for f in fields.get(s, []):
                        total = sum(float((sets.get(s, {}).get(str(m[pos]), {}) or {}).get(f) or 0)
                                    * (1 if binary else float(m[-1])) for m in members)
                        sums.append(f"{s}.{f} {_num(total)}")
                own = sets.get(first, {}).get(key, {})
                mine = ", ".join(f"{f} {_num(own[f])}" for f in fields.get(first, []) if own.get(f) is not None)
                lines.append(f"  {name(first, key)}: {len(members)} cells" + (f"; totals {', '.join(sums)}" if sums else "")
                             + (f" (its {mine})" if mine else ""))
            out.append(f"Per {first}:")
            out.extend(lines[:MAX_ROWS])

    if rec.get("results"):
        out.append("\nRULES:")
        relations = {c.get("id"): c.get("relation") for c in ir.get("constraints") or [] if isinstance(c, dict)}
        for r in rec["results"]:
            slack = r.get("slack")
            state = "held" if r.get("satisfied") else f"BROKEN, short by {_num(r.get('total_violation') or 0)}"
            relation = relations.get(r["constraint_id"])
            if r.get("satisfied") and relation != "=" and slack is not None and abs(float(slack)) < 1e-9:
                state += ", tight (no room left somewhere)"
            cost = float(r.get("penalty_paid") or 0)
            where = "; ".join(" · ".join(map(str, v.get("index") or v.get("instance") or []))
                              for v in (r.get("violations") or [])[:10])
            out.append(f"- {r['constraint_id']} ({'hard' if r.get('hard') else 'soft'}): {state}"
                       + (f"; cost of bending {_num(cost)}" if cost else "") + (f"; where: {where}" if where else ""))
    out.append("\nReport from these numbers only; do not recompute or round them differently.")
    return "\n".join(out)
