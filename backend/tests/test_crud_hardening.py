"""Generic CRUD-factory hardening guards.

These test `build_crud_router` itself -- 409 mapping, `q`/`f_<column>`/
`order_by` validation, and stable offset pagination -- not any particular
table. They were originally written against `domain.entity_type`,
`domain.entity` and `domain.role_type`; migration 0006 dropped those, so
every case is re-expressed against the four untouched `iam` tables
(`iam.role` carries the same code/name shape `domain.role_type` did, and
`iam.user_role` supplies the FK cases). No assertion was weakened.

Every test that creates a role/user_role via a real HTTP POST deletes it
in a `finally` block. `backend/tests/conftest.py` now drops and recreates
`solver_test` at the start of each session, so this is belt-and-braces
rather than load-bearing across runs -- but `test_list_order_by` is only
correct against a small table (default `limit=50`), so a test in this
same file leaving rows behind was enough to make a *different* test here
flaky within a single session too.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.main import app
from app.seed import seed_admin


@pytest.fixture(autouse=True)
def ensure_admin_seeded():
    db = SessionLocal()
    seed_admin(db)
    db.close()


@pytest.fixture
def auth_headers():
    settings = get_settings()
    client = TestClient(app)
    response = client.post(
        "/api/auth/login",
        data={"username": settings.admin_username, "password": settings.admin_password},
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def organization_id(auth_headers):
    client = TestClient(app)
    response = client.get("/api/iam/organization/", headers=auth_headers)
    items = response.json()["items"]
    default_org = next(item for item in items if item["code"] == "default")
    return default_org["id"]


@pytest.fixture
def admin_user_id(auth_headers):
    settings = get_settings()
    client = TestClient(app)
    response = client.get(
        f"/api/iam/user_account/?q={settings.admin_username}", headers=auth_headers
    )
    items = response.json()["items"]
    return next(item for item in items if item["username"] == settings.admin_username)["id"]


def _make_role(client, auth_headers, code: str, name: str | None = None) -> str:
    response = client.post(
        "/api/iam/role/",
        json={"code": code, "name": name if name is not None else code},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _make_user_role(client, auth_headers, user_id: str, role_id: str) -> str:
    response = client.post(
        "/api/iam/user_role/",
        json={"user_id": user_id, "role_id": role_id},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _delete_role(client, auth_headers, role_id: str) -> None:
    client.delete(f"/api/iam/role/{role_id}", headers=auth_headers)


def _delete_user_role(client, auth_headers, user_role_id: str) -> None:
    client.delete(f"/api/iam/user_role/{user_role_id}", headers=auth_headers)


def test_delete_referenced_row_returns_409(auth_headers, admin_user_id):
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]

    role_id = _make_role(client, auth_headers, f"ref-role-{suffix}", "Referenced Role")
    user_role_id = _make_user_role(client, auth_headers, admin_user_id, role_id)

    try:
        delete_response = client.delete(f"/api/iam/role/{role_id}", headers=auth_headers)
        assert delete_response.status_code == 409
        assert "still referenced" in delete_response.json()["detail"]
    finally:
        # The delete above is expected to fail (that's the point of the
        # test), so both rows are still live -- remove the referencing
        # user_role before the role, or the role stays permanently
        # undeletable for the same reason and both rows leak.
        _delete_user_role(client, auth_headers, user_role_id)
        _delete_role(client, auth_headers, role_id)


def test_duplicate_code_returns_409(auth_headers):
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]
    payload = {"code": f"dup-{suffix}", "name": "Duplicate"}

    first_response = client.post("/api/iam/role/", json=payload, headers=auth_headers)
    assert first_response.status_code == 201
    role_id = first_response.json()["id"]

    try:
        second_response = client.post("/api/iam/role/", json=payload, headers=auth_headers)
        assert second_response.status_code == 409
        assert "already exists" in second_response.json()["detail"]
    finally:
        # The duplicate (second) POST never created a row; only the first
        # one needs cleaning up.
        _delete_role(client, auth_headers, role_id)


def test_bad_fk_on_create_returns_409(auth_headers, admin_user_id):
    client = TestClient(app)

    response = client.post(
        "/api/iam/user_role/",
        json={"user_id": admin_user_id, "role_id": str(uuid.uuid4())},
        headers=auth_headers,
    )
    assert response.status_code == 409
    assert "does not exist" in response.json()["detail"]


def test_list_search_q(auth_headers):
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]

    role_ids = [
        _make_role(client, auth_headers, code) for code in (f"alpha-{suffix}", f"beta-{suffix}")
    ]

    try:
        search_response = client.get(f"/api/iam/role/?q=alpha-{suffix}", headers=auth_headers)
        assert search_response.status_code == 200
        items = search_response.json()["items"]
        assert len(items) == 1
        assert items[0]["code"] == f"alpha-{suffix}"
    finally:
        for role_id in role_ids:
            _delete_role(client, auth_headers, role_id)


def test_list_filter_by_column(auth_headers, admin_user_id):
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]

    role_a = _make_role(client, auth_headers, f"filter-role-a-{suffix}")
    role_b = _make_role(client, auth_headers, f"filter-role-b-{suffix}")
    user_role_ids = [_make_user_role(client, auth_headers, admin_user_id, r) for r in (role_a, role_b)]

    try:
        filter_response = client.get(
            f"/api/iam/user_role/?f_role_id={role_a}", headers=auth_headers
        )
        assert filter_response.status_code == 200
        items = filter_response.json()["items"]
        assert all(item["role_id"] == role_a for item in items)
        assert len(items) == 1
        assert not any(item["role_id"] == role_b for item in items)

        bad_filter_response = client.get("/api/iam/user_role/?f_nope=1", headers=auth_headers)
        assert bad_filter_response.status_code == 422
    finally:
        for user_role_id in user_role_ids:
            _delete_user_role(client, auth_headers, user_role_id)
        for role_id in (role_a, role_b):
            _delete_role(client, auth_headers, role_id)


def test_list_order_by(auth_headers):
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]

    role_ids = [
        _make_role(client, auth_headers, code)
        for code in (f"order-c-{suffix}", f"order-a-{suffix}", f"order-b-{suffix}")
    ]

    try:
        order_response = client.get(
            f"/api/iam/role/?q=order-&order_by=code&order=desc", headers=auth_headers
        )
        assert order_response.status_code == 200
        returned_codes = [
            item["code"] for item in order_response.json()["items"] if suffix in item["code"]
        ]
        assert returned_codes == sorted(returned_codes, reverse=True)
        assert len(returned_codes) == 3

        bad_order_response = client.get("/api/iam/role/?order_by=nope", headers=auth_headers)
        assert bad_order_response.status_code == 422
    finally:
        for role_id in role_ids:
            _delete_role(client, auth_headers, role_id)


def test_list_filter_bad_datetime_returns_422_not_500(auth_headers):
    """f_<column>=<garbage> against a non str/bool/int/uuid column (here,
    organization.created_at, a DateTime) used to fall through
    _cast_filter_value's `return raw` branch and hit Postgres as a raw string,
    surfacing as a 500 (psycopg2.errors.InvalidDatetimeFormat) instead of a
    clean validation error."""
    client = TestClient(app)

    bad_response = client.get(
        "/api/iam/organization/?f_created_at=notadate", headers=auth_headers
    )
    assert bad_response.status_code == 422

    valid_response = client.get(
        "/api/iam/organization/?f_created_at=2026-01-01T00:00:00%2B00:00", headers=auth_headers
    )
    assert valid_response.status_code == 200


def test_list_filter_and_order_reject_hidden_columns(auth_headers):
    """hashed_password is dropped from UserAccountRead via `hidden=`, so it
    must not be reachable through f_<column> or order_by either -- both
    used to return 200 and act as a password-hash oracle/side channel."""
    client = TestClient(app)

    order_response = client.get(
        "/api/iam/user_account/?order_by=hashed_password", headers=auth_headers
    )
    assert order_response.status_code == 422

    filter_response = client.get(
        "/api/iam/user_account/?f_hashed_password=x", headers=auth_headers
    )
    assert filter_response.status_code == 422


def test_list_order_rejects_invalid_direction(auth_headers):
    client = TestClient(app)

    response = client.get("/api/iam/role/?order_by=code&order=sideways", headers=auth_headers)
    assert response.status_code == 422


def test_list_pagination_is_stable_without_order_by(auth_headers):
    """With no order_by, the list route must still return rows in a stable order
    (ORDER BY id) -- otherwise offset pagination over N single-row pages can skip
    or repeat a row, since Postgres makes no ordering guarantee on its own (M-6)."""
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]

    codes = [f"page-{suffix}-{i}" for i in range(5)]
    role_ids = [_make_role(client, auth_headers, code) for code in codes]

    try:
        seen_ids = []
        for offset in range(len(codes)):
            page = client.get(
                f"/api/iam/role/?q={suffix}&limit=1&offset={offset}", headers=auth_headers
            )
            assert page.status_code == 200
            items = page.json()["items"]
            assert len(items) == 1
            seen_ids.append(items[0]["id"])

        assert len(seen_ids) == len(set(seen_ids)), "a row was repeated across pages"
        # Postgres compares uuids bytewise, which matches the hex-string order, so the
        # default ORDER BY id must yield ascending ids across pages -- this pins the
        # default ordering rather than relying on insertion order happening to hold.
        assert seen_ids == sorted(seen_ids), "rows were not returned in id order"
    finally:
        for role_id in role_ids:
            _delete_role(client, auth_headers, role_id)


def test_list_pagination_is_stable_with_order_by_on_a_non_unique_column(auth_headers):
    """order_by on a column that isn't unique (name, here, shared by every row created
    below) needs `id` appended as a tiebreaker, or rows with equal values can be
    reordered between two page fetches and a row can be skipped or repeated (M-6)."""
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]

    role_ids = [
        _make_role(client, auth_headers, f"tiebreak-{suffix}-{i}", f"same-name-{suffix}")
        for i in range(5)
    ]

    try:
        seen_ids = []
        for offset in range(5):
            page = client.get(
                f"/api/iam/role/?q={suffix}&order_by=name&limit=1&offset={offset}",
                headers=auth_headers,
            )
            assert page.status_code == 200
            items = page.json()["items"]
            assert len(items) == 1
            seen_ids.append(items[0]["id"])

        assert len(seen_ids) == len(set(seen_ids)), "a row was repeated across pages"
    finally:
        for role_id in role_ids:
            _delete_role(client, auth_headers, role_id)
