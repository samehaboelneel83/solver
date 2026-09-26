"""OAAS S04 — reserve CPU, memory, and license seats before portfolios / retries."""

from __future__ import annotations

from app.solve.reserve import Capacity, Need, can_admit, host_capacity, need_for


def test_plan_run_needs_its_workers_one_seat_and_planner_pool():
    need = need_for(purpose="plan", workers=8, memory_mb=1024, portfolio_size=1, licensed_entrants=0)
    assert need == Need(workers=8, memory_mb=1024, license_seats=1, pool="planner")


def test_shadow_and_suite_use_the_check_pool():
    assert need_for(purpose="shadow", workers=4, memory_mb=512).pool == "check"
    assert need_for(purpose="suite", workers=4, memory_mb=512).pool == "check"
    assert need_for(purpose="probe", workers=4, memory_mb=512).pool == "planner"


def test_portfolio_multiplies_memory_and_license_seats_not_workers():
    # Threads are shared across entrants; each sandbox still needs its own
    # memory envelope, and each licensed solver occupies a seat.
    need = need_for(
        purpose="plan",
        workers=8,
        memory_mb=1024,
        portfolio_size=3,
        licensed_entrants=2,
    )
    assert need.workers == 8
    assert need.memory_mb == 3072
    assert need.license_seats == 2


def test_unlicensed_portfolio_still_takes_one_seat_for_accounting():
    need = need_for(purpose="plan", workers=8, memory_mb=512, portfolio_size=2, licensed_entrants=0)
    assert need.license_seats == 1


def test_host_capacity_reads_env(monkeypatch):
    monkeypatch.setenv("SOLVE_HOST_WORKERS", "16")
    monkeypatch.setenv("SOLVE_HOST_MEMORY_MB", "8192")
    monkeypatch.setenv("SOLVE_LICENSE_SEATS", "4")
    monkeypatch.setenv("SOLVE_CHECK_SHARE", "0.25")
    cap = host_capacity()
    assert cap == Capacity(workers=16, memory_mb=8192, license_seats=4, check_share=0.25)


def test_admit_when_host_has_room():
    cap = Capacity(workers=16, memory_mb=4096, license_seats=4, check_share=0.25)
    # Planner floor is 12 workers; two runs of 4 fit comfortably.
    held = [Need(workers=4, memory_mb=1024, license_seats=1, pool="planner")]
    extra = Need(workers=4, memory_mb=1024, license_seats=1, pool="planner")
    assert can_admit(held, extra, cap) is None


def test_refuse_when_workers_exhausted():
    cap = Capacity(workers=16, memory_mb=4096, license_seats=4, check_share=0.25)
    held = [Need(workers=12, memory_mb=512, license_seats=1, pool="planner")]
    extra = Need(workers=8, memory_mb=512, license_seats=1, pool="planner")
    why = can_admit(held, extra, cap)
    assert why is not None
    assert "workers" in why


def test_refuse_when_memory_exhausted():
    cap = Capacity(workers=32, memory_mb=2048, license_seats=8, check_share=0.25)
    held = [Need(workers=4, memory_mb=1536, license_seats=1, pool="planner")]
    extra = Need(workers=4, memory_mb=1024, license_seats=1, pool="planner")
    why = can_admit(held, extra, cap)
    assert why is not None
    assert "memory" in why


def test_refuse_when_license_seats_exhausted():
    cap = Capacity(workers=32, memory_mb=8192, license_seats=2, check_share=0.25)
    held = [Need(workers=4, memory_mb=512, license_seats=2, pool="planner")]
    extra = Need(workers=4, memory_mb=512, license_seats=1, pool="planner")
    why = can_admit(held, extra, cap)
    assert why is not None
    assert "licence" in why or "license" in why


def test_check_pool_cannot_consume_planner_floor():
    # 25% of 16 workers = 4 for checks; a fifth check worker is refused even
    # when the host still has free planner capacity.
    cap = Capacity(workers=16, memory_mb=8192, license_seats=8, check_share=0.25)
    held = [Need(workers=4, memory_mb=512, license_seats=1, pool="check")]
    extra = Need(workers=1, memory_mb=256, license_seats=1, pool="check")
    why = can_admit(held, extra, cap)
    assert why is not None
    assert "check" in why


def test_planner_keeps_room_even_when_checks_want_more():
    cap = Capacity(workers=16, memory_mb=8192, license_seats=8, check_share=0.25)
    held = [
        Need(workers=12, memory_mb=1024, license_seats=1, pool="planner"),
        Need(workers=4, memory_mb=512, license_seats=1, pool="check"),
    ]
    # Planner floor is 75% = 12; already full of planners, so another planner waits.
    why = can_admit(held, Need(workers=1, memory_mb=256, license_seats=1, pool="planner"), cap)
    assert why is not None
    assert "workers" in why


def test_portfolio_fit_skips_when_host_is_full(monkeypatch):
    from app.solve import reserve as reserve_rows

    monkeypatch.setenv("SOLVE_HOST_WORKERS", "32")
    monkeypatch.setenv("SOLVE_HOST_MEMORY_MB", "16384")
    monkeypatch.setenv("SOLVE_LICENSE_SEATS", "1")
    monkeypatch.setenv("SOLVE_CHECK_SHARE", "0.25")
    monkeypatch.setattr(
        reserve_rows,
        "held_running",
        lambda db, exclude_run_id=None: [
            Need(workers=4, memory_mb=512, license_seats=1, pool="planner")
        ],
    )
    need, why = reserve_rows.portfolio_fit(
        db=None,
        run_id=99,
        purpose="plan",
        workers=8,
        memory_mb=512,
        candidates=["cp-sat", "highs"],
        licensed_names=set(),
    )
    assert need.license_seats == 1
    assert why is not None
    assert "licence" in why


def test_portfolio_fit_admits_when_host_has_room(monkeypatch):
    from app.solve import reserve as reserve_rows

    monkeypatch.setenv("SOLVE_HOST_WORKERS", "32")
    monkeypatch.setenv("SOLVE_HOST_MEMORY_MB", "16384")
    monkeypatch.setenv("SOLVE_LICENSE_SEATS", "8")
    monkeypatch.setenv("SOLVE_CHECK_SHARE", "0.25")
    monkeypatch.setattr(reserve_rows, "held_running", lambda db, exclude_run_id=None: [])
    need, why = reserve_rows.portfolio_fit(
        db=None,
        run_id=1,
        purpose="plan",
        workers=8,
        memory_mb=1024,
        candidates=["cp-sat", "highs"],
        licensed_names=set(),
    )
    assert why is None
    assert need.memory_mb == 2048
