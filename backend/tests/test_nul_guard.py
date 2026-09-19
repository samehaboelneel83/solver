"""A NUL byte anywhere in a request is a 422, not a 500.

PostgreSQL `text` cannot store U+0000, and psycopg2 refuses to adapt a
Python string containing one. Before this guard, four reachable paths
turned that refusal into an unhandled 500:

1. ``POST /api/v1/entities`` with a NUL in an `attrs` **value**
2. ``POST /api/v1/entities`` with a NUL in `key`
3. ``GET  /api/v1/entities?q=``   -- a query parameter
4. ``GET  /api/v1/entities?expr=`` -- a rule's `value`, a query parameter

Two of them are GET query parameters, so any visitor reaches them by
pasting a URL; the other two need only a JSON body with a ``\\u0000``
escape in it, which is legal JSON.

Why `translate_db_error` could not close this
---------------------------------------------
psycopg2 raises a **bare `ValueError`** ("A string literal cannot contain
NUL (0x00) characters.") while *adapting* the parameter -- before the
statement is sent. There is no SQLSTATE, so SQLAlchemy never wraps it in a
`DBAPIError`, so `translate_db_error` is never reached and never could
be: it keys on `exc.orig.pgcode`. Catching `ValueError` around every
`db.execute` would be both wider (it would swallow real bugs) and
narrower (it would still miss any route nobody remembered to wrap).

Why one guard and not a rule per field
--------------------------------------
The defect is not a property of `attrs`, `key`, `q` or `expr`. It is a
property of *every* string that reaches Postgres, and the four paths found
by review are the four that happen to exist today -- routers added later
would each reintroduce it. `NulByteGuard` (`app/core/nul_guard.py`) is
therefore ASGI middleware: it inspects the query string and the JSON or
form body of every request once, before routing, and the tests below
assert both that the four known paths are closed **and** that the guard is
general (an unrelated route, a nested path inside `attrs`, a query
parameter on the generic CRUD router).
"""

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.main import app
from app.seed import seed_admin

NUL = "\x00"


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
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def domain_id(auth_headers):
    client = TestClient(app)
    response = client.post(
        "/api/domain/",
        json={"name": f"nul-test-{uuid.uuid4().hex[:8]}"},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    created_id = response.json()["id"]
    try:
        yield created_id
    finally:
        client.delete(f"/api/domain/{created_id}", headers=auth_headers)


@pytest.fixture
def entity_type_id(auth_headers, domain_id):
    """An `employee` type with one optional `text` attribute, so a NUL can
    be put in an `attrs` value that the trigger would otherwise accept."""
    client = TestClient(app)
    response = client.post(
        "/api/v1/entity-types",
        json={"domain_id": domain_id, "name": "employee", "role": "agent"},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    type_id = response.json()["id"]
    attribute = client.post(
        f"/api/v1/entity-types/{type_id}/attributes",
        json={"name": "full_name", "data_type": "text"},
        headers=auth_headers,
    )
    assert attribute.status_code == 201, attribute.text
    return type_id


def _refusal(response) -> dict:
    """Assert `response` is the guard's 422 and return its one entry.

    The shape is FastAPI's own list-shaped validation error (Ruling 19 --
    the platform has exactly one 422 body), so `formatApiError` and every
    other consumer render it without a special case. `kind` is deliberately
    absent: that key marks a *database trigger's* refusal, and this one
    never reached the database."""
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert isinstance(detail, list), detail
    assert len(detail) == 1, detail
    entry = detail[0]
    assert entry["type"] == "value_error", entry
    assert "kind" not in entry, entry
    assert "NUL" in entry["msg"], entry
    return entry


# --- the four paths review found -----------------------------------------


def test_nul_in_an_attrs_value_is_422_naming_the_attribute(auth_headers, entity_type_id):
    client = TestClient(app)
    response = client.post(
        "/api/v1/entities",
        json={
            "entity_type_id": entity_type_id,
            "key": "e1",
            "attrs": {"full_name": f"Ada{NUL}Lovelace"},
        },
        headers=auth_headers,
    )
    assert _refusal(response)["loc"] == ["body", "attrs", "full_name"]


def test_nul_in_entity_key_is_422_naming_key(auth_headers, entity_type_id):
    client = TestClient(app)
    response = client.post(
        "/api/v1/entities",
        json={"entity_type_id": entity_type_id, "key": f"e{NUL}1", "attrs": {}},
        headers=auth_headers,
    )
    assert _refusal(response)["loc"] == ["body", "key"]


def test_nul_in_the_q_query_parameter_is_422_naming_q(auth_headers, entity_type_id):
    client = TestClient(app)
    response = client.get(
        "/api/v1/entities",
        params={"entity_type_id": entity_type_id, "q": f"a{NUL}b"},
        headers=auth_headers,
    )
    assert _refusal(response)["loc"] == ["query", "q"]


def test_nul_in_the_expr_query_parameter_is_422_naming_expr(auth_headers, entity_type_id):
    r"""`expr` is the path that could not have been fixed downstream: the
    expression compiler binds a rule's `value`, so the NUL reaches
    psycopg2's adapter as a bare ValueError rather than any DBAPIError.

    It is also the path that shows why a "does the request contain a NUL
    byte" check is not enough. `json.dumps` escapes a NUL to `\u0000`, so
    the document on the wire holds **no NUL byte at all** -- it becomes one
    only when the route parses it. The guard therefore parses a query value
    that is itself a JSON document, and reports a `loc` that continues into
    it, the way `_expression_filter` reports its own refusals."""
    client = TestClient(app)
    document = json.dumps(
        {
            "version": 1,
            "query": {
                "combinator": "and",
                "rules": [
                    {
                        "field": f"attr:{entity_type_id}:full_name",
                        "operator": "contains",
                        "value": f"a{NUL}b",
                    }
                ],
            },
        }
    )
    response = client.get(
        "/api/v1/entities",
        params={"entity_type_id": entity_type_id, "expr": document},
        headers=auth_headers,
    )
    assert _refusal(response)["loc"] == [
        "query",
        "expr",
        "query",
        "rules",
        0,
        "value",
    ]


# --- the guard is general, not four patches ------------------------------


def test_nul_deep_inside_a_body_names_the_whole_path(auth_headers, entity_type_id):
    """A NUL nested in an object and then a list is located exactly, the
    way Pydantic locates a failure inside a list item -- list indices are
    integers in `loc`, not strings."""
    client = TestClient(app)
    response = client.post(
        "/api/v1/entities",
        json={
            "entity_type_id": entity_type_id,
            "key": "nested",
            "attrs": {"tags": ["fine", f"a{NUL}b"]},
        },
        headers=auth_headers,
    )
    assert _refusal(response)["loc"] == ["body", "attrs", "tags", 1]


def test_nul_in_an_object_key_names_that_key(auth_headers, entity_type_id):
    client = TestClient(app)
    response = client.post(
        "/api/v1/entities",
        json={"entity_type_id": entity_type_id, "key": "e2", "attrs": {f"fu{NUL}ll": "x"}},
        headers=auth_headers,
    )
    assert _refusal(response)["loc"] == ["body", "attrs", f"fu{NUL}ll"]


def test_nul_on_the_generic_crud_router_is_also_422(auth_headers):
    """The guard runs before routing, so a router review never looked at is
    covered too."""
    client = TestClient(app)
    response = client.get(
        "/api/domain/", params={"q": f"x{NUL}y"}, headers=auth_headers
    )
    assert _refusal(response)["loc"] == ["query", "q"]


def test_nul_in_a_form_body_is_422(auth_headers):
    """`POST /api/auth/login` takes a form, not JSON, and looks the username
    up in `iam.user_account` -- the same 500 by a different content type.
    Review did not list this one."""
    client = TestClient(app)
    response = client.post(
        "/api/auth/login", data={"username": f"ad{NUL}min", "password": "x"}
    )
    assert _refusal(response)["loc"] == ["body", "username"]


def test_the_guard_runs_before_authentication(auth_headers):
    """Deliberate, and pinned so it is a decision rather than a surprise: a
    malformed request is refused without consulting the database at all, so
    an unauthenticated caller gets 422 rather than 401. Nothing about the
    system is disclosed by it -- only that NUL is not accepted."""
    client = TestClient(app)
    response = client.get("/api/domain/", params={"q": f"x{NUL}y"})
    assert response.status_code == 422, response.text


# --- and it does not refuse things that are fine -------------------------


def test_a_literal_backslash_u_0000_in_a_string_is_not_a_nul(auth_headers, entity_type_id):
    r"""The fast pre-check looks for the bytes `\u0000` before parsing, so
    the text `\u0000` (an escaped backslash, six ordinary characters) trips
    it. Parsing is what decides, so this must still be accepted."""
    client = TestClient(app)
    response = client.post(
        "/api/v1/entities",
        json={
            "entity_type_id": entity_type_id,
            "key": "literal",
            "attrs": {"full_name": r"a\u0000b"},
        },
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    assert response.json()["attrs"]["full_name"] == r"a\u0000b"


def test_a_query_value_that_is_not_json_is_left_alone(auth_headers, entity_type_id):
    r"""The guard parses a query value only to see whether it is a JSON
    document hiding an escaped NUL. A `q=` search for the literal six
    characters `\u0000` is not JSON, contains no NUL, and must search."""
    client = TestClient(app)
    response = client.get(
        "/api/v1/entities",
        params={"entity_type_id": entity_type_id, "q": r"a\u0000b"},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["items"] == []


def test_an_ordinary_request_is_untouched(auth_headers, entity_type_id):
    """The guard buffers and replays the request body; a normal POST must
    still arrive intact."""
    client = TestClient(app)
    response = client.post(
        "/api/v1/entities",
        json={"entity_type_id": entity_type_id, "key": "ok", "attrs": {"full_name": "Ada"}},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    assert response.json()["key"] == "ok"
    assert response.json()["attrs"]["full_name"] == "Ada"
