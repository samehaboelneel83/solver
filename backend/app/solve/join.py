"""`join` (network design): the links built join the places into one network, or into networks each reaching a source.

A link (a road, a cable, a pipe, a corridor) may be built or not -- `build[link]`, yes or no -- and joins its two
places, named by the two `ends` relationships (link to place). The rule says the built links join

- every place into one network, when the rule has neither `use` nor `sources` (a spanning network);
- every place to a source, with `sources` (a 0/1 field of the places, or a where list): networks fed from an
  exchange, a supply, a depot;
- only the places `use` chooses (a yes/no decision per place), with `use`: a link is then built only between two
  used places, and the model decides which places are worth joining (a Steiner network).

**Compiled** (`expand`) as an exact single-commodity flow, the way `connected` is: flow runs only along built
links, in either direction, at most N per link (N places); every used place that is not a root (or a source) keeps
one unit of what it takes in. A network is joined exactly when this flow exists, so the rows are exact, linear
and whole -- CP-SAT, HiGHS and SCIP all take them. Places no link could ever join to a source are found first (graph
components): with `use` they are switched off by a row; without it the rule cannot hold, and the run says which
place, rather than solving to "infeasible".

**Solved exactly as a graph** (`applies`, `solve`): when the model is just "build the cheapest links that join
the places" -- the join rule without `use`, links forced in or out by rules of one decision, the goal a sum over the
links built -- it is a minimum spanning tree (or, with sources, a minimum spanning forest, each tree holding one
source: Kruskal on the places with one more node joined to every source at no cost). Links that pay for
themselves (a negative cost when minimizing) and links forced in are taken first; Kruskal completes the rest. The
answer is the proven optimum, in milliseconds where branching on the flow takes minutes.

**A start** (`start`) for every other model with one join rule: the spanning tree or forest by the goal's own link
costs, or -- with `use` -- a Steiner tree (NetworkX's approximation) joining the places that must be used and the
sources, handed to the solver as a hint.
"""
from __future__ import annotations

import json
import time
from collections import deque
from decimal import Decimal
from typing import Any

from app.solve.compile import Compiled, VarKey

FLOW, ROOT, DEMAND = "__join_flow", "__join_root", "__join_demand"
#: The share of the run's time the start may take, and its ceiling in seconds.
SHARE, CEILING = 0.2, 30.0
#: The node standing for "any source": joined to every source at no cost, so a forest is one spanning tree.
SUPER = "\x00sources"


def _sources(compiler: Any, body: dict[str, Any]) -> set[str] | None:
    if not body.get("sources"):
        return None
    from app.solve.connected import sources_of

    return {str(s) for s in sources_of(compiler, {"sources": body["sources"], "units": body["places"]})}


def _ends(compiler: Any, body: dict[str, Any], links: list[str], known: set[str]):
    """Each link's two places (from the two `ends` relationships), and the links that have no usable pair."""
    sides: list[dict[str, list[str]]] = []
    for name in body["ends"]:
        side: dict[str, list[str]] = {}
        for e in compiler.edges.get(name, []):
            side.setdefault(str(e["from"]), []).append(str(e["to"]))
        sides.append(side)
    ends: dict[str, tuple[str, str]] = {}
    unusable: list[str] = []
    for link in links:
        a, b = sides[0].get(link, []), sides[1].get(link, [])
        if len(a) > 1 or len(b) > 1:
            from app.solve.compile import Unsupported

            name = body["ends"][0] if len(a) > 1 else body["ends"][1]
            raise Unsupported(f"the link {link!r} has {max(len(a), len(b))} places along {name!r}; a link has one "
                              f"place at each end -- one {name} edge per link")
        if not a or not b or a[0] not in known or b[0] not in known:
            unusable.append(link)
            continue
        ends[link] = (a[0], b[0])
    return ends, unusable


def _field(row: dict[str, Any], name: str) -> Decimal | None:
    """A record's number in `name`, or None when it has none."""
    value = row.get(name)
    if value is None and isinstance(row.get("attrs"), dict):
        value = row["attrs"].get(name)
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except Exception:  # noqa: BLE001 -- a text in a number field is said by the caller
        return Decimal("NaN")


def _numbers(compiler: Any, rule: str, set_name: str, ids: list[str], name: str, what: str) -> dict[str, Decimal]:
    """Each record's `name` (missing ones left out), refused when one is not a number of 0 or more."""
    from app.solve.compile import Unsupported

    rows = {str(r["id"]): r for r in compiler.sets.get(set_name, [])}
    out: dict[str, Decimal] = {}
    for i in ids:
        value = _field(rows.get(i, {}), name)
        if value is None:
            continue
        if value.is_nan() or value < 0:
            raise Unsupported(f"{rule}: the {set_name} {i!r} has {name} = {rows[i].get(name)!r}; {what} is a number of "
                              "0 or more")
        out[i] = value
    return out


def _components(places: list[str], pairs) -> dict[str, int]:
    parent = {p: p for p in places}

    def find(p: str) -> str:
        while parent[p] != p:
            parent[p] = parent[parent[p]]
            p = parent[p]
        return p

    for a, b in pairs:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    roots: dict[str, int] = {}
    return {p: roots.setdefault(find(p), len(roots)) for p in places}


def expand(compiler: Any, spec: dict[str, Any]) -> None:
    from app.solve.compile import Constraint, Linear, Unsupported, Variable

    rule, body = spec["id"], spec["join"]
    link_index, place_index = body["links"]["index"], body["places"]["index"]
    links = [str(row["id"]) for row in compiler.sets.get(body["links"]["set"], [])]
    places = [str(row["id"]) for row in compiler.sets.get(body["places"]["set"], [])]
    known = set(places)
    build = {link: (body["build"]["var"], (link,)) for link in links}
    use = {p: (body["use"]["var"], (p,)) for p in places} if body.get("use") else None
    missing = [k for k in [*build.values(), *(use or {}).values()] if k not in compiler.variables]
    if missing:  # pragma: no cover -- the validator pins the index
        raise Unsupported(f"{rule}: no variable {missing[0]}")
    sources = _sources(compiler, body)
    if sources is not None and places and not sources & known:
        raise Unsupported(
            f"{rule}: no {body['places']['set']} record is a source ({json.dumps(body['sources'])}), so no place can "
            "be joined to one; mark the records the network starts from")
    ends, unusable = _ends(compiler, body, links, known)
    one, zero = Decimal(1), Decimal(0)
    n = Decimal(max(len(places) - 1, 0))

    def row(index: dict[str, str], left: Linear, relation: str, right: Linear | None = None) -> None:
        compiler.constraints.append(Constraint(rule, index, left, relation, right or Linear()))

    for link in unusable:
        # An end missing, or a place outside the rule's places: the link joins nothing it could be built for.
        row({link_index: link}, Linear(coeffs={build[link]: one}), "<=")

    # Places no link could ever join (to each other, or to a source).
    component = _components(places, [ab for ab in ends.values() if ab[0] != ab[1]])
    unreachable: list[str] = []
    if sources is not None:
        fed = {component[s] for s in sources if s in component}
        unreachable = [p for p in places if component[p] not in fed]
    elif use is None and len(set(component.values())) > 1:
        apart = {}
        for p in places:
            apart.setdefault(component[p], p)
        first, second = list(apart.values())[:2]
        raise Unsupported(
            f"{rule}: every {body['places']['set']} must be joined, and no links could join {first!r} to {second!r} "
            f"({len(apart)} pieces no link connects); add links between them, or give the rule a use decision so "
            "only some places need joining")
    if unreachable and use is None:
        raise Unsupported(
            f"{rule}: {len(unreachable)} {body['places']['set']} record(s) can never be joined to a source by any link "
            f"(the first: {unreachable[0]!r}); add links to them, or give the rule a use decision so they may be left "
            "out")
    for p in unreachable:
        row({place_index: p}, Linear(coeffs={use[p]: one}), "<=")

    def x(p: str) -> Linear:
        return Linear(coeffs={use[p]: one}) if use is not None else Linear(const=one)

    into: dict[str, Linear] = {p: Linear() for p in places}
    flow: dict[tuple[str, str, str], VarKey] = {}
    for link, (a, b) in ends.items():
        if use is not None:
            row({link_index: link}, Linear(coeffs={build[link]: one, use[a]: -one}), "<=")
            if b != a:
                row({link_index: link}, Linear(coeffs={build[link]: one, use[b]: -one}), "<=")
        if a == b:
            continue  # a link from a place to itself joins nothing
        for u, v, way in ((a, b, "ab"), (b, a, "ba")):
            key = (FLOW, (rule, link, way))
            compiler.variables[key] = Variable(key, "integer", zero, n)
            flow[(link, u, v)] = key
            row({link_index: link}, Linear(coeffs={key: one, build[link]: -n}), "<=")
            into[v].add(Linear(coeffs={key: one}))
            into[u].add(Linear(coeffs={key: -one}))
    root: dict[str, VarKey] | None = None
    if sources is None and places:
        root = {p: (ROOT, (rule, p)) for p in places}
        for key in root.values():
            compiler.variables[key] = Variable(key, "binary", zero, one)
        roots = Linear(coeffs={k: one for k in root.values()})
        row({}, roots.copy(), "<=" if use is not None else "=", Linear(const=one))
        if use is not None:
            for p in places:
                row({place_index: p}, Linear(coeffs={root[p]: one, use[p]: -one}), "<=")
                row({place_index: p}, Linear(coeffs={use[p]: one}).add(roots, factor=-1), "<=")
    for p in places:
        if sources is not None and p in sources:
            continue  # a source sends what it likes
        balance = into[p].copy()
        balance.add(x(p), factor=-1)
        if root is not None:
            balance.add(Linear(coeffs={root[p]: n + one}))
        row({place_index: p}, balance, ">=")
    demand = _demand(compiler, spec, places, links, ends, build, sources, x, row) if body.get("demand") else None
    compiler.connectivity.append(rule)
    compiler.joins.append({
        "rule": rule, "build": build, "use": use, "ends": ends, "places": places, "sources": sources,
        "flow": flow, "root": root, "unusable": len(unusable), "unreachable": len(unreachable),
        **(demand or {"need": None, "dflow": {}, "capacity": {}, "supply": {}, "carry": None}),
    })


def _demand(compiler: Any, spec: dict[str, Any], places, links, ends, build, sources, x, row) -> dict[str, Any]:
    """What each place takes from the sources, carried along the built links: a second flow beside the one that
    joins the places (a place that takes nothing must still be joined, which this flow alone would not see).

    Every place but the sources takes in its `demand` more than it sends on (when used); a built link carries at
    most its `capacity`, both ways together; a source sends at most its `supply`; `carry[link]`, when named, is what
    the link carries -- the goal may price it and other rules may read it. Whole numbers keep the flow whole."""
    from app.solve.compile import Linear, Unsupported, Variable

    rule, body = spec["id"], spec["join"]
    if sources is None:  # pragma: no cover -- the validator asks demand for sources
        raise Unsupported(f"{rule}: a demand is delivered from sources; name the sources")
    link_index, place_index = body["links"]["index"], body["places"]["index"]
    place_set, link_set = body["places"]["set"], body["links"]["set"]
    need = _numbers(compiler, rule, place_set, places, body["demand"], "a demand")
    need = {p: need.get(p, Decimal(0)) for p in places if p not in sources}
    cap = _numbers(compiler, rule, link_set, links, body["capacity"], "a capacity") if body.get("capacity") else {}
    supply = _numbers(compiler, rule, place_set, sorted(sources), body["supply"], "a supply") \
        if body.get("supply") else {}
    total = sum(need.values(), Decimal(0))
    if body.get("supply") and len(supply) == len(sources) and body.get("use") is None and sum(supply.values()) < total:
        raise Unsupported(f"{rule}: the sources supply {sum(supply.values())} in all and the {place_set} records take "
                          f"{total}; every one must be joined, so no network can feed them all")
    whole = all(v == v.to_integral_value() for v in [*need.values(), *cap.values(), *supply.values()])
    one, zero = Decimal(1), Decimal(0)
    into: dict[str, Linear] = {p: Linear() for p in places}
    dflow: dict[tuple[str, str, str], Any] = {}
    carry = {link: (body["carry"]["var"], (link,)) for link in links} if body.get("carry") else None
    if carry is not None:
        missing = [k for k in carry.values() if k not in compiler.variables]
        if missing:  # pragma: no cover -- the validator pins the index
            raise Unsupported(f"{rule}: no variable {missing[0]}")
    for link, (a, b) in ends.items():
        carried = Linear()
        if a != b:
            limit = min(total, cap[link]) if link in cap else total
            for u, v, way in ((a, b, "ab"), (b, a, "ba")):
                key = (DEMAND, (rule, link, way))
                compiler.variables[key] = Variable(key, "integer" if whole else "continuous", zero, limit)
                dflow[(link, u, v)] = key
                carried.add(Linear(coeffs={key: one}))
                into[v].add(Linear(coeffs={key: one}))
                into[u].add(Linear(coeffs={key: -one}))
                if link not in cap:
                    row({link_index: link}, Linear(coeffs={key: one, build[link]: -total}), "<=")
            if link in cap:
                row({link_index: link}, carried.copy().add(Linear(coeffs={build[link]: -cap[link]})), "<=")
        if carry is not None:
            row({link_index: link}, Linear(coeffs={carry[link]: one}).add(carried, factor=-1), "=")
    if carry is not None:
        for link in links:
            if link not in ends:
                row({link_index: link}, Linear(coeffs={carry[link]: one}), "=")
    for p in places:
        if p in sources:
            if p in supply:
                # What it sends on, less what it takes in, within its supply (and nothing when it is not used).
                row({place_index: p}, into[p].copy().add(x(p), factor=supply[p]), ">=")
            continue
        if need[p]:
            row({place_index: p}, into[p].copy().add(x(p), factor=-need[p]), ">=")
        else:
            row({place_index: p}, into[p].copy(), ">=")
    return {"need": need, "dflow": dflow, "capacity": cap, "supply": supply, "carry": carry}


# --- the exact graph lane: a minimum spanning tree or forest -------------------------------------------------


def _single_rows(compiled: Compiled, rule: str, build_keys: set[VarKey]):
    """(forced in, forced out) from the rules of one decision over a link, or why the model is more than that."""
    forced_in: set[VarKey] = set()
    forced_out: set[VarKey] = set()
    for c in compiled.constraints:
        if c.id == rule:
            continue
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
            if not {"<=": 0 <= rhs, ">=": 0 >= rhs}.get(c.relation, rhs == 0):
                return f"the rule {c.id!r} reads no decision and never holds"
            continue
        if len(coeffs) > 1:
            return f"the rule {c.id!r} reads more than one decision (a budget, a degree, a choice between links)"
        (k, a), = coeffs.items()
        if k not in build_keys:
            return f"the rule {c.id!r} reads {k[0]!r}, which is not the links built"
        relation = c.relation if a > 0 else {"<=": ">=", ">=": "<="}.get(c.relation, c.relation)
        bound = rhs / a
        if relation in ("<=", "=", "==") and bound < 1:
            if bound < 0:
                return f"the rule {c.id!r} asks a yes-or-no decision to be below 0"
            forced_out.add(k)
        if relation in (">=", "=", "==") and bound > 0:
            if bound > 1:
                return f"the rule {c.id!r} asks a yes-or-no decision to be above 1"
            forced_in.add(k)
    both = forced_in & forced_out
    if both:
        return f"{next(iter(both))} is forced both in and out"
    return forced_in, forced_out


def _shape(compiled: Compiled):
    joins = getattr(compiled, "joins", None) or []
    if len(joins) != 1:
        return "the model has no single join rule" if not joins else "the model has more than one join rule"
    meta = joins[0]
    if meta["use"] is not None:
        return "the join rule has a use decision: which places to join is the model's choice (a Steiner network)"
    if meta["capacity"] or meta["supply"] or meta["carry"] is not None:
        return ("the join rule limits what links carry or sources send, or names what each link carries: a "
                "capacitated network design, left to the solver")
    if compiled.objective_quadratic or compiled.objective_mode == "lex":
        return "the goal is not one linear sum"
    if compiled.pwl or compiled.functions or compiled.intervals or compiled.placements or compiled.routes \
            or getattr(compiled, "predictions", None):
        return "the model has curves, functions, schedules, placements, routes or predictions"
    if set(compiled.connectivity) != {meta["rule"]}:
        return "the model has another connectivity rule"
    build_keys = set(meta["build"].values())
    for key in compiled.variables:
        if key[0] not in (FLOW, ROOT, DEMAND) and key not in build_keys:
            return f"{key[0]!r} is a decision besides the links built"
    for key in compiled.objective.coeffs:
        if key not in build_keys:
            return f"the goal reads {key[0]!r}, not only the links built"
    rows = _single_rows(compiled, meta["rule"], build_keys)
    if isinstance(rows, str):
        return rows
    return meta, rows


def applies(compiled: Compiled) -> str | None:
    shape = _shape(compiled)
    return shape if isinstance(shape, str) else None


def _tree(places: list[str], ends: dict[str, tuple[str, str]], sources: set[str] | None,
          cost: dict[str, Decimal], forced_in: set[str], forced_out: set[str]):
    """(links built, links carrying the tree, pieces left) of the cheapest network: forced and paying links first,
    then Kruskal."""
    nodes = [*places, SUPER] if sources is not None else list(places)
    parent = {p: p for p in nodes}

    def find(p: str) -> str:
        while parent[p] != p:
            parent[p] = parent[parent[p]]
            p = parent[p]
        return p

    def union(a: str, b: str) -> bool:
        ra, rb = find(a), find(b)
        if ra == rb:
            return False
        parent[ra] = rb
        return True

    for s in sorted(sources or ()):
        union(SUPER, s)
    built: set[str] = set()
    tree: set[str] = set()
    for link, (a, b) in ends.items():
        if link in forced_out:
            continue
        if link in forced_in or cost[link] < 0:
            built.add(link)
            if union(a, b):
                tree.add(link)
    for link in sorted((l for l in ends if l not in built and l not in forced_out), key=lambda l: (cost[l], l)):
        if union(*ends[link]):
            built.add(link)
            tree.add(link)
    pieces = len({find(p) for p in nodes})
    return built, tree, pieces


def _flows(meta: dict[str, Any], tree: set[str]) -> dict[VarKey, int]:
    """Flow along the tree's links that meets every balance: each link carries the size of the subtree past it."""
    places, ends, sources = meta["places"], meta["ends"], meta["sources"]
    near: dict[str, list[tuple[str, str]]] = {p: [] for p in places}
    for link in tree:
        a, b = ends[link]
        near[a].append((b, link))
        near[b].append((a, link))
    starts = sorted(sources) if sources is not None else ([places[0]] if places else [])
    order: list[str] = []
    up: dict[str, tuple[str, str] | None] = {s: None for s in starts}
    queue = deque(starts)
    while queue:
        p = queue.popleft()
        order.append(p)
        for q, link in near[p]:
            if q not in up:
                up[q] = (p, link)
                queue.append(q)
    size = {p: 1 for p in order}
    need = meta.get("need") or {}
    taken = {p: need.get(p, Decimal(0)) for p in order}
    values: dict[VarKey, Any] = {k: 0 for k in [*meta["flow"].values(), *meta.get("dflow", {}).values()]}
    for p in reversed(order):
        if up[p] is None:
            continue
        parent, link = up[p]
        size[parent] += size[p]
        taken[parent] += taken[p]
        values[meta["flow"][(link, parent, p)]] = size[p]
        if meta.get("dflow"):
            amount = taken[p]
            values[meta["dflow"][(link, parent, p)]] = int(amount) if amount == amount.to_integral_value() \
                else float(amount)
    if meta.get("carry") is not None:
        for link, key in meta["carry"].items():
            values[key] = sum(values.get(meta["dflow"].get((link, *ab), None), 0) or 0
                              for ab in (meta["ends"].get(link, ("", "")), meta["ends"].get(link, ("", ""))[::-1]))
    if meta["root"] is not None:
        for p, key in meta["root"].items():
            values[key] = 1 if starts and p == starts[0] else 0
    return values


def solve(compiled: Compiled):
    """The proven cheapest network that joins every place (or every place to a source), or a proof there is none."""
    from app.solve.network import Networked
    from app.solve.result import Solution

    started = time.monotonic()
    shape = _shape(compiled)
    if isinstance(shape, str):
        raise ValueError(shape)
    meta, (forced_in, forced_out) = shape
    sign = Decimal(1) if compiled.sense != "maximize" else Decimal(-1)
    link_of = {k: link for link, k in meta["build"].items()}
    cost = {link: sign * compiled.objective.coeffs.get(k, Decimal(0)) for link, k in meta["build"].items()}
    f_in = {link_of[k] for k in forced_in}
    f_out = {link_of[k] for k in forced_out} | {l for l in meta["build"] if l not in meta["ends"]}
    built, tree, pieces = _tree(meta["places"], meta["ends"], meta["sources"], cost, f_in, f_out)
    kind = "spanning forest" if meta["sources"] is not None else "spanning tree"
    record = {"kind": "spanning", "engine": f"minimum {kind} (Kruskal)", "places": len(meta["places"]),
              "links": len(meta["ends"]), "sources": len(meta["sources"]) if meta["sources"] is not None else None,
              "forced_in": len(f_in), "forced_out": len(f_out)}
    solver = f"minimum {kind} (Kruskal)"
    if pieces > 1:
        record["why"] = (f"the links that may be built leave {pieces} pieces"
                         + (" not joined to a source" if meta["sources"] is not None else ""))
        return Networked(Solution(status="infeasible", optimal=False, objective=None, assignments={},
                                  wall_seconds=round(time.monotonic() - started, 3), solver=solver), record)
    assignments: dict[VarKey, int] = {k: (1 if link in built else 0) for link, k in meta["build"].items()}
    assignments.update(_flows(meta, tree))
    objective = compiled.objective.evaluated_at(assignments)
    value = int(objective) if objective == int(objective) else float(objective)
    record["built"] = len(built)
    return Networked(Solution(status="optimal", optimal=True, objective=value, assignments=assignments,
                              wall_seconds=round(time.monotonic() - started, 3), solver=solver,
                              best_bound=value), record)


# --- a start for every other model with one join rule --------------------------------------------------------


def _overloaded(meta: dict[str, Any], hint: dict[VarKey, Any]) -> int:
    """How many links the start sends more along than their capacity (the solver then mends it)."""
    carried: dict[str, float] = {}
    for (link, _, _), key in meta.get("dflow", {}).items():
        carried[link] = carried.get(link, 0.0) + float(hint.get(key, 0) or 0)
    return sum(1 for link, c in (meta.get("capacity") or {}).items() if carried.get(link, 0.0) > float(c) + 1e-9)


def start_applies(compiled: Compiled) -> str | None:
    joins = getattr(compiled, "joins", None) or []
    if len(joins) != 1:
        return "the model has no single join rule"
    if compiled.objective_mode == "lex":
        return "goals solved in order are left to the solver"
    return None


def start(compiled: Compiled, *, seconds: float = CEILING) -> tuple[dict[VarKey, int], dict[str, Any]]:
    """A network that keeps the join rule, cheap by the goal's own link costs: the links built, the places used
    and the flow. Other rules may still need the solver to mend it -- it is a hint, never the answer."""
    began = time.monotonic()
    meta = compiled.joins[0]
    sign = Decimal(1) if compiled.sense != "maximize" else Decimal(-1)
    cost = {link: sign * compiled.objective.coeffs.get(k, Decimal(0)) for link, k in meta["build"].items()}
    single = _single_rows(compiled, meta["rule"], set(meta["build"].values()) | set((meta["use"] or {}).values()))
    # Forced links and places, as far as rules of one decision say (other rules are left to the solver).
    forced: set[VarKey] = set()
    banned: set[VarKey] = set()
    for c in compiled.constraints:
        if c.id == meta["rule"] or c.when is not None or c.quadratic:
            continue
        coeffs = {k: v for k, v in c.left.coeffs.items()}
        for k, v in c.right.coeffs.items():
            coeffs[k] = coeffs.get(k, Decimal(0)) - v
        coeffs = {k: v for k, v in coeffs.items() if v}
        if len(coeffs) != 1:
            continue
        (k, a), = coeffs.items()
        relation = c.relation if a > 0 else {"<=": ">=", ">=": "<="}.get(c.relation, c.relation)
        bound = (c.right.const - c.left.const) / a
        if relation in (">=", "=", "==") and bound > 0:
            forced.add(k)
        if relation in ("<=", "=", "==") and bound < 1:
            banned.add(k)
    link_of = {k: link for link, k in meta["build"].items()}
    f_in = {link_of[k] for k in forced if k in link_of}
    f_out = {link_of[k] for k in banned if k in link_of}
    record: dict[str, Any] = {"kind": "join", "single_rows_only": not isinstance(single, str)}
    if meta["use"] is None:
        built, tree, pieces = _tree(meta["places"], meta["ends"], meta["sources"], cost, f_in, f_out)
        if pieces > 1:
            return {}, {**record, "seconds": round(time.monotonic() - began, 3),
                        "why": "the links that may be built cannot join every place"}
        hint = {k: (1 if link in built else 0) for link, k in meta["build"].items()}
        hint.update(_flows(meta, tree))
        record.update(how="spanning " + ("forest" if meta["sources"] is not None else "tree"), built=len(built))
        if meta.get("capacity"):
            record["overloaded"] = _overloaded(meta, hint)
        return hint, {**record, "seconds": round(time.monotonic() - began, 3)}

    import networkx as nx
    from networkx.algorithms.approximation import steiner_tree

    place_of = {k: p for p, k in meta["use"].items()}
    must = {place_of[k] for k in forced if k in place_of}
    barred = {place_of[k] for k in banned if k in place_of}
    sources = meta["sources"]
    terminals = set(must) | ({SUPER} if sources is not None and must else set())
    if len(terminals) < 2:
        return {}, {**record, "seconds": round(time.monotonic() - began, 3),
                    "why": "no rule of one decision says which places must be joined, so there is no tree to start from"}
    graph = nx.Graph()
    shift = -min([Decimal(0), *cost.values()])
    for link, (a, b) in meta["ends"].items():
        if link in f_out or a == b or a in barred or b in barred:
            continue
        weight = float(cost[link] + shift)
        if not graph.has_edge(a, b) or graph[a][b]["weight"] > weight:
            graph.add_edge(a, b, weight=weight, link=link)
    if sources is not None:
        for s in sources:
            if s not in barred:
                graph.add_edge(SUPER, s, weight=0.0, link=None)
    missing = [t for t in terminals if t not in graph]
    if missing:
        return {}, {**record, "seconds": round(time.monotonic() - began, 3),
                    "why": f"{missing[0]!r} must be joined and no link that may be built reaches it"}
    piece = nx.node_connected_component(graph, next(iter(terminals)))
    if not terminals <= piece:
        return {}, {**record, "seconds": round(time.monotonic() - began, 3),
                    "why": "the places that must be joined are not all in one piece of the links"}
    sub = steiner_tree(graph.subgraph(piece), sorted(terminals, key=str), weight="weight")
    tree = {data["link"] for _, _, data in sub.edges(data=True) if data.get("link") is not None}
    used = {p for p in sub.nodes if p != SUPER} | set(must)
    built = tree | {l for l in f_in if all(e in used for e in meta["ends"].get(l, ("", "")))}
    hint = {k: (1 if link in built else 0) for link, k in meta["build"].items()}
    hint.update({k: (1 if p in used else 0) for p, k in meta["use"].items()})
    # Flow from the tree's own roots: the sources in it, or one used place.
    sub_meta = dict(meta, places=sorted(used, key=str),
                    sources=({s for s in sources if s in used} if sources is not None else None))
    if sub_meta["root"] is not None:
        sub_meta["root"] = {p: k for p, k in meta["root"].items() if p in used}
    flows = _flows(sub_meta, tree)
    hint.update({k: 0 for k in meta["flow"].values()})
    if meta["root"] is not None:
        hint.update({k: 0 for k in meta["root"].values()})
    hint.update(flows)
    if meta.get("capacity"):
        record["overloaded"] = _overloaded(meta, hint)
    record.update(how="Steiner tree (NetworkX approximation)", terminals=len(must), used_places=len(used),
                  built=len(built))
    return hint, {**record, "seconds": round(time.monotonic() - began, 3)}
