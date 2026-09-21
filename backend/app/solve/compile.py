"""Compile an IR and a frozen dataset into a flat linear model.

This is the half of solving that has nothing to do with any solver: it takes
the document `docs/contracts/problem-ir.md` defines and the document
`snapshot_dataset()` freezes, and produces variables and linear constraints
with every index resolved. `cpsat.py` then hands that to a solver.

Keeping them apart matters for a reason the roadmap gives: the platform is
meant to pick a technique per model. A compiler that emitted CP-SAT objects
directly would have to be rewritten for the second backend.

**What it assumes.** That the IR is valid — `app.ir.validate` has already
judged arity, binding, linearity and types, and this module does not repeat
those checks. It raises `Unsupported` for the things the contract admits but
this compiler does not yet do, so the gap is always a message rather than a
wrong answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from itertools import product
from typing import Any, Iterable

# A variable is identified by its name and the tuple of entity keys it is
# subscripted by: ("assign", ("ahmed", "mon", "morning")).
VarKey = tuple[str, tuple[str, ...]]

# The name violation variables are minted under. Not a legal IR variable name
# (the contract requires `^[a-z][a-z0-9_]*$`), so it cannot collide with one.
_VIOLATION = "__violation"
_VIOLATION_CEILING = 1_000_000


class Unsupported(Exception):
    """The IR is valid but this compiler cannot express it yet."""


def number(value: Any) -> Decimal:
    """Every quantity in a compiled model, as an exact decimal.

    `Decimal(str(x))` rather than `Decimal(x)`: a float built from `0.1` is
    not one tenth, and `Decimal(0.1)` faithfully preserves the error to fifty
    digits. Going through its shortest round-tripping repr recovers the number
    that was typed, which is what migration 0015 bounded the schema's
    precision to guarantee.
    """
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


@dataclass
class Linear:
    """`sum(coeff * var) + const`.

    Coefficients are decimals rather than ints from migration 0015 onwards.
    That is what lets a model be continuous at all -- and CP-SAT is not
    weakened by it, because a model whose numbers are fractional no longer
    fits CP-SAT's declared capabilities and is routed elsewhere with the
    reason recorded.
    """

    coeffs: dict[VarKey, Decimal] = field(default_factory=dict)
    const: Decimal = field(default_factory=lambda: Decimal(0))

    def add(self, other: "Linear", factor: Decimal | int = 1) -> "Linear":
        for key, coeff in other.coeffs.items():
            self.coeffs[key] = self.coeffs.get(key, Decimal(0)) + coeff * factor
            if self.coeffs[key] == 0:
                del self.coeffs[key]
        self.const += other.const * factor
        return self

    def scaled(self, factor: Decimal | int) -> "Linear":
        return Linear({k: v * factor for k, v in self.coeffs.items()}, self.const * factor)

    @property
    def is_constant(self) -> bool:
        return not self.coeffs


@dataclass
class Constraint:
    """One instance of a constraint: the `forall` has already been expanded,
    so `c_cover_demand` over 7 days and 3 shifts is 21 of these. `index`
    records which instance this is, because a refusal or an unsatisfied
    constraint has to name the day and shift, not just the id."""

    id: str
    index: dict[str, str]
    left: Linear
    relation: str
    right: Linear


@dataclass
class Variable:
    key: VarKey
    domain: str
    lower: Decimal
    upper: Decimal

    @property
    def is_integral(self) -> bool:
        return self.domain in ("binary", "integer")


@dataclass
class Compiled:
    variables: dict[VarKey, Variable]
    constraints: list[Constraint]
    objective: Linear
    sense: str
    # Kept for the result: solutions are reported in domain terms.
    var_index_sets: dict[str, list[str]]
    # constraint id -> the violation variables minted for its instances, so a
    # result can say *which* instance was broken and by how much, not merely
    # that a penalty was paid.
    violations: dict[str, list[VarKey]] = field(default_factory=dict)
    # constraint id -> what one unit of violation costs the objective, so a
    # result can report `penalty_paid` rather than only "it was broken".
    penalty_of: dict[str, int] = field(default_factory=dict)

    @property
    def is_integral(self) -> bool:
        """True when every variable and every coefficient is a whole number.

        Two things read this. A backend uses it to decide whether an answer
        is reported as `2` or `2.0` -- an integer model's answer should not
        acquire a decimal point because the arithmetic now runs in `Decimal`.
        And `classify` uses the same question of the model to decide whether
        CP-SAT may be offered it at all.
        """
        if any(not v.is_integral for v in self.variables.values()):
            return False
        numbers = [self.objective.const, *self.objective.coeffs.values()]
        for c in self.constraints:
            numbers += [c.left.const, c.right.const, *c.left.coeffs.values()]
            numbers += list(c.right.coeffs.values())
        return all(n == n.to_integral_value() for n in numbers)


def compile_model(ir: dict[str, Any], data: dict[str, Any]) -> Compiled:
    return _Compiler(ir, data).run()


class _Compiler:
    def __init__(self, ir: dict[str, Any], data: dict[str, Any]) -> None:
        self.ir = ir
        self.sets: dict[str, list[dict[str, Any]]] = data.get("sets", {})
        self.params_raw: dict[str, list[dict[str, Any]]] = data.get("parameters", {})
        self.defaults: dict[str, int] = data.get("parameter_defaults", {})
        #: The frozen edges, per declared relationship type (migrations 0011
        #: and 0016). Read from the snapshot and never from the live rows: a
        #: run that consulted the database for its edges would answer a
        #: different question each time the org chart changed, which is the
        #: reproducibility guarantee the whole RUN half is built on.
        self.edges: dict[str, list[dict[str, Any]]] = data.get("relationships", {})
        self._reach: dict[tuple[str, str, str, str], set[str]] = {}
        self.variables: dict[VarKey, Variable] = {}
        self.constraints: list[Constraint] = []
        self._params: dict[str, dict[tuple[str, ...], int]] = {}
        self.violations: dict[str, list[VarKey]] = {}
        self.penalty_of: dict[str, int] = {}
        self._penalties: list[tuple[VarKey, int]] = []

    # -- setup ------------------------------------------------------------

    def run(self) -> Compiled:
        self._check_edges_were_frozen()
        self._index_parameters()
        self._declare_variables()
        for spec in self.ir.get("constraints", []):
            self._expand_constraint(spec)
        objective, sense = self._objective()
        return Compiled(
            variables=self.variables,
            constraints=self.constraints,
            objective=objective,
            sense=sense,
            var_index_sets={n: v["index"] for n, v in self.ir.get("variables", {}).items()},
            violations=self.violations,
            penalty_of=self.penalty_of,
        )

    def _check_edges_were_frozen(self) -> None:
        """A model that declares a relationship must be solved against a
        dataset that carries it.

        Since migration 0016 the snapshot follows the declaration, so this
        can only fire for a dataset frozen before it -- where the two were
        not yet related. Saying so beats silently finding nothing reachable
        and reporting an answer to a constraint that never ran.
        """
        missing = [name for name in self.ir.get("relationships", []) if name not in self.edges]
        if missing:
            raise Unsupported(
                f"the model declares the relationship {missing[0]!r} and the frozen dataset "
                "carries no edges of that type; it was snapshotted before traversal existed. "
                "Re-run to take a fresh snapshot."
            )

    def _index_parameters(self) -> None:
        """A parameter arrives as rows keyed by set name (`{"day": "mon",
        "shift": "morning", "value": 3}`); solving wants a lookup by the
        ordered index tuple. An absent cell means the default (Ruling 28) --
        which is why `parameter_defaults` travels with the dataset."""
        for name, spec in self.ir.get("parameters", {}).items():
            order = spec["index"]
            table: dict[tuple[str, ...], Decimal] = {}
            for row in self.params_raw.get(name, []):
                table[tuple(row[set_name] for set_name in order)] = number(row["value"])
            self._params[name] = table

    def _declare_variables(self) -> None:
        for name, spec in self.ir.get("variables", {}).items():
            domain = spec.get("domain", "binary")
            if domain == "binary":
                lower, upper = Decimal(0), Decimal(1)
            elif domain in ("integer", "continuous"):
                # The default ceiling is a guard, not a modelling choice: an
                # unbounded variable makes a model that looks feasible and
                # answers with an arbitrary number. A model that needs more
                # says so.
                lower = number(spec.get("lower", 0))
                upper = number(spec.get("upper", 1_000_000))
            else:  # pragma: no cover -- the validator pins the vocabulary
                raise Unsupported(f"variable domain {domain!r} is not solvable here")
            for combo in self._members(spec["index"]):
                key: VarKey = (name, combo)
                self.variables[key] = Variable(key, domain, lower, upper)

    def _all_integral_so_far(self) -> bool:
        """Whether every variable *declared by the model* is integral.

        Declared, not compiled: the violation variables being minted here are
        excluded by construction, since they are the thing being decided.
        """
        return all(
            v.is_integral for key, v in self.variables.items() if key[0] != _VIOLATION
        )

    def _members(self, set_names: Iterable[str]) -> list[tuple[str, ...]]:
        pools = [[row["id"] for row in self.sets.get(s, [])] for s in set_names]
        return [tuple(c) for c in product(*pools)] if all(pools) else []

    # -- constraints ------------------------------------------------------

    def _expand_constraint(self, spec: dict[str, Any]) -> None:
        """One `Constraint` per instance of the `forall`.

        A **soft** constraint is relaxed rather than dropped: each instance
        gets its own violation variable, the relation is loosened by it, and
        the objective pays for it. Dropping it instead would return a roster
        that looks optimal and quietly breaks the rule; ignoring the penalty
        would make every soft constraint free.
        """
        if "left" not in spec or "right" not in spec:
            # A model version published before the IR contract existed: its
            # constraints carry an id and a prose note and nothing to solve.
            # `model_version` is immutable, so these rows are permanent and a
            # crash here would be indistinguishable from a compiler bug.
            raise Unsupported(
                f"constraint {spec['id']!r} carries no expression, so there is nothing "
                "to solve; it predates the IR contract. Publish a new version."
            )
        soft = spec.get("severity") == "soft"
        penalty = int(spec.get("penalty", 1)) if soft else 0
        if soft and spec["relation"] in ("<", ">"):  # pragma: no cover
            raise Unsupported(
                f"constraint {spec['id']!r} is soft with a strict relation; the "
                "amount by which it is broken is not well defined"
            )

        for env in self._bindings(spec.get("forall", [])):
            left = self._term(spec["left"], env)
            right = self._term(spec["right"], env)
            index = dict(env_keys(env))

            if soft:
                key: VarKey = (_VIOLATION, (spec["id"], *(index[k] for k in sorted(index))))
                # A violation is measured in the model's own numbers. In a
                # continuous model a rule can be short by half a unit, and an
                # integer violation variable would force it up to one -- the
                # answer would report a breach that did not happen and charge
                # a penalty nobody incurred.
                self.variables[key] = Variable(
                    key,
                    "integer" if self._all_integral_so_far() else "continuous",
                    Decimal(0),
                    Decimal(_VIOLATION_CEILING),
                )
                self.violations.setdefault(spec["id"], []).append(key)
                self.penalty_of[spec["id"]] = penalty
                self._penalties.append((key, penalty))
                slack = Linear(coeffs={key: Decimal(1)})
                # `>=` is helped by adding slack to the left, `<=` by taking
                # it away; `=` needs both directions, so it becomes a pair.
                if spec["relation"] == ">=":
                    left = Linear(dict(left.coeffs), left.const).add(slack)
                elif spec["relation"] == "<=":
                    left = Linear(dict(left.coeffs), left.const).add(slack, factor=-1)
                else:
                    self.constraints.append(
                        Constraint(
                            spec["id"],
                            index,
                            Linear(dict(left.coeffs), left.const).add(slack),
                            ">=",
                            right,
                        )
                    )
                    left = Linear(dict(left.coeffs), left.const).add(slack, factor=-1)
                    self.constraints.append(Constraint(spec["id"], index, left, "<=", right))
                    continue

            self.constraints.append(
                Constraint(spec["id"], index, left, spec["relation"], right)
            )

    def _bindings(
        self,
        bindings: list[dict[str, Any]],
        outer: dict[str, tuple[str, dict]] | None = None,
    ) -> list[dict[str, tuple[str, dict]]]:
        """Every combination the bindings range over, as environments mapping
        an index name to the row it is bound to. A `where` filter narrows a
        binding's own set before the product, so a filtered binding shrinks
        the instance count rather than producing instances that are then
        discarded.

        `outer` is what an enclosing `forall` bound, and the returned
        environments extend it. A sum used to be expanded in isolation and
        merged afterwards, which was equivalent while a binding could only
        read its own set; a `via` reads the index it walks from, so the
        enclosing scope has to be present while the product is built.
        """
        envs: list[dict[str, tuple[str, dict]]] = [dict(outer) if outer else {}]
        for binding in bindings:
            set_name = binding["set"]
            rows = [r for r in self.sets.get(set_name, []) if _passes(r, binding.get("where", []))]
            if "via" not in binding:
                envs = [
                    dict(env, **{binding["index"]: (set_name, row)}) for env in envs for row in rows
                ]
                continue
            # A traversal narrows the pool per environment rather than
            # once, because what it reaches depends on where it starts.
            # That is exactly why `via` is a binding and not a filter: a
            # `where` is a property of a row, and reachability is a
            # property of a row *and* the anchor.
            via = binding["via"]
            anchor_end = "from" if "from" in via else "to"
            grown: list[dict[str, tuple[str, dict]]] = []
            for env in envs:
                reachable = self._reachable(via, anchor_end, env[via[anchor_end]][1]["id"])
                grown.extend(
                    dict(env, **{binding["index"]: (set_name, row)})
                    for row in rows
                    if row["id"] in reachable
                )
            envs = grown
        return envs

    def _reachable(self, via: dict[str, Any], anchor_end: str, anchor: str) -> set[str]:
        """The keys a walk from `anchor` lands on, over the frozen edges.

        `from` in the document means the anchor sits at the from end, so the
        walk reads each edge in that direction and returns the other end.
        """
        rel = via["rel"]
        depth = via.get("depth", "one")
        far_end = "to" if anchor_end == "from" else "from"
        cache_key = (rel, anchor_end, depth, anchor)
        cached = self._reach.get(cache_key)
        if cached is not None:
            return cached

        steps: dict[str, list[str]] = {}
        for edge in self.edges.get(rel, []):
            steps.setdefault(edge[anchor_end], []).append(edge[far_end])

        if depth == "one":
            found = set(steps.get(anchor, ()))
        else:
            # Breadth-first with a seen set, so a relationship that happens
            # to hold a cycle terminates instead of hanging the worker.
            # `is_hierarchy` forbids one, but the contract admits any
            # self-referential type here and a dataset is not re-validated.
            found = set()
            frontier = [anchor]
            while frontier:
                nxt = []
                for key in frontier:
                    for other in steps.get(key, ()):
                        if other not in found:
                            found.add(other)
                            nxt.append(other)
                frontier = nxt
            if depth == "any_or_self":
                found.add(anchor)
        self._reach[cache_key] = found
        return found

    def _term(self, term: dict[str, Any], env: dict[str, tuple[str, dict]]) -> Linear:
        if "const" in term:
            return Linear(const=number(term["const"]))

        if "par" in term:
            name = term["par"]
            keys = tuple(env[i][1]["id"] for i in term["index"])
            table = self._params[name]
            return Linear(const=number(table.get(keys, self.defaults.get(name, 0))))

        if "attr" in term:
            of, attr_name = term["attr"]["of"], term["attr"]["name"]
            row = env[of][1]
            if attr_name not in row:
                # Absent because the attribute has no default and this entity
                # never set it. Zero would be a silent wrong answer.
                raise Unsupported(
                    f"entity {row['id']!r} carries no {attr_name!r}, so the term has no value"
                )
            return Linear(const=number(row[attr_name]))

        if "var" in term:
            keys = tuple(env[i][1]["id"] for i in term["index"])
            key: VarKey = (term["var"], keys)
            if key not in self.variables:  # pragma: no cover -- validator pins arity
                raise Unsupported(f"no variable {key}")
            return Linear(coeffs={key: Decimal(1)})

        if "sum" in term:
            total = Linear()
            for env2 in self._bindings(term.get("over", []), env):
                total.add(self._term(term["sum"], env2))
            return total

        if "add" in term:
            total = Linear()
            for part in term["add"]:
                total.add(self._term(part, env))
            return total

        if "mul" in term:
            a, b = (self._term(f, env) for f in term["mul"])
            # The validator already refused a product of two variable-bearing
            # factors, so exactly one side is constant here.
            if a.is_constant:
                return b.scaled(a.const)
            if b.is_constant:
                return a.scaled(b.const)
            raise Unsupported("a product of two variable terms is not linear")  # pragma: no cover

        raise Unsupported(f"unknown term {sorted(term)}")  # pragma: no cover

    # -- objective --------------------------------------------------------

    def _objective(self) -> tuple[Linear, str]:
        spec = self.ir.get("objective") or {}
        total = Linear()
        for term in spec.get("terms", []):
            expression = term.get("expression")
            if expression is None:
                raise Unsupported(
                    f"objective term {term.get('id')!r} carries no expression, so it "
                    "contributes nothing that can be optimised"
                )
            total.add(self._term(expression, {}), factor=number(term.get("weight", 1)))

        # Penalties push the objective the way it does not want to go: they
        # cost when minimising and subtract when maximising, so a soft
        # constraint is never free in either direction.
        sense = spec.get("sense", "minimize")
        direction = 1 if sense == "minimize" else -1
        for key, penalty in self._penalties:
            total.add(Linear(coeffs={key: Decimal(1)}), factor=number(penalty) * direction)
        return total, sense


def env_keys(env: dict[str, tuple[str, dict]]) -> list[tuple[str, str]]:
    return [(index, bound[1]["id"]) for index, bound in env.items()]


def _passes(row: dict[str, Any], filters: list[dict[str, Any]]) -> bool:
    for f in filters:
        value, wanted, op = row.get(f["attr"]), f.get("value"), f["op"]
        if op in ("=", "=="):
            ok = value == wanted
        elif op == "!=":
            ok = value != wanted
        elif op == "<":
            ok = value is not None and value < wanted
        elif op == "<=":
            ok = value is not None and value <= wanted
        elif op == ">":
            ok = value is not None and value > wanted
        elif op == ">=":
            ok = value is not None and value >= wanted
        elif op == "in":
            ok = value in (wanted or [])
        elif op == "notIn":
            ok = value not in (wanted or [])
        elif op == "null":
            ok = value is None
        elif op == "notNull":
            ok = value is not None
        else:  # pragma: no cover -- contract.json's filterOperators
            raise Unsupported(f"filter operator {op!r}")
        if not ok:
            return False
    return True
