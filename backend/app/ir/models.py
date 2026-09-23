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
Severity = Literal["hard", "soft"]
Sense = Literal["minimize", "maximize"]
ObjectiveMode = Literal["weighted", "lex"]
FilterOperator = Literal["=", "!=", "<", "<=", ">", ">=", "in", "notIn"]

#: The term kinds, by the key that names each (the IR has no `kind` field:
#: a term is `{"var": ...}`, `{"sum": ..., "over": ...}` and so on).
TERM_KINDS = ("const", "par", "var", "attr", "sum", "add", "mul", "pwl")


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
    index: list[Name] = Field(default_factory=list)


class VarRef(_Model):
    var: Name
    index: list[Name] = Field(default_factory=list)


class AttrPath(_Model):
    of: Name
    name: Name


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


Term = Union[Const, ParRef, VarRef, AttrRef, Sum, Add, Mul, Pwl]


class Parameter(_Model):
    index: list[Name]


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

    @model_validator(mode="after")
    def _interval_keys(self) -> "Variable":
        parts = {"start": self.start, "end": self.end, "size": self.size}
        if self.domain == "interval":
            missing = [k for k, v in parts.items() if v is None]
            if missing or self.lower is not None or self.upper is not None:
                raise ValueError("an interval names its start, end and size and carries no bounds")
        elif any(v is not None for v in (*parts.values(), self.presence)):
            raise ValueError("only an interval names a start, end, size or presence")
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


class Constraint(_Model):
    """An expression -- `left relation right` -- or, in version 2, one
    scheduling rule in its place."""

    id: Name
    note: Optional[str] = None
    forall: Optional[Bindings] = None
    left: Optional[Term] = None
    relation: Optional[Relation] = None
    right: Optional[Term] = None
    no_overlap: Optional[NoOverlap] = None
    cumulative: Optional[Cumulative] = None
    severity: Severity
    weight: Optional[StrictInt] = None
    when: Optional[When] = None

    @model_validator(mode="after")
    def _one_kind(self) -> "Constraint":
        expression = [self.left, self.relation, self.right]
        scheduling = [k for k in (self.no_overlap, self.cumulative) if k is not None]
        if scheduling:
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


for _model in (Sum, Add, Mul, NoOverlap, Cumulative, Constraint, ObjectiveTerm):
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
