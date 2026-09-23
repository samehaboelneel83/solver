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

VariableDomain = Literal["binary", "integer", "continuous"]
Relation = Literal["<=", "=", ">="]
TraversalDepth = Literal["one", "any", "any_or_self"]
Severity = Literal["hard", "soft"]
Sense = Literal["minimize", "maximize"]
ObjectiveMode = Literal["weighted", "lex"]
FilterOperator = Literal["=", "!=", "<", "<=", ">", ">=", "in", "notIn"]

#: The term kinds, by the key that names each (the IR has no `kind` field:
#: a term is `{"var": ...}`, `{"sum": ..., "over": ...}` and so on).
TERM_KINDS = ("const", "par", "var", "attr", "sum", "add", "mul")


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


Term = Union[Const, ParRef, VarRef, AttrRef, Sum, Add, Mul]


class Parameter(_Model):
    index: list[Name]


class Variable(_Model):
    index: list[Name]
    domain: VariableDomain
    lower: Optional[Number] = None
    upper: Optional[Number] = None


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


class Constraint(_Model):
    id: Name
    note: Optional[str] = None
    forall: Optional[Bindings] = None
    left: Term
    relation: Relation
    right: Term
    severity: Severity
    weight: Optional[StrictInt] = None
    when: Optional[When] = None


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


for _model in (Sum, Add, Mul, Constraint, ObjectiveTerm):
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
