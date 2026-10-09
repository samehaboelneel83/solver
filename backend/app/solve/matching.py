"""Pairings solved as pairings: a model that is a matching, solved by Edmonds' blossom algorithm (NetworkX).

Pairing crew members to share rooms, players into two-person teams, machines into back-up pairs: each decision
pairs two records (yes or no), and each record is in at most one pair -- or exactly one. When the two sides are
different (workers and shifts) this is an assignment, a network (`app.solve.network`). When any record may pair
with any other, it is not: three records pairwise joined make an odd cycle no network has, and its linear
relaxation is fractional (one half on each of the three pairs). Branching then works hard on what Edmonds'
blossom algorithm solves exactly in polynomial time -- `networkx.max_weight_matching`.

**When it applies** -- read off the compiled model:

- every decision yes or no (0..1), the goal linear, no curve, function, schedule or condition;
- every rule over two or more decisions is `sum <= 1` (each record in at most one pair) or every one is
  `sum = 1` (each record in exactly one pair: a perfect matching), with every coefficient +1;
- each decision in exactly two such rules -- the pair's two records; a decision in one rule only pairs its record
  with nobody else (a record left on its own, at that decision's worth), allowed when every rule is `<= 1`;
- a rule on one decision is its bound (`x <= 1`, or 0: that pair is not allowed).

The answer is proven: an optimum of a matching problem is the global one (`proves="global"`), and a perfect
matching that does not exist is a proof of infeasibility. Weights are scaled to whole numbers so NetworkX's
arithmetic is exact.
"""
from __future__ import annotations

import time
from decimal import Decimal
from typing import Any

from app.solve.compile import Compiled, VarKey


def _scale(values: list[Decimal]) -> int | None:
    from app.solve.network import _scale as scale

    return scale(values)


def _shape(compiled: Compiled):
    """(nodes, edges, perfect, fixed) of the model read as a matching, or why it is not one."""
    if compiled.objective_quadratic or compiled.objective_mode == "lex":
        return "the goal is not one linear sum"
    if compiled.pwl or compiled.functions or compiled.intervals or getattr(compiled, "placements", None):
        return "the model has curves, functions, schedules or placements"
    upper = {k: v.upper for k, v in compiled.variables.items()}
    for k, v in compiled.variables.items():
        if not v.is_integral or v.lower != 0 or v.upper > 1:
            return f"{k[0]!r} is not a yes-or-no decision"
    rows: list[tuple[str, list[VarKey]]] = []
    relations = set()
    for c in compiled.constraints:
        if c.when is not None or getattr(c, "schedule", None) is not None or c.quadratic:
            return f"the rule {c.id!r} is not a plain linear rule"
        coeffs: dict[VarKey, Decimal] = {}
        for k, v in c.left.coeffs.items():
            coeffs[k] = coeffs.get(k, Decimal(0)) + v
        for k, v in c.right.coeffs.items():
            coeffs[k] = coeffs.get(k, Decimal(0)) - v
        coeffs = {k: v for k, v in coeffs.items() if v}
        rhs = c.right.const - c.left.const
        if not coeffs:
            holds = {"<=": 0 <= rhs, ">=": 0 >= rhs}.get(c.relation, rhs == 0)
            if not holds:
                return f"the rule {c.id!r} reads no decision and never holds"
            continue
        if len(coeffs) == 1:
            (k, a), = coeffs.items()
            relation = c.relation if a > 0 else {"<=": ">=", ">=": "<="}.get(c.relation, c.relation)
            bound = rhs / a
            if relation in ("<=", "=") and bound < 1:
                if bound < 0:
                    return f"the rule {c.id!r} asks a yes-or-no decision to be below 0"
                upper[k] = Decimal(0)
            if relation in (">=", "=") and bound > 0:
                return f"the rule {c.id!r} forces a pair: not a matching"
            continue
        if any(v != 1 for v in coeffs.values()) or rhs != 1 or c.relation not in ("<=", "=", "=="):
            return f"the rule {c.id!r} is not 'each record in at most (or exactly) one pair'"
        relations.add("=" if c.relation in ("=", "==") else "<=")
        rows.append((c.id, list(coeffs)))
    if not rows:
        return "no rule pairs anything"
    if len(relations) > 1:
        return "some records must be paired and others may not: a mix the blossom algorithm does not take"
    perfect = relations == {"="}
    where: dict[VarKey, list[int]] = {k: [] for k in compiled.variables}
    for i, (_, keys) in enumerate(rows):
        for k in keys:
            where[k].append(i)
    for k, at in where.items():
        if len(at) > 2:
            return f"{k[0]!r} is in more than two rules: a pair has two records"
        if len(at) == 1 and perfect:
            return f"{k[0]!r} pairs a record with nobody, in a model where every record must be paired"
    return rows, where, perfect, upper


def applies(compiled: Compiled) -> str | None:
    shape = _shape(compiled)
    return shape if isinstance(shape, str) else None


def solve(compiled: Compiled):
    """The proven best matching, or a proof that the perfect matching asked for does not exist."""
    import networkx as nx

    from app.solve.network import Networked
    from app.solve.result import Solution

    started = time.monotonic()
    shape = _shape(compiled)
    if isinstance(shape, str):
        raise ValueError(shape)
    rows, where, perfect, upper = shape
    sign = 1 if compiled.sense == "maximize" else -1
    coeff = {k: compiled.objective.coeffs.get(k, Decimal(0)) for k in compiled.variables}
    scale = _scale(list(coeff.values())) or 1
    gain = {k: int(sign * coeff[k] * scale) for k in compiled.variables}
    graph = nx.Graph()
    graph.add_nodes_from(range(len(rows)))
    edge_of: dict[tuple[int, int], VarKey] = {}
    chosen: set[VarKey] = set()
    lone = len(rows)
    for k, at in where.items():
        if upper[k] == 0:
            continue
        if not at:
            # In no rule: chosen when it pays.
            if gain[k] > 0:
                chosen.add(k)
            continue
        a, b = (at[0], at[1]) if len(at) == 2 else (at[0], lone)
        if len(at) == 1:
            lone += 1  # a record on its own: a partner of its own that no rule constrains
        if a == b:
            continue  # a decision twice in one rule: it would count twice there
        key = (min(a, b), max(a, b))
        # Two decisions on the same pair: the better one stands for both (the other is never chosen).
        if key in edge_of and gain[edge_of[key]] >= gain[k]:
            continue
        edge_of[key] = k
    if perfect:
        # Among the matchings that pair everyone, the best: every weight raised by more than any spread, so the
        # most pairs come first and the weights then decide.
        big = 1 + sum(abs(g) for g in gain.values())
        for (a, b), k in edge_of.items():
            graph.add_edge(a, b, weight=gain[k] + big)
        matched = nx.max_weight_matching(graph, maxcardinality=True)
        if 2 * len(matched) < len(rows):
            return _none(compiled, started, "infeasible", "no way pairs every record", len(rows), len(edge_of))
    else:
        # Only pairs worth something are worth taking; a pair worth nothing is left out (the same goal).
        for (a, b), k in edge_of.items():
            if gain[k] > 0:
                graph.add_edge(a, b, weight=gain[k])
        matched = nx.max_weight_matching(graph, maxcardinality=False)
    for a, b in matched:
        chosen.add(edge_of[(min(a, b), max(a, b))])
    assignments: dict[VarKey, int] = {k: (1 if k in chosen else 0) for k in compiled.variables}
    objective = float(compiled.objective.evaluated_at(assignments))
    value = int(objective) if objective == int(objective) else objective
    record = {"kind": "matching", "engine": "networkx blossom", "records": len(rows), "pairs": len(edge_of),
              "perfect": perfect, "chosen": len(chosen)}
    return Networked(Solution(status="optimal", optimal=True, objective=value, assignments=assignments,
                              wall_seconds=round(time.monotonic() - started, 3),
                              solver="matching (Edmonds' blossom, NetworkX)", best_bound=value), record)


def _none(compiled: Compiled, started: float, status: str, why: str, nodes: int, edges: int):
    from app.solve.network import Networked
    from app.solve.result import Solution

    return Networked(Solution(status=status, optimal=False, objective=None, assignments={},
                              wall_seconds=round(time.monotonic() - started, 3),
                              solver="matching (Edmonds' blossom, NetworkX)"),
                     {"kind": "matching", "why": why, "records": nodes, "pairs": edges})
