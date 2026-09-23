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
"""

from __future__ import annotations

from dataclasses import dataclass, replace

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
