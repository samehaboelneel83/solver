"""A run as GenUI events (`app/genui/protocol.json`), Phase 1 of the GenUI plan.

    GET /api/v1/runs/{id}/genui

Server-sent events, one `genui` event per frame. The run's recorded events
(`app.api.run_events.records`) go through `app.genui.translate`; the stream
always starts from the beginning, and a client that reconnects rebuilds its
components by id (a `component.created` for an id it has is an upsert), so
nothing needs resuming.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.run_events import records
from app.core.db import get_db
from app.genui.translate import Translator
from app.models.iam import UserAccount
from app.models.v1_problem import Run

router = APIRouter(prefix="/api/v1", tags=["genui"])


def _frames(events: list[dict[str, Any]], counter: list[int]) -> str:
    out = ""
    for event in events:
        counter[0] += 1
        out += f"id: {counter[0]}\nevent: genui\ndata: {json.dumps(event, default=str)}\n\n"
    return out


async def _stream(translator: Translator, run_id: int) -> AsyncIterator[str]:
    counter = [0]
    yield _frames(translator.opening(), counter)
    async for item in records(run_id, 0):
        if item[0] == "event":
            _, _seq, kind, payload, _at = item
            frames = _frames(translator.feed(kind, payload), counter)
            if frames:
                yield frames
        elif item[0] == "alive":
            yield ": keep-alive\n\n"
        else:
            yield _frames(translator.settle(item[1]), counter)


@router.get("/runs/{run_id}/genui")
def run_genui(
    run_id: int,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
) -> StreamingResponse:
    # Read under the caller's tenant: another organization's run is not found.
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    ir = db.execute(
        text("SELECT mv.ir FROM scenario s JOIN model_version mv ON mv.id = s.model_version_id WHERE s.id = :s"),
        {"s": run.scenario_id},
    ).scalar_one_or_none() or {}
    spatial = any(isinstance(c, dict) and "connected" in c for c in ir.get("constraints", []))
    translator = Translator(
        run_id, status=str(run.status), time_limit_s=(run.params or {}).get("time_limit_s"), spatial=spatial
    )
    return StreamingResponse(
        _stream(translator, run_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
