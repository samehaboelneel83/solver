"""The problem IR as Pydantic models -- the contract's structure, typed.

`contract.json` stays the one source (principle 3 of the roadmap): these
models restate its shape so Python code can hold a model as objects rather
than nested dicts, and `tests/test_ir_models.py` binds them to it -- every
enumerated value here is compared with the JSON, and the shared fixtures
are run through both these models and `validate.py`.

**What the models decide, and what they leave.** Everything a type can say:
which keys an object carries (`extra="forbid"`), what type each value is
(`strict`: JSON `true` is not the number 1), which words a closed
vocabulary allows, that a name is a name, that `add` has at least one
summand and `mul` exactly two factors, that a `via` anchors at one end.
Not what needs the whole document or the domain -- a set used before it is
declared, a duplicated id, linearity, the depth and size limits, weights
that depend on severity: those stay with `validate.py`, which is still the
gate every published version goes through. `tests/test_ir_models.py`
assigns every rule code in the contract to one side or the other.

**Versions.** Contract version 2 is version 1 plus the constructs Phase 10
adds; a version 1 document is a valid version 2 one as it stands, and
`upgrade_v1` only restamps it.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Optional, Union

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictFloat, StrictInt, model_validator

NAME_PATTERN = r"^[a-z][a-z0-9_]*$"
ACCEPTED_VERSIONS = (1, 2)
#: How many indices one binding list may bind (`limits.maxIndices`).
MAX_INDICES = 6

Name = Annotated[str, Field(pattern=NAME_PATTERN)]
Number = Union[StrictInt, StrictFloat]
#: `forall` and `sum.over`: at least one index -- an empty one is written by
#: leaving the key out -- and at most `MAX_INDICES`.
Bindings = Annotated[list["Binding"], Field(min_length=1, max_length=MAX_INDICES)]

VariableDomain = Literal["binary", "integer", "continuous", "interval"]
Relation = Literal["<=", "=", ">="]
TraversalDepth = Literal["one", "any", "any_or_self"]
PathCombination = Literal["count", "max", "min", "product", "sum"]
Severity = Literal["hard", "soft"]
Sense = Literal["minimize", "maximize"]
ObjectiveMode = Literal["weighted", "lex"]
FilterOperator = Literal["=", "!=", "<", "<=", ">", ">=", "in", "notIn"]

#: The term kinds, by the key that names each (the IR has no `kind` field:
#: a term is `{"var": ...}`, `{"sum": ..., "over": ...}` and so on).
TERM_KINDS = ("const", "par", "var", "attr", "sum", "add", "mul", "pwl", "fn")
#: The function catalogue's names (`contract.json` `functions`).
FunctionName = Literal["exp", "log", "sqrt", "abs", "sin", "cos"]


def _accepted(version: int) -> int:
    if version not in ACCEPTED_VERSIONS:
        raise ValueError(f"version {version} is not one this platform expresses; it expresses {ACCEPTED_VERSIONS}")
    return version


Version = Annotated[StrictInt, AfterValidator(_accepted)]


class _Model(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", populate_by_name=True)


class Filter(_Model):
    attr: Name
    op: FilterOperator
    value: Any


class Via(_Model):
    rel: Name
    from_: Optional[Name] = Field(default=None, alias="from")
    to: Optional[Name] = None
    depth: Optional[TraversalDepth] = None
    # Queue R19: the edge this walk takes, read with `attr of <as>`.
    as_: Optional[Name] = Field(default=None, alias="as")

    @model_validator(mode="after")
    def _one_anchor(self) -> "Via":
        if (self.from_ is None) == (self.to is None):
            raise ValueError("a via anchors at exactly one end: `from` or `to`")
        return self


class Binding(_Model):
    index: Name
    set: Name
    where: Optional[list[Filter]] = None
    via: Optional[Via] = None


class Const(_Model):
    const: Number


class ParRef(_Model):
    par: Name
    # Queue R20b: a position may be an entity-valued parameter's cell.
    index: list[Union[Name, "ParRef"]] = Field(default_factory=list)


class VarRef(_Model):
    var: Name
    index: list[Union[Name, ParRef]] = Field(default_factory=list)


class AttrPath(_Model):
    of: Name
    name: Name
    # Queue R19: how an edge attribute combines along a repeated walk.
    along: Optional[PathCombination] = None


class AttrRef(_Model):
    attr: AttrPath


class Sum(_Model):
    sum: "Term"
    over: Bindings


class Add(_Model):
    add: list["Term"] = Field(min_length=1)


class Mul(_Model):
    mul: list["Term"] = Field(min_length=2, max_length=2)


class PwlArgument(_Model):
    var: Name
    index: list[Name]


class Pwl(_Model):
    """f(x) through `points` by linear interpolation (version 2). That the
    x's increase and the document is version 2 is `validate.py`'s to say."""

    pwl: PwlArgument
    points: list[Annotated[list[Number], Field(min_length=2, max_length=2)]] = Field(min_length=2)


class Fn(_Model):
    """A catalogue function of a linear argument (version 2). That the
    argument is linear and the document version 2 is `validate.py`'s to say."""

    fn: FunctionName
    of: "Term"


Term = Union[Const, ParRef, VarRef, AttrRef, Sum, Add, Mul, Pwl, Fn]


class IntervalUncertainty(_Model):
    """Each value may be off by up to `deviation` of itself; at most `gamma`
    of a rule's cells at once (all of them when absent)."""

    kind: Literal["interval"]
    deviation: Annotated[Number, Field(ge=0)]
    gamma: Optional[Annotated[Number, Field(ge=0)]] = None


class ScenarioUncertainty(_Model):
    kind: Literal["scenarios"]


class Parameter(_Model):
    index: list[Name]
    # Queue R20b: its values are entities of this set.
    entity: Optional[Name] = None
    # How the values may be wrong (version 2): what a robust solve reads.
    uncertainty: Optional[Annotated[Union[IntervalUncertainty, ScenarioUncertainty], Field(discriminator="kind")]] = None


class Variable(_Model):
    index: list[Name]
    domain: VariableDomain
    lower: Optional[Number] = None
    upper: Optional[Number] = None
    # An interval (version 2): its start and end variables, its size (a
    # whole number or a parameter), and optionally the binary that says
    # whether it happens at all. Which variables those are is checked by
    # `validate.py`, as it needs the declarations.
    start: Optional[Name] = None
    end: Optional[Name] = None
    size: Optional[Union[Annotated[StrictInt, Field(ge=0)], Name]] = None
    presence: Optional[Name] = None
    # When it is decided (version 2): 1 now, 2 once the uncertain data is
    # known -- what a two-stage stochastic solve reads.
    stage: Optional[Literal[1, 2]] = None

    @model_validator(mode="after")
    def _interval_keys(self) -> "Variable":
        parts = {"start": self.start, "end": self.end, "size": self.size}
        if self.domain == "interval":
            missing = [k for k, v in parts.items() if v is None]
            if missing or self.lower is not None or self.upper is not None:
                raise ValueError("an interval names its start, end and size and carries no bounds")
        elif any(v is not None for v in (*parts.values(), self.presence)):
            raise ValueError("only an interval names a start, end, size or presence")
        if self.domain == "interval" and self.stage is not None:
            raise ValueError("an interval has no stage; its start and end carry it")
        return self


def _zero_or_one(value: int) -> int:
    if value not in (0, 1):
        raise ValueError("a when's `is` is 0 or 1")
    return value


class When(_Model):
    """The switch on a conditional rule (version 2): the rule holds while
    `var[index]` is `is`. `var` must be binary -- `validate.py` checks that,
    as it needs the declarations."""

    var: Name
    index: list[Name]
    is_: Annotated[StrictInt, AfterValidator(_zero_or_one)] = Field(default=1, alias="is")


class Chance(_Model):
    """A chance rule (version 2): it may fail in at most `epsilon` of the
    futures a stochastic solve samples -- strictly between 0 and 1."""

    epsilon: Annotated[Number, Field(gt=0, lt=1)]


class NoOverlap(_Model):
    """The intervals `over` ranges across never run at once (version 2)."""

    interval: VarRef
    over: Bindings


class Cumulative(_Model):
    """At every moment, the demands of the intervals running stay within the
    capacity (version 2). Both are numbers the data gives."""

    interval: VarRef
    over: Bindings
    demand: Term
    capacity: Term


class ConnectedBody(_Model):
    """For every group, the units assigned to it are one piece over `via`
    (version 2). `empty: allowed` lets a group take no units."""

    assign: VarRef
    units: Binding
    groups: Binding
    via: Name
    empty: Literal["forbidden", "allowed"] = "forbidden"


class RouteBody(_Model):
    """Every stop but the depot visited once, by vehicles leaving the depot
    and coming back (version 2, queue R15b); `demand` on the stops and
    `capacity` on the vehicles, both attribute names, hold each vehicle's load."""

    visit: VarRef
    vehicles: Binding
    stops: Binding
    depot: Name
    demand: Optional[Name] = None
    capacity: Optional[Name] = None

    @model_validator(mode="after")
    def _both_or_neither(self) -> "RouteBody":
        if (self.demand is None) != (self.capacity is None):
            raise ValueError("a route names demand and capacity together, or neither")
        return self


class Constraint(_Model):
    """An expression -- `left relation right` -- or, in version 2, one
    scheduling rule or one connected rule in its place."""

    id: Name
    note: Optional[str] = None
    forall: Optional[Bindings] = None
    left: Optional[Term] = None
    relation: Optional[Relation] = None
    right: Optional[Term] = None
    no_overlap: Optional[NoOverlap] = None
    cumulative: Optional[Cumulative] = None
    connected: Optional[ConnectedBody] = None
    route: Optional[RouteBody] = None
    severity: Severity
    weight: Optional[StrictInt] = None
    when: Optional[When] = None
    chance: Optional[Chance] = None

    @model_validator(mode="after")
    def _one_kind(self) -> "Constraint":
        expression = [self.left, self.relation, self.right]
        scheduling = [k for k in (self.no_overlap, self.cumulative) if k is not None]
        if self.connected is not None and self.route is not None:
            raise ValueError("a constraint is one connected rule or one route rule")
        whole = self.connected if self.connected is not None else self.route
        if whole is not None:
            if scheduling or self.forall is not None or any(part is not None for part in expression):
                raise ValueError("a connected or route rule is neither an expression nor inside a forall")
        elif scheduling:
            if len(scheduling) > 1 or any(part is not None for part in expression):
                raise ValueError("a constraint is one expression or one scheduling rule")
        elif any(part is None for part in expression):
            raise ValueError("a constraint states left, relation and right")
        return self


class ObjectiveTerm(_Model):
    id: Name
    weight: StrictInt
    expression: Term


class Objective(_Model):
    sense: Sense
    #: An objective with no terms is written by leaving the objective out.
    terms: list[ObjectiveTerm] = Field(min_length=1)
    mode: Optional[ObjectiveMode] = None


class ProblemIR(_Model):
    version: Version
    sets: list[Name]
    parameters: dict[Name, Parameter]
    variables: dict[Name, Variable]
    constraints: list[Constraint]
    objective: Optional[Objective] = None
    relationships: Optional[list[Name]] = None


for _model in (Sum, Add, Mul, Fn, NoOverlap, Cumulative, ConnectedBody, Constraint, ObjectiveTerm):
    _model.model_rebuild()


def parse(ir: Any) -> ProblemIR:
    """The document as objects; raises `pydantic.ValidationError` on a
    structural fault. Not the gate -- `validate.py` is -- but everything that
    passes it parses here."""
    return ProblemIR.model_validate(ir)


def upgrade_v1(ir: dict[str, Any]) -> dict[str, Any]:
    """A version 1 document as version 2. Version 2 adds constructs and
    changes none, so this only restamps it; kept as a function so a stored
    document can always be brought forward the same way."""
    if ir.get("version") != 1 or isinstance(ir.get("version"), bool):
        raise ValueError("upgrade_v1 takes a version 1 document")
    return {**ir, "version": 2}
