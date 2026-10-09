"""On/off choices learnt from the problem's own runs: tried off only once it is safe, kept where faster."""
from __future__ import annotations

from app.solve.choices import RECHECK, TRIALS, decide


def run(on: bool, seconds: float, status: str = "optimal", gap: float | None = None, limit: float = 60.0):
    return {"on": on, "seconds": seconds, "status": status, "gap": gap, "limit": limit}


def test_on_until_proven_runs_make_trying_it_off_safe():
    assert decide("start", []).on
    assert decide("start", [run(True, 5.0)]).on
    assert decide("start", [run(True, 5.0, "feasible", 0.02)] * 3).on  # never proven: never tried off
    assert not decide("start", [run(True, 5.0)] * TRIALS).on


def test_kept_off_where_it_is_faster_and_on_where_it_is_needed():
    faster_off = [run(False, 2.0)] * TRIALS + [run(True, 5.0)] * TRIALS
    assert not decide("start", faster_off).on
    faster_on = [run(False, 9.0)] * TRIALS + [run(True, 5.0)] * TRIALS
    assert decide("start", faster_on).on
    unproven_off = [run(False, 60.0, "feasible", 0.01), run(True, 5.0), run(True, 5.0)]
    decided = decide("start", unproven_off)
    assert decided.on and "did not prove" in decided.evidence


def test_the_other_way_is_tried_again_after_a_while():
    history = [run(False, 2.0)] * RECHECK + [run(True, 5.0)] * TRIALS
    assert decide("start", history).on and "tried again" in decide("start", history).evidence
    assert not decide("start", history[1:]).on


from tests.test_quadratic import empty_queue  # noqa: E402,F401
from tests.test_v1_problem_run import db  # noqa: E402,F401


def test_a_problem_learns_whether_its_start_is_worth_building(db, empty_queue, steps_first):  # noqa: F811
    from sqlalchemy import text

    from app.solve.service import enqueue_run
    from app.worker import work_once
    from tests.test_benders import _facility
    from tests.test_v1_problem_run import make_domain, make_model_version, make_problem

    version = make_model_version(db, make_problem(db, make_domain(db, "learns")), _facility(2, 8, 20, tight=True))
    problem = db.execute(text("SELECT problem_id FROM model_version WHERE id = :v"), {"v": version}).scalar_one()
    scenario = db.execute(text("INSERT INTO scenario (problem_id, model_version_id, name) VALUES (:p, :v, 'base') "
                               "RETURNING id"), {"p": problem, "v": version}).scalar_one()
    db.commit()
    made = []
    for _ in range(TRIALS * 2 + 1):
        run_id = enqueue_run(db, scenario, time_limit=20.0, reuse=False)
        for _ in range(5):
            if db.execute(text("SELECT status FROM run WHERE id = :r"), {"r": run_id}).scalar_one() != "queued":
                break
            work_once(db)
        row = db.execute(text("SELECT status, params FROM run WHERE id = :r"), {"r": run_id}).mappings().one()
        assert row["status"] == "optimal"
        made.append(row["params"]["choices"]["start"])
    assert [m["on"] for m in made[:TRIALS * 2]] == [True] * TRIALS + [False] * TRIALS, made
    assert "median" in made[-1]["why"], made[-1]
