"""Relax-and-fix over a time horizon (app.solve.horizon, queue R9): a window at a time, a heuristic's answer."""

from __future__ import annotations

from sqlalchemy import text

from app.seed import seed_workforce_demo
from app.solve import compile_model, horizon
from app.solve.backends import by_name
from app.solve.service import claim_next, enqueue_run, execute_run, solve_compiled
from bench.families import generate
from tests.test_quadratic import empty_queue  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


def _rota(size="M"):
    case = generate("rota", size, 0)
    return compile_model(case.ir, case.data), [row["id"] for row in case.data["sets"]["day"]]


def _highs(model, seconds):
    return solve_compiled(by_name("highs"), model, time_limit=seconds, seed=1)[0]


def test_the_horizon_is_cut_into_even_consecutive_windows():
    days = [f"d{i}" for i in range(14)]
    cut = horizon.windows(days, 4)
    assert [len(w) for w in cut] == [4, 4, 4, 2] and sum(cut, []) == days
    assert horizon.windows(days[:5], 4) == [days[:3], days[3:5]]  # at least two periods a window


def test_a_window_holds_the_past_keeps_itself_whole_and_relaxes_the_future():
    compiled, days = _rota()
    positions = horizon.time_positions(compiled, "day")
    past = {key: 1 for key in compiled.variables if key[0] == "assign" and key[1][1] == days[0]}
    model = horizon.step(compiled, positions, set(days[1:3]), set(days[3:]), past)
    for key, var in model.variables.items():
        day = key[1][1] if key[0] == "assign" else None
        if day == days[0]:
            assert var.lower == var.upper == 1
        elif day in days[1:3]:
            assert var.domain == "binary"
        elif day in days[3:]:
            assert var.domain == "continuous" and var.upper == 1


def test_relax_and_fix_answers_the_whole_model_and_claims_nothing():
    compiled, days = _rota()
    whole = _highs(compiled, 30)
    rolled = horizon.solve(compiled, "day", days, _highs, time_limit=20)
    assert rolled.solution.status == "feasible" and not rolled.solution.optimal and rolled.solution.best_bound is None
    assert rolled.record["windows"] == len(horizon.windows(days))
    # A heuristic: never better than the proven optimum (rota minimizes), and here it reaches it.
    assert rolled.solution.objective >= whole.objective
    assert rolled.solution.objective <= whole.objective * 1.05


def test_what_it_refuses():
    compiled, days = _rota()
    assert horizon.applies(compiled, None, days) == "no set in this model is time (an entity type with the role time)"
    assert horizon.applies(compiled, "day", days[:3]) == "day has 3 periods: too few to cut into windows"
    assert horizon.applies(compiled, "day", days) is None


def test_a_run_rolls_the_workforce_demo_over_its_days(db, empty_queue):  # noqa: F811
    seeded = seed_workforce_demo(db)
    db.execute(text("INSERT INTO setting (scope, scope_id, key, value) VALUES ('problem', :p, 'solve.rolling_horizon', CAST('true' AS jsonb)),"
                    " ('problem', :p, 'solve.memory', CAST('false' AS jsonb))"), {"p": seeded["problem_id"]})
    db.commit()
    run_id = enqueue_run(db, seeded["scenario_id"], time_limit=20.0, reuse=False, solver="highs")
    claim_next(db)
    outcome = execute_run(db, run_id)
    row = db.execute(text("SELECT status, optimality, params FROM run WHERE id = :r"), {"r": run_id}).mappings().one()
    record = row["params"]["rolling_horizon_run"]
    assert record["used"] and record["time_set"] == "day" and record["windows"] >= 2, record
    assert outcome.status == "feasible" and row["optimality"] == "none"
    db.execute(text("DELETE FROM setting WHERE key = 'solve.rolling_horizon'"))
    db.commit()
