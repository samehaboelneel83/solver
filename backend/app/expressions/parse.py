"""Reading an expression document off the wire, and refusing it before
anything else happens.

**This module has no database in scope, and that is the point.**
:func:`parse_expression` takes a string and returns a tree of frozen
dataclasses; its only imports are the catalogue and the field decoder,
neither of which knows what a `Session` is. So every refusal it can make --
a malformed body, an unsupported version, a nest too deep, too many rules,
an unknown operator, an unknown function, a field id that is not one this
version expresses, a value of the wrong JSON shape, a list that is empty or
too long -- is made with no query executed, because there is nothing here
to execute one with. `test_expressions_refusal.py` asserts that property
directly, by asserting this function's signature.

What it cannot decide alone is anything that depends on what the domain
actually declares: whether `attr:7:capacity` exists, what data type it has,
whether a value is one of an enum's `enum_values`, whether the operator is
one that data type offers. Those need `attribute_def`, so they live in
`compiler.py` -- which runs second, and never runs at all for a document
refused here.

The first problem is raised rather than all of them collected. The client
validates the same document against the same catalogue before sending it
(`validate.ts`), so a 422 from here is either a hand-written request or a
catalogue the client has not reloaded; in both cases naming one thing
precisely beats listing several.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.expressions.catalogue import (
    EXPRESSION_VERSION,
    MAX_DEPTH,
    MAX_EXPRESSION_BYTES,
    MAX_LIST_LENGTH,
    MAX_RULES,
    OPERATORS,
)
from app.expressions.fields import (
    FieldRef,
    FunctionRef,
    RelationshipRef,
    decode_field_id,
    function_exists,
    is_nested_function_id,
)

Path = tuple[str | int, ...]


class ExpressionRefusal(Exception):
    """One reason a document cannot be compiled.

    `path` points into the document the way Pydantic points into a body, so
    the route can hand it straight to `loc` and the builder can highlight
    the rule it names (Ruling 30: consumers key on `loc`, not on a code).
    `code` exists for tests and for the report; no client branches on it.
    """

    def __init__(self, path: Path, code: str, message: str) -> None:
        super().__init__(message)
        self.path = path
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ParsedRule:
    path: Path
    field_id: str
    ref: FieldRef
    operator: str
    value: Any


@dataclass(frozen=True)
class ParsedGroup:
    path: Path
    combinator: str
    negated: bool
    children: tuple["ParsedGroup | ParsedRule", ...]


@dataclass(frozen=True)
class ParsedDocument:
    root: ParsedGroup
    #: Every rule at any depth, flat. `compiler.py` reads it to find out
    #: which entity and relationship types it has to look up, in one query
    #: each rather than one per rule.
    rules: tuple[ParsedRule, ...]

    @property
    def rule_count(self) -> int:
        return len(self.rules)


def _reject_constant(name: str) -> Any:
    # `json.loads` accepts NaN, Infinity and -Infinity by default. None of
    # them compares meaningfully, and psycopg2 would happily send 'NaN' to
    # Postgres, where `numeric` accepts it and orders it above everything.
    raise ValueError(f"{name} is not a value an expression can hold")


def _is_scalar(value: Any) -> bool:
    """A value that can be bound as one parameter. `bool` is checked by
    `isinstance` against the same tuple as `int`, which it subclasses --
    both are scalars, so the distinction does not matter here; the data
    type check in `compiler.py` is where `True` stops being an integer."""
    return isinstance(value, (str, int, float, bool))


class _Walker:
    def __init__(self) -> None:
        self.rules: list[ParsedRule] = []

    def group(self, node: Any, path: Path, depth: int) -> ParsedGroup:
        if not isinstance(node, dict):
            raise ExpressionRefusal(path, "malformed", "A group must be an object.")
        combinator = node.get("combinator")
        if combinator not in ("and", "or"):
            raise ExpressionRefusal(
                (*path, "combinator"),
                "bad_combinator",
                f'A group joins its conditions with "and" or "or", not {json.dumps(combinator)}.',
            )
        negated = node.get("not", False)
        if not isinstance(negated, bool):
            raise ExpressionRefusal((*path, "not"), "malformed", "A group's `not` must be true or false.")
        rules = node.get("rules")
        if not isinstance(rules, list):
            raise ExpressionRefusal((*path, "rules"), "malformed", "A group's conditions must be a list.")
        # Depth is checked before the children are walked, so a document
        # built to exhaust the stack is refused rather than recursed into.
        if depth > MAX_DEPTH:
            raise ExpressionRefusal(
                path, "too_deep", f"Groups may be nested at most {MAX_DEPTH} deep."
            )

        children: list[ParsedGroup | ParsedRule] = []
        for index, child in enumerate(rules):
            child_path: Path = (*path, "rules", index)
            if isinstance(child, dict) and isinstance(child.get("rules"), list):
                children.append(self.group(child, child_path, depth + 1))
            else:
                children.append(self.rule(child, child_path))
        return ParsedGroup(path, combinator, negated, tuple(children))

    def rule(self, node: Any, path: Path) -> ParsedRule:
        if not isinstance(node, dict):
            raise ExpressionRefusal(path, "malformed", "A condition must be an object.")
        field_id = node.get("field")
        operator = node.get("operator")
        if not isinstance(field_id, str) or not isinstance(operator, str):
            raise ExpressionRefusal(
                path, "malformed", "A condition needs a field and a comparison, both text."
            )
        if len(self.rules) >= MAX_RULES:
            raise ExpressionRefusal(
                (),
                "too_many_rules",
                f"An expression holds at most {MAX_RULES} conditions.",
            )

        ref = self._reference(field_id, (*path, "field"))
        if operator not in OPERATORS:
            raise ExpressionRefusal(
                (*path, "operator"),
                "bad_operator",
                f"{json.dumps(operator)} is not a comparison this app knows.",
            )
        value = self._value(node.get("value"), operator, (*path, "value"))

        parsed = ParsedRule(path, field_id, ref, operator, value)
        self.rules.append(parsed)
        return parsed

    def _reference(self, field_id: str, path: Path) -> FieldRef:
        ref = decode_field_id(field_id)
        if ref is None:
            if is_nested_function_id(field_id):
                raise ExpressionRefusal(
                    path,
                    "nested_function",
                    f"One function inside another is not supported: {json.dumps(field_id)}.",
                )
            if field_id.startswith("fn:"):
                name = field_id.split(":")[1] if len(field_id.split(":")) > 2 else ""
                if name and not function_exists(name):
                    raise ExpressionRefusal(
                        path, "unknown_function", f"There is no function called {json.dumps(name)}."
                    )
            raise ExpressionRefusal(
                path, "unknown_field", f"{json.dumps(field_id)} is not a field this app can filter by."
            )
        if isinstance(ref, FunctionRef):
            if not function_exists(ref.fn):
                raise ExpressionRefusal(
                    path, "unknown_function", f"There is no function called {json.dumps(ref.fn)}."
                )
            wants_relationship = ref.fn == "count"
            has_relationship = isinstance(ref.argument, RelationshipRef)
            if wants_relationship != has_relationship:
                raise ExpressionRefusal(
                    path,
                    "bad_argument_type",
                    "count() takes a relationship type and a direction; every other function takes a field."
                    if wants_relationship
                    else f"{ref.fn}() takes a field, not a relationship type.",
                )
        return ref

    def _value(self, value: Any, operator: str, path: Path) -> Any:
        arity = OPERATORS[operator]["arity"]
        if arity == "unary":
            # "is empty" has no value. The builder leaves the previous
            # operator's behind and `document.ts` nulls it; either way it
            # is not read, so it is not judged.
            return None
        if arity == "list":
            if not isinstance(value, list):
                raise ExpressionRefusal(
                    path, "bad_value_type", 'This comparison takes a list of values.'
                )
            if not value:
                raise ExpressionRefusal(path, "empty_list", "Choose at least one value.")
            if len(value) > MAX_LIST_LENGTH:
                raise ExpressionRefusal(
                    path, "list_too_long", f"This comparison takes at most {MAX_LIST_LENGTH} values."
                )
            for index, item in enumerate(value):
                if not _is_scalar(item):
                    raise ExpressionRefusal(
                        (*path, index), "bad_value_type", "Each value must be a single value."
                    )
            return list(value)
        if not _is_scalar(value):
            raise ExpressionRefusal(path, "bad_value_type", "This comparison takes a single value.")
        return value


def parse_expression(raw: str) -> ParsedDocument:
    """`raw` as a document, or an :class:`ExpressionRefusal`."""
    if len(raw) > MAX_EXPRESSION_BYTES:
        raise ExpressionRefusal(
            (), "too_large", f"An expression may be at most {MAX_EXPRESSION_BYTES} characters."
        )
    try:
        document = json.loads(raw, parse_constant=_reject_constant)
    except RecursionError as exc:  # pragma: no cover - guarded by the size cap
        raise ExpressionRefusal((), "too_deep", "This expression is nested too deeply to read.") from exc
    except ValueError as exc:
        raise ExpressionRefusal((), "malformed", "This expression is not readable JSON.") from exc

    if not isinstance(document, dict):
        raise ExpressionRefusal((), "malformed", "An expression is an object with a version and a query.")
    # `is not` rather than `!=`: `True == 1` in Python, and a document
    # saying `version: true` is not a document saying version 1.
    version = document.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version != EXPRESSION_VERSION:
        raise ExpressionRefusal(
            ("version",),
            "unsupported_version",
            f"This expression says version {json.dumps(version)}; "
            f"this server reads version {EXPRESSION_VERSION}.",
        )
    if not isinstance(document.get("query"), dict):
        raise ExpressionRefusal(
            ("query",), "malformed", "An expression is an object with a version and a query."
        )

    walker = _Walker()
    root = walker.group(document["query"], ("query",), 1)
    return ParsedDocument(root=root, rules=tuple(walker.rules))
