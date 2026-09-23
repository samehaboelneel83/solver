"""The run API: ask for an answer over HTTP, and read the one you got.

The interesting assertions are about what a *status* means, because that is
the whole contract of an endpoint that can legitimately answer "there is no
answer":

- an infeasible model is a **201 with `status: "infeasible"`**, not a 4xx.
  The request was fine; the model has no solution, and saying so is the
  answer;
- a model this compiler cannot express is likewise a run carrying its reason,
  so the gap is visible in the record rather than only in a log;
- a solved run reports which constraints held **and which gave**, because a
  roster with no account of what it broke is not usable by a planner.
"""

from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.main import app
from app.seed import seed_admin, seed_workforce_demo
from app.worker import work_once
from tests.test_v1_problem_run import db  # noqa: F401  (fixture)


@pytest.fixture(autouse=True)
def ensure_admin_seeded():
    """`TestClient(app)` does not run the startup hook that seeds the admin,
    so every API test file seeds it explicitly."""
    session = SessionLocal()
    seed_admin(session)
    session.close()


@pytest.fixture
def auth_headers():
    settings = get_settings()
    client = TestClient(app)
    response = client.post(
        "/api/auth/login",
        data={"username": settings.admin_username, "password": settings.admin_password},
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def seeded(db):
    """The shipped demo, whose scenario softens coverage -- the only reason
    an over-subscribed model has an answer at all."""
    created = seed_workforce_demo(db)
    db.commit()
    yield created
    db.execute(text("DELETE FROM domain WHERE id = :d"), {"d": created["domain_id"]})
    db.commit()


def test_submitting_queues_a_run_rather_than_solving_in_the_request(seeded, auth_headers, db):
    """Solving happens in a worker, so the answer is not in this response.
    The data is frozen here, though -- a run answers the question as it was
    asked, not as the domain becomes while it waits."""
    client = TestClient(app)

    response = client.post(
        f"/api/v1/scenarios/{seeded['scenario_id']}/runs",
        json={"time_limit_s": 30},
        headers=auth_headers,
    )

    assert response.status_code == 201, response.text
    queued = response.json()
    assert queued["status"] == "queued"
    assert queued["dataset_id"] is not None
    assert queued["assignments"] is None
    assert queued["finished_at"] is None


def test_running_a_scenario_returns_the_roster_and_what_it_broke(seeded, auth_headers, db):
    client = TestClient(app)

    response = client.post(
        f"/api/v1/scenarios/{seeded['scenario_id']}/runs",
        json={"time_limit_s": 30},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    # The worker does the solving; the API is read back afterwards, which is
    # exactly what a caller polling `GET /runs/{id}` does.
    work_once(db)
    run = client.get(f"/api/v1/runs/{response.json()['id']}", headers=auth_headers).json()

    assert run["status"] in ("optimal", "feasible")
    assert run["solver"] == "cp-sat"
    assert "ortools" in run["solver_version"]
    assert run["params"]["classified_as"] == "IP"
    assert run["params"]["time_limit_s"] == 30

    roster = run["assignments"]["assign"]
    assert roster and all(len(entry) == 3 for entry in roster)

    by_id = {c["constraint_id"]: c for c in run["constraints"]}
    assert set(by_id) == {
        "c_cover_demand",
        "c_one_shift_per_day",
        "c_max_hours",
        "c_north_region_lates",
    }
    # Softened coverage is what gives, and the run says where.
    assert by_id["c_cover_demand"]["satisfied"] is False
    assert by_id["c_cover_demand"]["total_violation"] > 0
    assert by_id["c_cover_demand"]["penalty_paid"] > 0
    assert by_id["c_cover_demand"]["violations"], "a broken constraint that names no instance"
    assert by_id["c_one_shift_per_day"]["satisfied"] is True
    # Slack is the residual, filled for every backend: a held rule with no
    # room left is 0, a broken preference is short.
    assert by_id["c_one_shift_per_day"]["slack"] is not None
    assert by_id["c_one_shift_per_day"]["slack"] >= 0
    assert by_id["c_cover_demand"]["slack"] is not None
    assert by_id["c_cover_demand"]["slack"] < 0
    # CP-SAT has no duals; a number here would be invented.
    assert by_id["c_one_shift_per_day"]["dual"] is None
    assert by_id["c_cover_demand"]["dual"] is None
    assert run["reduced_costs"] is None


def test_broken_constraints_are_listed_before_the_ones_that_held(seeded, auth_headers, db):
    """A planner reads this to find out what went wrong; making them scroll
    past the rules that worked is a small cruelty."""
    client = TestClient(app)

    queued = client.post(
        f"/api/v1/scenarios/{seeded['scenario_id']}/runs", headers=auth_headers
    ).json()
    work_once(db)
    run = client.get(f"/api/v1/runs/{queued['id']}", headers=auth_headers).json()

    satisfied_flags = [c["satisfied"] for c in run["constraints"]]
    assert satisfied_flags == sorted(satisfied_flags), "broken constraints must come first"


def test_an_unsolvable_model_is_a_recorded_run_not_a_client_error(db, auth_headers):
    """The demo's *original* model version predates the IR contract: its
    constraints carry a note and nothing to solve. That is a fact about the
    model, so it is a run with a reason -- a 4xx would blame the caller."""
    client = TestClient(app)
    domain = db.execute(
        text("INSERT INTO domain (name) VALUES ('runs-legacy') RETURNING id")
    ).scalar_one()
    problem = db.execute(
        text("INSERT INTO problem (domain_id, name) VALUES (:d, 'p') RETURNING id"),
        {"d": domain},
    ).scalar_one()
    version = db.execute(
        text(
            "INSERT INTO model_version (problem_id, ir) VALUES (:p, :ir) RETURNING id"
        ),
        {
            "p": problem,
            "ir": '{"version": 1, "sets": [], "parameters": {}, "variables": {},'
            ' "constraints": [{"id": "c_old", "note": "never expressed"}],'
            ' "objective": {"sense": "minimize", "terms": []}}',
        },
    ).scalar_one()
    scenario = db.execute(
        text(
            "INSERT INTO scenario (problem_id, model_version_id, name)"
            " VALUES (:p, :v, 's') RETURNING id"
        ),
        {"p": problem, "v": version},
    ).scalar_one()
    db.commit()

    try:
        response = client.post(f"/api/v1/scenarios/{scenario}/runs", headers=auth_headers)
        assert response.status_code == 201
        work_once(db)
        run = client.get(f"/api/v1/runs/{response.json()['id']}", headers=auth_headers).json()

        assert run["status"] == "error"
        assert "no expression" in run["error"]
        assert run["assignments"] is None, "no answer is not the same as an empty answer"
    finally:
        db.execute(text("DELETE FROM domain WHERE id = :d"), {"d": domain})
        db.commit()


def test_an_infeasible_run_says_which_rules_cannot_hold_together(db, auth_headers):
    """The difference between a tool and a calculator. "Infeasible" tells a
    planner nothing they did not know; the pair of rules that cannot both
    hold, and the instances where they collide, is what they can act on."""
    from tests.test_solve import _feasible

    client = TestClient(app)
    # Demand 2 a day against an 8-hour weekly cap: four slots to fill, two
    # that can be filled.
    version, _ = _feasible(db, demand_value=2, hours=8)
    problem = db.execute(
        text("SELECT problem_id FROM model_version WHERE id = :v"), {"v": version}
    ).scalar_one()
    domain = db.execute(
        text("SELECT domain_id FROM problem WHERE id = :p"), {"p": problem}
    ).scalar_one()
    scenario = db.execute(
        text(
            "INSERT INTO scenario (problem_id, model_version_id, name)"
            " VALUES (:p, :v, 's') RETURNING id"
        ),
        {"p": problem, "v": version},
    ).scalar_one()
    db.commit()

    try:
        created = client.post(
            f"/api/v1/scenarios/{scenario}/runs",
            headers=auth_headers,
            json={"time_limit_s": 20},
        )
        assert created.status_code == 201
        work_once(db)
        run = client.get(f"/api/v1/runs/{created.json()['id']}", headers=auth_headers).json()

        assert run["status"] == "infeasible"
        assert run["assignments"] is None
        assert {item["constraint_id"] for item in run["conflict"]} == {"c_cover", "c_max_hours"}
        # Instances, not just rules: the day and shift that collide.
        assert ["mon", "morning"] in [item["instance"] for item in run["conflict"]]
        # And it is proven irreducible, which is what makes "remove any one of
        # these" a safe thing for the UI to say.
        assert run["conflict_minimal"] is True
        # What each rule means, as its author wrote it: the words the page
        # reads the conflict in.
        assert run["rule_notes"]["c_cover"] == "each day/shift is staffed to demand"
        assert run["rule_notes"]["c_max_hours"] == "eight hours a shift, within the weekly limit"
    finally:
        db.execute(text("DELETE FROM domain WHERE id = :d"), {"d": domain})
        db.commit()


def test_runs_are_listed_newest_first_and_filtered_by_scenario(seeded, auth_headers, db):
    client = TestClient(app)
    first = client.post(
        f"/api/v1/scenarios/{seeded['scenario_id']}/runs", headers=auth_headers
    ).json()
    second = client.post(
        f"/api/v1/scenarios/{seeded['scenario_id']}/runs", headers=auth_headers
    ).json()

    work_once(db)
    work_once(db)
    listed = client.get(
        f"/api/v1/runs?scenario_id={seeded['scenario_id']}", headers=auth_headers
    ).json()

    assert [row["id"] for row in listed["items"]][:2] == [second["id"], first["id"]]
    assert listed["total"] >= 2
    assert {row["scenario_id"] for row in listed["items"]} == {seeded["scenario_id"]}

    # And the same run reads back by id, agreeing with its listed row. The
    # POST response is not compared: it was the run when it was queued, and
    # the point of a queue is that the answer arrives later.
    listed_second = next(row for row in listed["items"] if row["id"] == second["id"])
    fetched = client.get(f"/api/v1/runs/{second['id']}", headers=auth_headers).json()
    assert fetched["objective"] == listed_second["objective"]
    assert fetched["status"] == listed_second["status"]
    assert fetched["assignments"] is not None


def test_two_runs_can_be_compared_and_say_what_they_differ_by(db, auth_headers):
    """Side by side over HTTP, with the caveat attached. A caller that read
    the roster change without `patch_is_the_only_difference` could credit a
    relaxed rule for a change the data caused."""
    from tests.test_solve import _feasible

    client = TestClient(app)
    version, _ = _feasible(db, demand_value=2, hours=8)
    problem = db.execute(
        text("SELECT problem_id FROM model_version WHERE id = :v"), {"v": version}
    ).scalar_one()
    domain = db.execute(
        text("SELECT domain_id FROM problem WHERE id = :p"), {"p": problem}
    ).scalar_one()
    scenarios = [
        db.execute(
            text(
                "INSERT INTO scenario (problem_id, model_version_id, name, patch)"
                " VALUES (:p, :v, :n, CAST(:patch AS jsonb)) RETURNING id"
            ),
            {"p": problem, "v": version, "n": name, "patch": patch},
        ).scalar_one()
        for name, patch in (("strict", "{}"), ("relaxed", '{"soften": {"c_cover": 100}}'))
    ]
    db.commit()

    try:
        runs = []
        for scenario in scenarios:
            created = client.post(
                f"/api/v1/scenarios/{scenario}/runs",
                headers=auth_headers,
                json={"time_limit_s": 20},
            )
            assert created.status_code == 201
            work_once(db)
            runs.append(created.json()["id"])

        response = client.get(
            f"/api/v1/runs/{runs[0]}/compare/{runs[1]}", headers=auth_headers
        )
        assert response.status_code == 200
        body = response.json()
        assert body["differs_by"] == ["patch"]
        assert body["patch_is_the_only_difference"] is True
        assert body["left"]["status"] == "infeasible"
        assert body["right"]["status"] in ("optimal", "feasible")
        assert body["moved"]["assign"]["added"]

        # Comparing a run with itself is a bad request, not a missing page:
        # both runs exist, the pairing is what is wrong.
        refused = client.get(
            f"/api/v1/runs/{runs[0]}/compare/{runs[0]}", headers=auth_headers
        )
        assert refused.status_code == 422
        assert "itself" in refused.json()["detail"]
    finally:
        db.execute(text("DELETE FROM domain WHERE id = :d"), {"d": domain})
        db.commit()


def test_unknown_scenarios_and_runs_are_404(auth_headers):
    client = TestClient(app)

    assert client.post("/api/v1/scenarios/999999/runs", headers=auth_headers).status_code == 404
    assert client.get("/api/v1/runs/999999", headers=auth_headers).status_code == 404


def test_a_run_needs_a_session(seeded):
    client = TestClient(app)

    assert client.post(f"/api/v1/scenarios/{seeded['scenario_id']}/runs").status_code == 401
    assert client.get("/api/v1/runs").status_code == 401


def test_a_time_limit_outside_the_allowed_range_is_refused(seeded, auth_headers):
    """Solving happens in the request, so the ceiling is what stops one
    running away. Refused at the request layer, naming the field."""
    client = TestClient(app)

    response = client.post(
        f"/api/v1/scenarios/{seeded['scenario_id']}/runs",
        json={"time_limit_s": 600},
        headers=auth_headers,
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "time_limit_s"]


def test_classify_reports_the_model_in_planner_language(auth_headers):
    """The editor asks this of a draft. Same function a run records, so the
    two cannot disagree about what the model is."""
    client = TestClient(app)

    response = client.post(
        "/api/v1/classify",
        json={
            "ir": {
                "variables": {"assign": {"domain": "binary"}},
                "constraints": [{"severity": "soft"}],
            }
        },
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["model_class"] == "IP"
    assert "every decision is yes or no" in body["planner"]
    assert "every rule is linear" in body["planner"]
    assert "at least one rule can bend, at a cost" in body["planner"]
    assert "soft-constraints" in body["needs"]
    assert body["empty_ranges"] == []
    assert body["would_solve"]
    assert "combinatorial" in body["would_solve"].lower()
    assert "cp-sat" not in body["would_solve"].lower()


def test_classify_says_when_no_solver_this_platform_has_can_take_the_model(auth_headers):
    """A draft the registry cannot take is still classified: the editor
    has to say so before publish, not wait for a run to fail."""
    client = TestClient(app)

    response = client.post(
        "/api/v1/classify",
        json={"ir": {"variables": {"x": {"domain": "foo"}}}},
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["model_class"] == "unsupported"
    assert body["would_solve"] is None


def test_classify_against_live_data_names_empty_ranges_without_writing(
    seeded, auth_headers, db
):
    """The editor needs compile_model(ir, data) to see a vacuous forall.
    snapshot_dataset() writes; a keystroke must not. The live read is the
    same JSON a freeze would produce, and the dataset table stays put."""
    client = TestClient(app)
    ir = copy.deepcopy(
        db.execute(
            text("SELECT ir FROM model_version WHERE id = :v"),
            {"v": seeded["model_version_id"]},
        ).scalar_one()
    )
    ir["constraints"] = [
        *ir["constraints"],
        {
            "id": "c_nobody",
            "forall": [
                {
                    "index": "e",
                    "set": "employee",
                    "where": [{"attr": "full_name", "op": "=", "value": "nobody-at-all"}],
                }
            ],
            "left": {
                "sum": {"var": "assign", "index": ["e", "d", "s"]},
                "over": [
                    {"index": "d", "set": "day"},
                    {"index": "s", "set": "shift"},
                ],
            },
            "relation": ">=",
            "right": {"const": 1},
            "severity": "hard",
        },
    ]
    before = db.execute(
        text("SELECT count(*) FROM dataset WHERE problem_id = :p"),
        {"p": seeded["problem_id"]},
    ).scalar_one()

    response = client.post(
        "/api/v1/classify",
        json={"ir": ir, "problem_id": seeded["problem_id"]},
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["model_class"] == "IP"
    assert {"constraint_id": "c_nobody", "kind": "forall", "index": {}} in body[
        "empty_ranges"
    ]
    after = db.execute(
        text("SELECT count(*) FROM dataset WHERE problem_id = :p"),
        {"p": seeded["problem_id"]},
    ).scalar_one()
    assert after == before


def test_classify_unknown_problem_is_404(auth_headers):
    client = TestClient(app)
    response = client.post(
        "/api/v1/classify",
        json={
            "ir": {"variables": {"x": {"domain": "binary"}}},
            "problem_id": 9_000_000_000,
        },
        headers=auth_headers,
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "problem not found"


def test_cancelling_a_queued_run_returns_it_cancelled(seeded, auth_headers, db):
    """Nothing has started, so there is no worker to tell. The status is the
    answer: this question will not be solved."""
    client = TestClient(app)
    queued = client.post(
        f"/api/v1/scenarios/{seeded['scenario_id']}/runs",
        json={"time_limit_s": 30},
        headers=auth_headers,
    )
    run_id = queued.json()["id"]

    response = client.post(f"/api/v1/runs/{run_id}/cancel", headers=auth_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "cancelled"
    assert body["cancel_requested"] is True
    assert body["assignments"] is None
    work_once(db)
    assert (
        client.get(f"/api/v1/runs/{run_id}", headers=auth_headers).json()["status"]
        == "cancelled"
    )


def test_cancelling_a_finished_run_is_refused(seeded, auth_headers, db):
    """The result is already written. Stopping it would be rewriting history."""
    client = TestClient(app)
    queued = client.post(
        f"/api/v1/scenarios/{seeded['scenario_id']}/runs",
        json={"time_limit_s": 30},
        headers=auth_headers,
    )
    run_id = queued.json()["id"]
    work_once(db)

    response = client.post(f"/api/v1/runs/{run_id}/cancel", headers=auth_headers)

    assert response.status_code == 422, response.text
    assert "already finished" in response.json()["detail"]
