"""What a rule may name, and how a name travels -- the server's half of
`frontend/src/expressions/fields.ts`.

A rule stores its field as ONE string, because that is what
react-querybuilder's `RuleType.field` is. The string is an identity rather
than a bare name, for two reasons this schema produces: an entity type may
legally declare an attribute called `key`, `label`, `sort_order` or
`active`, and two entity types may each declare `capacity` with different
data types.

    col:<column>                      an entity column
    attr:<entityTypeId>:<name>        an attribute of one entity type
    fn:<function>:<argument>          a call, one level deep
    rel:<relTypeId>:<direction>       only ever a call's argument

**Everything here is a closed vocabulary or a pattern, and nothing here
ever becomes SQL text.** A column resolves to a `Column` object through a
dict; a function resolves to a Python builder through a dict; an id becomes
an `int`; an attribute name becomes a bound parameter. The decoder is
nevertheless as strict as it can be, because a refusal here happens with no
database in scope at all (see `parse.py`), and it costs nothing to refuse
`attr:1:"; drop table entity` by its shape rather than by a catalogue miss:

- ids are digits **and** must fit a signed bigint, since `attribute_def`'s
  are `bigint GENERATED ALWAYS AS IDENTITY` and a 40-digit literal would
  reach psycopg2 as a `NumericValueOutOfRange`, i.e. a 500;
- an attribute name must match `^[a-z][a-z0-9_]*$`, which is
  `attribute_def`'s own CHECK -- a name that cannot satisfy it cannot name
  a real attribute, so refusing it loses nothing;
- the column, direction and function vocabularies are the catalogue's.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.expressions.catalogue import COLUMNS, FUNCTIONS, RELATIONSHIP_DIRECTIONS

_ID_RE = re.compile(r"[0-9]{1,18}")
# `attribute_def.name ~ '^[a-z][a-z0-9_]*$'` (migration 0006), capped at the
# length a name could plausibly have so the pattern cannot be fed a megabyte.
_ATTRIBUTE_RE = re.compile(r"[a-z][a-z0-9_]{0,126}")


@dataclass(frozen=True)
class ColumnRef:
    column: str


@dataclass(frozen=True)
class AttributeRef:
    entity_type_id: int
    attribute: str


@dataclass(frozen=True)
class RelationshipRef:
    relationship_type_id: int
    direction: str


@dataclass(frozen=True)
class FunctionRef:
    fn: str
    argument: ColumnRef | AttributeRef | RelationshipRef


FieldRef = ColumnRef | AttributeRef | FunctionRef
AnyRef = ColumnRef | AttributeRef | RelationshipRef | FunctionRef


def _decode_argument(field_id: str) -> ColumnRef | AttributeRef | RelationshipRef | None:
    parts = field_id.split(":")
    if parts[0] == "col":
        return ColumnRef(parts[1]) if len(parts) == 2 and parts[1] in COLUMNS else None
    if parts[0] == "attr":
        if len(parts) != 3 or not _ID_RE.fullmatch(parts[1]) or not _ATTRIBUTE_RE.fullmatch(parts[2]):
            return None
        return AttributeRef(int(parts[1]), parts[2])
    if parts[0] == "rel":
        if len(parts) != 3 or not _ID_RE.fullmatch(parts[1]) or parts[2] not in RELATIONSHIP_DIRECTIONS:
            return None
        return RelationshipRef(int(parts[1]), parts[2])
    return None


def decode_field_id(field_id: str) -> FieldRef | None:
    """The reference this id names, or None when it is not one version 1
    expresses.

    A bare `rel:...` is None: a relationship is only ever `count`'s
    argument, never a field in its own right. A nested call is None too --
    version 1 is one level deep, and reading `fn:abs:fn:year:x` as `abs(fn)`
    would quietly drop a level. This mirrors `fields.ts`'s `decodeFieldId`
    exactly; a document the client accepts must not be refused here for a
    reason the client does not have.
    """
    if not field_id:
        return None
    parts = field_id.split(":")
    if parts[0] != "fn":
        base = _decode_argument(field_id)
        return base if isinstance(base, (ColumnRef, AttributeRef)) else None
    if len(parts) < 3:
        return None
    argument_id = ":".join(parts[2:])
    if argument_id.startswith("fn:"):
        return None
    argument = _decode_argument(argument_id)
    if argument is None:
        return None
    return FunctionRef(parts[1], argument)


def is_nested_function_id(field_id: str) -> bool:
    """`abs(year(d))` is a thing somebody will try, and "unknown field"
    would be a lie about why it was refused."""
    return field_id.startswith("fn:") and "fn:" in field_id[3:]


def function_exists(name: str) -> bool:
    return name in FUNCTIONS
