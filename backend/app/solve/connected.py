"""`connected`, compiled: an exact single-commodity flow per group (spatial spec §4).

For group z: one root among its units; flow runs only between two units of
the group, along `via` edges in either direction; every assigned unit that
is not the root takes in one unit more than it sends on. A group is
connected exactly when this flow exists -- every unit is reached from the
root -- so the rows are exact and linear.

The flow is integer, not continuous: supplies and demands are whole, so an
integer flow exists whenever any flow does, and a whole-number model stays
one -- CP-SAT keeps taking it.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

ROOT, FLOW = "__root", "__flow"


def sources_of(compiler: Any, body: dict[str, Any]) -> set[str]:
    """The units whose `sources` field is set (1, true): where a sourced network starts."""
    field = body["sources"]
    out = set()
    if isinstance(field, list):  # a where list on the units' own fields (kind = "exchange")
        from app.solve.compile import _passes

        return {row["id"] for row in compiler.sets.get(body["units"]["set"], []) if _passes(row, field)}
    for row in compiler.sets.get(body["units"]["set"], []):
        value = (row.get("attrs") or row).get(field) if isinstance(row, dict) else None
        if value is None and isinstance(row, dict):
            value = row.get(field)
        if value not in (None, "", 0, "0", False, "false", "False"):
            try:
                if float(value) == 0:
                    continue
            except (TypeError, ValueError):
                pass
            out.add(row["id"])
    return out


def _expand_sourced(compiler: Any, spec: dict[str, Any]) -> None:
    """`connected` with `sources`: every chosen unit is reached along `via` from a chosen source unit.

    A flow per group (or one, with no groups): a chosen source may send any amount; every other chosen unit
    keeps one unit of what it takes in; flow runs only between two chosen units. No root is chosen -- the
    sources are given -- so it is exact, linear and whole, as the unsourced rule is (corridors that reach a
    door, pipes fed from a supply, roads joined to a depot)."""
    from app.solve.compile import Constraint, Linear, Unsupported, Variable

    body = spec["connected"]
    rule = spec["id"]
    var = body["assign"]["var"]
    units = [row["id"] for row in compiler.sets.get(body["units"]["set"], [])]
    grouped = body.get("groups") is not None
    groups = [row["id"] for row in compiler.sets.get(body["groups"]["set"], [])] if grouped else [None]
    sources = sources_of(compiler, body)
    if units and not sources:
        # Nothing could be reached, so the only answer would choose nothing -- and a solver calls that
        # optimal. The camp retest (October 2026) got "optimal, 0 beds" from cells built without the field.
        raise Unsupported(
            f"{rule}: no {body['units']['set']} record is a source ({json.dumps(body['sources'])}), so nothing can "
            f"be reached from a source and every {var} would be 0; mark the records the network starts from")
    known = set(units)
    pairs = sorted({tuple(sorted((e["from"], e["to"]))) for e in compiler.edges.get(body["via"], [])
                    if e["from"] in known and e["to"] in known and e["from"] != e["to"]})
    arcs = [*pairs, *((b, a) for a, b in pairs)]
    n = Decimal(len(units))
    one = Decimal(1)
    into: dict[str, list] = {u: [] for u in units}
    out_of: dict[str, list] = {u: [] for u in units}
    for z in groups:
        x = {u: (var, (u, z) if grouped else (u,)) for u in units}
        missing = [k for k in x.values() if k not in compiler.variables]
        if missing:  # pragma: no cover -- the validator pins the index
            raise Unsupported(f"{rule}: no variable {missing[0]}")
        flow = {(a, b): (FLOW, (rule, a, b) + ((z,) if grouped else ())) for a, b in arcs}
        for key in flow.values():
            compiler.variables[key] = Variable(key, "integer", Decimal(0), max(n - one, Decimal(0)))
        index = {body["groups"]["index"]: z} if grouped else {}
        for u in units:
            into[u], out_of[u] = [], []
        for (a, b), f in flow.items():
            out_of[a].append(f)
            into[b].append(f)
            compiler.constraints.append(Constraint(rule, dict(index), Linear(coeffs={f: one, x[a]: -(n - one)}), "<=", Linear()))
            compiler.constraints.append(Constraint(rule, dict(index), Linear(coeffs={f: one, x[b]: -(n - one)}), "<=", Linear()))
        for u in units:
            if u in sources:
                continue  # a source sends what it likes
            balance = Linear(coeffs={x[u]: -one})
            for f in into[u]:
                balance.add(Linear(coeffs={f: one}))
            for f in out_of[u]:
                balance.add(Linear(coeffs={f: -one}))
            compiler.constraints.append(Constraint(rule, dict(index), balance, ">=", Linear()))
    compiler.connectivity.append(rule)


def expand(compiler: Any, spec: dict[str, Any]) -> None:
    from app.solve.compile import Constraint, Linear, Unsupported, Variable

    if spec["connected"].get("sources"):
        _expand_sourced(compiler, spec)
        return
    body = spec["connected"]
    rule = spec["id"]
    var = body["assign"]["var"]
    units = [row["id"] for row in compiler.sets.get(body["units"]["set"], [])]
    groups = [row["id"] for row in compiler.sets.get(body["groups"]["set"], [])]
    allowed = body.get("empty", "forbidden") == "allowed"
    known = set(units)
    pairs = sorted(
        {
            tuple(sorted((e["from"], e["to"])))
            for e in compiler.edges.get(body["via"], [])
            if e["from"] in known and e["to"] in known and e["from"] != e["to"]
        }
    )
    arcs = [*pairs, *((b, a) for a, b in pairs)]
    n = Decimal(len(units))
    one = Decimal(1)
    for z in groups:
        x = {u: (var, (u, z)) for u in units}
        missing = [k for k in x.values() if k not in compiler.variables]
        if missing:  # pragma: no cover -- the validator pins the index
            raise Unsupported(f"{rule}: no variable {missing[0]}")
        root = {u: (ROOT, (rule, u, z)) for u in units}
        for key in root.values():
            compiler.variables[key] = Variable(key, "binary", Decimal(0), one)
        flow = {(a, b): (FLOW, (rule, a, b, z)) for a, b in arcs}
        for key in flow.values():
            compiler.variables[key] = Variable(key, "integer", Decimal(0), max(n - one, Decimal(0)))
        index = {body["groups"]["index"]: z}

        def row(left: Linear, relation: str, right: Linear) -> None:
            compiler.constraints.append(Constraint(rule, dict(index), left, relation, right))

        roots = Linear(coeffs={k: one for k in root.values()})
        # One root; with empty groups allowed, at most one, and one as soon
        # as the group has any unit.
        row(roots.copy(), "<=" if allowed else "=", Linear(const=one))
        for u in units:
            row(Linear(coeffs={root[u]: one, x[u]: -one}), "<=", Linear())
            if allowed:
                row(Linear(coeffs={x[u]: one}).add(roots, factor=-1), "<=", Linear())
        # Flow only between two units of the group.
        for (a, b), f in flow.items():
            row(Linear(coeffs={f: one, x[a]: -(n - one)}), "<=", Linear())
            row(Linear(coeffs={f: one, x[b]: -(n - one)}), "<=", Linear())
        # Every assigned unit but the root keeps one unit of what it takes in.
        for u in units:
            balance = Linear()
            for (a, b), f in flow.items():
                if b == u:
                    balance.add(Linear(coeffs={f: one}))
                if a == u:
                    balance.add(Linear(coeffs={f: -one}))
            balance.add(Linear(coeffs={x[u]: -one, root[u]: n}))
            row(balance, ">=", Linear())
    compiler.connectivity.append(rule)
