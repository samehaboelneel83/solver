"""Translate structured database trigger errors into HTTP responses.

Schema v1's validation triggers raise SQLSTATE **23514**
(check_violation) with a JSON ``DETAIL`` payload naming exactly which field
failed and why (see ``backend/tests/test_v1_domain_triggers.py`` and
``test_v1_integrity_rules.py`` for the payload shapes). Ten `kind` values
exist, from two migrations:

``0006_schema_v1_domain`` -- `entity_validate`: `unknown_attribute`,
`required_attribute`, `attribute_type`; `relationship_validate`:
`type_mismatch`, `cardinality`, `cycle`; `parameter_value_validate`:
`parameter_index`.

``0009_snapshot_defaults_integrity_colour`` -- `parameter_def_validate`:
`index_type_domain`, `parameter_reindex` (both with ``field =
'index_type_ids'``); `entity_type_guard`: `index_type_in_use`, with
``field = 'domain_id'`` -- it is raised only for an UPDATE that moves an
entity type between domains. That trigger's **DELETE** path deliberately
does not use this shape: a DELETE has no request body to blame a field in,
so it raises **23503** naming ``parameter_def`` as the referencing table.
Unlike a real foreign key it has no ``constraint_name``, which is how the
conflict branch below tells the two apart: it forwards the trigger's
sentence (naming the parameters) rather than conflict_detail()'s generic
"still referenced by parameter_def records".

`field` is set by **every** one of the ten: the attribute name for
`entity_validate`'s kinds, the relationship type's *name* (not a column)
for `relationship_validate`'s, the literal ``'entity_ids'`` for
`parameter_index`, and a real column name for 0009's three. (An earlier
version of this docstring said `parameter_index` omitted `field`;
migration 0006 line 315 says otherwise.) psycopg2 raises `CheckViolation`,
a subclass of `IntegrityError`, and SQLAlchemy wraps it as
`sqlalchemy.exc.IntegrityError`.

One 422 body shape (Ruling 19)
------------------------------
A trigger's 422 is emitted in **FastAPI's own validation-error shape** --
a list of ``{"type", "loc", "msg"}`` entries -- with the trigger's `kind`
carried as a fourth, sibling key on the entry:

    {"detail": [{"type": "value_error",
                 "loc":  ["body", "<field>"],
                 "msg":  "<the trigger's message>",
                 "kind": "<kind>"}]}

Task 3 originally emitted a bare object ``{"message", "field", "kind"}``.
That gave the API two incompatible bodies under one status code -- every
client had to sniff ``Array.isArray(detail)`` before reading either -- so
it was normalised at this edge rather than in each consumer. `kind` is
kept because it is the only machine-readable discriminator a client has
for a trigger failure (task 8 surfaces `kind="parameter_index"`), and its
presence is also what distinguishes a database refusal from a request-
layer one now that the envelopes match.

The immutability trigger (``forbid_update``, migration
``0007_schema_v1_problem_run``) and ``snapshot_dataset()``'s IR-resolution
failures use a bare ``RAISE EXCEPTION``, which defaults to SQLSTATE
**P0001**. These carry a human-readable message but no JSON `DETAIL` and no
single field the caller could fix -- updating an immutable row or
referencing a stale IR name isn't a validation mistake in the payload, it's
a conflict with the row's current state. psycopg2 maps SQLSTATE class `P0`
to `InternalError` (concretely `psycopg2.errors.RaiseException`), wrapped by
SQLAlchemy as `sqlalchemy.exc.InternalError`.

Both are subclasses of `sqlalchemy.exc.DBAPIError`, so `translate_db_error`
keys on `exc.orig.pgcode` rather than the wrapper's Python type. Catching on
a wrapper type such as `ProgrammingError` (as an earlier draft of the task
brief for this module suggested) can never match either path:
`ProgrammingError` is reserved for SQLSTATE classes 20/21/3D/3F/42/44, none
of which apply to these triggers.
"""

import json

from fastapi import HTTPException
from sqlalchemy.exc import DBAPIError

from app.crud.errors import conflict_detail

# foreign_key_violation, unique_violation, not_null_violation -- the three
# classes conflict_detail() already knows how to describe.
#
# Note: this is narrower than the old bare `except IntegrityError` in
# factory.py, which caught every SQLSTATE class 23 (integrity_constraint_
# violation) and gave it a generic 409. A class-23 code outside this set --
# e.g. 23001 restrict_violation or 23P01 exclusion_violation -- now falls
# through to the final `raise exc` below and surfaces as a 500 instead.
# No table in this schema declares a RESTRICT FK action or an EXCLUDE
# constraint today, so this is currently unreachable, but a future one
# would need adding here (or a broader `code.startswith("23")` fallback).
_CONFLICT_CODES = {"23503", "23505", "23502"}


def translate_db_error(exc: DBAPIError, table: str) -> HTTPException:
    """Map a DBAPIError raised by a v1 trigger (or a plain constraint) to an
    HTTPException, or re-raise `exc` unchanged if none of the known cases apply.

    - 23514 (check_violation) with a well-formed JSON DETAIL -> 422 in the
      list shape described in the module docstring, one entry whose `loc`
      names the field and which carries the trigger's `kind`.
    - 23514 without a parseable JSON DETAIL -> falls through to the 409
      path below. conflict_detail() has no bespoke branch for "23514", so
      this returns its generic catch-all message rather than a tailored
      one -- still a reasonable 409, just not a field-specific one.
    - 23503 / 23505 / 23502 -> 409 via the existing conflict_detail(),
      reused unchanged -- except a 23503 with no ``constraint_name`` and
      a ``message_primary``. That is migration 0009's `entity_type_guard`
      DELETE (``TABLE = 'parameter_def'``): a real FK always names its
      constraint, and the trigger's sentence names the parameters, which
      conflict_detail() would drop.
    - P0001 (bare RAISE EXCEPTION: forbid_update immutability,
      snapshot_dataset IR-resolution failures) -> 409 with the trigger's
      own human message. Not a 422: there's no single field the caller can
      change to fix it, so this is a conflict, not a validation error.
    - anything else -> re-raised untouched, so unrelated DBAPIErrors keep
      surfacing as the 500 they already were rather than being silently
      swallowed into a misleading 409.
    """
    code = getattr(exc.orig, "pgcode", "") or ""
    diag = getattr(exc.orig, "diag", None)

    if code == "23514":
        raw_detail = getattr(diag, "message_detail", None) if diag is not None else None
        if raw_detail:
            try:
                payload = json.loads(raw_detail)
            except (TypeError, ValueError):
                payload = None
            if isinstance(payload, dict) and "kind" in payload:
                message = getattr(diag, "message_primary", None) or str(exc.orig).strip()
                field = payload.get("field")
                # No trigger omits `field` today, but a missing one must
                # blame the body as a whole (`["body"]`), never produce
                # `["body", None]` -- which a client would render as the
                # literal text "None: ...".
                loc = ["body", str(field)] if field not in (None, "") else ["body"]
                return HTTPException(
                    status_code=422,
                    detail=[
                        {
                            "type": "value_error",
                            "loc": loc,
                            "msg": message,
                            "kind": payload.get("kind"),
                        }
                    ],
                )
        # No parseable JSON DETAIL -- fall through to the generic 409 path.
        return HTTPException(status_code=409, detail=conflict_detail(exc, table))

    if code in _CONFLICT_CODES:
        if code == "23503":
            constraint = (
                (getattr(diag, "constraint_name", None) or "") if diag is not None else ""
            )
            primary = getattr(diag, "message_primary", None) if diag is not None else None
            # A RAISE ... USING ERRCODE '23503' has a TABLE but no CONSTRAINT,
            # which is how entity_type_guard's DELETE is told apart from a
            # real foreign key. Forward the trigger sentence; conflict_detail
            # would rewrite it to "still referenced by {table} records".
            if not constraint and primary:
                return HTTPException(status_code=409, detail=primary)
        return HTTPException(status_code=409, detail=conflict_detail(exc, table))

    if code == "P0001":
        message = getattr(diag, "message_primary", None) if diag is not None else None
        return HTTPException(status_code=409, detail=message or str(exc.orig).strip())

    raise exc
