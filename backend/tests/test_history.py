"""A record's history (migration 0100): who changed what, from what to what, by any writer."""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.history import changes
from app.core.db import SessionLocal
from app.main import app
from tests.test_api_relationships import _entity, auth_headers, ensure_admin_seeded, types, domain_id  # noqa: F401

client = TestClient(app)


def _history(entity_id, headers):
    got = client.get(f"/api/v1/entities/{entity_id}/history", headers=headers)
    assert got.status_code == 200, got.text
    return got.json()


def test_changes_are_field_by_field():
    before = {"key": "a", "label": None, "active": True, "sort_order": 0, "attrs": {"bays": 4, "fuel": "diesel"}}
    after = {**before, "label": "A", "attrs": {"bays": 6}}
    assert changes(before, after) == [{"field": "label", "before": None, "after": "A"},
                                      {"field": "bays", "before": 4, "after": 6},
                                      {"field": "fuel", "before": "diesel", "after": None}]


def test_create_edit_and_delete_are_kept_with_who_did_them(auth_headers, types):  # noqa: F811
    unit = types["unit"]
    made = _entity(client, auth_headers, unit, "north", label="North")
    assert client.patch(f"/api/v1/entities/{made}", json={"label": "North depot"}, headers=auth_headers).status_code == 200
    # A save that changes nothing is not a change.
    assert client.patch(f"/api/v1/entities/{made}", json={"label": "North depot"}, headers=auth_headers).status_code == 200

    h = _history(made, auth_headers)
    assert [i["op"] for i in h["items"]] == ["update", "insert"] and h["total"] == 2
    assert h["items"][0]["changes"] == [{"field": "label", "before": "North", "after": "North depot"}]
    assert h["items"][0]["actor"] == "admin"

    assert client.delete(f"/api/v1/entities/{made}", headers=auth_headers).status_code == 204
    after_delete = _history(made, auth_headers)  # outlives the record
    assert after_delete["items"][0]["op"] == "delete" and after_delete["total"] == 3


def test_a_writer_outside_the_api_is_kept_too_with_no_one_named(auth_headers, types):  # noqa: F811
    made = _entity(client, auth_headers, types["unit"], "south")
    with SessionLocal() as db:
        db.execute(text("UPDATE entity SET sort_order = 5 WHERE id = :e"), {"e": made})
        db.commit()
    latest = _history(made, auth_headers)["items"][0]
    assert latest["actor"] is None and latest["changes"] == [{"field": "sort_order", "before": 0, "after": 5}]


def test_an_unknown_record_with_no_history_is_404(auth_headers):  # noqa: F811
    assert client.get("/api/v1/entities/999999999/history", headers=auth_headers).status_code == 404
