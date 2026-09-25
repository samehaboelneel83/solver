"""Compiling a parsed document to a SQLAlchemy Core predicate.

    WHERE <the route's own filters> AND <this>

**How user input reaches SQL, exhaustively.** There are four kinds of
user-derived value in a document, and each has exactly one route:

1. **Literals** (a rule's `value`) become bound parameters, always. They
   are passed to SQLAlchemy comparison operators, which produce
   `BindParameter` nodes; psycopg2 sends them out-of-band. No literal is
   ever rendered into the statement text, including the `%`/`_`-escaped
   needle of a `contains` -- the escaping happens to the Python string,
   which is then bound.
2. **Column names** never travel as text at all. `col:sort_order` is a
   dict lookup in :data:`_COLUMNS` that yields the mapped `Column` object;
   a name that is not a key was already refused by `fields.py`.
3. **Attribute names** become bound parameters too: `Entity.attrs[name]`
   compiles to ``entity.attrs -> %(param)s``. The name is data being
   indexed, never identifier text.
4. **Function and direction names** are dict lookups yielding Python
   builders (:data:`_FUNCTIONS`, :data:`_DIRECTIONS`). The `sql` strings in
   `catalogue.json` are documentation; nothing formats or executes them.

There is no f-string, `%`, `.format()` or `+` producing SQL anywhere in
this module, and nothing calls `text()`.

**Why every attribute read is wrapped in a guarded CASE.** `entity_validate`
(migration 0006) checks `date` and `time` attributes only for
``jsonb_typeof(v) = 'string'`` -- its `CASE d.data_type` has no arm for
them. So the database really does hold ``{"hired": "not-a-date"}`` in a
`date` attribute, and ``(attrs->>'hired')::date`` raises on it: a 500 for
one row, produced by a filter that named a different entity type. Postgres
does not promise to evaluate the `entity_type_id = :t` conjunct first, so
the narrowing is not a guard. A CASE is: only the selected branch is
evaluated, so the cast never sees a value its guard has not already
accepted, and a value that fails the guard becomes NULL -- which is exactly
what the client's evaluator calls ABSENT, and an absent value compares to
nothing. The two implementations agree for the same reason rather than by
coincidence.

`date` is not cast at all. The client orders ISO dates as TEXT
(`evaluate.ts`'s `compare`), which is chronological for well-formed ones
and defined for malformed ones; casting here would disagree with the
browser on exactly the rows the database lets through.

**Refusals that need the catalogue.** Whether `attr:7:capacity` exists,
what data type it has, whether an operator is one that type offers, and
whether an enum value is in `enum_values` are all facts only
`attribute_def` holds. They are checked here, before a single construct is
built, and the two lookups they need are two `SELECT`s against
`attribute_def` and `relationship_type` -- never against `entity`. So a
document refused for one of these reasons has still never caused the table
it would have filtered to be read.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import re
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session, aliased
from sqlalchemy.sql import ColumnElement

from app.expressions.catalogue import (
    COLUMNS,
    FUNCTIONS,
    function_return_type,
    operators_for,
)
from app.expressions.fields import (
    AttributeRef,
    ColumnRef,
    FunctionRef,
    RelationshipRef,
)
from app.expressions.parse import (
    ExpressionRefusal,
    ParsedDocument,
    ParsedGroup,
    ParsedRule,
    Path,
)
from app.models.v1_domain import AttributeDef, Entity, Relationship, RelationshipType

# --- the vocabularies, as objects rather than text -------------------------

#: `col:<name>` -> the mapped column. A name outside this dict was refused
#: by `fields.py`; a name inside it never becomes a string again.
_COLUMNS: dict[str, ColumnElement[Any]] = {
    "key": Entity.key,
    "label": Entity.label,
    "sort_order": Entity.sort_order,
    "active": Entity.active,
}

# POSIX regexes, bound as parameters like any other literal. They are the
# server's spelling of the two the client uses: `DATE_RE` in attrTypes.tsx
# and the one `timeSeconds()` in evaluate.ts applies. Under the time one,
# `::time` cannot fail -- hours are 00-23 and both other fields 00-59.
_DATE_GUARD = "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"
_TIME_GUARD = "^([01][0-9]|2[0-3]):[0-5][0-9](:[0-5][0-9])?$"

_DATE_VALUE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_TIME_VALUE_RE = re.compile(r"([01]\d|2[0-3]):([0-5]\d)(?::([0-5]\d))?")

#: JSON's exact-integer range, which is what the client's
#: `Number.isSafeInteger` enforces on the other side.
_MAX_SAFE_INTEGER = 2**53 - 1


def _null_like(expr: ColumnElement[Any]) -> ColumnElement[Any]:
    """A typed NULL for a CASE's `else_`, so the CASE keeps the type of its
    `then` branch instead of becoming `unknown`."""
    return sa.cast(sa.null(), expr.type)


# --- reading one field's value ---------------------------------------------


def _attribute_value(name: str, data_type: str) -> ColumnElement[Any]:
    """`attrs.<name>` as a value of its declared type, or NULL.

    `name` is bound, not interpolated: `Entity.attrs[name]` is
    ``entity.attrs -> %(param)s``.
    """
    stored = Entity.attrs[name]
    text = stored.astext
    kind = sa.func.jsonb_typeof(stored)
    if data_type in ("text", "enum", "date", "reference"):
        # `date` deliberately stays text; see the module docstring.
        return sa.case((kind == "string", text), else_=_null_like(text))
    if data_type in ("integer", "number"):
        numeric = sa.cast(text, sa.Numeric)
        return sa.case((kind == "number", numeric), else_=_null_like(numeric))
    if data_type == "boolean":
        boolean = sa.cast(text, sa.Boolean)
        return sa.case((kind == "boolean", boolean), else_=_null_like(boolean))
    if data_type == "time":
        clock = sa.cast(text, sa.Time)
        return sa.case(
            (sa.and_(kind == "string", text.regexp_match(_TIME_GUARD)), clock),
            else_=_null_like(clock),
        )
    if data_type == "geometry":
        # The GeoJSON object itself. It offers no filter operator
        # (catalogue `operatorsByType`), so this is read only for display.
        return sa.case((kind == "object", stored), else_=_null_like(stored))
    raise AssertionError(f"no reader for data type {data_type!r}")  # pragma: no cover


def _date_part(base: ColumnElement[Any], start: int, length: int) -> ColumnElement[Any]:
    """One field of an ISO date, cut out of the text.

    Not `EXTRACT(... FROM x::date)`: the cast would raise on the non-dates
    the trigger permits, and it would disagree with the client, which reads
    the digits of a well-formed ISO string and calls anything else absent.
    A two- or four-digit run is always a valid `int`, so this cannot fail.
    """
    digits = sa.cast(sa.func.substring(base, start, length), sa.Integer)
    return sa.case((base.regexp_match(_DATE_GUARD), digits), else_=_null_like(digits))


#: `fn:<name>` -> a Python builder. The `sql` strings in `catalogue.json`
#: describe these; they are never read by code.
_FUNCTIONS = {
    "year": lambda base: _date_part(base, 1, 4),
    "month": lambda base: _date_part(base, 6, 2),
    "day": lambda base: _date_part(base, 9, 2),
    "hour": lambda base: sa.cast(sa.extract("hour", base), sa.Integer),
    "minute": lambda base: sa.cast(sa.extract("minute", base), sa.Integer),
    "lower": lambda base: sa.func.lower(base, type_=sa.Text),
    "upper": lambda base: sa.func.upper(base, type_=sa.Text),
    "length": lambda base: sa.func.length(base, type_=sa.Integer),
    "abs": lambda base: sa.func.abs(base, type_=sa.Numeric),
}

#: `rel:<id>:<direction>` -> which end of a relationship row an entity is.
#: Three fixed predicates; the direction is a dict key, never concatenated.
_DIRECTIONS = {
    "outgoing": lambda rel: rel.from_entity_id == Entity.id,
    "incoming": lambda rel: rel.to_entity_id == Entity.id,
    "any": lambda rel: sa.or_(rel.from_entity_id == Entity.id, rel.to_entity_id == Entity.id),
}


def _relationship_count(ref: RelationshipRef) -> ColumnElement[Any]:
    """`count(<relationshipType>, direction)` -- the one catalogue entry
    whose SQL is a correlated subquery rather than a scalar expression.

    It compiles: `relationship` is aliased so it cannot collide with the
    outer statement, the type id is bound, and the correlation on `entity`
    is explicit rather than inferred. No relationships is 0, not NULL,
    because `count(*)` over no rows is 0 -- which is what the client means
    by "a missing degree key is zero".
    """
    rel = aliased(Relationship)
    return (
        sa.select(sa.func.count())
        .select_from(rel)
        .where(
            rel.relationship_type_id == ref.relationship_type_id,
            _DIRECTIONS[ref.direction](rel),
        )
        .correlate(Entity)
        .scalar_subquery()
    )


# --- what the domain declares ----------------------------------------------


class _Resolved:
    """One rule's field, once the catalogue has answered for it."""

    __slots__ = ("value", "absent", "data_type", "nullable", "enum_values", "owner_entity_type_id")

    def __init__(
        self,
        value: ColumnElement[Any],
        absent: ColumnElement[bool],
        data_type: str,
        nullable: bool,
        enum_values: list[str] | None,
        owner_entity_type_id: int | None,
    ) -> None:
        self.value = value
        #: What "is empty" tests. NOT `value IS NULL`: for an attribute,
        #: `value` is a GUARDED read, so a stored value whose JSON type
        #: disagrees with the attribute's declared type reads as NULL --
        #: and calling that "empty" would say the attribute has no value
        #: when it plainly has one. The client draws the same line:
        #: `baseValue` calls a key ABSENT when it is missing or `null`, and
        #: a value of the wrong type is neither. (The two disagree only
        #: when an `attribute_def.data_type` is changed under rows that
        #: already exist, which the trigger does not revisit -- Ruling 29 --
        #: but that is exactly when a filter must not start lying.)
        self.absent = absent
        self.data_type = data_type
        self.nullable = nullable
        self.enum_values = enum_values
        self.owner_entity_type_id = owner_entity_type_id


class _Catalogue:
    """The `attribute_def` and `relationship_type` rows this document
    mentions, fetched in one query each.

    Not scoped to a domain, because `GET /api/v1/entities` is not: it is
    scoped by `entity_type_id`, whose type belongs to one domain. An
    expression cannot widen that -- it only ever ANDs predicates onto the
    query the route had already built.
    """

    def __init__(self, db: Session, parsed: ParsedDocument) -> None:
        entity_type_ids: set[int] = set()
        relationship_type_ids: set[int] = set()
        for rule in parsed.rules:
            ref = rule.ref
            inner = ref.argument if isinstance(ref, FunctionRef) else ref
            if isinstance(inner, AttributeRef):
                entity_type_ids.add(inner.entity_type_id)
            elif isinstance(inner, RelationshipRef):
                relationship_type_ids.add(inner.relationship_type_id)

        self.attributes: dict[tuple[int, str], Any] = {}
        if entity_type_ids:
            rows = db.execute(
                sa.select(
                    AttributeDef.entity_type_id,
                    AttributeDef.name,
                    AttributeDef.data_type,
                    AttributeDef.required,
                    AttributeDef.enum_values,
                ).where(AttributeDef.entity_type_id.in_(sorted(entity_type_ids)))
            ).all()
            self.attributes = {(row[0], row[1]): row for row in rows}

        self.relationship_types: set[int] = set()
        if relationship_type_ids:
            self.relationship_types = set(
                db.scalars(
                    sa.select(RelationshipType.id).where(
                        RelationshipType.id.in_(sorted(relationship_type_ids))
                    )
                ).all()
            )


def _attribute_absent(name: str) -> ColumnElement[bool]:
    """Whether `attrs` has no value under this key: the key is missing, or
    it holds a JSON `null`. The client's two ABSENT cases, exactly."""
    kind = sa.func.jsonb_typeof(Entity.attrs[name])
    return sa.or_(kind.is_(None), kind == "null")


def _resolve_base(
    catalogue: _Catalogue, ref: Any, path: Path
) -> tuple[ColumnElement[Any], ColumnElement[bool], str, bool, list[str] | None, int | None]:
    if isinstance(ref, ColumnRef):
        declared = COLUMNS[ref.column]
        column = _COLUMNS[ref.column]
        return column, column.is_(None), declared["dataType"], declared["nullable"], None, None
    assert isinstance(ref, AttributeRef)
    row = catalogue.attributes.get((ref.entity_type_id, ref.attribute))
    if row is None:
        raise ExpressionRefusal(
            path,
            "unknown_field",
            f"No entity type here declares an attribute called {json.dumps(ref.attribute)}.",
        )
    _, _, data_type, required, enum_values = row
    return (
        _attribute_value(ref.attribute, data_type),
        _attribute_absent(ref.attribute),
        data_type,
        not required,
        list(enum_values) if enum_values else None,
        ref.entity_type_id,
    )


def _resolve(catalogue: _Catalogue, rule: ParsedRule) -> _Resolved:
    path: Path = (*rule.path, "field")
    ref = rule.ref
    if not isinstance(ref, FunctionRef):
        value, absent, data_type, nullable, enum_values, owner = _resolve_base(catalogue, ref, path)
        return _Resolved(value, absent, data_type, nullable, enum_values, owner)

    if isinstance(ref.argument, RelationshipRef):
        if ref.argument.relationship_type_id not in catalogue.relationship_types:
            raise ExpressionRefusal(
                path, "unknown_field", "count() names a relationship type this app does not have."
            )
        count = _relationship_count(ref.argument)
        return _Resolved(count, sa.false(), "integer", False, None, None)

    base, _, argument_type, _, _, owner = _resolve_base(catalogue, ref.argument, path)
    allowed = FUNCTIONS[ref.fn]["argumentTypes"]
    if argument_type not in allowed:
        raise ExpressionRefusal(
            path,
            "bad_argument_type",
            f"{ref.fn}() takes {' or '.join(allowed)}, and that field is {argument_type}.",
        )
    # A function of an absent value is absent, and SQL says the same -- but
    # "is empty" on a call is confusing, so calls are not nullable and the
    # null operators are not offered on them. Same rule as `fields.ts`.
    call = _FUNCTIONS[ref.fn](base)
    return _Resolved(
        call,
        call.is_(None),
        function_return_type(ref.fn, argument_type),
        False,
        None,
        owner,
    )


# --- judging a value against its field's type ------------------------------


def _bad_value(path: Path, message: str, code: str = "bad_value_type") -> ExpressionRefusal:
    return ExpressionRefusal(path, code, message)


def _scalar(value: Any, resolved: _Resolved, path: Path) -> Any:
    """`value` as something that can be bound against this field, or a
    refusal. Mirrors `validate.ts`'s `scalarProblem` -- a document the
    client accepts must not be refused here for a reason it does not have,
    and vice versa."""
    data_type = resolved.data_type
    if data_type == "integer":
        if not isinstance(value, int) or isinstance(value, bool) or abs(value) > _MAX_SAFE_INTEGER:
            raise _bad_value(path, "must be a whole number, such as 8 or -2 (no decimals).")
        return value
    if data_type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise _bad_value(path, "must be a number, such as 2.5.")
        return value
    if data_type == "boolean":
        if not isinstance(value, bool):
            raise _bad_value(path, "must be True or False.")
        return value
    if data_type == "text":
        if not isinstance(value, str):
            raise _bad_value(path, "must be text.")
        return value
    if data_type == "enum":
        allowed = resolved.enum_values or []
        if not isinstance(value, str) or value not in allowed:
            raise _bad_value(
                path,
                f"{json.dumps(value)} is not one of {', '.join(allowed)}.",
                code="bad_enum_value",
            )
        return value
    if data_type == "date":
        match = _DATE_VALUE_RE.fullmatch(value) if isinstance(value, str) else None
        if match is None:
            raise _bad_value(path, "must be a date (YYYY-MM-DD).")
        try:
            dt.date(int(match[1]), int(match[2]), int(match[3]))
        except ValueError as exc:
            # The client checks the same thing with `new Date(Date.UTC(...))`
            # and a round-trip comparison: 2024-02-31 is a well-formed
            # string and not a day.
            raise _bad_value(path, "must be a date (YYYY-MM-DD).") from exc
        return value
    if data_type == "time":
        match = _TIME_VALUE_RE.fullmatch(value) if isinstance(value, str) else None
        if match is None:
            raise _bad_value(path, "must be a time of day (HH:MM).")
        # Bound as a real `time`, not as text: the column side of the
        # comparison is `time` too, which is what makes 09:30 equal
        # 09:30:00 (Ruling 36) rather than differ by three characters.
        return dt.time(int(match[1]), int(match[2]), int(match[3] or 0))
    if data_type == "reference":
        # An entity's key (migration 0067): any non-empty text; one naming no
        # entity simply matches nothing.
        if not isinstance(value, str) or value == "":
            raise _bad_value(path, "must be the key of an entity.")
        return value
    raise AssertionError(f"no value rule for {data_type!r}")  # pragma: no cover


# --- operators --------------------------------------------------------------


def _escape_like(needle: str) -> str:
    """`%` and `_` are characters here, not wildcards -- the client's
    `contains` is `String.includes`, which has no pattern language at all.
    The escaping happens to the Python string; the result is then BOUND,
    so this is not SQL being built."""
    return needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _predicate(resolved: _Resolved, rule: ParsedRule) -> ColumnElement[bool]:
    expr = resolved.value
    operator = rule.operator
    value_path: Path = (*rule.path, "value")

    if operator == "null":
        return resolved.absent
    if operator == "notNull":
        # `not_(absent)` would be NULL where `absent` is -- it never is,
        # since both branches are IS NULL / equality tests on jsonb_typeof
        # -- but spelling the complement out keeps it two-valued by
        # construction rather than by argument.
        return sa.not_(sa.type_coerce(sa.func.coalesce(resolved.absent, sa.false()), sa.Boolean))

    if operator in ("in", "notIn"):
        values = [_scalar(item, resolved, (*value_path, index)) for index, item in enumerate(rule.value)]
        # `in_` binds one parameter per value (the list length is capped in
        # `parse.py`, so this cannot become a statement of unbounded size).
        member = expr.in_(values)
        return member if operator == "in" else sa.not_(member)

    value = _scalar(rule.value, resolved, value_path)

    if operator == "=":
        return expr == value
    if operator == "!=":
        return expr != value
    if operator == "<":
        return expr < value
    if operator == "<=":
        return expr <= value
    if operator == ">":
        return expr > value
    if operator == ">=":
        return expr >= value

    # The three text searches. ILIKE, because the client folds case for
    # exactly these three and leaves `=` case sensitive (evaluate.ts).
    needle = _escape_like(value)
    patterns = {
        "contains": f"%{needle}%",
        "doesNotContain": f"%{needle}%",
        "beginsWith": f"{needle}%",
        "endsWith": f"%{needle}",
    }
    like = expr.ilike(patterns[operator], escape="\\")
    return sa.not_(like) if operator == "doesNotContain" else like


# --- the walk ---------------------------------------------------------------


def _rule_predicate(catalogue: _Catalogue, rule: ParsedRule) -> ColumnElement[bool]:
    resolved = _resolve(catalogue, rule)
    if rule.operator not in operators_for(resolved.data_type, resolved.nullable):
        raise ExpressionRefusal(
            (*rule.path, "operator"),
            "bad_operator",
            f"{json.dumps(rule.operator)} is not a comparison a {resolved.data_type} field offers.",
        )
    predicate = _predicate(resolved, rule)
    if resolved.owner_entity_type_id is not None:
        # A rule about `unit.capacity` is false for an entity that is not a
        # unit, whatever the operator -- including "is empty", which would
        # otherwise match every shift as well. The same narrowing the
        # client applies in `fieldApplies`.
        predicate = sa.and_(Entity.entity_type_id == resolved.owner_entity_type_id, predicate)
    return predicate


def _group_predicate(catalogue: _Catalogue, group: ParsedGroup) -> ColumnElement[bool]:
    if not group.children:
        # An empty group is no constraint, not an impossible one.
        inner: ColumnElement[bool] = sa.true()
    else:
        parts = [
            _group_predicate(catalogue, child)
            if isinstance(child, ParsedGroup)
            else _rule_predicate(catalogue, child)
            for child in group.children
        ]
        inner = sa.and_(*parts) if group.combinator == "and" else sa.or_(*parts)

    if not group.negated:
        return inner
    # SQL is three-valued and the client's evaluator is two-valued. In a
    # positive context that difference is invisible -- NULL and false both
    # drop the row -- but `NOT NULL` is NULL, where the client says `!false
    # = true`. Collapsing NULL to false here, and only here, makes the two
    # agree without putting a `coalesce` in front of every predicate (which
    # would also stop the planner using an index on `key` or `sort_order`).
    return sa.not_(sa.type_coerce(sa.func.coalesce(inner, sa.false()), sa.Boolean))


def compile_expression(db: Session, parsed: ParsedDocument) -> ColumnElement[bool]:
    """The parsed document as one boolean predicate over `entity`.

    Raises :class:`ExpressionRefusal` for anything the catalogue cannot
    answer. Nothing is built until every rule has been resolved, so a
    refusal never leaves a half-built statement behind.
    """
    catalogue = _Catalogue(db, parsed)
    return _group_predicate(catalogue, parsed.root)
