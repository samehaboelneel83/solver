"""Rules learnt from past plans (10 October 2026).

The plans people approved often keep rules nobody wrote into the model: nobody works more than five shifts a
week, a depot never sends more than 40 a day, every route visits at least three stops. When the model lacks
them, its answers break them and get rejected. This finds them -- constraint acquisition from examples, in the
spirit of ModelSeeker and COUNT-CP -- the same way for every model, from its decisions' own shapes:

1. **Candidates.** For each decision over sets (`assign[employee, day, shift]`) and each way of grouping it (by
   employee; by employee and day; by day and shift; ... ; all of it at once; for a whole-number or continuous
   decision, each cell alone), the sum of the decision in each group.
2. **What the plans did.** Across every group of every plan, the most and the least that sum took. A rule
   `for every group: sum <= most` (and `>= least`) holds in every plan by construction.
3. **Only what the model does not already say.** A rule the decisions' own bounds already keep is dropped;
   then, for the groups the plans pushed hardest (up to `CHECKED_GROUPS`), the model's relaxation is solved for
   the largest (or least) sum it allows. When the model cannot go past the plans' value there, the rule is
   already implied and dropped; otherwise it is proposed with both numbers -- "the plans never went above 5;
   the model allows 7".

Each proposal is a rule in the model's own contract (`forall`, `sum ... over`), ready to add, with how many
plans it rests on. A rule learnt from fewer than `MIN_PLANS` plans is not proposed: one plan says nothing
about what is usual. Nothing is added by itself -- a planner reads each and decides.
"""
from __future__ import annotations

import itertools
import math
from decimal import Decimal
from typing import Any

from app.solve.compile import Compiled, Linear, VarKey

MIN_PLANS = 2
#: Groups per candidate whose relaxation is solved to see whether the model already keeps the rule.
CHECKED_GROUPS = 3
#: Seconds for each of those solves.
CHECK_SECONDS = 2.0
#: Index positions a decision may have for every grouping of it to be tried (2^k groupings).
MAX_POSITIONS = 5
#: The most rules proposed.
MOST = 40


def plans_from_answers(ir: dict[str, Any], answers: list[tuple[dict, dict | None]]) -> list[dict[VarKey, float]]:
    """Plans from stored answers: each (`assignments` -- the cells a decision took, as lists of index values --,
    `amounts` -- {decision: [{index, value}]} for whole-number and continuous decisions)."""
    variables = ir.get("variables") or {}
    out = []
    for assignments, amounts in answers:
        plan: dict[VarKey, float] = {}
        for name, cells in (assignments or {}).items():
            if name not in variables:
                continue
            for cell in cells or []:
                plan[(name, tuple(str(c) for c in cell))] = 1.0
        for name, rows in (amounts or {}).items():
            if name not in variables:
                continue
            for row in rows or []:
                plan[(name, tuple(str(c) for c in row.get("index") or []))] = float(row.get("value") or 0)
        out.append(plan)
    return out


def _letters(sets: list[str]) -> list[str]:
    out: list[str] = []
    for name in sets:
        base = "".join(ch for ch in name.lower() if ch.isalpha())[:1] or "i"
        letter, n = base, 2
        while letter in out:
            letter, n = f"{base}{n}", n + 1
        out.append(letter)
    return out


def learn(ir: dict[str, Any], compiled: Compiled, plans: list[dict[VarKey, float]], *,
          check=None) -> dict[str, Any]:
    """Proposed rules, most telling first. `check(objective: Linear, sense) -> float | None` is the model's
    relaxation's best for a sum (None when it cannot say); left out, `Relaxation` is used."""
    if len(plans) < MIN_PLANS:
        return {"plans": len(plans), "rules": [],
                "says": f"Rules are learnt from at least {MIN_PLANS} plans; there {'is' if len(plans) == 1 else 'are'} "
                        f"{len(plans)}."}
    if check is None:
        try:
            check = Relaxation(compiled).best
        except Exception:  # noqa: BLE001 -- no check: every candidate goes to the planner
            check = lambda objective, sense: None  # noqa: E731
    proposals: list[dict[str, Any]] = []
    existing = {c.get("id") for c in ir.get("constraints") or []}
    for name, spec in (ir.get("variables") or {}).items():
        sets = [s for s in (spec or {}).get("index") or [] if isinstance(s, str)]
        domain = (spec or {}).get("domain", "binary")
        if domain == "interval" or len(sets) > MAX_POSITIONS:
            continue
        keys = [k for k in compiled.variables if k[0] == name]
        if not keys:
            continue
        k = len(sets)
        letters = _letters(sets)
        integral = all(compiled.variables[key].is_integral for key in keys)
        for size in range(0, k + 1):
            if size == k and (domain == "binary" or k == 0):
                continue  # a yes/no cell alone says nothing its bounds do not
            for kept in itertools.combinations(range(k), size):
                groups: dict[tuple, list[VarKey]] = {}
                for key in keys:
                    groups.setdefault(tuple(key[1][p] for p in kept), []).append(key)
                names = list(groups)
                sums = [[sum(plan.get(key, 0.0) for key in groups[g]) for g in names] for plan in plans]
                most = max(max(row) for row in sums)
                least = min(min(row) for row in sums)
                tops = {g: sum(float(compiled.variables[x].upper) for x in groups[g]) for g in names}
                bottoms = {g: sum(float(compiled.variables[x].lower) for x in groups[g]) for g in names}
                peak = {g: max(row[i] for row in sums) for i, g in enumerate(names)}
                low = {g: min(row[i] for row in sums) for i, g in enumerate(names)}
                for direction in ("most", "least"):
                    bound = most if direction == "most" else least
                    if integral:
                        bound = math.floor(bound + 1e-9) if direction == "most" else math.ceil(bound - 1e-9)
                    room = [g for g in groups if (tops[g] > bound + 1e-9 if direction == "most"
                                                  else bottoms[g] < bound - 1e-9)]
                    if not room:
                        continue  # the decisions' own bounds keep it
                    # The groups the plans pushed hardest that way, where the model's limit matters most.
                    order = sorted(names, key=lambda g: -peak[g]) if direction == "most" else sorted(names, key=low.get)
                    checked = [g for g in order if g in room][:CHECKED_GROUPS]
                    allows = []
                    for g in checked:
                        objective = Linear({key: Decimal(1) for key in groups[g]})
                        value = check(objective, "maximize" if direction == "most" else "minimize")
                        if value is not None:
                            allows.append(value)
                    if allows and len(allows) == len(checked):
                        model_most = max(allows) if direction == "most" else min(allows)
                        if integral:
                            model_most = math.floor(model_most + 1e-6) if direction == "most" else math.ceil(model_most - 1e-6)
                        implied = model_most <= bound + 1e-6 if direction == "most" else model_most >= bound - 1e-6
                        if implied:
                            continue
                    else:
                        model_most = None
                    proposals.append(_rule(name, sets, letters, kept, direction, bound, model_most, len(plans),
                                           len(groups), existing, integral))
    # Most telling first: the widest gap between what the model allows and what the plans did, relative.
    def gap(p: dict[str, Any]) -> float:
        allows, bound = p.get("model_allows"), p["bound"]
        if allows is None:
            return 0.0
        return abs(float(allows) - float(bound)) / max(1.0, abs(float(bound)))
    proposals.sort(key=lambda p: (-gap(p), p["id"]))
    return {"plans": len(plans), "rules": proposals[:MOST],
            "says": f"{len(proposals)} rule{'' if len(proposals) == 1 else 's'} every one of the {len(plans)} plans kept "
                    "and the model does not." if proposals else
                    f"Every rule of these shapes that the {len(plans)} plans kept, the model already keeps."}


def _rule(name: str, sets: list[str], letters: list[str], kept: tuple[int, ...], direction: str, bound,
          model_allows, plans: int, groups: int, existing: set, integral: bool) -> dict[str, Any]:
    summed = [p for p in range(len(sets)) if p not in kept]
    by = "_".join(sets[p] for p in kept) or "total"
    rule_id, n = f"c_learnt_{name}_{by}_{'max' if direction == 'most' else 'min'}", 2
    base = rule_id
    while rule_id in existing:
        rule_id, n = f"{base}_{n}", n + 1
    existing.add(rule_id)
    cell = {"var": name, "index": letters}
    left: dict[str, Any] = ({"sum": cell, "over": [{"index": letters[p], "set": sets[p]} for p in summed]}
                            if summed else cell)
    value = int(bound) if integral or float(bound).is_integer() else round(float(bound), 6)
    relation = "<=" if direction == "most" else ">="
    rule = {"id": rule_id, "left": left, "relation": relation, "right": {"const": value}, "severity": "hard",
            "note": f"learnt from {plans} past plans: {'never more' if direction == 'most' else 'never less'} than "
                    f"{value}" + ("" if model_allows is None else f"; the model allows {model_allows}")}
    if kept:
        rule["forall"] = [{"index": letters[p], "set": sets[p]} for p in kept]
    each = (", for each " + ", ".join(sets[p] for p in kept)) if kept else ""
    over = (", summed over " + ", ".join(sets[p] for p in summed)) if summed else ""
    says = (f"{name}{over}{each}: {'at most' if direction == 'most' else 'at least'} {value} "
            f"-- every one of {plans} plans kept it")
    if model_allows is not None:
        says += f"; the model allows {'up to' if direction == 'most' else 'as little as'} {model_allows}"
    return {"id": rule_id, "decision": name, "by": [sets[p] for p in kept], "over": [sets[p] for p in summed],
            "direction": direction, "bound": value, "model_allows": model_allows, "plans": plans, "groups": groups,
            "says": says, "rule": rule}


class Relaxation:
    """The model with every decision continuous, as one sparse LP built once and solved per sum asked (SciPy's
    HiGHS, in this process). A rule an LP cannot hold (conditional, quadratic, scheduling) is left out, which
    only lets the relaxation allow more -- so a rule is never dropped as implied when it is not."""

    def __init__(self, compiled: Compiled):
        import numpy as np
        from scipy.sparse import csr_matrix

        from app.solve.pywraplp_model import row_bounds

        self.keys = list(compiled.variables)
        position = {k: i for i, k in enumerate(self.keys)}
        rows, cols, vals, low, high = [], [], [], [], []
        for c in compiled.constraints:
            if c.quadratic or c.when is not None or getattr(c, "schedule", None) is not None:
                continue
            try:
                coeffs, lo, hi = row_bounds(c)
            except ValueError:
                continue
            r = len(low)
            for key, coeff in coeffs.items():
                if key in position and coeff != 0:
                    rows.append(r)
                    cols.append(position[key])
                    vals.append(float(coeff))
            low.append(lo)
            high.append(hi)
        n = len(self.keys)
        self.A = csr_matrix((vals, (rows, cols)), shape=(len(low), n))
        self.low, self.high = np.array(low, dtype=float), np.array(high, dtype=float)
        self.bounds = [(float(compiled.variables[k].lower), float(compiled.variables[k].upper)) for k in self.keys]
        self.position = position

    def best(self, objective: Linear, sense: str) -> float | None:
        import numpy as np
        from scipy.optimize import linprog

        c = np.zeros(len(self.keys))
        for key, coeff in objective.coeffs.items():
            if key in self.position:
                c[self.position[key]] += float(coeff)
        sign = 1.0 if sense == "minimize" else -1.0
        upper = self.high < np.inf
        lower = self.low > -np.inf
        equal = upper & lower & (self.high == self.low)
        ub_rows = upper & ~equal
        lb_rows = lower & ~equal
        from scipy.sparse import vstack

        A_ub = vstack([self.A[ub_rows], -self.A[lb_rows]]) if (ub_rows.any() or lb_rows.any()) else None
        b_ub = np.concatenate([self.high[ub_rows], -self.low[lb_rows]]) if A_ub is not None else None
        try:
            found = linprog(sign * c, A_ub=A_ub, b_ub=b_ub,
                            A_eq=self.A[equal] if equal.any() else None, b_eq=self.low[equal] if equal.any() else None,
                            bounds=self.bounds, method="highs", options={"time_limit": CHECK_SECONDS})
        except Exception:  # noqa: BLE001 -- a check that cannot run leaves the rule to the planner
            return None
        if found.status != 0:
            return None
        return float(sign * found.fun + float(objective.const))
