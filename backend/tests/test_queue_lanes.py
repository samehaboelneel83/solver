"""Short runs never wait behind long ones, and a long run is not passed for ever (the queue measured in October
2026: 26-second runs waited 35 minutes to 2 hours). Both are host settings: off, the queue is as before."""
from __future__ import annotations

from sqlalchemy import text

from app.solve.reserve import Capacity, Need, can_admit
from app.solve.service import claim_next, enqueue_run
from tests.test_quadratic import empty_queue  # noqa: F401
from tests.test_v1_problem_run import db, make_domain, make_model_version, make_problem, make_scenario  # noqa: F401

EMPTY_IR = {"version": 1, "sets": [], "parameters": {}, "variables": {}, "constraints": [],
            "objective": {"sense": "minimize", "terms": []}}


def test_long_runs_leave_the_short_reserve_free():
    cap = Capacity(20, 20480, 8, .25, short_share=.25, short_seconds=60)  # 5 threads kept for short runs
    held = [Need(6, 4096, 1, "planner"), Need(6, 4096, 1, "planner")]
    assert "kept for short runs" in can_admit(held, Need(6, 4096, 1, "planner"), cap)
    assert can_admit(held, Need(4, 4096, 1, "planner", short=True), cap) is None
    # Without a reserve, as before: the third long run fits the 16 threads? no -- 18 > 16; a 4-thread one does.
    assert can_admit(held, Need(4, 4096, 1, "planner"), Capacity(16, 20480, 8, .25)) is None


def _scenario(db, name):  # noqa: F811
    domain = make_domain(db, name)
    problem = make_problem(db, domain)
    scenario = make_scenario(db, problem, make_model_version(db, problem, ir=EMPTY_IR))
    db.commit()
    return scenario


def _queue(db, scenario, seconds, workers=None, ago=None):  # noqa: F811
    run_id = enqueue_run(db, scenario, time_limit=seconds, reuse=False)
    if workers:
        db.execute(text("UPDATE run SET params = params || jsonb_build_object('workers', :w) WHERE id = :r"),
                   {"w": workers, "r": run_id})
    if ago:
        db.execute(text("UPDATE run SET queued_at = now() - make_interval(secs => :s) WHERE id = :r"),
                   {"s": ago, "r": run_id})
    db.commit()
    return run_id


def _reason(db, run_id):  # noqa: F811
    return (db.execute(text("SELECT params FROM run WHERE id = :r"), {"r": run_id}).scalar_one() or {}).get("queue_reason")


def test_a_short_run_starts_while_long_runs_fill_their_share(db, empty_queue, monkeypatch):  # noqa: F811
    for k, v in {"SOLVE_HOST_WORKERS": "20", "SOLVE_WORKER_CPUS": "6", "SOLVE_HOST_MEMORY_MB": "20480",
                 "SOLVE_MEMORY_MB": "4096", "SOLVE_SHORT_SHARE": "0.25", "SOLVE_SHORT_SECONDS": "60"}.items():
        monkeypatch.setenv(k, v)
    scenario = _scenario(db, "lanes")
    long1, long2, long3 = (_queue(db, scenario, 300) for _ in range(3))
    short = _queue(db, scenario, 10)
    assert claim_next(db) == long1 and claim_next(db) == long2
    # The third long run would take the reserve: it waits, and the short run behind it starts.
    assert claim_next(db) == short
    assert "kept for short runs" in _reason(db, long3)
    params = db.execute(text("SELECT params FROM run WHERE id = :r"), {"r": short}).scalar_one()
    assert params["reservation"]["short"] is True and params["workers"] == 5
    assert claim_next(db) is None


def test_a_long_run_that_waited_too_long_is_not_passed_by_other_long_runs(db, empty_queue, monkeypatch):  # noqa: F811
    for k, v in {"SOLVE_HOST_WORKERS": "16", "SOLVE_WORKER_CPUS": "16", "SOLVE_HOST_MEMORY_MB": "65536",
                 "SOLVE_MEMORY_MB": "1024", "SOLVE_SHORT_SHARE": "0"}.items():
        monkeypatch.setenv(k, v)
    from app.solve import service

    monkeypatch.setattr(service, "STARVE_SECONDS", 600.0)
    scenario = _scenario(db, "starve")
    running = _queue(db, scenario, 300, workers=8, ago=3000)
    assert claim_next(db) == running
    big = _queue(db, scenario, 300, workers=16, ago=2000)    # needs the whole host; has waited 33 minutes
    small_long = _queue(db, scenario, 300, workers=4)       # would fit beside the running one
    quick = _queue(db, scenario, 10, workers=4)             # short
    assert claim_next(db) == quick                          # short runs still pass
    assert "waiting behind run" in _reason(db, small_long)  # the long one does not jump the queue
    assert "host workers exhausted" in _reason(db, big)
    assert claim_next(db) is None
