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

import math
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
#: The auxiliary variables `pwl` terms stand for. Like violations, a name
#: no IR variable can have (`^[a-z]...`).
_PWL = "__pwl"
#: The auxiliary variables `fn` terms stand for, one per function and argument.
_FN = "__fn"
_VIOLATION_CEILING = 1_000_000
# The upper bound of an integer or continuous variable the model left
# unbounded. Every solver here needs a finite one (CP-SAT always, the rest to
# keep an unbounded model from answering with an arbitrary number), so the
# ceiling is kept and marked (`Variable.default_upper`) instead of dropped.
DEFAULT_UPPER = 1_000_000
_MAX_EMPTY_RANGES = 50


class Unsupported(Exception):
    """The IR is valid but this compiler cannot express it yet."""


def parameter_index(row: dict[str, Any], order: list[str]) -> tuple[str, ...]:
    """The entity keys of one frozen parameter cell, in index order.

    New snapshots of a self-indexed parameter (`distance[location,
    location]`) key the two ends ``"0"`` and ``"1"``: type name would
    collapse them. Older snapshots, and every uniquely-typed parameter,
    still key by type name. Prefer positions when they are all present so
    a run frozen before 0025 and one frozen after both compile.
    """
    if all(str(i) in row for i in range(len(order))):
        return tuple(str(row[str(i)]) for i in range(len(order)))
    return tuple(row[set_name] for set_name in order)


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

    def copy(self) -> "Linear":
        return Linear(dict(self.coeffs), self.const)

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

    def evaluated_at(
        self,
        assignments: dict[VarKey, Any],
        *,
        skip_names: set[str] | None = None,
    ) -> Decimal:
        """The number this linear form takes at an assignment.

        `skip_names` drops variables the caller does not want counted --
        violation slacks, when measuring the original rule rather than the
        compiled one that already absorbed them.
        """
        skip = skip_names or set()
        total = self.const
        for key, coeff in self.coeffs.items():
            if key[0] in skip:
                continue
            total += coeff * number(assignments.get(key, 0))
        return total


@dataclass(frozen=True)
class IntervalDef:
    """One instance of an interval variable (IR version 2): `end = start +
    size`, both integer decisions, unless `presence` (a binary) is 0 -- then
    the interval does not happen and neither holds. Not a decision itself: a
    backend that holds intervals (CP-SAT) builds one from these."""

    key: VarKey
    start: VarKey
    end: VarKey
    size: int
    presence: VarKey | None = None


@dataclass(frozen=True)
class Schedule:
    """A scheduling rule instance: `no_overlap` (the members never run at
    once) or `cumulative` (the running members' demands stay within
    `capacity` at every moment). `members` pairs each interval with its
    demand (1 for `no_overlap`)."""

    kind: str
    members: tuple[tuple[VarKey, int], ...]
    capacity: int | None = None


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
    # The quadratic part of `left - right`: coefficient per pair of variables,
    # as `Compiled.objective_quadratic`. It belongs to the left side, so the
    # rule reads `left + quadratic  relation  right`. Empty for a linear rule;
    # only a backend that provides `quadratic-constraints` is offered one
    # that is not.
    quadratic: dict[tuple[VarKey, VarKey], Decimal] = field(default_factory=dict)
    # The switch on a conditional rule (IR version 2, `when`): the rule holds
    # while this binary variable has this value, and says nothing otherwise.
    # None for an unconditional rule -- every rule before version 2.
    when: tuple[VarKey, int] | None = None
    # A scheduling rule instance (version 2) in place of an expression: the
    # left and right are empty and say nothing. Only a backend that provides
    # `scheduling` is offered one.
    schedule: Schedule | None = None

    def is_active(self, assignments: dict[VarKey, Any]) -> bool:
        """Whether the rule binds at an assignment: always, unless its switch
        is set the other way."""
        if self.when is None:
            return True
        key, value = self.when
        return int(round(float(assignments.get(key, 0)))) == value


@dataclass(frozen=True)
class PwlDef:
    """`y = f(x)`, f the piecewise-linear curve through `points` (IR version 2,
    a `pwl` term). `y` is an auxiliary variable the term stands for; how a
    backend holds the equation is its own business -- CP-SAT a table, SCIP
    SOS2, HiGHS and the MILP wrapper the incremental formulation or, for a
    convex curve the objective only pushes down, an epigraph
    (`app.solve.reformulate`). x is kept within the first and last point."""

    x: VarKey
    y: VarKey
    points: tuple[tuple[Decimal, Decimal], ...]

    def value_at(self, x: Decimal) -> Decimal:
        pts = self.points
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            if x0 <= x <= x1:
                return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
        raise ValueError(f"{x} is outside the curve's {pts[0][0]}..{pts[-1][0]}")

    @property
    def slopes(self) -> list[Decimal]:
        pts = self.points
        return [(y1 - y0) / (x1 - x0) for (x0, y0), (x1, y1) in zip(pts, pts[1:])]


#: The catalogue's functions (`contract.json` `functions`), as numbers.
_FUNCTIONS = {
    "exp": math.exp,
    "log": math.log,
    "sqrt": math.sqrt,
    "abs": abs,
    "sin": math.sin,
    "cos": math.cos,
}
_INFINITY = Decimal("Infinity")


def function_value(name: str, x: float) -> float:
    """f(x) for a catalogue function; inf where exp overflows a float."""
    try:
        return float(_FUNCTIONS[name](x))
    except OverflowError:
        return math.inf


def function_range(name: str, low: float, high: float) -> tuple[float, float]:
    """The least and greatest f takes over [low, high], which the argument's
    bounds imply -- given to the stand-in as its own bounds. `low` is inside
    the function's domain (the compiler has checked)."""
    if name in ("exp", "log", "sqrt"):  # increasing
        return function_value(name, low), (math.inf if high == math.inf else function_value(name, high))
    if name == "abs":
        if low >= 0:
            return low, high
        if high <= 0:
            return -high, -low
        return 0.0, max(-low, high)
    return -1.0, 1.0  # sin, cos


@dataclass(frozen=True)
class FnDef:
    """`y = f(argument)`, f from the contract's catalogue (IR version 2, a
    `fn` term). `y` is an auxiliary variable the term stands for, bounded by
    what f takes over the argument's range; only a backend that holds the
    equation itself (SCIP) is offered one."""

    name: str
    argument: "Linear"
    y: VarKey

    def value_at(self, assignments: dict[VarKey, Any]) -> float:
        x = float(self.argument.const) + sum(
            float(coeff) * float(assignments.get(key, 0)) for key, coeff in self.argument.coeffs.items()
        )
        return function_value(self.name, x)


@dataclass
class Variable:
    key: VarKey
    domain: str
    lower: Decimal
    upper: Decimal
    # True when the model set no upper bound and the compiler's guard
    # (`DEFAULT_UPPER`) stands in. An answer resting on such a ceiling is not
    # an optimum of the model; it is a sign the goal can improve without limit.
    default_upper: bool = False

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
    # `weighted` (default) is a scalarised sum; `lex` is term order, first
    # term most important. Omit `mode` on the IR and this is `weighted`.
    objective_mode: str = "weighted"
    objective_term_ids: list[str] = field(default_factory=list)
    objective_terms: list[Linear] = field(default_factory=list)
    # Soft-constraint penalties, already pointed the way the sense wants.
    # Weighted mode folds them into `objective`; lex solves them last.
    penalty_objective: Linear = field(default_factory=Linear)
    # The quadratic part of a weighted objective: coefficient per PAIR of
    # variables, the pair in sorted order so x*y and y*x are one entry, and
    # x*x keyed (x, x). Empty for every linear model, which is every model
    # but a quadratic program. The contract keeps rules linear and allows
    # this only in a weighted objective, so nothing else carries one.
    objective_quadratic: dict[tuple[VarKey, VarKey], Decimal] = field(default_factory=dict)
    # constraint id -> the violation variables minted for its instances, so a
    # result can say *which* instance was broken and by how much, not merely
    # that a penalty was paid.
    violations: dict[str, list[VarKey]] = field(default_factory=dict)
    # constraint id -> what one unit of violation costs the objective, so a
    # result can report `penalty_paid` rather than only "it was broken".
    penalty_of: dict[str, int] = field(default_factory=dict)
    # Bindings whose `where`/`via` matched nobody. The constraint is then
    # vacuously true (a forall over the empty set) or a sum that counted as
    # zero -- both look like a solved model and are usually a data mistake.
    empty_ranges: list[dict[str, Any]] = field(default_factory=list)
    # The piecewise-linear curves the model's `pwl` terms stand for, each an
    # auxiliary `y` defined by its `x` (IR version 2).
    pwl: list[PwlDef] = field(default_factory=list)
    # The catalogue functions the model's `fn` terms stand for, each an
    # auxiliary `y` equal to f of its linear argument (IR version 2).
    functions: list[FnDef] = field(default_factory=list)
    # Every instance of every interval variable, by its key (version 2).
    intervals: dict[VarKey, IntervalDef] = field(default_factory=dict)
    # Classes of interchangeable entities, per set (`app.solve.symmetry`):
    # what a backend without symmetry detection may be told to order.
    symmetry: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)

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
        numbers = [
            self.objective.const,
            *self.objective.coeffs.values(),
            *self.objective_quadratic.values(),
        ]
        for c in self.constraints:
            numbers += [c.left.const, c.right.const, *c.left.coeffs.values()]
            numbers += [*c.right.coeffs.values(), *c.quadratic.values()]
        return all(n == n.to_integral_value() for n in numbers)


def slack_of(constraint: Constraint, assignments: dict[VarKey, Any]) -> Decimal:
    """How much room this instance has left at the recorded assignment.

    Measured on the original rule, ignoring violation variables: a soft
    constraint that paid a penalty has negative slack (it is short), and a
    hard one that sits exactly on its bound has zero. Duals would say the
    same for GLOP and nothing for CP-SAT; the residual is what every
    backend already knows.
    """
    left = constraint.left.evaluated_at(assignments, skip_names={_VIOLATION})
    left += quadratic_at(constraint.quadratic, assignments)
    right = constraint.right.evaluated_at(assignments, skip_names={_VIOLATION})
    if constraint.relation in (">=", ">"):
        return left - right
    if constraint.relation in ("<=", "<"):
        return right - left
    # Equality is tight when it holds; a residual is a breach.
    residual = left - right
    return residual if residual == 0 else -abs(residual)


def slack_by_constraint(
    compiled: Compiled, assignments: dict[VarKey, Any]
) -> dict[str, Decimal]:
    """The tightest instance of each constraint -- the rule with no room left."""
    tightest: dict[str, Decimal] = {}
    for constraint in compiled.constraints:
        # A conditional rule switched off has no room to measure: it does not
        # bind, however far its sides are apart.
        if not constraint.is_active(assignments) or constraint.schedule is not None:
            # A scheduling rule has no one number of room left.
            continue
        value = slack_of(constraint, assignments)
        current = tightest.get(constraint.id)
        if current is None or value < current:
            tightest[constraint.id] = value
    return tightest


def compile_model(ir: dict[str, Any], data: dict[str, Any]) -> Compiled:
    return _Compiler(ir, data).run()


class _Compiler:
    def __init__(self, ir: dict[str, Any], data: dict[str, Any]) -> None:
        self._pwls: list[PwlDef] = []
        self._fns: list[FnDef] = []
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
        self.empty_ranges: list[dict[str, Any]] = []
        self._empty_seen: set[tuple[Any, ...]] = set()
        self._current_id: str | None = None

    # -- setup ------------------------------------------------------------

    def run(self) -> Compiled:
        self._check_edges_were_frozen()
        self._index_parameters()
        self._declare_variables()
        intervals = self._declare_intervals()
        for spec in self.ir.get("constraints", []):
            self._expand_constraint(spec)
        objective, sense, mode, term_ids, terms, penalties, quadratic = self._objective()
        return Compiled(
            variables=self.variables,
            constraints=self.constraints,
            objective=objective,
            sense=sense,
            objective_mode=mode,
            objective_term_ids=term_ids,
            objective_terms=terms,
            penalty_objective=penalties,
            objective_quadratic=quadratic,
            # An interval is not a decision with a value; its start and end are.
            var_index_sets={
                n: v["index"] for n, v in self.ir.get("variables", {}).items() if v.get("domain") != "interval"
            },
            violations=self.violations,
            penalty_of=self.penalty_of,
            empty_ranges=self.empty_ranges[:_MAX_EMPTY_RANGES],
            pwl=list(self._pwls),
            functions=list(self._fns),
            intervals=intervals,
            symmetry=self._symmetry(),
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
        "shift": "morning", "value": 3}`) or, when an index type repeats,
        by position (`{"0": "a", "1": "b", "value": 4}`). Solving wants a
        lookup by the ordered index tuple. An absent cell means the default
        (Ruling 28) -- which is why `parameter_defaults` travels with the
        dataset."""
        for name, spec in self.ir.get("parameters", {}).items():
            order = spec["index"]
            table: dict[tuple[str, ...], Decimal] = {}
            for row in self.params_raw.get(name, []):
                table[parameter_index(row, order)] = number(row["value"])
            self._params[name] = table

    def _declare_variables(self) -> None:
        for name, spec in self.ir.get("variables", {}).items():
            domain = spec.get("domain", "binary")
            if domain == "interval":
                continue  # `_declare_intervals`, once its start and end exist
            if domain == "binary":
                lower, upper = Decimal(0), Decimal(1)
            elif domain in ("integer", "continuous"):
                # The default ceiling is a guard, not a modelling choice: an
                # unbounded variable makes a model that looks feasible and
                # answers with an arbitrary number. A model that needs more
                # says so.
                lower = number(spec.get("lower", 0))
                upper = number(spec.get("upper", DEFAULT_UPPER))
            else:  # pragma: no cover -- the validator pins the vocabulary
                raise Unsupported(f"variable domain {domain!r} is not solvable here")
            defaulted = domain != "binary" and "upper" not in spec
            for combo in self._members(spec["index"]):
                key: VarKey = (name, combo)
                self.variables[key] = Variable(key, domain, lower, upper, defaulted)

    def _symmetry(self) -> list[tuple[str, tuple[str, ...]]]:
        from app.solve.symmetry import classes

        return classes(self.ir, {"sets": self.sets, "parameters": self.params_raw, "relationships": self.edges})

    def _declare_intervals(self) -> dict[VarKey, IntervalDef]:
        out: dict[VarKey, IntervalDef] = {}
        for name, spec in self.ir.get("variables", {}).items():
            if spec.get("domain") != "interval":
                continue
            size_spec = spec["size"]
            for combo in self._members(spec["index"]):
                if isinstance(size_spec, str):
                    size = self._params[size_spec].get(combo, self.defaults.get(size_spec, 0))
                else:
                    size = size_spec
                size = number(size)
                label = f"{name}[{', '.join(combo)}]" if combo else name
                if size < 0 or size != size.to_integral_value():
                    raise Unsupported(
                        f"the size of the interval {label} is {size}; an interval's size is a "
                        "non-negative whole number of time units"
                    )
                presence = spec.get("presence")
                out[(name, combo)] = IntervalDef(
                    (name, combo),
                    (spec["start"], combo),
                    (spec["end"], combo),
                    int(size),
                    (presence, combo) if presence else None,
                )
        return out

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
        kind = next((k for k in ("no_overlap", "cumulative") if k in spec), None)
        if kind is not None:
            self._expand_scheduling(spec, kind)
            return
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
        # `weight` is the contract's key (§3.4), and a soft constraint must
        # carry one. The default is for a document that predates the rule,
        # not for a valid one -- reading a key the contract does not have
        # priced every declared weight at 1 and said nothing.
        penalty = int(spec.get("weight", 1)) if soft else 0
        if soft and spec["relation"] in ("<", ">"):  # pragma: no cover
            raise Unsupported(
                f"constraint {spec['id']!r} is soft with a strict relation; the "
                "amount by which it is broken is not well defined"
            )

        forall = spec.get("forall") or []
        envs = self._bindings(forall)
        if forall and not envs:
            # Vacuous: the rule never fired. Emitting nothing is correct
            # mathematically and the wrong thing to hide from a planner --
            # "North Region has no people" looks like a solved model.
            self._note_empty(spec["id"], "forall", {})
            return
        self._current_id = spec["id"]
        for env in envs:
            when = self._when(spec.get("when"), env)
            left, square = self._poly(spec["left"], env)
            right, right_square = self._poly(spec["right"], env)
            # Both sides' products move to the left, as `Constraint.quadratic`.
            _add_quadratic(square, _scaled(right_square, -1))
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
                            dict(square),
                        )
                    )
                    left = Linear(dict(left.coeffs), left.const).add(slack, factor=-1)
                    self.constraints.append(
                        Constraint(spec["id"], index, left, "<=", right, dict(square))
                    )
                    continue

            self.constraints.append(
                Constraint(spec["id"], index, left, spec["relation"], right, square, when)
            )
        self._current_id = None

    def _expand_scheduling(self, spec: dict[str, Any], kind: str) -> None:
        """One `Constraint` carrying a `Schedule` per instance of the
        `forall`, over the intervals its `over` ranges across."""
        if spec.get("severity") == "soft":
            # Only a scenario can get here: the validator refuses a soft one.
            raise Unsupported(
                f"the {kind} rule {spec['id']!r} was softened by the scenario; a scheduling rule "
                "has no amount by which it is broken, so it can only be kept or disabled"
            )
        body = spec[kind]
        forall = spec.get("forall") or []
        envs = self._bindings(forall)
        if forall and not envs:
            self._note_empty(spec["id"], "forall", {})
            return
        interval = body["interval"]
        for env in envs:
            index = dict(env_keys(env))
            members = []
            inner = self._bindings(body["over"], env)
            if not inner:
                self._note_empty(spec["id"], "over", index)
            for env2 in inner:
                key: VarKey = (interval["var"], tuple(env2[i][1]["id"] for i in interval["index"]))
                demand = self._amount(body["demand"], env2, spec["id"], "demand") if kind == "cumulative" else 1
                members.append((key, demand))
            capacity = self._amount(body["capacity"], env, spec["id"], "capacity") if kind == "cumulative" else None
            self.constraints.append(
                Constraint(spec["id"], index, Linear(), "<=", Linear(), schedule=Schedule(kind, tuple(members), capacity))
            )

    def _amount(self, term: dict[str, Any], env, rule: str, what: str) -> int:
        value = self._term(term, env).const
        if value < 0 or value != value.to_integral_value():
            raise Unsupported(
                f"the {what} of {rule!r} comes to {value} here; a scheduling rule counts in "
                "non-negative whole numbers"
            )
        return int(value)

    def _when(self, spec: dict[str, Any] | None, env) -> tuple[VarKey, int] | None:
        """This instance's switch: the binary variable at these indices, and
        the value that turns the rule on. The validator has made sure the
        variable is binary and the rule is hard and linear."""
        if spec is None:
            return None
        keys = tuple(env[i][1]["id"] for i in spec["index"])
        key: VarKey = (spec["var"], keys)
        if key not in self.variables:  # pragma: no cover -- validator pins arity
            raise Unsupported(f"no variable {key}")
        return key, int(spec.get("is", 1))

    def _pwl(self, term: dict[str, Any], env) -> VarKey:
        """The auxiliary variable a `pwl` term stands for -- one per (x, curve),
        so the same curve of the same x written twice is one variable."""
        argument = term["pwl"]
        x: VarKey = (argument["var"], tuple(env[i][1]["id"] for i in argument["index"]))
        if x not in self.variables:  # pragma: no cover -- validator pins arity
            raise Unsupported(f"no variable {x}")
        points = tuple((number(px), number(py)) for px, py in term["points"])
        for existing in self._pwls:
            if existing.x == x and existing.points == points:
                return existing.y
        y: VarKey = (_PWL, (str(len(self._pwls)),))
        spec = self.variables[x]
        ys = [py for _, py in points]
        # Whole-number y exactly when x is whole and the curve is whole at
        # every whole x it covers -- what lets CP-SAT hold it as a table.
        whole = spec.is_integral and _whole_on_integers(points)
        self.variables[y] = Variable(y, "integer" if whole else "continuous", min(ys), max(ys))
        self._pwls.append(PwlDef(x, y, points))
        return y

    def _fn(self, name: str, argument: Linear) -> Linear:
        """What a `fn` term compiles to: f's value when its argument is data,
        else the auxiliary variable standing for it -- one per (f, argument),
        so the same function of the same thing written twice is one."""
        where = f" in {self._current_id}" if self._current_id else " in the goal"
        domain = {"log": "above zero", "sqrt": "at least zero"}.get(name)
        if argument.is_constant:
            x = float(argument.const)
            if (name == "log" and x <= 0) or (name == "sqrt" and x < 0):
                raise Unsupported(f"{name}{where} is applied to {argument.const}; {name} needs its argument {domain}")
            value = function_value(name, x)
            if math.isinf(value):
                raise Unsupported(f"{name}({argument.const}){where} is too large to hold as a number")
            return Linear(const=Decimal(repr(value)))
        low, high = self._range(argument)
        if (name == "log" and low <= 0) or (name == "sqrt" and low < 0):
            raise Unsupported(
                f"{name}{where} needs its argument {domain}, but the decisions it reads let it go as low "
                f"as {_shown(low)} -- give them bounds that keep it {domain}"
            )
        for existing in self._fns:
            if existing.name == name and existing.argument == argument:
                return Linear(coeffs={existing.y: Decimal(1)})
        y: VarKey = (_FN, (str(len(self._fns)),))
        least, most = function_range(name, low, high)
        # Widened by a hair: the float bounds must never cut off the true value.
        slack = lambda v: 1e-9 * (1 + abs(v))  # noqa: E731
        self.variables[y] = Variable(
            y,
            "continuous",
            -_INFINITY if math.isinf(least) else Decimal(repr(least - slack(least))),
            _INFINITY if math.isinf(most) else Decimal(repr(most + slack(most))),
        )
        self._fns.append(FnDef(name, argument.copy(), y))
        return Linear(coeffs={y: Decimal(1)})

    def _range(self, argument: Linear) -> tuple[float, float]:
        """The least and greatest a linear argument can be, from its
        decisions' bounds (a stand-in's may be infinite)."""
        low = high = float(argument.const)
        for key, coeff in argument.coeffs.items():
            spec = self.variables[key]
            a, b = float(coeff) * float(spec.lower), float(coeff) * float(spec.upper)
            low, high = low + min(a, b), high + max(a, b)
        return low, high

    def _note_empty(self, constraint_id: str, kind: str, index: dict[str, str]) -> None:
        key = (constraint_id, kind, tuple(sorted(index.items())))
        if key in self._empty_seen:
            return
        self._empty_seen.add(key)
        self.empty_ranges.append(
            {"constraint_id": constraint_id, "kind": kind, "index": dict(index)}
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

        if "pwl" in term:
            return Linear(coeffs={self._pwl(term, env): Decimal(1)})

        if "fn" in term:
            return self._fn(term["fn"], self._term(term["of"], env))

        if "sum" in term:
            over = term.get("over") or []
            inner = self._bindings(over, env)
            if over and not inner and self._current_id:
                self._note_empty(self._current_id, "sum", dict(env_keys(env)))
            total = Linear()
            for env2 in inner:
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

    def _poly(self, term: dict[str, Any], env: dict[str, tuple[str, dict]]) -> tuple[Linear, Quadratic]:
        """A term as a polynomial of degree two at most: a linear part and a
        quadratic part. Rules and objectives are both compiled this way; the
        contract keeps them to degree two, and only a product can raise the
        degree, so every other kind defers to `_term`.
        """
        if "sum" in term:
            over = term.get("over") or []
            inner = self._bindings(over, env)
            if over and not inner and self._current_id:
                self._note_empty(self._current_id, "sum", dict(env_keys(env)))
            linear, quadratic = Linear(), {}
            for env2 in inner:
                part, square = self._poly(term["sum"], env2)
                linear.add(part)
                _add_quadratic(quadratic, square)
            return linear, quadratic

        if "add" in term:
            linear, quadratic = Linear(), {}
            for part in term["add"]:
                piece, square = self._poly(part, env)
                linear.add(piece)
                _add_quadratic(quadratic, square)
            return linear, quadratic

        if "mul" in term:
            (a, qa), (b, qb) = (self._poly(f, env) for f in term["mul"])
            # A quadratic factor times a constant stays quadratic. The
            # validator refused anything of higher degree.
            if qa or qb:
                if qa and b.is_constant:
                    return a.scaled(b.const), _scaled(qa, b.const)
                if qb and a.is_constant:
                    return b.scaled(a.const), _scaled(qb, a.const)
                raise Unsupported("a product of more than two variables is not quadratic")  # pragma: no cover
            # (sum a_i x_i + a0)(sum b_j x_j + b0): the cross terms are the
            # quadratic part, and each constant scales the other side.
            quadratic: Quadratic = {}
            for ka, ca in a.coeffs.items():
                for kb, cb in b.coeffs.items():
                    _add_quadratic(quadratic, {_pair(ka, kb): ca * cb})
            linear = Linear(const=a.const * b.const)
            linear.add(Linear(coeffs=dict(b.coeffs)), factor=a.const)
            linear.add(Linear(coeffs=dict(a.coeffs)), factor=b.const)
            return linear, quadratic

        return self._term(term, env), {}

    def _objective(
        self,
    ) -> tuple[Linear, str, str, list[str], list[Linear], Linear, Quadratic]:
        spec = self.ir.get("objective") or {}
        total = Linear()
        quadratic: Quadratic = {}
        term_ids: list[str] = []
        terms: list[Linear] = []
        for term in spec.get("terms", []):
            expression = term.get("expression")
            if expression is None:
                raise Unsupported(
                    f"objective term {term.get('id')!r} carries no expression, so it "
                    "contributes nothing that can be optimised"
                )
            linear, square = self._poly(expression, {})
            weight = number(term.get("weight", 1))
            term_ids.append(str(term.get("id")))
            terms.append(linear.copy())
            total.add(linear, factor=weight)
            _add_quadratic(quadratic, _scaled(square, weight))

        # Penalties push the objective the way it does not want to go: they
        # cost when minimising and subtract when maximising, so a soft
        # constraint is never free in either direction.
        sense = spec.get("sense", "minimize")
        mode = spec.get("mode", "weighted")
        direction = 1 if sense == "minimize" else -1
        penalties = Linear()
        for key, penalty in self._penalties:
            penalties.add(Linear(coeffs={key: Decimal(1)}), factor=number(penalty) * direction)
        total.add(penalties.copy())
        return total, sense, mode, term_ids, terms, penalties, quadratic


Quadratic = dict[tuple[VarKey, VarKey], Decimal]


def _whole_on_integers(points, limit: int = 100_000) -> bool:
    import math

    lo, hi = math.ceil(points[0][0]), math.floor(points[-1][0])
    if hi - lo > limit:
        return False
    curve = PwlDef(("", ()), ("", ()), points)
    return all(curve.value_at(Decimal(k)) == curve.value_at(Decimal(k)).to_integral_value() for k in range(lo, hi + 1))


def _shown(value: float) -> str:
    return "minus infinity" if value == -math.inf else f"{value:g}"


def _pair(a: VarKey, b: VarKey) -> tuple[VarKey, VarKey]:
    """One key per unordered pair, so x*y and y*x add up rather than being
    two terms a solver would see separately."""
    return (a, b) if a <= b else (b, a)


def quadratic_at(quadratic: Quadratic, assignments: dict[VarKey, Any]) -> Decimal:
    """The value of a quadratic part at an assignment."""
    return sum(
        (
            coeff * number(assignments.get(a, 0)) * number(assignments.get(b, 0))
            for (a, b), coeff in quadratic.items()
        ),
        Decimal(0),
    )


def _add_quadratic(into: Quadratic, more: Quadratic) -> None:
    for key, coeff in more.items():
        total = into.get(key, Decimal(0)) + coeff
        if total == 0:
            into.pop(key, None)
        else:
            into[key] = total


def _scaled(quadratic: Quadratic, factor: Decimal | int) -> Quadratic:
    return {key: coeff * factor for key, coeff in quadratic.items() if coeff * factor != 0}


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
