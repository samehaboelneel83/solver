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

from decimal import Decimal
from typing import Any

ROOT, FLOW = "__root", "__flow"


def expand(compiler: Any, spec: dict[str, Any]) -> None:
    from app.solve.compile import Constraint, Linear, Unsupported, Variable

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
