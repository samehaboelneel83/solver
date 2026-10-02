"""Watching a run as it is solved (migration 0036, target roadmap Phase 8).

    GET /api/v1/runs/{id}/events

Server-sent events. Everything recorded so far is replayed first -- so a
finished run shows its whole curve, and a reconnecting client passes
`Last-Event-ID` and gets only what it missed -- then the stream waits on
Postgres `LISTEN` for what the worker records next, and closes once the run
has settled.

The connection is the browser's for as long as the solve takes, so it does
not use a request session: it borrows a connection of its own and gives it
back at the end. What may be read was decided before the stream opened, by
loading the run under the caller's own tenant (row-level security); after
that, every query is by that run's id.
"""

from __future__ import annotations

import asyncio
import json
import select
import threading
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import engine, get_db
from app.models.iam import UserAccount
from app.models.v1_problem import Run

router = APIRouter(prefix="/api/v1", tags=["runs"])

SETTLED = ("optimal", "feasible", "infeasible", "unbounded", "unknown", "error", "cancelled")
# Long enough not to chatter, short enough that a dead connection is noticed
# and a proxy does not time the stream out while a solver thinks.
HEARTBEAT_SECONDS = 15.0


def _frame(seq: int, kind: str, data: dict[str, Any]) -> str:
    return f"id: {seq}\nevent: {kind}\ndata: {json.dumps(data, default=str)}\n\n"


def _rows(cursor, run_id: int, after: int) -> list[tuple]:
    cursor.execute(
        "SELECT seq, kind, payload, at FROM run_event"
        " WHERE run_id = %s AND seq > %s ORDER BY seq",
        (run_id, after),
    )
    return cursor.fetchall()


def _status(cursor, run_id: int) -> str | None:
    cursor.execute("SELECT status FROM run WHERE id = %s", (run_id,))
    row = cursor.fetchone()
    return row[0] if row else None


def _wait(connection, seconds: float) -> None:
    """Block until Postgres notifies this connection, or `seconds` pass."""
    select.select([connection], [], [], seconds)
    connection.poll()
    connection.notifies.clear()


_FINAL = (
    "SELECT status::text, objective::float8, best_bound, gap, optimality, wall_time_s, solver, error"
    " FROM run WHERE id = %s"
)


async def records(run_id: int, after: int) -> AsyncIterator[tuple]:
    """The run's recorded events, then what it ended with:

    - `("event", seq, kind, payload, at)` for each `run_event`,
    - `("alive",)` each time the wait for more times out,
    - `("settled", final, replayed)` once, last -- `final` the run's record,
      `replayed` True when it had settled before its last event was read here.

    Shared by the events stream and the GenUI stream (`app.api.genui`).
    """
    # Every use of this connection runs off the event loop and under one lock: a query on the loop
    # stalls every request the server is handling, and psycopg2 does not take one connection from two
    # threads at once. (Benchmark, October 2026: a page left while its run solved closed the stream
    # mid-wait; the UNLISTEN on the loop then hung the whole API.)
    raw = await asyncio.to_thread(engine.raw_connection)
    connection = raw.driver_connection
    lock = threading.Lock()

    def locked(fn, *args):
        with lock:
            return fn(*args)

    def run(fn, *args):
        return asyncio.to_thread(locked, fn, *args)

    def opening():
        # Autocommit, because LISTEN must not sit inside a transaction that
        # holds a snapshot: this connection has to see rows the worker
        # commits while it watches. Put back before the connection returns
        # to the pool -- an autocommit connection handed to the next borrower
        # cannot take a savepoint, and SQLAlchemy uses those.
        connection.autocommit = True
        cur = connection.cursor()
        # This connection reads by run id, as system code: whether the caller
        # may watch this run was settled before the stream opened. Said here
        # rather than assumed, because a pooled connection last used by a
        # request would otherwise still be acting as that tenant -- and a
        # tenant with no organization set sees nothing at all.
        cur.execute("RESET ROLE")
        cur.execute("SELECT set_config('app.org_id', '', false)")
        cur.execute(f'LISTEN "run_{run_id}"')
        return cur

    def closing(cur) -> None:
        with lock:  # after any wait still in its thread has let go of the connection
            try:
                cur.execute(f'UNLISTEN "run_{run_id}"')
            except Exception:  # pragma: no cover -- a closed connection needs no unlisten
                pass
            try:
                connection.autocommit = False
            finally:
                raw.close()

    cursor = None
    try:
        cursor = await run(opening)
        last = after
        while True:
            ended = False
            for seq, kind, payload, at in await run(_rows, cursor, run_id, last):
                last = seq
                yield ("event", seq, kind, payload, at)
                if kind == "stage" and payload.get("stage") == "settled":
                    ended = True
            if ended:
                yield ("settled", await run(_final, cursor, run_id), False)
                break
            # A run that settled before this stream opened has no further
            # events to wait for; one still going is waited on.
            if await run(_status, cursor, run_id) in SETTLED and not await run(_rows, cursor, run_id, last):
                yield ("settled", await run(_final, cursor, run_id), True)
                break
            await run(_wait, connection, HEARTBEAT_SECONDS)
            yield ("alive",)
    finally:
        if cursor is None:
            raw.close()
        else:
            # On its own thread, never awaited: a stream closed by a client that left must not wait,
            # on the loop, for a wait still running in another thread.
            threading.Thread(target=closing, args=(cursor,), daemon=True).start()


def _final(cursor, run_id: int) -> dict[str, Any]:
    cursor.execute(_FINAL, (run_id,))
    row = cursor.fetchone()
    keys = ("status", "objective", "best_bound", "gap", "optimality", "wall_time_s", "solver", "error")
    return dict(zip(keys, row)) if row else {}


async def _stream(run_id: int, after: int) -> AsyncIterator[str]:
    async for item in records(run_id, after):
        if item[0] == "event":
            _, seq, kind, payload, at = item
            yield _frame(seq, kind, {"seq": seq, "kind": kind, "at": at, **payload})
        elif item[0] == "alive":
            yield ": keep-alive\n\n"
        elif item[2]:
            # Settled before the stream saw its last event: say so, as before.
            yield ": settled\n\n"


@router.get("/runs/{run_id}/events")
def run_events(
    run_id: int,
    last_event_id: int | None = Query(default=None, alias="last_event_id"),
    last_event_id_header: str | None = Header(default=None, alias="Last-Event-ID"),
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
) -> StreamingResponse:
    # Read under the caller's tenant: another organization's run is not found,
    # which is what makes everything after this safe to read by id alone.
    if db.get(Run, run_id) is None:
        raise HTTPException(status_code=404, detail="run not found")
    after = last_event_id if last_event_id is not None else _as_int(last_event_id_header)
    return StreamingResponse(
        _stream(run_id, after),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


def _as_int(value: str | None) -> int:
    try:
        return max(0, int(value or 0))
    except ValueError:
        return 0
