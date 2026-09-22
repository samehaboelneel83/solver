"""Settings: three levels, one direction, and a run that obeys them.

The test that carries the feature is `a_problem_overrides_its_domain_which
_overrides_the_platform`: if that ordering is wrong, every other setting in
the system is wrong in a way nobody would notice until a solve took the wrong
amount of time.

Two properties are about honesty rather than mechanism:

- every resolved value says **where it came from**, because a number nobody
  can attribute is a number nobody can change with confidence;
- unsetting a level **restores the level above** rather than writing a zero,
  or a platform could only ever accumulate overrides.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.main import app
from app.seed import seed_admin
from app.settings_resolve import resolve, value_of
from app.solve.service import enqueue_run
from tests.test_solve import _feasible  # noqa: F401
from tests.test_v1_problem_run import (  # noqa: F401
    _data,
    _snapshot,
    db,
    make_attribute_def,
    make_domain,
    make_entity,
    make_entity_type,
    make_model_version,
    make_parameter_def,
    make_parameter_value,
    make_problem,
)


@pytest.fixture(autouse=True)
def ensure_admin_seeded():
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


@pytest.fixture(autouse=True)
def clean_up_domains(db):
    """`_problem` commits, so the usual rollback does not undo it."""
    yield
    db.execute(text("DELETE FROM domain WHERE name LIKE 'settings-%'"))
    db.commit()


@pytest.fixture(autouse=True)
def clean_platform_settings(db):
    """The platform level is shared by every test in the run, so a leftover
    override would silently govern someone else's assertions."""
    db.execute(text("DELETE FROM setting WHERE scope = 'platform'"))
    db.commit()
    yield
    db.execute(text("DELETE FROM setting WHERE scope = 'platform'"))
    db.commit()


def _set(db, scope: str, scope_id: int | None, key: str, value: str) -> None:
    db.execute(
        text(
            "INSERT INTO setting (scope, scope_id, key, value)"
            " VALUES (CAST(:s AS setting_scope), :i, :k, CAST(:v AS jsonb))"
            " ON CONFLICT (scope, scope_id, key) DO UPDATE SET value = EXCLUDED.value"
        ),
        {"s": scope, "i": scope_id, "k": key, "v": value},
    )
    db.commit()


def _problem(db) -> tuple[int, int]:
    """A problem and its domain, committed.

    Committed because the API routes below run in their own session: a domain
    that exists only inside this test's transaction is invisible to them, and
    the scope trigger would rightly refuse a setting pointing at it.
    """
    domain = make_domain(db, f"settings-{uuid.uuid4().hex[:8]}")
    problem = make_problem(db, domain)
    db.commit()
    return problem, domain


# -- resolution -------------------------------------------------------------


def test_nothing_set_anywhere_resolves_to_the_built_in_default(db):
    problem, _ = _problem(db)

    found = resolve(db, problem_id=problem)["solve.time_limit_s"]

    assert found.value == 10
    assert found.source == "default"


def test_a_problem_overrides_its_domain_which_overrides_the_platform(db):
    """The whole rule, in one test. Get this ordering wrong and every setting
    in the system is wrong in a way nobody notices until a solve takes the
    wrong amount of time."""
    problem, domain = _problem(db)

    _set(db, "platform", None, "solve.time_limit_s", "15")
    assert resolve(db, problem_id=problem)["solve.time_limit_s"].value == 15

    _set(db, "domain", domain, "solve.time_limit_s", "30")
    assert resolve(db, problem_id=problem)["solve.time_limit_s"].value == 30

    _set(db, "problem", problem, "solve.time_limit_s", "45")
    resolved = resolve(db, problem_id=problem)["solve.time_limit_s"]
    assert resolved.value == 45
    assert resolved.source == "problem"


def test_a_resolved_value_says_which_level_it_came_from(db):
    """"60, from this domain" tells you which of three places to edit;
    "60" tells you to go looking."""
    problem, domain = _problem(db)
    _set(db, "domain", domain, "solve.time_limit_s", "60")

    resolved = resolve(db, problem_id=problem)

    assert resolved["solve.time_limit_s"].source == "domain"
    assert resolved["solve.seed"].source == "default"


def test_one_domains_setting_does_not_govern_another(db):
    mine, my_domain = _problem(db)
    theirs, _ = _problem(db)
    _set(db, "domain", my_domain, "solve.time_limit_s", "99")

    assert resolve(db, problem_id=mine)["solve.time_limit_s"].value == 99
    assert resolve(db, problem_id=theirs)["solve.time_limit_s"].value == 10


def test_value_of_reads_one_setting(db):
    problem, _ = _problem(db)
    _set(db, "problem", problem, "solve.workers", "2")

    assert value_of(db, "solve.workers", problem_id=problem) == 2
    assert value_of(db, "no.such.key", problem_id=problem, default="fallback") == "fallback"


# -- what the database refuses ----------------------------------------------


def test_a_setting_pointing_at_a_domain_that_does_not_exist_is_refused(db):
    """An orphan governs nothing and says nothing, so it is refused at write
    time rather than discovered at read time."""
    with pytest.raises(DBAPIError) as excinfo:
        _set(db, "domain", 10**9, "solve.time_limit_s", "5")
    db.rollback()

    assert "does not exist" in str(excinfo.value)


def test_a_platform_setting_may_not_name_a_scope(db):
    with pytest.raises(DBAPIError):
        _set(db, "platform", 1, "solve.time_limit_s", "5")
    db.rollback()


def test_a_domain_setting_must_name_one(db):
    with pytest.raises(DBAPIError):
        _set(db, "domain", None, "solve.time_limit_s", "5")
    db.rollback()


def test_an_unknown_key_is_refused(db):
    problem, _ = _problem(db)
    with pytest.raises(DBAPIError):
        _set(db, "problem", problem, "solve.time_limt_s", "5")  # typo, deliberately
    db.rollback()


def test_the_platform_level_holds_one_row_per_key(db):
    """`NULLS NOT DISTINCT`: without it Postgres treats every null scope_id as
    different, and "the platform setting" becomes whichever row was read."""
    _set(db, "platform", None, "solve.time_limit_s", "5")
    _set(db, "platform", None, "solve.time_limit_s", "7")

    rows = db.execute(
        text("SELECT count(*) FROM setting WHERE scope = 'platform' AND key = 'solve.time_limit_s'")
    ).scalar_one()
    assert rows == 1


def test_deleting_a_domain_takes_its_settings_with_it(db):
    _, domain = _problem(db)
    _set(db, "domain", domain, "solve.time_limit_s", "5")

    db.execute(text("DELETE FROM domain WHERE id = :d"), {"d": domain})
    db.commit()

    left = db.execute(
        text("SELECT count(*) FROM setting WHERE scope = 'domain' AND scope_id = :d"),
        {"d": domain},
    ).scalar_one()
    assert left == 0


# -- a run that obeys them --------------------------------------------------


def test_a_run_takes_its_time_limit_from_settings_and_records_where_it_came_from(db):
    version, _ = _feasible(db, demand_value=1)
    problem = db.execute(
        text("SELECT problem_id FROM model_version WHERE id = :v"), {"v": version}
    ).scalar_one()
    scenario = db.execute(
        text(
            "INSERT INTO scenario (problem_id, model_version_id, name)"
            " VALUES (:p, :v, 's') RETURNING id"
        ),
        {"p": problem, "v": version},
    ).scalar_one()
    db.commit()
    _set(db, "problem", problem, "solve.time_limit_s", "42")

    run_id = enqueue_run(db, scenario)

    params = db.execute(
        text("SELECT params FROM run WHERE id = :r"), {"r": run_id}
    ).scalar_one()
    assert params["time_limit_s"] == 42
    # A run whose time limit nobody can account for is a run nobody can make
    # faster.
    assert params["from_settings"]["time_limit_s"] == "problem"

    db.execute(text("DELETE FROM run WHERE id = :r"), {"r": run_id})
    db.commit()


def test_an_explicit_time_limit_still_wins_over_the_setting(db):
    """Settings are the default, not a ceiling. A caller who names a number
    means it."""
    version, _ = _feasible(db, demand_value=1)
    problem = db.execute(
        text("SELECT problem_id FROM model_version WHERE id = :v"), {"v": version}
    ).scalar_one()
    scenario = db.execute(
        text(
            "INSERT INTO scenario (problem_id, model_version_id, name)"
            " VALUES (:p, :v, 's') RETURNING id"
        ),
        {"p": problem, "v": version},
    ).scalar_one()
    db.commit()
    _set(db, "problem", problem, "solve.time_limit_s", "42")

    run_id = enqueue_run(db, scenario, time_limit=3.0)

    params = db.execute(text("SELECT params FROM run WHERE id = :r"), {"r": run_id}).scalar_one()
    assert params["time_limit_s"] == 3.0
    assert "time_limit_s" not in params.get("from_settings", {})

    db.execute(text("DELETE FROM run WHERE id = :r"), {"r": run_id})
    db.commit()


# -- over HTTP --------------------------------------------------------------


def test_settings_are_read_with_their_source_and_written_by_level(db, auth_headers):
    client = TestClient(app)
    problem, domain = _problem(db)

    assert client.put(
        "/api/v1/settings",
        headers=auth_headers,
        json={"scope": "domain", "scope_id": domain, "key": "solve.time_limit_s", "value": 25},
    ).status_code == 200

    body = client.get(
        f"/api/v1/settings?problem_id={problem}", headers=auth_headers
    ).json()
    found = next(item for item in body["items"] if item["key"] == "solve.time_limit_s")
    assert found["value"] == 25
    assert found["source"] == "domain"


def test_unsetting_restores_the_level_above_rather_than_writing_a_zero(db, auth_headers):
    client = TestClient(app)
    problem, domain = _problem(db)
    _set(db, "domain", domain, "solve.time_limit_s", "25")
    _set(db, "problem", problem, "solve.time_limit_s", "5")

    client.put(
        "/api/v1/settings",
        headers=auth_headers,
        json={"scope": "problem", "scope_id": problem, "key": "solve.time_limit_s", "value": None},
    )

    found = resolve(db, problem_id=problem)["solve.time_limit_s"]
    assert found.value == 25
    assert found.source == "domain"


def test_a_value_of_the_wrong_type_is_refused_at_the_screen_that_set_it(db, auth_headers):
    """A string where a number belongs would resolve happily and fail at solve
    time, a long way from the person who typed it."""
    client = TestClient(app)
    _, domain = _problem(db)

    response = client.put(
        "/api/v1/settings",
        headers=auth_headers,
        json={"scope": "domain", "scope_id": domain, "key": "solve.time_limit_s", "value": "soon"},
    )

    assert response.status_code == 422
    assert "is a number" in response.json()["detail"]


def test_an_unknown_key_is_refused_rather_than_stored(db, auth_headers):
    client = TestClient(app)
    response = client.put(
        "/api/v1/settings",
        headers=auth_headers,
        json={"scope": "platform", "key": "solve.time_limt_s", "value": 5},
    )

    assert response.status_code == 422
    assert "no setting called" in response.json()["detail"]


def test_changing_a_setting_needs_the_capability(db):
    """Changing what governs everyone's runs is its own decision."""
    from tests.test_capabilities_enforced import _account

    client = TestClient(app)
    planner = _account(db, "planner")

    response = client.put(
        "/api/v1/settings",
        headers=planner,
        json={"scope": "platform", "key": "solve.time_limit_s", "value": 5},
    )

    assert response.status_code == 403
    assert "settings.edit" in response.json()["detail"]


def test_a_run_records_its_threads_and_gap_and_where_they_came_from(db):
    version, _ = _feasible(db, demand_value=1)
    problem = db.execute(
        text("SELECT problem_id FROM model_version WHERE id = :v"), {"v": version}
    ).scalar_one()
    scenario = db.execute(
        text(
            "INSERT INTO scenario (problem_id, model_version_id, name)"
            " VALUES (:p, :v, 's') RETURNING id"
        ),
        {"p": problem, "v": version},
    ).scalar_one()
    db.commit()
    _set(db, "problem", problem, "solve.gap_rel", "0.05")

    run_id = enqueue_run(db, scenario)

    params = db.execute(text("SELECT params FROM run WHERE id = :r"), {"r": run_id}).scalar_one()
    assert params["gap_rel"] == 0.05
    assert params["from_settings"]["gap_rel"] == "problem"
    # Nothing set: the built-in default, and the run says so.
    assert params["workers"] == 8
    assert params["from_settings"]["workers"] == "default"

    db.execute(text("DELETE FROM run WHERE id = :r"), {"r": run_id})
    db.commit()


@pytest.mark.parametrize(
    "key, value",
    [
        ("solve.gap_rel", -0.1),
        ("solve.gap_rel", 0.9),
        ("solve.workers", 0),
        ("solve.workers", 2.5),
        ("solve.time_limit_s", 0),
    ],
)
def test_a_solve_setting_out_of_range_is_refused(db, auth_headers, key, value):
    response = TestClient(app).put(
        "/api/v1/settings",
        headers=auth_headers,
        json={"scope": "platform", "scope_id": None, "key": key, "value": value},
    )
    assert response.status_code == 422, response.text
    assert key in response.json()["detail"]
