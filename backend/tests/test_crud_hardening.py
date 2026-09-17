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


def test_delete_referenced_row_returns_409(auth_headers, organization_id):
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]

    et_response = client.post(
        "/api/domain/entity_type/",
        json={
            "organization_id": organization_id,
            "code": f"ref-type-{suffix}",
            "name": "Referenced Type",
            "is_abstract": False,
        },
        headers=auth_headers,
    )
    assert et_response.status_code == 201
    entity_type_id = et_response.json()["id"]

    entity_response = client.post(
        "/api/domain/entity/",
        json={
            "organization_id": organization_id,
            "entity_type_id": entity_type_id,
            "code": f"ref-entity-{suffix}",
            "name": "Referencing Entity",
        },
        headers=auth_headers,
    )
    assert entity_response.status_code == 201

    delete_response = client.delete(f"/api/domain/entity_type/{entity_type_id}", headers=auth_headers)
    assert delete_response.status_code == 409
    assert "still referenced" in delete_response.json()["detail"]


def test_duplicate_code_returns_409(auth_headers, organization_id):
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]
    code = f"dup-{suffix}"
    payload = {
        "organization_id": organization_id,
        "code": code,
        "name": "Duplicate",
        "is_abstract": False,
    }

    first_response = client.post("/api/domain/entity_type/", json=payload, headers=auth_headers)
    assert first_response.status_code == 201

    second_response = client.post("/api/domain/entity_type/", json=payload, headers=auth_headers)
    assert second_response.status_code == 409
    assert "already exists" in second_response.json()["detail"]


def test_bad_fk_on_create_returns_409(auth_headers, organization_id):
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]

    response = client.post(
        "/api/domain/entity/",
        json={
            "organization_id": organization_id,
            "entity_type_id": str(uuid.uuid4()),
            "code": f"bad-fk-{suffix}",
            "name": "Bad FK Entity",
        },
        headers=auth_headers,
    )
    assert response.status_code == 409
    assert "does not exist" in response.json()["detail"]


def test_list_search_q(auth_headers):
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]

    for code in (f"alpha-{suffix}", f"beta-{suffix}"):
        response = client.post(
            "/api/domain/role_type/",
            json={"code": code, "name": code},
            headers=auth_headers,
        )
        assert response.status_code == 201

    search_response = client.get(
        f"/api/domain/role_type/?q=alpha-{suffix}", headers=auth_headers
    )
    assert search_response.status_code == 200
    items = search_response.json()["items"]
    assert len(items) == 1
    assert items[0]["code"] == f"alpha-{suffix}"


def test_list_filter_by_column(auth_headers, organization_id):
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]

    et_a = client.post(
        "/api/domain/entity_type/",
        json={
            "organization_id": organization_id,
            "code": f"filter-type-a-{suffix}",
            "name": "Filter Type A",
            "is_abstract": False,
        },
        headers=auth_headers,
    )
    assert et_a.status_code == 201
    entity_type_a_id = et_a.json()["id"]

    et_b = client.post(
        "/api/domain/entity_type/",
        json={
            "organization_id": organization_id,
            "code": f"filter-type-b-{suffix}",
            "name": "Filter Type B",
            "is_abstract": False,
        },
        headers=auth_headers,
    )
    assert et_b.status_code == 201
    entity_type_b_id = et_b.json()["id"]

    entity_a = client.post(
        "/api/domain/entity/",
        json={
            "organization_id": organization_id,
            "entity_type_id": entity_type_a_id,
            "code": f"filter-entity-a-{suffix}",
            "name": "Entity A",
        },
        headers=auth_headers,
    )
    assert entity_a.status_code == 201

    entity_b = client.post(
        "/api/domain/entity/",
        json={
            "organization_id": organization_id,
            "entity_type_id": entity_type_b_id,
            "code": f"filter-entity-b-{suffix}",
            "name": "Entity B",
        },
        headers=auth_headers,
    )
    assert entity_b.status_code == 201

    filter_response = client.get(
        f"/api/domain/entity/?f_entity_type_id={entity_type_a_id}", headers=auth_headers
    )
    assert filter_response.status_code == 200
    items = filter_response.json()["items"]
    assert all(item["entity_type_id"] == entity_type_a_id for item in items)
    assert any(item["code"] == f"filter-entity-a-{suffix}" for item in items)
    assert not any(item["code"] == f"filter-entity-b-{suffix}" for item in items)

    bad_filter_response = client.get("/api/domain/entity/?f_nope=1", headers=auth_headers)
    assert bad_filter_response.status_code == 422


def test_list_order_by(auth_headers):
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]

    codes = [f"order-c-{suffix}", f"order-a-{suffix}", f"order-b-{suffix}"]
    for code in codes:
        response = client.post(
            "/api/domain/role_type/",
            json={"code": code, "name": code},
            headers=auth_headers,
        )
        assert response.status_code == 201

    order_response = client.get(
        f"/api/domain/role_type/?q=order-&order_by=code&order=desc", headers=auth_headers
    )
    assert order_response.status_code == 200
    returned_codes = [item["code"] for item in order_response.json()["items"] if suffix in item["code"]]
    assert returned_codes == sorted(returned_codes, reverse=True)
    assert len(returned_codes) == 3

    bad_order_response = client.get("/api/domain/role_type/?order_by=nope", headers=auth_headers)
    assert bad_order_response.status_code == 422


def test_list_filter_bad_datetime_returns_422_not_500(auth_headers, organization_id):
    """f_<column>=<garbage> against a non str/bool/int/uuid column (here,
    entity_type.created_at, a DateTime) used to fall through _cast_filter_value's
    `return raw` branch and hit Postgres as a raw string, surfacing as a 500
    (psycopg2.errors.InvalidDatetimeFormat) instead of a clean validation error."""
    client = TestClient(app)

    bad_response = client.get(
        "/api/domain/entity_type/?f_created_at=notadate", headers=auth_headers
    )
    assert bad_response.status_code == 422

    valid_response = client.get(
        "/api/domain/entity_type/?f_created_at=2026-01-01T00:00:00%2B00:00", headers=auth_headers
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

    response = client.get(
        "/api/domain/role_type/?order_by=code&order=sideways", headers=auth_headers
    )
    assert response.status_code == 422


def test_list_pagination_is_stable_without_order_by(auth_headers):
    """With no order_by, the list route must still return rows in a stable order
    (ORDER BY id) -- otherwise offset pagination over N single-row pages can skip
    or repeat a row, since Postgres makes no ordering guarantee on its own (M-6)."""
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]

    codes = [f"page-{suffix}-{i}" for i in range(5)]
    for code in codes:
        response = client.post(
            "/api/domain/role_type/",
            json={"code": code, "name": code},
            headers=auth_headers,
        )
        assert response.status_code == 201

    seen_ids = []
    for offset in range(len(codes)):
        page = client.get(
            f"/api/domain/role_type/?q={suffix}&limit=1&offset={offset}", headers=auth_headers
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


def test_list_pagination_is_stable_with_order_by_on_a_non_unique_column(auth_headers, organization_id):
    """order_by on a column that isn't unique (name, here, shared by every row created
    below) needs `id` appended as a tiebreaker, or rows with equal values can be
    reordered between two page fetches and a row can be skipped or repeated (M-6)."""
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]

    for i in range(5):
        response = client.post(
            "/api/domain/entity_type/",
            json={
                "organization_id": organization_id,
                "code": f"tiebreak-{suffix}-{i}",
                "name": f"same-name-{suffix}",
            },
            headers=auth_headers,
        )
        assert response.status_code == 201

    seen_ids = []
    for offset in range(5):
        page = client.get(
            f"/api/domain/entity_type/?q={suffix}&order_by=name&limit=1&offset={offset}",
            headers=auth_headers,
        )
        assert page.status_code == 200
        items = page.json()["items"]
        assert len(items) == 1
        seen_ids.append(items[0]["id"])

    assert len(seen_ids) == len(set(seen_ids)), "a row was repeated across pages"
