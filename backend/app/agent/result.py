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

import json
import re
from typing import Any

from app.api.run_export import _labels, _num, decision_rows

MAX_ROWS = 80
MAX_FIELDS = 6


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
    from app.solve import whatif

    patch = rec.get("patch") or {}
    # The run solved its frozen data WITH its scenario's what-if changes; numbers here are read the same way
    # (the furniture retest: finishing raised to 120 by a what-if was read back as 110 -- "uses 109 of 110").
    data = whatif.apply(rec.get("data") or {}, rec.get("ir") or {}, patch)
    limits_set = {str(k): float(v) for k, v in (patch.get("set_limit") or {}).items()}
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
    # Two decimals for a goal that is not whole (the routing test read 154.97 km as "155").
    goal = "none (feasibility)" if rec.get("objective") is None else _amount(rec["objective"])
    out.append(f"RUN {rec.get('id')}: {rec.get('status')}; goal ({sense}) = {goal}; solver {rec.get('solver')}.")
    if rec.get("status") == "feasible" and rec.get("objective") is not None:
        # The camp retest (October 2026): a feasible run 26 % from its bound was reported as "Optimal solution
        # found ... no room to add another bed".
        bound = params.get("best_bound") if params.get("best_bound") is not None else rec.get("best_bound")
        gap = ""
        try:
            if bound is not None:
                b, v = float(bound), float(rec["objective"])
                gap = (f"; the best possible is {'at most' if sense == 'maximize' else 'at least'} {_num(b)}, so it is "
                       f"{abs(b - v) / max(abs(b), 1e-9) * 100:.1f}% short of that bound (a bound, not an answer found: the true "
                        f"best lies between the two)")
        except (TypeError, ValueError):
            pass
        out.append("NOT PROVEN OPTIMAL: the solver stopped at its time limit with a good answer, not the proven best"
                   + gap + ". Never call it optimal, never say nothing better exists; offer a longer run.")
    skipped = (params.get("stochastic") or {}).get("skipped") if isinstance(params.get("stochastic"), dict) else None
    if skipped and "futures were asked for" in skipped:
        out.append("UNCERTAINTY NOT SOLVED: " + skipped + ". This is NOT an average over futures: never report it as "
                   "one. Tell the user, and propose the corrected plan: decisions made once the data is known get "
                   '"stage": 2, those made now "stage": 1; then what_if with futures.')
    elif skipped:
        out.append("UNCERTAINTY NOT SOLVED: " + skipped + ". Tell the user this answer ignores the uncertainty, and offer to plan for it: what_if on this "
                   "scenario with futures (e.g. 50), which solves it over that many sampled futures.")
    run_id = rec.get("id")
    shaped = bool(data.get("sets") and any("geometry" in (rows[0] if rows and isinstance(rows[0], dict) else {})
                                           for rows in (data.get("sets") or {}).values() if isinstance(rows, list)))
    by_metres = any(k in json.dumps(ir)[:20000] for k in ('"x_m"', '"occupies"'))
    # Records placed by metres reach a map only through a drawing placed in the workspace's map data (the camp
    # retest, October 2026: a new workspace without it got a GeoJSON link that came back empty).
    mapped = shaped or (by_metres and rec.get("map_placed", True))
    out.append(f"EXPORTS (give the user the ones they asked for, as links): spreadsheet /api/v1/runs/{run_id}/export?format=xlsx, "
               f"CSV ?format=csv, PDF report ?format=pdf"
               + (f", MAP: GeoJSON /api/v1/runs/{run_id}/export?format=geojson" if mapped else "")
               + (f", CAD drawing /api/v1/runs/{run_id}/export?format=dxf (the chosen items on the drawing)"
                  if shaped or by_metres else "") + ".")
    if by_metres and not mapped:
        out.append("NO MAP: this workspace holds no placed drawing, so the answer cannot be shown on a map (no GeoJSON); "
                   "the DXF has it in the drawing's metres. To get a map, the user attaches the drawing again.")
    structure = params.get("structure") or {}
    actual_split = params.get("blocks") or {}
    if actual_split.get("blocks"):
        out.append(f"DECOMPOSITION: solved as {actual_split['blocks']} independent blocks, grouped into "
                   f"{actual_split.get('groups', actual_split['blocks'])} parallel solves; block statuses "
                   f"{', '.join(actual_split.get('statuses') or [])}. The block objectives and bounds were merged.")
    elif actual_split.get("solved_whole"):
        out.append(f"DECOMPOSITION: solved as one model ({actual_split['solved_whole']}).")
    elif structure.get("linking_rules", 0):
        out.append(f"DECOMPOSITION: structure analysis found {structure.get('blocks', 1)} near-independent groups, "
                   f"tied by {structure.get('linking_rules')} instances of "
                   f"{', '.join(structure.get('linking') or [])}; this was not an exact split.")
    elif structure.get("blocks", 1) > 1:
        out.append(f"DECOMPOSITION: {structure['blocks']} independent blocks were detected, but this run did not "
                   "record a block-by-block solve.")
    else:
        out.append("DECOMPOSITION: the compiled decisions form one coupled block.")
    if rec.get("error"):
        out.append(f"ERROR: {rec['error']}")
    made_of = params.get("objective_breakdown") or {}
    planned = params.get("stochastic") if isinstance(params.get("stochastic"), dict) else {}
    later = set(planned.get("stage_two") or []) if planned.get("samples") else set()
    if later:
        # Planned for sampled futures (the bakery test, October 2026): the goal is an average over the futures,
        # and the decisions made later differ per future -- the plain parts below would read "sold 0".
        oos = planned.get("out_of_sample") or {}
        out.append(f"UNCERTAINTY PLANNED FOR: {planned['samples']} sampled futures. The answer is the plan for the "
                   f"decisions made now; the goal {goal} is its AVERAGE over those futures."
                   + (f" Costed again on {oos['futures']} fresh futures it averages {_amount(oos['mean'])} "
                      f"(95% within +/- {_amount(oos.get('ci95') or 0)}); quote that as the expected value."
                      if oos.get("mean") is not None else "")
                   + (f" In {oos['unmet']} fresh futures the plan could not be carried out." if oos.get("unmet") else "")
                   + f" Decided later, per future, so not one number: {', '.join(sorted(later))}.")
        made_of = {}
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
        by_var: dict[str, float] = {}
        for c in cells:
            by_var[c["var"]] = by_var.get(c["var"], 0.0) + float(c.get("value") or 0)
        if len(by_var) > 1 and t.get("cell_count", len(cells)) <= len(cells):
            # One goal made of several costs (the production-plan test: one term for making, holding and lateness;
            # the reply split it as 4,650 + 2,100 where the parts were 3,000 and 3,750).
            out.append(f"{t['id']} by decision (exact; quote these parts, never split the total yourself): "
                       + "; ".join(f"{v} {_amount(x)}" for v, x in sorted(by_var.items(), key=lambda kv: -abs(kv[1]))))

    out.extend(_front(rec, params, sets, fields))
    out.extend(_routes(rec, ir, sets, made_of))
    out.extend(_resources(rec, ir, data))
    if rec.get("assignments") is None and rec.get("amounts") is None:
        out.append("No decisions: the run has no answer.")
    # Only the products the model itself makes: field x decision where a rule or goal multiplies them (the
    # production-plan test got "demand_units x inventory = 230,300" and took a cost from such a line).
    multiplied = _multiplied(ir)
    for var, (index, rows) in decision_rows(rec).items():
        if var in later:
            continue
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
                line.append(_amount(row[-1]))
            out.append(" | ".join(line))
        if len(rows) > MAX_ROWS:
            out.append(f"...[{len(rows) - MAX_ROWS} more cells; the run's export has them all]")
        if binary and len(index) == 1 and fields.get(index[0]):
            # The chosen records' fields added up, over all of them (the fibre test: the model added 12 places'
            # households itself and wrote 1,770 for 1,870).
            s0 = index[0]
            totals = {f: sum(float((sets.get(s0, {}).get(str(row[0]), {}) or {}).get(f) or 0) for row in rows)
                      for f in fields[s0]}
            out.append(f"Totals over the {len(rows)} chosen: " + ", ".join(f"{f} {_amount(v)}" for f, v in totals.items()))
        paired = [f for f in fields.get(index[0], []) if f in multiplied.get(var, set())] if len(index) == 1 else []
        if not binary and len(index) == 1 and paired:
            # Each record's field times its amount, and their totals (the furniture retest: "9 tables use 27
            # finishing hours" for 36, and a total of "110 + 9 = 119").
            s0 = index[0]
            per_row, totals = [], {f: 0.0 for f in paired}
            for row in rows[:MAX_ROWS]:
                record = sets.get(s0, {}).get(str(row[0]), {})
                parts = []
                for f in paired:
                    if record.get(f) is not None:
                        value = float(record[f]) * float(row[-1])
                        totals[f] += value
                        parts.append(f"{f} {_amount(value)}")
                per_row.append(f"  {name(s0, str(row[0]))}: " + ", ".join(parts))
            out.append(f"Each {s0}'s field x {var}:")
            out.extend(per_row)
            out.append(f"Totals of field x {var}: " + ", ".join(f"{f} {_amount(v)}" for f, v in totals.items()))
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

    ranges = rec.get("ranges") or {}
    rows_by_rule: dict[str, list[dict[str, Any]]] = {}
    tight_where: dict[str, list[str]] = {}
    for row in ranges.get("rows") or []:
        rows_by_rule.setdefault(str(row.get("rule")), []).append(row)
        if row.get("index") and abs(float(row.get("dual") or 0)) > 1e-9:
            tight_where.setdefault(str(row.get("rule")), []).append(", ".join(map(str, (row["index"] or {}).values())))
    rules_ir = {c.get("id"): c for c in ir.get("constraints") or [] if isinstance(c, dict)}
    if rec.get("results"):
        out.append("\nRULES:")
        relations = {c.get("id"): c.get("relation") for c in ir.get("constraints") or [] if isinstance(c, dict)}
        for r in rec["results"]:
            slack = r.get("slack")
            state = "held" if r.get("satisfied") else f"BROKEN, short by {_num(r.get('total_violation') or 0)}"
            relation = relations.get(r["constraint_id"])
            body = (rules_ir.get(r["constraint_id"]) or {}).get("connected")
            if isinstance(body, dict):
                # A network rule has no room to speak of (the fibre test read "held, tight (no room left)").
                joined = "every chosen one joined to a source" if body.get("sources") is not None else \
                    "each group in one connected piece"
                out.append(f"- {r['constraint_id']} (hard): " + (f"held: {joined} along {body.get('via')}"
                                                                if r.get("satisfied") else state))
                continue
            per_record = (_room_per_record(rules_ir.get(r["constraint_id"]) or {}, rec, sets, data)
                          if r.get("satisfied") and relation in ("<=", ">=") else None)
            if r.get("satisfied") and relation != "=" and slack is not None and per_record is None \
                    and _tight(slack, rows_by_rule.get(r["constraint_id"])):
                indexed = bool(((rules_ir.get(r["constraint_id"]) or {}).get("forall")))
                state += ", tight (no room left" + (f": {', '.join(tight_where[r['constraint_id']])}"
                                                   if tight_where.get(r["constraint_id"])
                                                   else " somewhere" if indexed else "") + ")"
            if r.get("satisfied") and relation in ("<=", ">=") and slack is not None:
                # How much is used and how much is left, from the run (the furniture retest: the model wrote
                # "154/154 hours, tight" for 151 used, and other usage figures it made up).
                rule = rules_ir.get(r["constraint_id"]) or {}
                room = abs(float(slack))
                limit = (limits_set.get(r["constraint_id"]) if r["constraint_id"] in limits_set
                         else _value(rule.get("right"), data)) if not rule.get("forall") else None
                if limit is not None:
                    used = limit - room if relation == "<=" else limit + room
                    state += f"; uses {_amount(used)} of {_amount(limit)}, room left {_amount(room)}"
                elif rule.get("forall"):
                    per = per_record
                    if per:
                        full = [k for k, x in per if abs(x) <= 1e-6]
                        rest = [f"{k} {_amount(x)}" for k, x in per if abs(x) > 1e-6]
                        # The production-plan test: "capacity fully used in every month" when June had 50 spare.
                        least = min(x for _, x in per)
                        state += ((f", tight (no room left on {len(full)} of {len(per)}: {', '.join(full[:20])})"
                                   if full else "") + f"; least room left on any one record {_amount(least)}"
                                  + (f"; room left on the others: {', '.join(rest[:20])}" if rest else ""))
                    else:
                        state += f"; least room left on any one record {_amount(room)}"
            cost = float(r.get("penalty_paid") or 0)
            where = "; ".join(" · ".join(map(str, v.get("index") or v.get("instance") or []))
                              for v in (r.get("violations") or [])[:10])
            out.append(f"- {r['constraint_id']} ({'hard' if r.get('hard') else 'soft'}): {state}"
                       + (f"; cost of bending {_num(cost)}" if cost else "") + (f"; where: {where}" if where else ""))
    out.extend(_sensitivity(rec, ir, data, sense))
    out.append("\nReport from these numbers only; do not recompute or round them differently.")
    return "\n".join(out)


def _amount(value: Any) -> str:
    """A decision's amount: two decimals (241.56 kg), whole numbers without them."""
    v = float(value)
    return f"{v:,.0f}" if abs(v - round(v)) < 1e-4 else f"{v:,.2f}"  # a solver's 6,999.999999 is 7,000


def _tight(slack: Any, rows: list[dict[str, Any]] | None) -> bool:
    """No room left, within the solver's tolerance (the blend test: fat's slack of 2e-6 read as room)."""
    if rows and any(abs(float(r.get("dual") or 0)) > 1e-9 for r in rows):
        return True
    return abs(float(slack)) <= 1e-5


def _scalar(data: dict[str, Any], name: str) -> float | None:
    rows = (data.get("parameters") or {}).get(name)
    if isinstance(rows, list) and len(rows) == 1 and isinstance(rows[0], dict) and "value" in rows[0]:
        try:
            return float(rows[0]["value"])
        except (TypeError, ValueError):
            return None
    default = (data.get("parameter_defaults") or {}).get(name)
    try:
        return float(default) if default is not None and not rows else None
    except (TypeError, ValueError):
        return None


def _product_factors(term: Any) -> list[Any] | None:
    """A limit written as a product of single numbers (max_fiber × batch_size): its factors, else None."""
    if not isinstance(term, dict):
        return None
    if "mul" in term:
        out: list[Any] = []
        for f in term["mul"] or []:
            sub = _product_factors(f)
            if sub is None:
                return None
            out += sub
        return out
    if "par" in term and not term.get("index"):
        return [term]
    if "const" in term:
        return [term]
    return None


def _sensitivity(rec: dict[str, Any], ir: dict[str, Any], data: dict[str, Any], sense: str) -> list[str]:
    """What the limits cost, from the solver's ranging (an LP proven optimal): per tight rule, how much the goal
    moves per unit of its limit and of each single number the limit is made of, and how far that holds; per
    unused decision, how much cheaper it must become. The blend test: the model read a fiber shadow price of
    -1.018 per kg-% as 10.2 EGP per %, then as 1,018 EGP for 7 % -> 8 % -- far past the 7.142 % it holds to."""
    ranges = rec.get("ranges") or {}
    rows = ranges.get("rows") or []
    if not rows:
        return []
    from app.agent.readback import term as as_text

    rules = {c.get("id"): c for c in ir.get("constraints") or [] if isinstance(c, dict)}
    used_in: dict[str, int] = {}
    for c in rules.values():
        for name in set(re.findall(r'"par":\s*"([^"]+)"', json.dumps(c))):
            used_in[name] = used_in.get(name, 0) + 1
    out = ["\nSENSITIVITY (from the solver; exact only inside each range -- for a bigger change call what_if):"]
    for row in rows:
        dual = float(row.get("dual") or 0)
        if abs(dual) < 1e-9:
            continue
        rule = rules.get(row.get("rule")) or {}
        rhs, low, high = row.get("rhs"), row.get("low"), row.get("high")
        where = ", ".join(map(str, (row.get("index") or {}).values()))
        name = f"{row.get('rule')}" + (f" [{where}]" if where else "")
        right = rule.get("right")
        written = f" = {as_text(right)}" if isinstance(right, dict) and "const" not in right else ""
        span = (f"from {_num(low) if low is not None else '-∞'} to {_num(high) if high is not None else '∞'}")
        direction = "goal rises" if dual > 0 else "goal falls"
        out.append(f"- {name} ({rule.get('relation', '')} limit {_num(rhs)}{written}): each +1 on the limit "
                   f"changes the goal by {dual:+,.6g} ({direction}); holds while the limit stays {span}.")
        factors = _product_factors(right) if row.get("index") in (None, {}) else None
        if factors and rhs not in (None, 0):
            values = []
            for f in factors:
                v = float(f["const"]) if "const" in f else _scalar(data, f["par"])
                values.append(v)
            if all(v not in (None, 0) for v in values):
                for f, v in zip(factors, values):
                    if "par" not in f:
                        continue
                    if used_in.get(f["par"], 0) > 1:
                        # batch_size is in four rules: changing it moves them all; one rule's price says nothing.
                        out.append(f"    {f['par']} is in {used_in[f['par']]} rules: a change to it moves them all "
                                   "together -- use what_if.")
                        continue
                    per = float(rhs) / v  # the limit moves by this much per +1 on the parameter
                    lo = None if low is None else float(low) / per
                    hi = None if high is None else float(high) / per
                    room = []
                    if hi is not None and hi - v < 1:
                        room.append(f"only {_num(hi - v)} of room above {_num(v)}, so +1 is OUTSIDE it")
                    if lo is not None and v - lo < 1:
                        room.append(f"only {_num(v - lo)} of room below {_num(v)}, so -1 is OUTSIDE it")
                    out.append(f"    per +1 on {f['par']} (now {_num(v)}): limit +{_num(per)}, goal {dual * per:+,.6g}; "
                               f"holds for {f['par']} from {_num(lo) if lo is not None else '-∞'} to "
                               f"{_num(hi) if hi is not None else '∞'}"
                               + (f" ({'; '.join(room)}: never quote this rate for such a change, call what_if)"
                                  if room else "") + ". Outside that: what_if.")
    used = {(var, tuple(map(str, row[:-1]))) for var, (_, rows_) in decision_rows(rec).items() for row in rows_}
    unused, capped = [], []
    for var, cells in (rec.get("reduced_costs") or {}).items():
        for cell in cells or []:
            value = float(cell.get("value") or 0)
            if abs(value) > 1e-9:
                index = tuple(map(str, cell.get("index") or []))
                text = f"{var}[{', '.join(index)}] {abs(value):,.6g}"
                (capped if (var, index) in used else unused).append(text)
    better = "fall" if sense == "minimize" else "rise"
    if unused:
        out.append(f"Not used (at 0): its cost per unit must {better} by this much before the answer would use it: "
                   + "; ".join(unused[:20]))
    if capped:
        out.append("Used up to its bound: each extra unit allowed would improve the goal by: " + "; ".join(capped[:20]))
    costs = [c for c in ranges.get("costs") or [] if c.get("low") is not None or c.get("high") is not None]
    if costs:
        out.append("The plan stays the same while each cost stays in: " + "; ".join(
            f"{c.get('var')}[{', '.join(map(str, c.get('index') or []))}] {_num(c['low']) if c.get('low') is not None else '-∞'}"
            f"..{_num(c['high']) if c.get('high') is not None else '∞'} (now {_num(c.get('cost'))})" for c in costs[:20]))
    return out


def _value(term: Any, data: dict[str, Any]) -> float | None:
    """A rule's limit when it is made of single numbers (a constant, a one-number parameter, their sums and
    products); None when it depends on records or decisions."""
    if not isinstance(term, dict):
        return None
    if "const" in term:
        try:
            return float(term["const"])
        except (TypeError, ValueError):
            return None
    if "par" in term and not term.get("index"):
        return _scalar(data, term["par"])
    if "mul" in term or "add" in term:
        parts = [_value(t, data) for t in term.get("mul") or term.get("add") or []]
        if not parts or any(p is None for p in parts):
            return None
        total = 1.0 if "mul" in term else 0.0
        for p in parts:
            total = total * p if "mul" in term else total + p
        return total
    return None


def _front(rec: dict[str, Any], params: dict[str, Any], sets: dict[str, dict[str, dict]] | None = None,
           fields: dict[str, list[str]] | None = None) -> list[str]:
    """The trade-off front's points, each with what it chooses (a council field test, October 2026: "show us the
    trade-off" had no way to be answered but by guessing compromises)."""
    front = rec.get("front") or []
    if not front:
        return []
    terms = (params.get("pareto") or {}).get("terms") or ["first goal", "second goal"]
    out = [f"\nTRADE-OFF FRONT ({len(front)} points; {terms[0]} against {terms[1]}; each point is a full answer in its "
           "own run, and none can improve one goal without the other getting worse -- report them as given):"]
    variables = (rec.get("ir") or {}).get("variables") or {}
    for p in front:
        # The chosen records' fields added up, per point (the council test: the reply gave "999" as the cost of
        # four points whose projects cost 964, 981, 937 and 791).
        totals = []
        for var, keys in (p.get("chosen") or {}).items():
            index = (variables.get(var) or {}).get("index") or []
            if len(index) == 1 and (variables.get(var) or {}).get("domain", "binary") == "binary":
                rows = (sets or {}).get(index[0], {})
                for f in (fields or {}).get(index[0], []):
                    totals.append(f"{f} {_amount(sum(float((rows.get(k) or {}).get(f) or 0) for k in keys))}")
        chosen = "; ".join(f"{var}: {', '.join(keys[:30])}" + (f" (+{len(keys) - 30} more)" if len(keys) > 30 else "")
                           for var, keys in (p.get("chosen") or {}).items())
        out.append(f"- point {p['seq']}: {terms[0]} {_amount(p['first'])}, {terms[1]} {_amount(p['second'])}"
                   + ("" if p.get("status") == "optimal" else f" ({p.get('status')})")
                   + (f"; run {p['run_id']}" if p.get("run_id") else "") + (f"; chooses {chosen}" if chosen else "")
                   + (f"; totals of the chosen: {', '.join(totals)}" if totals else ""))
    return out


def _room_per_record(rule: dict[str, Any], rec: dict[str, Any], sets: dict[str, dict[str, dict]],
                     data: dict[str, Any]) -> list[tuple[str, float]] | None:
    """Room left per record for a rule of the shape `for every r: x[r] <= r.field` (or a parameter of r, or >=,
    either way round), read from the answer; None for any other shape."""
    forall = rule.get("forall") or []
    if len(forall) != 1 or not isinstance(forall[0], dict) or forall[0].get("where") or forall[0].get("via"):
        return None
    i, set_name = forall[0].get("index"), forall[0].get("set")
    left, right, relation = rule.get("left"), rule.get("right"), rule.get("relation")
    if relation not in ("<=", ">="):
        return None

    def is_var(t: Any) -> bool:
        return isinstance(t, dict) and set(t) == {"var", "index"} and t.get("index") == [i]

    if is_var(right) and not is_var(left):
        left, right, relation = right, left, {"<=": ">=", ">=": "<="}[relation]
    if not is_var(left):
        return None
    amounts = {tuple(map(str, k)): v for k, v in
               ((tuple(r[:-1]), r[-1]) for r in (decision_rows(rec).get(left["var"]) or ([], []))[1])}
    params = (data.get("parameters") or {})
    out = []
    for key, record in sets.get(set_name, {}).items():
        if isinstance(right, dict) and isinstance(right.get("attr"), dict) and right["attr"].get("of") == i:
            limit = record.get(right["attr"].get("name"))
        elif isinstance(right, dict) and right.get("par") and right.get("index") == [i]:
            cells = params.get(right["par"]) if isinstance(params.get(right["par"]), list) else []
            limit = next((c.get("value") for c in cells if isinstance(c, dict)
                          and [str(x) for x in (c.get("index") or c.get("key") or [])] == [key]), None)
            if limit is None:
                limit = (data.get("parameter_defaults") or {}).get(right["par"])
        else:
            return None
        try:
            limit = float(limit)
        except (TypeError, ValueError):
            return None
        value = float(amounts.get((key,), 0.0))
        out.append((key, limit - value if relation == "<=" else value - limit))
    return out or None


def _multiplied(ir: dict[str, Any]) -> dict[str, set[str]]:
    """For each decision, the record fields some product in the model multiplies it by."""
    out: dict[str, set[str]] = {}

    def names(node: Any, attrs: set[str], vars_: set[str]) -> None:
        if isinstance(node, dict):
            if isinstance(node.get("attr"), dict) and node["attr"].get("name"):
                attrs.add(str(node["attr"]["name"]))
            if isinstance(node.get("var"), str):
                vars_.add(node["var"])
            for value in node.values():
                names(value, attrs, vars_)
        elif isinstance(node, list):
            for value in node:
                names(value, attrs, vars_)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if isinstance(node.get("mul"), list):
                attrs: set[str] = set()
                vars_: set[str] = set()
                names(node["mul"], attrs, vars_)
                for v in vars_:
                    out.setdefault(v, set()).update(attrs)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk([ir.get("constraints"), ir.get("objective")])
    return out


def _resources(rec: dict[str, Any], ir: dict[str, Any], data: dict[str, Any]) -> list[str]:
    """Each one-at-a-time resource's busy time and idle gaps, for every `no_overlap` rule whose intervals have
    named start and end decisions (the job-shop retest, October 2026: the answer of 231 was right, and the reply
    then said the drill "had no idle time" -- it stood idle 33, 42 and 4 minutes)."""
    out: list[str] = []
    variables = ir.get("variables") or {}
    rows = decision_rows(rec) if rec.get("assignments") is not None or rec.get("amounts") is not None else {}

    def values(var: str) -> dict[tuple, float]:
        return {tuple(map(str, r[:-1])): float(r[-1]) for r in (rows.get(var) or ([], []))[1]}

    for c in ir.get("constraints") or []:
        body = c.get("no_overlap") if isinstance(c, dict) else None
        if not isinstance(body, dict):
            continue
        ivar = (body.get("interval") or {}).get("var")
        spec = variables.get(ivar) or {}
        over = body.get("over") or []
        if not (isinstance(spec.get("start"), str) and isinstance(spec.get("end"), str)) or len(over) != 1:
            continue
        binding = over[0]
        if not isinstance(binding, dict) or set(binding) - {"index", "set", "via"}:
            continue
        starts, ends = values(spec["start"]), values(spec["end"])
        members = [str(r.get("id")) for r in (data.get("sets") or {}).get(binding.get("set"), []) if isinstance(r, dict)]
        groups: dict[str, list[str]] = {}
        via = binding.get("via")
        if isinstance(via, dict) and via.get("rel"):
            links = (data.get("relationships") or {}).get(via["rel"]) or []
            if "to" in via:
                for e in links:
                    groups.setdefault(str(e.get("to")), []).append(str(e.get("from")))
            else:
                for e in links:
                    groups.setdefault(str(e.get("from")), []).append(str(e.get("to")))
        elif not via:
            groups[c.get("id") or "all"] = members
        else:
            continue
        if not groups:
            continue
        end_all = max([*ends.values(), 0.0])
        out.append(f"\nRESOURCES ({c.get('id')}; exact, from the answer -- quote these, never judge idle time yourself; "
                   f"the answer ends at {_amount(end_all)}):")
        for group, ops in sorted(groups.items()):
            spans = sorted((starts.get((o,), 0.0), ends.get((o,), 0.0), o) for o in ops if o in members or not members)
            if not spans:
                continue
            busy = sum(b - a for a, b, _ in spans)
            gaps = [(spans[i][1], spans[i + 1][0]) for i in range(len(spans) - 1) if spans[i + 1][0] > spans[i][1] + 1e-9]
            lead = spans[0][0]
            idle = ([f"before {_amount(lead)}"] if lead > 1e-9 else []) + [
                f"{_amount(a)}-{_amount(b)} ({_amount(b - a)})" for a, b in gaps]
            if spans[-1][1] < end_all - 1e-9:
                idle.append(f"after {_amount(spans[-1][1])}")
            out.append(f"- {group}: {len(spans)} tasks, busy {_amount(busy)} from {_amount(lead)} to "
                       f"{_amount(spans[-1][1])}; idle " + (", ".join(idle) if idle else "never"))
    return out


def _routes(rec: dict[str, Any], ir: dict[str, Any], sets: dict[str, dict[str, dict]], made_of: dict) -> list[str]:
    """Each vehicle's route as a sequence, its load and its part of the goal, for every `route` rule (the
    evaluation's routing test: the model worked out each truck's km and load itself and wrote 103.60 for 103.65)."""
    out: list[str] = []
    for c in ir.get("constraints") or []:
        body = c.get("route") if isinstance(c, dict) else None
        if not isinstance(body, dict):
            continue
        var = (body.get("visit") or {}).get("var")
        arcs = [a for a in ((rec.get("assignments") or {}).get(var) or []) if isinstance(a, list) and len(a) >= 3]
        if not arcs:
            continue
        share: dict[tuple, float] = {}
        complete = True
        for t in made_of.get("terms") or []:
            cells = t.get("cells") or []
            complete &= t.get("cell_count", len(cells)) <= len(cells)
            for cell in cells:
                if cell.get("var") == var:
                    key = tuple(map(str, cell.get("index") or []))
                    share[key] = share.get(key, 0.0) + float(cell.get("value") or 0)
        depot, vehicles_set = str(body.get("depot")), (body.get("vehicles") or {}).get("set")
        stops_set = (body.get("stops") or {}).get("set")
        demand, capacity = body.get("demand"), body.get("capacity")
        out.append(f"\nROUTES ({c.get('id')}; exact, from the answer -- report these, never add up yourself):")
        vehicles = list(sets.get(vehicles_set, {})) or sorted({str(a[0]) for a in arcs})
        for v in vehicles:
            mine = {str(a[1]): str(a[2]) for a in arcs if str(a[0]) == v}
            if not mine:
                out.append(f"- {v}: not used")
                continue
            order, here, seen = [depot], depot, set()
            while here in mine and mine[here] not in seen and len(order) <= len(mine) + 1:
                here = mine[here]
                order.append(here)
                seen.add(here)
                if here == depot:
                    break
            line = f"- {v}: " + " -> ".join(order) + f" ({len(order) - 2} stops)"
            if demand:
                load = sum(float((sets.get(stops_set, {}).get(s) or {}).get(demand) or 0) for s in order[1:-1])
                cap = (sets.get(vehicles_set, {}).get(v) or {}).get(capacity) if capacity else None
                line += f"; load {_amount(load)}" + (f" of {_amount(cap)} (room left {_amount(float(cap) - load)})"
                                                     if cap is not None else "")
            if complete and share:
                part = sum(share.get((v, a, b), 0.0) for a, b in zip(order, order[1:]))
                line += f"; goal part {_amount(part)}"
            out.append(line)
    return out

