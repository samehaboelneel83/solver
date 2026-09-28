"""Server-saved drafts and their publication (`app/api/drafts.py`).

What is pinned:

- a save names the revision it was built on; any other is the platform's
  stale-record 409, and the stored draft is unchanged;
- a draft may be incomplete, but publication validates the exact locked
  revision, and a refused publication leaves the draft in place;
- a retried publish with the same Idempotency-Key creates one version, and
  a reused key with a different request is refused;
- a draft belongs to one account: a colleague in the same organization
  does not see it, and another organization does not see the problem;
- a draft starts from a version of its own problem.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.api.concurrency import STALE_PREFIX
from app.api.drafts import MAX_DRAFT_BYTES
from app.core.security import hash_password
from tests.test_api_problems import (  # noqa: F401
    _ir,
    _problem,
    auth_headers,
    client,
    db,
    domain_id,
    ensure_admin_seeded,
)
from tests.test_tenancy import _login, tenants  # noqa: F401


@pytest.fixture
def problem_id(client, auth_headers, domain_id):
    return _problem(client, auth_headers, domain_id, f"drafts-{uuid.uuid4().hex[:6]}")


def _save(client, headers, problem_id, ir, expected=None, base=None):
    return client.put(
        f"/api/v1/problems/{problem_id}/draft",
        json={"ir": ir, "expected_revision": expected, "base_version_id": base},
        headers=headers,
    )


def _versions(client, headers, problem_id):
    return client.get(f"/api/v1/problems/{problem_id}/versions", headers=headers).json()["total"]


def test_saves_advance_the_revision_and_stale_saves_are_refused(client, auth_headers, problem_id):
    assert client.get(f"/api/v1/problems/{problem_id}/draft", headers=auth_headers).status_code == 404
    created = _save(client, auth_headers, problem_id, _ir("a"))
    assert created.status_code == 201, created.text
    assert created.json()["revision"] == 1
    updated = _save(client, auth_headers, problem_id, _ir("b"), expected=1)
    assert updated.status_code == 200, updated.text
    assert updated.json()["revision"] == 2

    stale = _save(client, auth_headers, problem_id, _ir("c"), expected=1)
    assert stale.status_code == 409
    assert STALE_PREFIX in stale.json()["detail"]
    # A second "first save" would overwrite the existing draft: also stale.
    assert _save(client, auth_headers, problem_id, _ir("c")).status_code == 409

    read = client.get(f"/api/v1/problems/{problem_id}/draft", headers=auth_headers).json()
    assert read["revision"] == 2
    assert "b" in read["ir"]["variables"]


def test_a_save_after_the_draft_was_published_elsewhere_is_stale(client, auth_headers, problem_id):
    _save(client, auth_headers, problem_id, _ir("a"))
    published = client.post(
        f"/api/v1/problems/{problem_id}/draft/publish", json={"expected_revision": 1}, headers=auth_headers
    )
    assert published.status_code == 201, published.text
    assert _save(client, auth_headers, problem_id, _ir("b"), expected=1).status_code == 409


def test_an_incomplete_draft_is_kept_but_not_published(client, auth_headers, problem_id):
    incomplete = {"version": 1, "sets": ["no-such-set"], "variables": {}}
    assert _save(client, auth_headers, problem_id, incomplete).status_code == 201
    refused = client.post(
        f"/api/v1/problems/{problem_id}/draft/publish", json={"expected_revision": 1}, headers=auth_headers
    )
    assert refused.status_code == 422
    assert refused.json()["detail"][0]["loc"][:2] == ["body", "ir"]
    assert _versions(client, auth_headers, problem_id) == 0
    assert client.get(f"/api/v1/problems/{problem_id}/draft", headers=auth_headers).json()["revision"] == 1


def test_publishing_validates_the_named_revision(client, auth_headers, problem_id):
    _save(client, auth_headers, problem_id, _ir("a"))
    _save(client, auth_headers, problem_id, _ir("b"), expected=1)
    stale = client.post(
        f"/api/v1/problems/{problem_id}/draft/publish", json={"expected_revision": 1}, headers=auth_headers
    )
    assert stale.status_code == 409
    assert _versions(client, auth_headers, problem_id) == 0

    published = client.post(
        f"/api/v1/problems/{problem_id}/draft/publish",
        json={"expected_revision": 2, "note": "second"},
        headers=auth_headers,
    )
    assert published.status_code == 201, published.text
    body = published.json()
    assert body["version"] == 1 and body["note"] == "second"
    assert "b" in body["ir"]["variables"]
    assert client.get(f"/api/v1/problems/{problem_id}/draft", headers=auth_headers).status_code == 404


def test_a_retried_publish_creates_one_version(client, auth_headers, problem_id):
    _save(client, auth_headers, problem_id, _ir("a"))
    headers = {**auth_headers, "Idempotency-Key": f"pub-{uuid.uuid4().hex}"}
    first = client.post(
        f"/api/v1/problems/{problem_id}/draft/publish", json={"expected_revision": 1, "note": "n"}, headers=headers
    )
    again = client.post(
        f"/api/v1/problems/{problem_id}/draft/publish", json={"expected_revision": 1, "note": "n"}, headers=headers
    )
    assert first.status_code == 201, first.text
    assert again.status_code == 200, again.text
    assert again.json()["id"] == first.json()["id"]
    assert _versions(client, auth_headers, problem_id) == 1

    reused = client.post(
        f"/api/v1/problems/{problem_id}/draft/publish",
        json={"expected_revision": 1, "note": "different"},
        headers=headers,
    )
    assert reused.status_code == 409
    assert "Idempotency-Key" in reused.json()["detail"]


def test_without_a_key_a_double_submit_still_publishes_once(client, auth_headers, problem_id):
    _save(client, auth_headers, problem_id, _ir("a"))
    url = f"/api/v1/problems/{problem_id}/draft/publish"
    assert client.post(url, json={"expected_revision": 1}, headers=auth_headers).status_code == 201
    assert client.post(url, json={"expected_revision": 1}, headers=auth_headers).status_code == 404
    assert _versions(client, auth_headers, problem_id) == 1


def test_a_malformed_idempotency_key_is_refused(client, auth_headers, problem_id):
    _save(client, auth_headers, problem_id, _ir("a"))
    refused = client.post(
        f"/api/v1/problems/{problem_id}/draft/publish",
        json={"expected_revision": 1},
        headers={**auth_headers, "Idempotency-Key": "x" * 129},
    )
    assert refused.status_code == 422
    assert _versions(client, auth_headers, problem_id) == 0


def test_discard_names_the_revision(client, auth_headers, problem_id):
    _save(client, auth_headers, problem_id, _ir("a"))
    _save(client, auth_headers, problem_id, _ir("b"), expected=1)
    url = f"/api/v1/problems/{problem_id}/draft"
    assert client.delete(f"{url}?expected_revision=1", headers=auth_headers).status_code == 409
    assert client.delete(f"{url}?expected_revision=2", headers=auth_headers).status_code == 204
    assert client.get(url, headers=auth_headers).status_code == 404
    assert client.delete(f"{url}?expected_revision=2", headers=auth_headers).status_code == 404


def test_a_draft_starts_from_a_version_of_its_own_problem(client, auth_headers, domain_id, problem_id):
    other = _problem(client, auth_headers, domain_id, f"other-{uuid.uuid4().hex[:6]}")
    foreign = client.post(
        f"/api/v1/problems/{other}/versions", json={"ir": _ir("o")}, headers=auth_headers
    ).json()["id"]
    refused = _save(client, auth_headers, problem_id, _ir("a"), base=foreign)
    assert refused.status_code == 422
    assert refused.json()["detail"][0]["loc"] == ["body", "base_version_id"]

    own = client.post(
        f"/api/v1/problems/{problem_id}/versions", json={"ir": _ir("v")}, headers=auth_headers
    ).json()["id"]
    saved = _save(client, auth_headers, problem_id, _ir("a"), base=own)
    assert saved.status_code == 201 and saved.json()["base_version_id"] == own
    assert saved.json()["base_version"] == 1
    read = client.get(f"/api/v1/problems/{problem_id}/draft", headers=auth_headers).json()
    assert read["base_version_id"] == own and read["base_version"] == 1


def test_an_oversized_draft_is_refused(client, auth_headers, problem_id):
    big = {**_ir("a"), "notes": "x" * (MAX_DRAFT_BYTES + 1)}
    refused = _save(client, auth_headers, problem_id, big)
    assert refused.status_code == 422
    assert client.get(f"/api/v1/problems/{problem_id}/draft", headers=auth_headers).status_code == 404


@pytest.fixture
def colleague(db):
    """A second administrator in the seed organization."""
    name = f"colleague-{uuid.uuid4().hex[:8]}"
    user_id = db.execute(
        text(
            "INSERT INTO iam.user_account (id, organization_id, username, hashed_password)"
            " SELECT gen_random_uuid(), id, :u, :p FROM iam.organization WHERE code = 'default'"
            " RETURNING id"
        ),
        {"u": name, "p": hash_password("colleague-password")},
    ).scalar_one()
    db.execute(
        text(
            "INSERT INTO iam.user_role (id, user_id, role_id)"
            " SELECT gen_random_uuid(), :u, id FROM iam.role WHERE name = 'Admin'"
        ),
        {"u": user_id},
    )
    db.commit()
    yield _login(name, "colleague-password")
    db.execute(text("DELETE FROM model_draft WHERE owner_id = :u"), {"u": user_id})
    db.execute(text("DELETE FROM iam.user_role WHERE user_id = :u"), {"u": user_id})
    db.execute(text("DELETE FROM iam.user_account WHERE id = :u"), {"u": user_id})
    db.commit()


def test_a_draft_is_its_owners_alone(client, auth_headers, problem_id, colleague):
    _save(client, auth_headers, problem_id, _ir("mine"))
    assert client.get(f"/api/v1/problems/{problem_id}/draft", headers=colleague).status_code == 404
    theirs = _save(client, colleague, problem_id, _ir("theirs"))
    assert theirs.status_code == 201
    mine = client.get(f"/api/v1/problems/{problem_id}/draft", headers=auth_headers).json()
    assert "mine" in mine["ir"]["variables"]
    assert client.delete(
        f"/api/v1/problems/{problem_id}/draft?expected_revision=1", headers=colleague
    ).status_code == 204
    assert client.get(f"/api/v1/problems/{problem_id}/draft", headers=auth_headers).status_code == 200


def test_another_organization_cannot_reach_the_problems_drafts(client, tenants):
    problem = tenants["problem_a"]
    assert _save(client, tenants["a"], problem, _ir("a")).status_code == 201
    for response in (
        client.get(f"/api/v1/problems/{problem}/draft", headers=tenants["b"]),
        _save(client, tenants["b"], problem, _ir("b")),
        client.post(f"/api/v1/problems/{problem}/draft/publish", json={"expected_revision": 1}, headers=tenants["b"]),
    ):
        assert response.status_code == 404, response.text
    assert client.get(f"/api/v1/problems/{problem}/draft", headers=tenants["a"]).json()["revision"] == 1


def test_concurrent_retries_with_one_key_publish_once(client, auth_headers, problem_id):
    """The retries race: the draft's row lock serialises them, and the loser
    finds the winner's publication rather than a second version."""
    from concurrent.futures import ThreadPoolExecutor

    from fastapi.testclient import TestClient

    from app.main import app

    _save(client, auth_headers, problem_id, _ir("a"))
    headers = {**auth_headers, "Idempotency-Key": f"race-{uuid.uuid4().hex}"}
    url = f"/api/v1/problems/{problem_id}/draft/publish"

    def publish(_):
        return TestClient(app).post(url, json={"expected_revision": 1}, headers=headers)

    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(publish, range(4)))
    assert sorted(r.status_code for r in responses) == [200, 200, 200, 201], [r.text for r in responses]
    assert len({r.json()["id"] for r in responses}) == 1
    assert _versions(client, auth_headers, problem_id) == 1
