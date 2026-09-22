"""`entity_type.icon` (migration 0033): the picture the Graph View draws a
type's entities with.

One column, two forms: a gallery key (`hotel`, the frontend's bundled
icons) or an uploaded image as a `data:` URI. NULL means "not chosen", and
the frontend picks a default from the type's name and role -- so, like
`colour`, NULL must stay expressible and is never defaulted away here.

An upload is only ever drawn as an image (a canvas `background-image`, an
`<img>`), where an SVG's scripts do not run. The request layer still
refuses an SVG carrying script, event handlers or external references:
the file is stored and handed to every viewer of the domain, and "it is
harmless where we draw it today" is not a property worth relying on.
"""

import base64
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.main import app
from app.seed import seed_admin

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)
SAFE_SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 8 8"><rect width="8" height="8" fill="#16a34a"/></svg>'


def data_uri(mime: str, payload: bytes) -> str:
    return f"data:{mime};base64,{base64.b64encode(payload).decode()}"


@pytest.fixture(autouse=True)
def ensure_admin_seeded():
    db = SessionLocal()
    seed_admin(db)
    db.close()


@pytest.fixture
def auth_headers():
    settings = get_settings()
    response = TestClient(app).post(
        "/api/auth/login",
        data={"username": settings.admin_username, "password": settings.admin_password},
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def domain_id(auth_headers):
    client = TestClient(app)
    response = client.post(
        "/api/domain/", json={"name": f"icon-test-{uuid.uuid4().hex[:8]}"}, headers=auth_headers
    )
    assert response.status_code == 201, response.text
    created_id = response.json()["id"]
    try:
        yield created_id
    finally:
        client.delete(f"/api/domain/{created_id}", headers=auth_headers)


def _create(auth_headers, domain_id, **extra):
    return TestClient(app).post(
        "/api/v1/entity-types",
        json={"domain_id": domain_id, "name": "hotel", **extra},
        headers=auth_headers,
    )


def _patch(auth_headers, type_id, **body):
    return TestClient(app).patch(
        f"/api/v1/entity-types/{type_id}", json=body, headers=auth_headers
    )


def _blamed(response, field="icon") -> str:
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    matches = [e for e in detail if e["loc"][:1] == ["body"] and e["loc"][-1:] == [field]]
    assert matches, detail
    return matches[0]["msg"]


def test_icon_defaults_to_null(auth_headers, domain_id):
    response = _create(auth_headers, domain_id)
    assert response.status_code == 201, response.text
    assert response.json()["icon"] is None


def test_gallery_key_round_trips_and_null_clears_it(auth_headers, domain_id):
    created = _create(auth_headers, domain_id, icon="bus_stop").json()
    assert created["icon"] == "bus_stop"
    cleared = _patch(auth_headers, created["id"], icon=None)
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["icon"] is None


def test_patch_without_icon_leaves_it_alone(auth_headers, domain_id):
    created = _create(auth_headers, domain_id, icon="hotel").json()
    renamed = _patch(auth_headers, created["id"], name="inn").json()
    assert renamed["icon"] == "hotel"


@pytest.mark.parametrize("bad", ["Hotel", "bus stop", "1hotel", "", "a" * 41, "hotel\n"])
def test_a_gallery_key_must_be_a_lowercase_name(auth_headers, domain_id, bad):
    assert "gallery" in _blamed(_create(auth_headers, domain_id, icon=bad))


@pytest.mark.parametrize(
    "mime,payload", [("image/png", PNG_1PX), ("image/svg+xml", SAFE_SVG)]
)
def test_an_uploaded_image_round_trips(auth_headers, domain_id, mime, payload):
    uri = data_uri(mime, payload)
    created = _create(auth_headers, domain_id, icon=uri)
    assert created.status_code == 201, created.text
    assert created.json()["icon"] == uri


def test_webp_is_accepted(auth_headers, domain_id):
    webp = b"RIFF\x1a\x00\x00\x00WEBPVP8L\x0d\x00\x00\x00/\x00\x00\x00\x10\x07\x10\x11\x11\x88\x88\xfe\x07\x00"
    assert _create(auth_headers, domain_id, icon=data_uri("image/webp", webp)).status_code == 201


def test_an_image_over_200_kb_is_refused(auth_headers, domain_id):
    big = PNG_1PX + b"\0" * (200 * 1024)
    assert "200 KB" in _blamed(_create(auth_headers, domain_id, icon=data_uri("image/png", big)))


@pytest.mark.parametrize("mime", ["image/gif", "text/html", "image/jpeg"])
def test_only_png_svg_and_webp_are_accepted(auth_headers, domain_id, mime):
    assert "PNG, SVG or WebP" in _blamed(
        _create(auth_headers, domain_id, icon=data_uri(mime, PNG_1PX))
    )


def test_content_must_match_the_declared_type(auth_headers, domain_id):
    """A PNG label on bytes that are not a PNG is refused, not stored."""
    assert "is not a" in _blamed(
        _create(auth_headers, domain_id, icon=data_uri("image/png", SAFE_SVG))
    )


def test_broken_base64_is_refused(auth_headers, domain_id):
    assert "base64" in _blamed(
        _create(auth_headers, domain_id, icon="data:image/png;base64,@@not-base64@@")
    )


@pytest.mark.parametrize(
    "svg",
    [
        b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>',
        b'<svg xmlns="http://www.w3.org/2000/svg"><a href="javascript:alert(1)"/></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg"><image href="https://evil.example/x.png"/></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg"><foreignObject/></svg>',
        b'<!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]><svg/>',
    ],
)
def test_an_svg_that_could_run_or_fetch_anything_is_refused(auth_headers, domain_id, svg):
    assert "SVG" in _blamed(
        _create(auth_headers, domain_id, icon=data_uri("image/svg+xml", svg))
    )


def test_the_graph_carries_icon_and_role(auth_headers, domain_id):
    created = _create(auth_headers, domain_id, icon="hotel", role="location").json()
    graph = TestClient(app).get(f"/api/v1/graph?domain_id={domain_id}", headers=auth_headers)
    assert graph.status_code == 200, graph.text
    option = next(o for o in graph.json()["entity_types"] if o["id"] == str(created["id"]))
    assert option["icon"] == "hotel"
    assert option["role"] == "location"


def test_database_check_backs_up_the_request_layer(domain_id):
    """The CHECK still fires for a writer that is not this router."""
    db = SessionLocal()
    try:
        # Named, so a refusal for another reason (a NOT NULL, a tenancy
        # rule) cannot pass for this CHECK.
        with pytest.raises(IntegrityError, match="entity_type_icon_form"):
            db.execute(
                text(
                    "INSERT INTO entity_type (domain_id, name, icon)"
                    " VALUES (:d, 'probe', 'data:text/html;base64,PGI+')"
                ),
                {"d": domain_id},
            )
            db.flush()
    finally:
        db.rollback()
        db.close()
