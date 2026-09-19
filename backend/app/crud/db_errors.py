"""Translate structured database trigger errors into HTTP responses.

Schema v1's DOMAIN validation triggers (``entity_validate``,
``relationship_validate``, ``parameter_value_validate`` -- migration
``0006_schema_v1_domain``) raise SQLSTATE **23514** (check_violation) with a
JSON ``DETAIL`` payload naming exactly which field failed and why (see
``backend/tests/test_v1_domain_triggers.py`` for the payload shapes: `kind`
one of `unknown_attribute`, `required_attribute`, `attribute_type`,
`type_mismatch`, `cardinality`, `cycle`, `parameter_index`; `field` the
attribute or relationship-type name, or absent for `parameter_index` which
carries `entity_ids` instead). psycopg2 raises `CheckViolation`, a subclass
of `IntegrityError`, and SQLAlchemy wraps it as `sqlalchemy.exc.IntegrityError`.

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
_CONFLICT_CODES = {"23503", "23505", "23502"}


def translate_db_error(exc: DBAPIError, table: str) -> HTTPException:
    """Map a DBAPIError raised by a v1 trigger (or a plain constraint) to an
    HTTPException, or re-raise `exc` unchanged if none of the known cases apply.

    - 23514 (check_violation) with a well-formed JSON DETAIL -> 422 naming
      the field and kind, per the Task 1 DETAIL contract.
    - 23514 without a parseable JSON DETAIL -> falls through to the 409
      path below (conflict_detail() still produces a reasonable message
      from pgcode "23514", even though it has no bespoke branch for it).
    - 23503 / 23505 / 23502 -> 409 via the existing conflict_detail(),
      reused unchanged.
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
                return HTTPException(
                    status_code=422,
                    detail={
                        "message": message,
                        "field": payload.get("field"),
                        "kind": payload.get("kind"),
                    },
                )
        # No parseable JSON DETAIL -- fall through to the generic 409 path.
        return HTTPException(status_code=409, detail=conflict_detail(exc, table))

    if code in _CONFLICT_CODES:
        return HTTPException(status_code=409, detail=conflict_detail(exc, table))

    if code == "P0001":
        message = getattr(diag, "message_primary", None) if diag is not None else None
        return HTTPException(status_code=409, detail=message or str(exc.orig).strip())

    raise exc
