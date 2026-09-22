"""Request-layer validation helpers shared by the schema v1 routers.

Moved here from `entity_types.py` in Task 8 (Ruling 22): `relationships.py`
had imported the private `_validate_name`/`_field_error` from that module,
and `parameters.py` became the third consumer, which is the point at which
the ruling asked for a shared module rather than another private import.
Behaviour is unchanged; only the home and the (now public) names moved.
"""

import base64
import binascii
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


# `entity_type.colour` and `relationship_type.colour` (migration 0009) carry
# CHECK (colour ~ '^#[0-9a-f]{6}$') -- lowercase six-digit hex, so every
# consumer can rely on one format and NULL unambiguously means "not chosen".
#
# The request layer accepts either case and **normalises** to lowercase
# rather than refusing an uppercase value. Hex is case-insensitive
# everywhere a user meets it -- CSS, `<input type="color">`, the copy button
# of every design tool -- so `#AABBCC` is not an ambiguous or mistaken
# value, and a 422 there would refuse something the user got right. The
# lowercase spelling is a storage rule, and the request layer is where a
# storage format is imposed; the CHECK stays as the backstop for every
# writer that is not this API (the seed, a migration, psql), which
# `test_api_entity_types.py` asserts still fires.
#
# The shorthand `#abc` is NOT expanded: expanding is a guess about intent,
# and the message says what form is wanted instead. `re.fullmatch` for the
# same reason as the name pattern -- Python's `$` also matches before a
# trailing newline, Postgres's does not, so a colour with one would
# otherwise pass here and be refused by the database as a confusing 409.
COLOUR_PATTERN = "^#[0-9a-f]{6}$"
_COLOUR_RE = re.compile(r"#[0-9a-fA-F]{6}")

_COLOUR_MESSAGE = (
    "must be a six-digit hex colour such as #1f77b4 (upper case is accepted "
    "and stored lower case; the three-digit form is not)"
)


def validate_colour(value: str | None) -> str | None:
    """Pydantic field validator for the `colour` CHECK. `None` passes
    through: on create it means "no colour", on PATCH an explicit null
    clears one and an omitted key leaves it alone."""
    if value is None:
        return value
    if _COLOUR_RE.fullmatch(value) is None:
        raise ValueError(_COLOUR_MESSAGE)
    return value.lower()


# `entity_type.icon` (migration 0031): a gallery key, or an uploaded image
# as a base64 data: URI. The CHECK only sees the shape; this decodes it.
ICON_MAX_BYTES = 200 * 1024
_ICON_KEY_RE = re.compile(r"[a-z][a-z0-9_]{0,39}")
_ICON_URI_RE = re.compile(r"data:(image/png|image/webp|image/svg\+xml);base64,(.*)", re.DOTALL)

# What an SVG would need to run script, fetch something, or smuggle in a
# document: refused outright rather than stripped, because a stripped file
# is a different picture from the one the user chose, silently. Matched
# case-insensitively on the decoded text.
_SVG_DANGER = [
    (re.compile(rb"<\s*script", re.I), "a <script> element"),
    (re.compile(rb"<\s*foreignObject", re.I), "a <foreignObject> element"),
    (re.compile(rb"<!\s*(DOCTYPE|ENTITY)", re.I), "a DOCTYPE or entity declaration"),
    (re.compile(rb"\son[a-z]+\s*=", re.I), "an event-handler attribute"),
    (re.compile(rb"javascript\s*:", re.I), "a javascript: link"),
    # Any href or url() that is not a fragment (#id) or an inline data: URI
    # reaches outside the file.
    (re.compile(rb"href\s*=\s*[\"'](?!#|data:)", re.I), "a link to another file"),
    (re.compile(rb"url\(\s*[\"']?(?!#|data:)", re.I), "a url() to another file"),
]

_ICON_KEY_MESSAGE = (
    "must be a gallery icon name (a lowercase letter, then up to 39 lowercase "
    "letters, digits or underscores) or an uploaded image"
)


def _looks_like(mime: str, payload: bytes) -> bool:
    if mime == "image/png":
        return payload.startswith(b"\x89PNG\r\n\x1a\n")
    if mime == "image/webp":
        return payload[:4] == b"RIFF" and payload[8:12] == b"WEBP"
    head = payload[:1024].lstrip().lower()
    return b"<svg" in head


def validate_icon(value: str | None) -> str | None:
    """Pydantic field validator for `entity_type.icon`. `None` passes
    through: on create it means "use the default", on PATCH an explicit null
    goes back to the default and an omitted key leaves it alone."""
    if value is None:
        return value
    if not value.startswith("data:"):
        if _ICON_KEY_RE.fullmatch(value) is None:
            raise ValueError(_ICON_KEY_MESSAGE)
        return value
    match = _ICON_URI_RE.fullmatch(value)
    if match is None:
        raise ValueError("an uploaded image must be PNG, SVG or WebP, sent as a base64 data: URI")
    mime, encoded = match.groups()
    try:
        payload = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("the uploaded image is not valid base64") from None
    if len(payload) > ICON_MAX_BYTES:
        raise ValueError(
            f"the uploaded image is {len(payload) // 1024} KB; the limit is 200 KB"
        )
    if not _looks_like(mime, payload):
        raise ValueError(f"the uploaded file is not a {mime.split('/')[1].split('+')[0].upper()} image")
    if mime == "image/svg+xml":
        for pattern, what in _SVG_DANGER:
            if pattern.search(payload):
                raise ValueError(
                    f"this SVG contains {what}; upload an SVG with shapes only, or a PNG"
                )
    return value


def field_error(
    field: str | list[str | int],
    message: str,
    value: Any,
    where: str = "body",
) -> RequestValidationError:
    """Build a refusal in exactly the shape FastAPI's own body validation
    produces, so a caller (and `formatApiError` in the frontend) does not
    have to special-case rules that happen to be checked by hand.

    `field` is a single body field, or a path into the body such as
    ``["cells", 3, "entity_ids"]`` -- the same `loc` Pydantic would give a
    failure inside a list item.

    `where` is the first `loc` segment. It defaults to ``"body"``, which is
    what every caller before Task 14d wanted; the expression filter arrives
    as a query parameter, and Pydantic's own refusals for those say
    ``"query"``, so a hand-raised one has to as well or a client keying on
    `loc` (Ruling 30) would not recognise it.
    """
    path = [field] if isinstance(field, str) else list(field)
    return RequestValidationError(
        [{"type": "value_error", "loc": (where, *path), "msg": message, "input": value}]
    )


def reject_null(value: Any, info) -> Any:
    """Pydantic field validator for PATCH bodies: omitting a field means
    "unchanged", but an explicit `null` for a NOT NULL column would
    otherwise reach the database as a 409 (`23502`) rather than a 422
    naming the field.

    Pydantic does not run validators on defaults, so this fires only when
    the client actually sent `null`."""
    if value is None:
        raise ValueError(f"{info.field_name} cannot be null")
    return value
