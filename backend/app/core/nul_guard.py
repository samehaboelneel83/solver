"""Refuse a request carrying a NUL (U+0000) with a 422, once, for every route.

PostgreSQL `text` cannot hold U+0000, and psycopg2 refuses to adapt a
Python string containing one. It refuses with a **bare `ValueError`** --
"A string literal cannot contain NUL (0x00) characters." -- raised while
adapting the parameter, before any statement is sent. There is no
SQLSTATE, so SQLAlchemy does not wrap it in a `DBAPIError`, so
`app.crud.db_errors.translate_db_error` cannot see it: that function keys
on `exc.orig.pgcode`, and there is no `orig`. Every one of these was an
unhandled 500.

Review found four reachable paths -- a NUL in an `attrs` value, in
`entity.key`, in `?q=` and in `?expr=` -- and this module deliberately
does not fix four things. A NUL is illegal in *every* string that reaches
the database, on every route that exists now and every route added later;
`?q=` alone is on three routers. So the check is made once, at the edge,
before routing, and a new router inherits it rather than having to
remember it. (A fifth path the review did not list, the form-encoded
`username` of `POST /api/auth/login`, is closed by the same code; see
`tests/test_nul_guard.py`.)

What it inspects
----------------
* the **query string** of every request, key and value;
* the **body**, when the content type is JSON or form-encoded.

Nothing else. A `multipart/form-data` or `application/octet-stream` body
is passed through untouched and unbuffered: binary payloads legitimately
contain NUL bytes, and the day this application grows a file upload, a
guard that scanned it would be a bug rather than a protection. Path
segments are not inspected either -- every path parameter in this API is
a bigint or a UUID, both of which already 422 on anything else.

Cost, and why buffering the body is safe here
---------------------------------------------
Both checks start with a fast byte test (`\\x00`, `%00`, or the six
characters `\\u0000`) on the raw bytes. A request that does not contain
those bytes is never parsed, so the normal path is one substring search
over the query string and one over the body.

The body has to be buffered to be inspected, and then replayed to the
application. That adds no exposure that was not already there: the only
content types buffered are the ones every FastAPI route handler already
reads whole (`await request.json()` / `await request.form()`), so the peak
memory for a request is unchanged.

Shape of the refusal
--------------------
FastAPI's own list-shaped validation error (Ruling 19 -- the platform has
exactly one 422 body), so `formatApiError` and every other consumer render
it with no special case::

    {"detail": [{"type": "value_error",
                 "loc":  ["body", "attrs", "full_name"],
                 "msg":  "... must not contain a NUL ...",
                 "input": null}]}

`loc` names the field precisely, including a path into a nested object or
list, exactly as Pydantic would. `kind` is absent, which is what
distinguishes a request-layer refusal from a database trigger's.

`input` is `null` rather than the offending value: echoing a string back
with a NUL still in it only hands the problem to whatever renders the
error.

Ordering
--------
This runs before authentication, so an unauthenticated request carrying a
NUL is answered 422 and not 401. That is deliberate: the decision needs no
user and no database, and it discloses only that NUL is not accepted.
`tests/test_nul_guard.py::test_the_guard_runs_before_authentication` pins
it so it stays a decision.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qsl

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

NUL = "\x00"

MESSAGE = (
    "must not contain a NUL (U+0000) character: PostgreSQL text values "
    "cannot store one"
)

# A body worth inspecting: the two content types this API actually accepts
# and every route handler already reads in full.
_JSON_TYPES = ("application/json", "+json")
_FORM_TYPE = "application/x-www-form-urlencoded"

# Cheap pre-tests on raw bytes, one set per place a NUL can hide. Each is
# only a filter: whatever trips it is then decoded and checked properly,
# so a false positive here costs a parse and nothing else.
#
# * `\x00` -- the byte itself.
# * `%00` -- its percent-encoding, in a query string or a form body.
# * `\u0000` -- its JSON escape. `json.dumps` emits this for every control
#   character, so a JSON *document carried in a query parameter* (`?expr=`
#   is one) contains no NUL byte at all until it is parsed. The marker is
#   looked for without the backslash, because the backslash itself is
#   percent-encoded to `%5C` on the way in.
_JSON_BODY_MARKERS = (b"\x00", b"\\u0000")
_FORM_BODY_MARKERS = (b"\x00", b"%00")
_QUERY_MARKERS = (b"\x00", b"%00", b"u0000", b"U0000")
_JSON_ESCAPES = ("\\u0000", "\\U0000")


def _find_nul(node: Any) -> list[str | int] | None:
    """The `loc` path to the first string containing a NUL, or None.

    Iterative rather than recursive: the input is attacker-supplied and a
    deep enough document would otherwise raise `RecursionError`, i.e.
    trade one 500 for another. Dict keys are checked as well as values --
    `attrs` keys become column-like names in a jsonb object and are just
    as unstorable.
    """
    stack: list[tuple[Any, tuple[str | int, ...]]] = [(node, ())]
    while stack:
        current, path = stack.pop()
        if isinstance(current, str):
            if NUL in current:
                return list(path)
        elif isinstance(current, dict):
            for key, value in current.items():
                if isinstance(key, str) and NUL in key:
                    return [*path, key]
                stack.append((value, (*path, key)))
        elif isinstance(current, list):
            for index, value in enumerate(current):
                stack.append((value, (*path, index)))
    return None


def _refusal(loc: list[str | int]) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "detail": [
                {"type": "value_error", "loc": loc, "msg": MESSAGE, "input": None}
            ]
        },
    )


def _json_document_refusal(value: str, loc: list[str | int]) -> JSONResponse | None:
    """A query parameter (or form field) whose value is itself a JSON
    document is inspected as one.

    `?expr=` is such a parameter: `json.dumps` escapes a NUL to `\\u0000`,
    so the document travels with no NUL byte in it and only becomes one
    when the route parses it -- after which it is bound straight into a
    statement. The `loc` continues into the document the same way
    `entities.py::_expression_filter` reports a refusal, so a client
    keying on `loc` (Ruling 30) can point at the rule.

    A value that merely *contains the text* `\\u0000` and is not JSON is
    left alone: six ordinary characters are not a NUL.
    """
    if not any(escape in value for escape in _JSON_ESCAPES):
        return None
    try:
        document = json.loads(value)
    except (ValueError, RecursionError):
        return None
    found = _find_nul(document)
    return _refusal([*loc, *found]) if found is not None else None


def _query_refusal(query_string: bytes) -> JSONResponse | None:
    if not any(marker in query_string for marker in _QUERY_MARKERS):
        return None
    raw = query_string.decode("utf-8", errors="replace")
    for name, value in parse_qsl(raw, keep_blank_values=True):
        if NUL in name:
            return _refusal(["query", name])
        if NUL in value:
            return _refusal(["query", name])
        nested = _json_document_refusal(value, ["query", name])
        if nested is not None:
            return nested
    return None


def _body_refusal(content_type: str, body: bytes) -> JSONResponse | None:
    if not body:
        return None
    lowered = content_type.lower()
    if any(token in lowered for token in _JSON_TYPES):
        if not any(marker in body for marker in _JSON_BODY_MARKERS):
            return None
        try:
            document = json.loads(body)
        except (ValueError, RecursionError):
            # Not JSON we can read. FastAPI's own body parsing will answer
            # it; refusing here would replace its precise message with a
            # vaguer one.
            return None
        found = _find_nul(document)
        return _refusal(["body", *found]) if found is not None else None
    if _FORM_TYPE in lowered:
        if not any(marker in body for marker in _FORM_BODY_MARKERS):
            return None
        pairs = parse_qsl(body.decode("utf-8", errors="replace"), keep_blank_values=True)
        for name, value in pairs:
            if NUL in value or NUL in name:
                return _refusal(["body", name])
    return None


def _should_inspect_body(content_type: str) -> bool:
    lowered = content_type.lower()
    return _FORM_TYPE in lowered or any(token in lowered for token in _JSON_TYPES)


def _content_type(scope: Scope) -> str:
    for key, value in scope.get("headers", ()):
        if key == b"content-type":
            return value.decode("latin-1")
    return ""


async def _drain(receive: Receive) -> tuple[bytes, list[Message]]:
    """Read the whole request body, keeping the messages so they can be
    replayed to the application unchanged."""
    messages: list[Message] = []
    chunks: list[bytes] = []
    while True:
        message = await receive()
        messages.append(message)
        if message["type"] != "http.request":
            break
        chunks.append(message.get("body", b""))
        if not message.get("more_body", False):
            break
    return b"".join(chunks), messages


def _replay(messages: list[Message], upstream: Receive) -> Receive:
    """The drained messages, then the real connection's own. Answering
    `http.disconnect` once the body was replayed told a streamed response to
    a POST (the assistant's chat) that the client had gone, and Starlette
    stopped the stream before its first line."""
    queue = list(messages)

    async def receive() -> Message:
        if queue:
            return queue.pop(0)
        return await upstream()

    return receive


class NulByteGuard:
    """ASGI middleware. Add it with
    ``app.add_middleware(NulByteGuard)`` -- it is written against the raw
    ASGI interface rather than Starlette's `BaseHTTPMiddleware` because
    the latter cannot read a request body without consuming it.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        refusal = _query_refusal(scope.get("query_string", b""))

        if refusal is None and _should_inspect_body(_content_type(scope)):
            body, messages = await _drain(receive)
            receive = _replay(messages, receive)
            refusal = _body_refusal(_content_type(scope), body)

        if refusal is not None:
            await refusal(scope, receive, send)
            return

        await self.app(scope, receive, send)
