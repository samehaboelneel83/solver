"""The learned solver selector (app.solve.selector, queue R11): a pick from evidence, recorded, acting on nothing."""

from __future__ import annotations

from sqlalchemy import text

from app.seed import seed_workforce_demo
from app.solve import selector
from app.solve.service import claim_next, enqueue_run, execute_run
from tests.test_quadratic import empty_queue  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


def fp(variables, binary, rows, cover=0, general=0):
    return {"variables": variables, "binary": binary, "integer": 0, "continuous": variables - binary, "auxiliary": 0,
            "rows": rows, "nnz": variables * 3, "rows_cover": cover, "rows_general": general, "density": 0.01,
            "coef_range_log10": 0.0, "bounds_declared": 1.0, "objective_degree": 1, "integral_data": True, "blocks": 1}


# Two shapes: all yes-or-no with cover rows (CP-SAT proved them first), all continuous with general rows (HiGHS).
BINARY = [(selector.features(fp(600, 600, 250, cover=250)), "cp-sat", "rota"),
          (selector.features(fp(900, 900, 400, cover=400)), "cp-sat", "rota"),
          (selector.features(fp(300, 300, 100, cover=100)), "cp-sat", "rota_teams")]
MIXED = [(selector.features(fp(1200, 15, 1300, general=1300)), "highs", "facility"),
         (selector.features(fp(3000, 40, 3300, general=3300)), "highs", "facility"),
         (selector.features(fp(2000, 30, 2100, general=2100)), "highs", "facility_regions")]
EXAMPLES = BINARY + MIXED


def test_it_picks_what_the_nearest_models_proved_fastest():
    guess = selector.predict(fp(700, 700, 300, cover=300), ["cp-sat", "highs", "scip"], examples=EXAMPLES)
    assert guess["pick"] == "cp-sat" and "rota" in guess["like"]
    guess = selector.predict(fp(2500, 35, 2600, general=2600), ["highs", "scip"], examples=EXAMPLES)
    assert guess["pick"] == "highs" and guess["confidence"] >= 0.6


def test_it_never_suggests_a_backend_the_rules_do_not_admit():
    guess = selector.predict(fp(700, 700, 300, cover=300), ["highs", "scip"], examples=EXAMPLES)
    assert guess["pick"] == "highs"  # the only admissible one with evidence
    assert selector.predict(fp(700, 700, 300), ["glop"], examples=EXAMPLES) is None


def test_a_family_can_be_left_out_so_it_is_judged_on_models_it_has_not_seen():
    guess = selector.predict(fp(700, 700, 300, cover=300), ["cp-sat", "highs"], examples=EXAMPLES, exclude_family="rota")
    assert "rota" not in guess["like"]


def test_nothing_to_go_on_is_no_pick():
    assert selector.predict(None, ["cp-sat"]) is None
    assert selector.predict(fp(10, 10, 5), [], examples=EXAMPLES) is None


def test_every_run_records_the_pick_beside_the_rules_and_the_rules_still_solve(db, empty_queue):  # noqa: F811
    seeded = seed_workforce_demo(db)
    run_id = enqueue_run(db, seeded["scenario_id"], time_limit=10.0, reuse=False)
    claim_next(db)
    execute_run(db, run_id)
    params = db.execute(text("SELECT params FROM run WHERE id = :r"), {"r": run_id}).scalar_one()
    if selector.DATA.exists():
        record = params["selector"]
        assert record["chosen"] == params["chosen_solver"]  # the rules' choice solved it
        assert record["agree"] == (record["pick"] == record["chosen"])
        assert 0 < record["confidence"] <= 1
