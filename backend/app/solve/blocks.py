"""Separable blocks: the parts of a model that share nothing.

Two decisions are linked when a rule reads both, a product multiplies
them, a rule is switched by one and reads the other, an interval ties its
start, end and presence, a scheduling rule holds several intervals, or a
curve or a function ties its argument to the variable standing for it. The
components of that graph are the model's blocks: a rule belongs to the one
its decisions are in, and the goal is a sum over them. With more than one,
the model is several smaller models, and the best answer to it is the best
answer to each, put together.

Blocks are found on the compiled model, not the IR: one `forall` rule is
one rule in the document but many rows here, and rows are where
independence shows (one team's rota and another's).

**When a split is refused, by name.** A lexicographic goal (its terms are
solved in turn across the whole model); soft rules (their penalties are
settled against the whole goal); symmetry-ordering rows (a class of
interchangeable entities may span blocks); a trade-off front and a robust
counterpart (they rewrite the model first). Target roadmap Phase 14.

**Near-separable models** (`structure`, queue R4): a model that is one block
may be many blocks tied together by a few rules -- one nurse's week per
nurse, joined only by each shift's cover; one site's shipments per site,
joined only by each customer's demand. For every set the decisions range
over, decisions are grouped by their member of it; a rule instance reading
two groups is a linking rule, and what is left falls into blocks. The set
whose grouping leaves the fewest linking rules, with no block holding most
of the model, is reported: "k blocks by person, m linking rules". Reported
only -- the input to a decomposition, which is per template (R12), never
automatic.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from app.solve.compile import Compiled, Linear, VarKey


@dataclass(frozen=True)
class Block:
    variables: frozenset[VarKey]
    #: Positions in `compiled.constraints`.
    rows: tuple[int, ...]


class _Links:
    def __init__(self, keys) -> None:
        self.parent = {key: key for key in keys}

    def find(self, key: VarKey) -> VarKey:
        root = key
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[key] != root:
            self.parent[key], key = root, self.parent[key]
        return root

    def join(self, keys) -> None:
        keys = list(keys)
        for other in keys[1:]:
            a, b = self.find(keys[0]), self.find(other)
            if a != b:
                self.parent[b] = a


def _row_keys(compiled: Compiled, i: int) -> list[VarKey]:
    c = compiled.constraints[i]
    keys = [*c.left.coeffs, *c.right.coeffs, *(k for pair in c.quadratic for k in pair)]
    if c.when is not None:
        keys.append(c.when[0])
    if c.schedule is not None:
        for interval, _ in c.schedule.members:
            spec = compiled.intervals[interval]
            keys += [spec.start, spec.end, *([spec.presence] if spec.presence else [])]
    return keys


def blocks(compiled: Compiled) -> list[Block]:
    """The model's components, largest first; a row with no decision in it
    (one that holds or fails whatever is decided) goes with the first."""
    links = _Links(compiled.variables)
    for i in range(len(compiled.constraints)):
        links.join(_row_keys(compiled, i))
    for a, b in compiled.objective_quadratic:
        links.join([a, b])
    for spec in compiled.intervals.values():
        links.join([spec.start, spec.end, *([spec.presence] if spec.presence else [])])
    for curve in compiled.pwl:
        links.join([curve.x, curve.y])
    for function in compiled.functions:
        links.join([function.y, *function.argument.coeffs])

    members: dict[VarKey, set[VarKey]] = {}
    for key in compiled.variables:
        members.setdefault(links.find(key), set()).add(key)
    rows: dict[VarKey, list[int]] = {root: [] for root in members}
    constant_rows = []
    for i in range(len(compiled.constraints)):
        keys = _row_keys(compiled, i)
        if keys:
            rows[links.find(keys[0])].append(i)
        else:
            constant_rows.append(i)
    ordered = sorted(members, key=lambda root: (-len(members[root]), sorted(members[root])[0]))
    found = [Block(frozenset(members[root]), tuple(rows[root])) for root in ordered]
    if constant_rows and found:
        found[0] = Block(found[0].variables, tuple(sorted([*found[0].rows, *constant_rows])))
    return found


def refusal(compiled: Compiled, *, symmetry: bool = False, pareto: bool = False, robust: bool = False) -> str | None:
    """Why this model may not be solved block by block, or None."""
    if compiled.objective_mode == "lex":
        return "a lexicographic goal is solved one term at a time across the whole model"
    if compiled.penalty_of or compiled.violations:
        return "soft rules' penalties are settled against the whole goal"
    if symmetry and compiled.symmetry:
        return "symmetry-ordering rows may tie entities in different blocks together"
    if pareto:
        return "a trade-off front is solved point by point over the whole model"
    if robust:
        return "a robust counterpart rewrites the model before it is solved"
    return None


def split(compiled: Compiled, parts: list[Block]) -> list[Compiled]:
    """Each block as a model of its own. The goal's constant goes with the
    first, so the pieces' goals add up to the model's."""
    pieces = []
    for n, block in enumerate(parts):
        keep = block.variables
        objective = Linear(
            coeffs={k: c for k, c in compiled.objective.coeffs.items() if k in keep},
            const=compiled.objective.const if n == 0 else Linear().const,
        )
        pieces.append(
            replace(
                compiled,
                variables={k: v for k, v in compiled.variables.items() if k in keep},
                constraints=[compiled.constraints[i] for i in block.rows],
                objective=objective,
                objective_quadratic={p: c for p, c in compiled.objective_quadratic.items() if p[0] in keep},
                objective_terms=[
                    Linear(coeffs={k: c for k, c in term.coeffs.items() if k in keep},
                           const=term.const if n == 0 else Linear().const)
                    for term in compiled.objective_terms
                ],
                empty_ranges=[],
                pwl=[c for c in compiled.pwl if c.x in keep],
                functions=[f for f in compiled.functions if f.y in keep],
                intervals={k: s for k, s in compiled.intervals.items() if s.start in keep},
                symmetry=[],
            )
        )
    return pieces


# -- solved: each block on its own, then put together (14b) ------------------------------------------

#: At most this many blocks' solves at once. Each is a child process with a
#: whole solve's memory ceiling (`app.solve.sandbox`): the ceiling is on
#: address space, which a solver reserves far beyond what it uses, so a
#: share of it fails a block that needs little (the bench found this -- a
#: quarter of 4096 MB ran HiGHS out). The cap on how many run at once is
#: what bounds the footprint. Blocks beyond it are packed into groups.
MAX_PARALLEL = 4


def worth_splitting(parts: list[Block]) -> bool:
    """At least two blocks hold rules. A decision no rule reads is a block of
    its own, but splitting it off buys nothing and costs the progress curve
    and a child process."""
    return sum(1 for b in parts if b.rows) >= 2


def grouped(parts: list[Block], most: int) -> list[Block]:
    """The blocks packed into at most `most` groups, largest first into the
    lightest group -- a group of blocks is still a model of its own."""
    count = max(1, min(most, len(parts)))
    bins: list[tuple[set, list[int]]] = [(set(), []) for _ in range(count)]
    for block in sorted(parts, key=lambda b: -len(b.variables)):
        lightest = min(bins, key=lambda b: len(b[0]))
        lightest[0].update(block.variables)
        lightest[1].extend(block.rows)
    return [Block(frozenset(keys), tuple(sorted(rows))) for keys, rows in bins if keys]


def merge(pieces: list[Compiled], results: list[Any], *, optimal_gap: float) -> Any:
    """One answer from the pieces' answers: the goal summed, the status the
    worst -- infeasible, then unbounded, then no answer at all, then an
    answer not proven best -- and the bound summed only when every piece has
    one."""
    from app.solve.result import Solution

    statuses = [r.status for r in results]
    wall = max((r.wall_seconds for r in results), default=0.0)
    solver = results[0].solver if results else ""
    for worst in ("infeasible", "unbounded"):
        if worst in statuses:
            return Solution(status=worst, optimal=False, objective=None, assignments={}, wall_seconds=wall, solver=solver)
    if any(s not in ("optimal", "feasible") for s in statuses):
        # A piece with no answer leaves the model without one.
        unanswered = next(s for s in statuses if s not in ("optimal", "feasible"))
        return Solution(status=unanswered, optimal=False, objective=None, assignments={}, wall_seconds=wall, solver=solver)

    def value(number, piece: Compiled):
        # A piece whose goal is only its constant may come back without one.
        return float(number) if number is not None else float(piece.objective.const)

    objective = sum(value(r.objective, p) for r, p in zip(results, pieces, strict=True))
    bounds = [r.best_bound for r in results]
    bound = sum(float(b) for b in bounds) if all(b is not None for b in bounds) else None
    status = "optimal" if all(s == "optimal" for s in statuses) else "feasible"
    if status == "optimal" and bound is not None:
        gap = abs(objective - bound) / max(abs(objective), 1e-9) if (objective or bound) else 0.0
        if gap > optimal_gap:
            status = "feasible"
    assignments: dict = {}
    reduced: dict | None = {}
    duals: dict | None = {}
    for r in results:
        assignments.update(r.assignments)
        reduced = None if reduced is None or r.reduced_costs is None else {**reduced, **r.reduced_costs}
        if duals is not None and r.duals is not None:
            for rule, dual in r.duals.items():
                # One number per rule: the instance whose dual is largest (`fold_duals`).
                if rule not in duals or abs(dual) > abs(duals[rule]):
                    duals[rule] = dual
        else:
            duals = None
    whole = all(isinstance(r.objective, int) or r.objective is None for r in results)
    return Solution(
        status=status,
        optimal=status == "optimal",
        objective=int(round(objective)) if whole and objective == round(objective) else objective,
        assignments=assignments,
        wall_seconds=wall,
        solver=solver,
        duals=duals,
        reduced_costs=reduced,
        best_bound=bound,
    )


def solve(compiled: Compiled, parts: list[Block], run_one, *, workers: int, optimal_gap: float,
          hint: dict | None = None) -> tuple[Any, str | None, dict[str, Any]]:
    """Solve the blocks at once and put the answers together. `run_one(piece,
    workers, hint)` solves one piece and returns `(Solution, reason)`, as
    `solve_compiled` does; each group gets its share of the threads."""
    from concurrent.futures import ThreadPoolExecutor

    groups = grouped(parts, MAX_PARALLEL)
    pieces = split(compiled, groups)
    share = max(1, workers // len(pieces))
    hints = [{k: v for k, v in (hint or {}).items() if k in piece.variables} or None for piece in pieces]
    with ThreadPoolExecutor(max_workers=len(pieces)) as pool:
        outcomes = list(pool.map(lambda args: run_one(args[0], share, args[1]), zip(pieces, hints)))
    results = [result for result, _ in outcomes]
    reason = next((r for _, r in outcomes if r is not None), None)
    record = {
        "blocks": len(parts),
        "groups": len(pieces),
        "sizes": [len(p.variables) for p in pieces],
        "statuses": [r.status for r in results],
        "seconds": [round(r.wall_seconds, 3) for r in results],
    }
    return merge(pieces, results, optimal_gap=optimal_gap), reason, record


#: A near-separable report needs linking rules to be at most this share of the rows ...
LINKING_SHARE = 0.2
#: ... and no block to hold more than this share of the decisions.
LARGEST_SHARE = 0.8


def _is_decision(key: VarKey) -> bool:
    return not key[0].startswith("__")


def _components(compiled: Compiled, skip: set[int]) -> dict[VarKey, VarKey]:
    """Each variable's component root, joining every row not in `skip` and every tie a row does not carry."""
    links = _Links(compiled.variables)
    for i in range(len(compiled.constraints)):
        if i not in skip:
            links.join(_row_keys(compiled, i))
    for a, b in compiled.objective_quadratic:
        links.join([a, b])
    for spec in compiled.intervals.values():
        links.join([spec.start, spec.end, *([spec.presence] if spec.presence else [])])
    for curve in compiled.pwl:
        links.join([curve.x, curve.y])
    for function in compiled.functions:
        links.join([function.y, *function.argument.coeffs])
    return {key: links.find(key) for key in compiled.variables}


def _sizes(compiled: Compiled, roots: dict[VarKey, VarKey]) -> list[int]:
    counts: dict[VarKey, int] = {}
    for key, root in roots.items():
        if _is_decision(key):
            counts[root] = counts.get(root, 0) + 1
    return sorted(counts.values(), reverse=True)


def structure(compiled: Compiled) -> dict[str, Any]:
    """How the model splits: `{"blocks", "linking_rules", "linking", "by", "largest_share"}` --
    exact blocks (`linking_rules` 0) when it is separable, else the near-separable grouping with the
    fewest linking rule instances, else one block. `linking` names the rules (by id) that tie it."""
    decisions = sum(1 for key in compiled.variables if _is_decision(key))
    whole = _sizes(compiled, _components(compiled, set()))
    if len(whole) > 1 or decisions == 0:
        return {"blocks": max(1, len(whole)), "linking_rules": 0, "linking": [], "by": None,
                "largest_share": round(whole[0] / decisions, 3) if whole else 1.0}
    rows = len(compiled.constraints)
    sets = sorted({name for index in compiled.var_index_sets.values() for name in index})
    best: dict[str, Any] | None = None
    for by in sets:
        def group(key: VarKey, by=by):
            index = compiled.var_index_sets.get(key[0], [])
            return key[1][index.index(by)] if by in index and len(key[1]) > index.index(by) else None

        linking = set()
        for i in range(rows):
            groups = {g for g in (group(k) for k in _row_keys(compiled, i) if _is_decision(k)) if g is not None}
            if len(groups) > 1:
                linking.add(i)
        if not linking or len(linking) > LINKING_SHARE * rows:
            continue
        sizes = _sizes(compiled, _components(compiled, linking))
        if len(sizes) < 2 or sizes[0] > LARGEST_SHARE * decisions:
            continue
        found = {"blocks": len(sizes), "linking_rules": len(linking),
                 "linking": sorted({compiled.constraints[i].id for i in linking}), "by": by,
                 "largest_share": round(sizes[0] / decisions, 3)}
        if best is None or (found["linking_rules"], -found["blocks"]) < (best["linking_rules"], -best["blocks"]):
            best = found
    return best or {"blocks": 1, "linking_rules": 0, "linking": [], "by": None, "largest_share": 1.0}


def said(found: dict[str, Any]) -> str | None:
    """The structure in a planner's words, or None for a model that is one block."""
    if found["blocks"] < 2:
        return None
    if not found["linking_rules"]:
        return f"it falls into {found['blocks']} independent parts, solved separately when that is on"
    rules = ", ".join(found["linking"])
    return (f"it is {found['blocks']} parts, one per {found['by']}, tied together only by "
            f"{found['linking_rules']} instance{'s' if found['linking_rules'] != 1 else ''} of {rules}")
