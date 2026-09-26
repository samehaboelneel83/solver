"""An organization's own licences for added solvers (queue R42, app.solve.licences).

    GET    /api/v1/solver-licences            each added solver: needs one? set? when, by whom, fingerprint
    PUT    /api/v1/solver-licences/{adapter}  {env?: {NAME: value}, file?: text} -- set or replace
    DELETE /api/v1/solver-licences/{adapter}

**Write-only.** No route returns a licence: not the values, not the file, not a part of either.
What comes back is whether one is set, when, by whom, and a 12-character fingerprint that tells
two licences apart. Setting and removing need `solver.configure`, the capability that already
decides who may choose a solver.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, requires
from app.core.db import get_db
from app.models.iam import UserAccount
from app.solve import licences
from app.solve.backends import REGISTRY, by_name

router = APIRouter(prefix="/api/v1", tags=["solvers"])


class LicenceWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    env: dict[str, str] | None = None
    file: str | None = None


def _adapter(name: str):
    backend = by_name(name)
    if backend is None or backend.origin != "adapter":
        raise HTTPException(status_code=404, detail=f"there is no added solver called {name!r}")
    return backend


def _state(db: Session, organization_id) -> dict[str, dict[str, Any]]:
    rows = db.execute(
        text("SELECT adapter, fingerprint, set_by, set_at FROM iam.solver_licence WHERE organization_id = :o"),
        {"o": organization_id},
    ).mappings().all()
    return {r["adapter"]: dict(r) for r in rows}


def licence_state(db: Session, organization_id, backend) -> str:
    """`not needed`, `set` or `missing`, for the Solvers list."""
    if backend.origin != "adapter" or not licences.spec(backend.manifest):
        return "not needed"
    stored = _state(db, organization_id).get(backend.name)
    if stored is not None:
        return "set"
    return "missing" if licences.required(backend) else "not needed"


@router.post("/solvers/{name}/conformance")
def run_conformance(name: str, db: Session = Depends(get_db),
                    user: UserAccount = Depends(requires("solver.configure"))) -> dict[str, Any]:
    """Run the conformance kit on an added solver now and keep the report (queue R43). An operator's
    act: passing makes the solver eligible to be chosen unasked for every organization. A solver
    that needs a licence is run with this organization's."""
    from app.solve import conformance, sandbox

    if not db.execute(text("SELECT app_is_operator()")).scalar_one():
        raise HTTPException(status_code=403, detail="only an operator runs the conformance kit")
    backend = _adapter(name)
    if not backend.is_available():
        raise HTTPException(status_code=409, detail=f"{name} is not available here")
    licence, missing = licences.for_solve(db, user.organization_id, backend)
    if missing:
        raise HTTPException(status_code=409, detail=missing)
    with sandbox.licensed(licence):
        report = conformance.run(backend)
    conformance.store(db, report, user.username)
    return {"adapter": name, "version": report.version, "passed": report.passed, "checks": report.checks}


@router.get("/solver-licences")
def list_licences(db: Session = Depends(get_db), user: UserAccount = Depends(get_current_user)) -> dict[str, Any]:
    stored = _state(db, user.organization_id)
    items = []
    for backend in REGISTRY:
        if backend.origin != "adapter" or not licences.spec(backend.manifest):
            continue
        wanted = licences.spec(backend.manifest)
        row = stored.get(backend.name)
        items.append({
            "adapter": backend.name,
            "required": bool(wanted.get("required")),
            "env": list(wanted.get("env") or []),
            "file": bool(wanted.get("file")),
            "set": row is not None,
            **({"fingerprint": row["fingerprint"], "set_by": row["set_by"], "set_at": row["set_at"]} if row else {}),
        })
    return {"items": items}


@router.put("/solver-licences/{adapter}")
def set_licence(adapter: str, payload: LicenceWrite, db: Session = Depends(get_db),
                user: UserAccount = Depends(requires("solver.configure"))) -> dict[str, Any]:
    backend = _adapter(adapter)
    try:
        licence = licences.checked(backend, payload.model_dump(exclude_none=True))
    except licences.LicenceRefused as exc:
        raise HTTPException(status_code=422,
                            detail=[{"type": exc.code, "loc": ["body"], "msg": str(exc)}]) from exc
    sealed, fingerprint = licences.seal(licence)
    db.execute(
        text(
            "INSERT INTO iam.solver_licence (organization_id, adapter, payload, fingerprint, set_by)"
            " VALUES (:o, :a, :p, :f, :u)"
            " ON CONFLICT (organization_id, adapter) DO UPDATE"
            " SET payload = EXCLUDED.payload, fingerprint = EXCLUDED.fingerprint,"
            "     set_by = EXCLUDED.set_by, set_at = now()"
        ),
        {"o": user.organization_id, "a": adapter, "p": sealed, "f": fingerprint, "u": user.username},
    )
    db.commit()
    return {"adapter": adapter, "set": True, "fingerprint": fingerprint}


@router.delete("/solver-licences/{adapter}", status_code=204, response_model=None)
def delete_licence(adapter: str, db: Session = Depends(get_db),
                   user: UserAccount = Depends(requires("solver.configure"))) -> None:
    _adapter(adapter)
    db.execute(text("DELETE FROM iam.solver_licence WHERE organization_id = :o AND adapter = :a"),
               {"o": user.organization_id, "a": adapter})
    db.commit()
