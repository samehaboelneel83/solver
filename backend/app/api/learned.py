"""Rules learnt from a problem's past plans (`app.solve.learn`).

    GET /api/v1/problems/{id}/learned-rules?source=approved|answered

`approved` (the default) learns from the plans people approved (`approved_plan`, superseded ones included:
each was approved once); `answered` from the problem's last `ANSWERED` answered runs -- what the model already
produces, useful only to see what its answers have in common. The model is the problem's latest version on
today's data. Each proposed rule is in the model's contract, ready to add; nothing is added here.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models.iam import UserAccount

router = APIRouter(prefix="/api/v1", tags=["problems"])

#: The most runs read for `source=answered` (and approved plans, newest first).
ANSWERED = 50


def _answers(db: Session, run_ids: list[int]) -> list[tuple[dict, dict | None]]:
    out = []
    for run_id in run_ids:
        row = db.execute(text("SELECT assignments, amounts FROM solution WHERE run_id = :r"), {"r": run_id}).one_or_none()
        if row is None:
            continue
        amounts = row[1]
        if amounts is None:
            amounts = {}
            for variable, rows in db.execute(text(
                    "SELECT variable, rows FROM solution_amount_chunk WHERE run_id = :r ORDER BY variable, chunk_index"),
                    {"r": run_id}).all():
                amounts.setdefault(variable, []).extend(rows or [])
        out.append((row[0] or {}, amounts))
    return out


@router.get("/problems/{problem_id}/learned-rules")
def learned_rules(problem_id: int, source: str = Query("approved", pattern="^(approved|answered)$"),
                  db: Session = Depends(get_db), _: UserAccount = Depends(get_current_user)) -> dict[str, Any]:
    from app.solve.compile import Unsupported, compile_model
    from app.solve.learn import learn, plans_from_answers
    from app.solve.preview import live_data

    problem = db.execute(text("SELECT id, domain_id FROM problem WHERE id = :p"), {"p": problem_id}).mappings().one_or_none()
    if problem is None:
        raise HTTPException(404, "problem not found")
    version = db.execute(text("SELECT id, version, ir FROM model_version WHERE problem_id = :p ORDER BY version DESC"
                              " LIMIT 1"), {"p": problem_id}).mappings().one_or_none()
    if version is None:
        raise HTTPException(422, {"code": "no_model", "message": "This problem has no published model yet."})
    if source == "approved":
        run_ids = [r for (r,) in db.execute(text(
            "SELECT run_id FROM approved_plan WHERE problem_id = :p ORDER BY approved_at DESC LIMIT :n"),
            {"p": problem_id, "n": ANSWERED}).all()]
    else:
        run_ids = [r for (r,) in db.execute(text(
            "SELECT r.id FROM run r JOIN scenario s ON s.id = r.scenario_id WHERE s.problem_id = :p"
            "   AND r.status IN ('optimal', 'feasible')"
            "   AND r.params->>'pareto_of' IS NULL AND r.params->>'alternative_of' IS NULL"
            " ORDER BY r.id DESC LIMIT :n"), {"p": problem_id, "n": ANSWERED}).all()]
    ir = version["ir"] or {}
    try:
        compiled = compile_model(ir, live_data(db, problem["domain_id"], ir))
    except Unsupported as exc:
        raise HTTPException(422, {"code": "does_not_compile", "message": str(exc)}) from exc
    plans = plans_from_answers(ir, _answers(db, run_ids))
    found = learn(ir, compiled, plans)
    return {**found, "source": source, "runs": run_ids, "version": version["version"]}
