"""Optimistic concurrency for the three tables that have an editable form.

Ruling 42. `entity`, `entity_type` and `relationship_type` each carry an
`updated_at` maintained by a database trigger (migration ``0010``). A read
route returns it; a form sends it back on save; :func:`check_not_stale`
refuses the save with a **409** when the stored value has moved on.

Why a 409 with a string ``detail``
----------------------------------
The platform has exactly two refusal bodies (Ruling 19): a list-shaped 422
for "this field is wrong", and ``{"detail": "<text>"}`` with a 409 for
"this conflicts with the row's current state". A concurrent edit is the
second: no field in the payload is wrong, and re-sending the same payload
unchanged would be refused again. It is the same status the immutability
trigger and the unique-key violations already use.

Why the message has a fixed leading clause
------------------------------------------
:data:`STALE_PREFIX` is what the browser matches on to tell this 409 apart
from the other 409 a save can get -- ``UNIQUE (entity_type_id, key)``,
which is a field error the form pins to the key box. A 409 carries no
machine-readable ``kind``; the 422 shape's ``kind`` key has no equivalent
here, and inventing an object ``detail`` would give the API a third body
shape for one case. Both sides' tests assert this constant, so the coupling
is pinned rather than implied.

Why the row is locked
---------------------
Reading the row, comparing, and then writing it is three steps; without a
lock a second client can commit between the comparison and the write, and
the check would pass while the edit it exists to catch is lost. The read
therefore takes ``FOR UPDATE`` **when, and only when, the payload carries a
timestamp** -- a caller that does not opt in to the check keeps exactly the
locking it had before. The lock is held for the few statements until the
request's commit, and the row is one the request is about to UPDATE anyway.
"""

from datetime import datetime

from fastapi import HTTPException

# The browser matches this (see `frontend/src/api/errors.ts`
# `isStaleRecordError`). Changing it is a wire-contract change.
STALE_PREFIX = "changed by someone else"


def stale_record_conflict(label: str) -> HTTPException:
    """The 409 a save built on a superseded read is refused with."""
    return HTTPException(
        status_code=409,
        detail=(
            f"This {label} was {STALE_PREFIX} after this form loaded it. "
            f"Reload the {label} and apply your changes to the current version."
        ),
    )


def check_not_stale(label: str, stored: datetime, expected: datetime | None) -> None:
    """Refuse a save built on a read older than the row's current state.

    `expected` is what the client last read. ``None`` means the client did
    not opt in to the check -- every route keeps working for callers that
    predate migration 0010 (the graph's inline node rename, `curl`, the
    seed), and the three forms that can lose a concurrent edit send it.
    """
    if expected is None:
        return
    if stored != expected:
        raise stale_record_conflict(label)


__all__ = ["STALE_PREFIX", "check_not_stale", "stale_record_conflict"]
