"""Host resource reservations for concurrent solves (OAAS S04).

A portfolio or retry must fit in the host's CPU, memory, and licence seats
before it starts. Shadow / suite work uses a separate **check** pool capped
at ``SOLVE_CHECK_SHARE`` of each resource so quality checks cannot starve
planner runs.

Env (host-wide, shared by every worker process):

* ``SOLVE_HOST_WORKERS`` — total solver threads (default 32)
* ``SOLVE_HOST_MEMORY_MB`` — total sandbox memory (default ``SOLVE_MEMORY_MB`` × 4)
* ``SOLVE_LICENSE_SEATS`` — concurrent commercial-licence seats (default 8)
* ``SOLVE_CHECK_SHARE`` — fraction reserved for shadow/suite (default 0.25)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Literal

Pool = Literal["planner", "check"]
CHECK_PURPOSES = frozenset({"shadow", "suite"})


@dataclass(frozen=True)
class Need:
    workers: int
    memory_mb: int
    license_seats: int
    pool: Pool


@dataclass(frozen=True)
class Capacity:
    workers: int
    memory_mb: int
    license_seats: int
    check_share: float


def host_capacity() -> Capacity:
    memory_default = int(os.environ.get("SOLVE_MEMORY_MB", "4096")) * 8
    share = float(os.environ.get("SOLVE_CHECK_SHARE", "0.25"))
    share = min(0.9, max(0.0, share))
    return Capacity(
        workers=max(1, int(os.environ.get("SOLVE_HOST_WORKERS", "32"))),
        memory_mb=max(64, int(os.environ.get("SOLVE_HOST_MEMORY_MB", str(memory_default)))),
        license_seats=max(1, int(os.environ.get("SOLVE_LICENSE_SEATS", "8"))),
        check_share=share,
    )


def need_for(
    *,
    purpose: str,
    workers: int,
    memory_mb: int | None,
    portfolio_size: int = 1,
    licensed_entrants: int = 0,
) -> Need:
    """What one run would occupy if it starts now.

    Portfolio entrants share the run's worker budget but each still opens its
    own sandbox (memory × size). Licensed commercial solvers each take a seat;
    an all-open-source portfolio still counts as one seat for accounting.
    """
    size = max(1, int(portfolio_size))
    mem = max(64, int(memory_mb or os.environ.get("SOLVE_MEMORY_MB", "4096")))
    seats = max(1, int(licensed_entrants)) if licensed_entrants > 0 else 1
    if size > 1 and licensed_entrants > 0:
        seats = max(seats, int(licensed_entrants))
    return Need(
        workers=max(1, int(workers)),
        memory_mb=mem * size,
        license_seats=seats,
        pool="check" if purpose in CHECK_PURPOSES else "planner",
    )


def _sum(held: list[Need], pool: Pool | None = None) -> tuple[int, int, int]:
    rows = held if pool is None else [n for n in held if n.pool == pool]
    return (
        sum(n.workers for n in rows),
        sum(n.memory_mb for n in rows),
        sum(n.license_seats for n in rows),
    )


def can_admit(held: list[Need], extra: Need, capacity: Capacity) -> str | None:
    """None when ``extra`` fits; otherwise a short reason for the run record."""
    w_all, m_all, s_all = _sum(held)
    if w_all + extra.workers > capacity.workers:
        return (
            f"host workers exhausted (need {extra.workers}, "
            f"{max(0, capacity.workers - w_all)} free of {capacity.workers})"
        )
    if m_all + extra.memory_mb > capacity.memory_mb:
        return (
            f"host memory exhausted (need {extra.memory_mb} MB, "
            f"{max(0, capacity.memory_mb - m_all)} free of {capacity.memory_mb})"
        )
    if s_all + extra.license_seats > capacity.license_seats:
        return (
            f"licence seats exhausted (need {extra.license_seats}, "
            f"{max(0, capacity.license_seats - s_all)} free of {capacity.license_seats})"
        )

    # Per-pool caps: checks stay within their share; planners keep the rest.
    check_w = max(1, int(capacity.workers * capacity.check_share))
    check_m = max(64, int(capacity.memory_mb * capacity.check_share))
    check_s = max(1, int(capacity.license_seats * capacity.check_share))

    w_pool, m_pool, s_pool = _sum(held, extra.pool)
    if extra.pool == "check":
        if w_pool + extra.workers > check_w:
            return (
                f"check pool workers exhausted (need {extra.workers}, "
                f"cap {check_w} for shadow/suite)"
            )
        if m_pool + extra.memory_mb > check_m:
            return (
                f"check pool memory exhausted (need {extra.memory_mb} MB, "
                f"cap {check_m} for shadow/suite)"
            )
        if s_pool + extra.license_seats > check_s:
            return (
                f"check pool licence seats exhausted (need {extra.license_seats}, "
                f"cap {check_s} for shadow/suite)"
            )
    # Planners may borrow idle check capacity. The aggregate checks above
    # still prevent oversubscription when a check is actually running.
    return None


def allocated_workers(requested: int, purpose: str, capacity: Capacity) -> int:
    """Fit a thread preference to the deployment, including already queued runs."""
    limit = min(capacity.workers, max(1, int(os.environ.get("SOLVE_WORKER_CPUS", str(capacity.workers)))))
    if purpose in CHECK_PURPOSES:
        limit = min(limit, max(1, int(capacity.workers * capacity.check_share)))
    return min(max(1, requested), limit)


def need_from_params(params: dict[str, Any] | None, purpose: str) -> Need | None:
    """Reconstruct a held reservation from a running run's params, if stamped."""
    stamped = (params or {}).get("reservation")
    if not isinstance(stamped, dict):
        return None
    try:
        return Need(
            workers=max(1, int(stamped["workers"])),
            memory_mb=max(64, int(stamped["memory_mb"])),
            license_seats=max(1, int(stamped["license_seats"])),
            pool="check" if stamped.get("pool") == "check" else "planner",
        )
    except (KeyError, TypeError, ValueError):
        return need_for(
            purpose=purpose,
            workers=int((params or {}).get("workers") or 8),
            memory_mb=(params or {}).get("memory_mb"),
        )


def as_params(need: Need) -> dict[str, Any]:
    return {
        "workers": need.workers,
        "memory_mb": need.memory_mb,
        "license_seats": need.license_seats,
        "pool": need.pool,
    }


def held_running(db, *, exclude_run_id: int | None = None) -> list[Need]:
    """Reservations already occupied by ``running`` rows (OAAS S04)."""
    from sqlalchemy import text

    rows = db.execute(
        text(
            "SELECT id, purpose, params FROM run WHERE status = 'running'"
            + (" AND id <> :x" if exclude_run_id is not None else "")
        ),
        {"x": exclude_run_id} if exclude_run_id is not None else {},
    ).mappings().all()
    held: list[Need] = []
    for row in rows:
        purpose = row["purpose"] or "plan"
        stamped = need_from_params(row["params"], purpose)
        if stamped is not None:
            held.append(stamped)
        else:
            held.append(
                need_for(
                    purpose=purpose,
                    workers=int((row["params"] or {}).get("workers") or 8),
                    memory_mb=(row["params"] or {}).get("memory_mb"),
                )
            )
    return held


def portfolio_fit(
    db,
    *,
    run_id: int,
    purpose: str,
    workers: int,
    memory_mb: int | None,
    candidates: list[str],
    licensed_names: set[str],
) -> tuple[Need, str | None]:
    """Whether a portfolio of ``candidates`` fits beside other running work.

    Returns ``(need, None)`` when it fits, or ``(need, reason)`` to skip.
    """
    need = need_for(
        purpose=purpose,
        workers=workers,
        memory_mb=memory_mb,
        portfolio_size=len(candidates),
        licensed_entrants=sum(1 for name in candidates if name in licensed_names),
    )
    why = can_admit(held_running(db, exclude_run_id=run_id), need, host_capacity())
    return need, why

