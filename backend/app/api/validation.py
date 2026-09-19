"""Request-layer validation helpers shared by the schema v1 routers.

Moved here from `entity_types.py` in Task 8 (Ruling 22): `relationships.py`
had imported the private `_validate_name`/`_field_error` from that module,
and `parameters.py` became the third consumer, which is the point at which
the ruling asked for a shared module rather than another private import.
Behaviour is unchanged; only the home and the (now public) names moved.
"""

import re
from typing import Any

from fastapi.exceptions import RequestValidationError

# `entity_type.name`, `attribute_def.name`, `relationship_type.name` and
# `parameter_def.name` all carry CHECK (name ~ '^[a-z][a-z0-9_]*$') -- the
# names are used verbatim in IR expressions. Quoted here for the error
# message; the match itself uses `re.fullmatch` on the unanchored body
# rather than `re.match` on the anchored form, because Python's `$` also
# matches just before a trailing newline while Postgres's does not --
# `"employee\n"` would otherwise pass validation and then be rejected by
# the database as a confusing 409.
NAME_PATTERN = "^[a-z][a-z0-9_]*$"
_NAME_RE = re.compile(r"[a-z][a-z0-9_]*")

_NAME_MESSAGE = (
    f"must match {NAME_PATTERN}: a lowercase letter, then lowercase letters, "
    "digits or underscores (it is used verbatim in model expressions)"
)


def validate_name(value: str | None) -> str | None:
    """Pydantic field validator for the `^[a-z][a-z0-9_]*$` name CHECK.
    `None` passes through: on PATCH it means "not being changed"."""
    if value is None:
        return value
    if _NAME_RE.fullmatch(value) is None:
        raise ValueError(_NAME_MESSAGE)
    return value


def field_error(field: str | list[str | int], message: str, value: Any) -> RequestValidationError:
    """Build a refusal in exactly the shape FastAPI's own body validation
    produces, so a caller (and `formatApiError` in the frontend) does not
    have to special-case rules that happen to be checked by hand.

    `field` is a single body field, or a path into the body such as
    ``["cells", 3, "entity_ids"]`` -- the same `loc` Pydantic would give a
    failure inside a list item."""
    path = [field] if isinstance(field, str) else list(field)
    return RequestValidationError(
        [{"type": "value_error", "loc": ("body", *path), "msg": message, "input": value}]
    )


def reject_null(value: Any, info) -> Any:
    """Pydantic field validator for PATCH bodies: omitting a field means
    "unchanged", but an explicit `null` for a NOT NULL column would
    otherwise reach the database as a 409 (`23502`) rather than a 422
    naming the field.

    Pydantic does not run validators on defaults, so this fires only when
    the client actually sent `null`. (`parameters.py` keeps an identical
    private `_not_null` from Task 8; the two can be merged whenever that
    module is next touched.)"""
    if value is None:
        raise ValueError(f"{info.field_name} cannot be null")
    return value
