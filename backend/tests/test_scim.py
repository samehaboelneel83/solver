"""SCIM 2.0 (queue R36)."""

from __future__ import annotations

from sqlalchemy import text

from app import scim
from app.core.security import create_access_token, decode_access_token
from app.seed import seed_admin
from tests.test_api_problems import auth_headers, client  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


def test_scim_mint_create_and_deprovision(db, client, auth_headers):
    seed_admin(db)
    minted = client.post("/api/v1/scim/token", headers=auth_headers)
    assert minted.status_code == 200, minted.text
    token = minted.json()["token"]
    assert token.startswith("scim_")
    h = {"Authorization": f"Bearer {token}"}

    created = client.post(
        "/scim/v2/Users",
        headers=h,
        json={
            "userName": "bob.scim",
            "displayName": "Bob",
            "emails": [{"value": "bob@example.com"}],
            "active": True,
            "externalId": "ext-bob",
        },
    )
    assert created.status_code == 201, created.text
    user_id = created.json()["id"]

    listed = client.get("/scim/v2/Users", headers=h)
    assert listed.status_code == 200
    assert listed.json()["totalResults"] >= 1

    # Issue a JWT then deprovision — token_version bump must invalidate it.
    tv = db.execute(
        text("SELECT token_version FROM iam.user_account WHERE id = :u"),
        {"u": user_id},
    ).scalar_one()
    jwt = create_access_token(subject="bob.scim", token_version=tv)
    assert decode_access_token(jwt)["sub"] == "bob.scim"

    deleted = client.delete(f"/scim/v2/Users/{user_id}", headers=h)
    assert deleted.status_code == 204
    row = db.execute(
        text("SELECT is_active, token_version FROM iam.user_account WHERE id = :u"),
        {"u": user_id},
    ).mappings().one()
    assert row["is_active"] is False
    assert row["token_version"] == tv + 1

    groups = client.get("/scim/v2/Groups", headers=h)
    assert groups.status_code == 200
    assert groups.json()["totalResults"] >= 1
