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


def test_get_domain_graph_returns_entity_as_node(auth_headers, organization_id):
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]

    et_response = client.post(
        "/api/domain/entity_type/",
        json={"organization_id": organization_id, "code": f"unit-{suffix}", "name": "Unit"},
        headers=auth_headers,
    )
    assert et_response.status_code == 201
    entity_type_id = et_response.json()["id"]
    entity_type_code = et_response.json()["code"]

    entity_response = client.post(
        "/api/domain/entity/",
        json={
            "organization_id": organization_id,
            "entity_type_id": entity_type_id,
            "code": f"e1-{suffix}",
            "name": "Test Entity",
        },
        headers=auth_headers,
    )
    assert entity_response.status_code == 201
    entity_id = entity_response.json()["id"]

    graph_response = client.get(
        f"/api/graph/domain?organization_id={organization_id}", headers=auth_headers
    )
    assert graph_response.status_code == 200
    body = graph_response.json()

    node = next(n for n in body["nodes"] if n["id"] == entity_id)
    assert node["type"] == entity_type_code
    assert node["label"] == "Test Entity"
    assert node["parent"] is None
    assert node["attributes"]["code"] == f"e1-{suffix}"
    assert any(et["id"] == entity_type_id for et in body["entity_types"])


def test_get_domain_graph_requires_auth():
    client = TestClient(app)
    response = client.get(f"/api/graph/domain?organization_id={uuid.uuid4()}")
    assert response.status_code == 401


def test_graph_edges_exclude_cross_org_targets(auth_headers, organization_id):
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]

    other_org_response = client.post(
        "/api/iam/organization/",
        json={"code": f"other-org-{suffix}", "name": "Other Org"},
        headers=auth_headers,
    )
    assert other_org_response.status_code == 201
    other_organization_id = other_org_response.json()["id"]

    type_a = client.post(
        "/api/domain/entity_type/",
        json={"organization_id": organization_id, "code": f"thing-a-{suffix}", "name": "Thing A"},
        headers=auth_headers,
    ).json()
    type_b = client.post(
        "/api/domain/entity_type/",
        json={"organization_id": other_organization_id, "code": f"thing-b-{suffix}", "name": "Thing B"},
        headers=auth_headers,
    ).json()
    rel_type = client.post(
        "/api/domain/relationship_type/",
        json={"code": f"linked_to-{suffix}", "name": "Linked To", "is_directed": False},
        headers=auth_headers,
    ).json()

    node_in_org = client.post(
        "/api/graph/domain/nodes",
        json={"organization_id": organization_id, "entity_type_id": type_a["id"], "name": "In Org"},
        headers=auth_headers,
    ).json()
    node_in_other_org = client.post(
        "/api/graph/domain/nodes",
        json={"organization_id": other_organization_id, "entity_type_id": type_b["id"], "name": "In Other Org"},
        headers=auth_headers,
    ).json()

    edge_response = client.post(
        "/api/graph/domain/edges",
        json={
            "relationship_type_id": rel_type["id"],
            "source_entity_id": node_in_org["id"],
            "target_entity_id": node_in_other_org["id"],
        },
        headers=auth_headers,
    )
    assert edge_response.status_code == 201

    graph_response = client.get(
        f"/api/graph/domain?organization_id={organization_id}", headers=auth_headers
    )
    assert graph_response.status_code == 200
    edge_ids = {edge["id"] for edge in graph_response.json()["edges"]}
    assert edge_response.json()["id"] not in edge_ids

    # Sanity check: the source-side node is still in the graph, just not the edge.
    node_ids = {node["id"] for node in graph_response.json()["nodes"]}
    assert node_in_org["id"] in node_ids
    assert node_in_other_org["id"] not in node_ids


def test_relationship_type_constraint_resolves_across_organizations(auth_headers, organization_id):
    """relationship_type has no organization_id column and is returned for every
    organisation's graph -- a source/target constraint naming an entity_type that
    belongs to a DIFFERENT org than the one being viewed used to resolve to `null`
    ("any -> any") because it was looked up only in the current org's entity-type
    map (M-1), which then let the create-edge picker offer, and the backend 422
    reject, a combination it should have excluded outright."""
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]

    other_org_response = client.post(
        "/api/iam/organization/",
        json={"code": f"other-org-{suffix}", "name": "Other Org"},
        headers=auth_headers,
    )
    assert other_org_response.status_code == 201
    other_organization_id = other_org_response.json()["id"]

    # Both source and target types live in the OTHER organization -- the
    # currently-viewed org (organization_id) has no entity_types of its own here.
    source_type = client.post(
        "/api/domain/entity_type/",
        json={"organization_id": other_organization_id, "code": f"source-type-{suffix}", "name": "Source Type"},
        headers=auth_headers,
    ).json()
    target_type = client.post(
        "/api/domain/entity_type/",
        json={"organization_id": other_organization_id, "code": f"target-type-{suffix}", "name": "Target Type"},
        headers=auth_headers,
    ).json()

    rel_type = client.post(
        "/api/domain/relationship_type/",
        json={
            "code": f"cross-org-rel-{suffix}",
            "name": "Cross Org Rel",
            "is_directed": True,
            "source_entity_type": source_type["id"],
            "target_entity_type": target_type["id"],
        },
        headers=auth_headers,
    )
    assert rel_type.status_code == 201

    graph_response = client.get(
        f"/api/graph/domain?organization_id={organization_id}", headers=auth_headers
    )
    assert graph_response.status_code == 200
    body = graph_response.json()

    rt = next(r for r in body["relationship_types"] if r["id"] == rel_type.json()["id"])
    assert rt["source_entity_type"] == source_type["code"]
    assert rt["target_entity_type"] == target_type["code"]


def test_eav_attribute_code_colliding_with_a_builtin_key_does_not_overwrite_it(auth_headers, organization_id):
    """An attribute_definition whose code is "status" (or code/description) must
    never shadow the entity's own status column in the assembled node -- the
    built-in value always wins (M-9), both through create_node's return value and
    through a subsequent get_domain_graph read."""
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]

    et_response = client.post(
        "/api/domain/entity_type/",
        json={"organization_id": organization_id, "code": f"widget-{suffix}", "name": "Widget"},
        headers=auth_headers,
    )
    assert et_response.status_code == 201
    entity_type_id = et_response.json()["id"]

    attr_response = client.post(
        "/api/domain/attribute_definition/",
        json={
            "entity_type_id": entity_type_id,
            "code": "status",
            "name": "Shadow Status",
            "data_type": "string",
        },
        headers=auth_headers,
    )
    assert attr_response.status_code == 201

    node_response = client.post(
        "/api/graph/domain/nodes",
        json={
            "organization_id": organization_id,
            "entity_type_id": entity_type_id,
            "name": f"Widget-{suffix}",
            "status": "REAL_STATUS",
            "attributes": {"status": "eav-shadow-value"},
        },
        headers=auth_headers,
    )
    assert node_response.status_code == 201
    assert node_response.json()["attributes"]["status"] == "REAL_STATUS"
    entity_id = node_response.json()["id"]

    graph_response = client.get(
        f"/api/graph/domain?organization_id={organization_id}", headers=auth_headers
    )
    assert graph_response.status_code == 200
    node = next(n for n in graph_response.json()["nodes"] if n["id"] == entity_id)
    assert node["attributes"]["status"] == "REAL_STATUS"
