"""Graph layouts saved on the server (`app/api/layouts.py`).

A layout is one person's arrangement of one problem's graph: saved and read
back, replaced by the next save, cleared by an empty one or a delete, never
seen by a colleague, and out of reach of another organization. Its shape is
checked: finite x and y for each card, and no more cards than the browser keeps.
"""

from __future__ import annotations

import uuid

import pytest

from app.api.layouts import MAX_CARDS
from tests.test_api_drafts import colleague  # noqa: F401
from tests.test_api_problems import (  # noqa: F401
    _problem,
    auth_headers,
    client,
    db,
    domain_id,
    ensure_admin_seeded,
)
from tests.test_tenancy import tenants  # noqa: F401


@pytest.fixture
def problem_id(client, auth_headers, domain_id):  # noqa: F811
    return _problem(client, auth_headers, domain_id, f"layouts-{uuid.uuid4().hex[:6]}")


def _url(problem):
    return f"/api/v1/problems/{problem}/graph-layout"


def test_a_layout_is_saved_replaced_and_cleared(client, auth_headers, problem_id):  # noqa: F811
    empty = client.get(_url(problem_id), headers=auth_headers)
    assert empty.status_code == 200 and empty.json() == {"positions": {}, "updated_at": None}
    saved = client.put(_url(problem_id), json={"positions": {"var:x": {"x": 10, "y": -4.5}}}, headers=auth_headers)
    assert saved.status_code == 200, saved.text
    assert saved.json()["positions"] == {"var:x": {"x": 10.0, "y": -4.5}} and saved.json()["updated_at"]
    client.put(_url(problem_id), json={"positions": {"rule:c": {"x": 1, "y": 2}}}, headers=auth_headers)
    assert client.get(_url(problem_id), headers=auth_headers).json()["positions"] == {"rule:c": {"x": 1.0, "y": 2.0}}
    cleared = client.put(_url(problem_id), json={"positions": {}}, headers=auth_headers)
    assert cleared.json()["updated_at"] is None
    client.put(_url(problem_id), json={"positions": {"a": {"x": 1, "y": 2}}}, headers=auth_headers)
    assert client.delete(_url(problem_id), headers=auth_headers).status_code == 204
    assert client.get(_url(problem_id), headers=auth_headers).json()["positions"] == {}


@pytest.mark.parametrize("positions", [
    {"a": {"x": 1}},
    {"a": {"x": 1, "y": "2"}},
    {"a": {"x": 1, "y": True}},
    {"a": {"x": 1, "y": 2, "z": 3}},
    {"a": {"x": 1e12, "y": 0}},
    {"": {"x": 1, "y": 2}},
    {f"c{i}": {"x": i, "y": i} for i in range(MAX_CARDS + 1)},
])
def test_a_malformed_layout_is_refused_and_nothing_is_kept(client, auth_headers, problem_id, positions):  # noqa: F811
    refused = client.put(_url(problem_id), json={"positions": positions}, headers=auth_headers)
    assert refused.status_code == 422
    assert client.get(_url(problem_id), headers=auth_headers).json()["positions"] == {}


def test_a_layout_is_its_owners_alone(client, auth_headers, problem_id, colleague):  # noqa: F811
    client.put(_url(problem_id), json={"positions": {"mine": {"x": 1, "y": 1}}}, headers=auth_headers)
    assert client.get(_url(problem_id), headers=colleague).json()["positions"] == {}
    client.put(_url(problem_id), json={"positions": {"theirs": {"x": 2, "y": 2}}}, headers=colleague)
    assert client.delete(_url(problem_id), headers=colleague).status_code == 204
    assert client.get(_url(problem_id), headers=auth_headers).json()["positions"] == {"mine": {"x": 1.0, "y": 1.0}}


def test_another_organization_cannot_reach_the_problems_layouts(client, tenants):  # noqa: F811
    problem = tenants["problem_a"]
    assert client.put(_url(problem), json={"positions": {"a": {"x": 1, "y": 1}}}, headers=tenants["a"]).status_code == 200
    assert client.get(_url(problem), headers=tenants["b"]).status_code == 404
    assert client.put(_url(problem), json={"positions": {"b": {"x": 1, "y": 1}}}, headers=tenants["b"]).status_code == 404
    assert client.delete(_url(problem), headers=tenants["b"]).status_code == 404
    assert client.get(_url(problem), headers=tenants["a"]).json()["positions"] == {"a": {"x": 1.0, "y": 1.0}}
