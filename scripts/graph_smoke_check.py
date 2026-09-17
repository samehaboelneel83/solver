"""Full-stack smoke check for the Graph Editor sub-project.

Assumes the platform stack is already up (`docker compose up -d`) and
migrated, and that the frontend/backend images have been rebuilt to
include this sub-project's code. Run the graph demo seed first:
    docker compose exec -T backend python -m app.seed_graph_demo
Then run this script from the host:
    python scripts/graph_smoke_check.py
(use `python3` instead if that's what resolves on your machine)
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = "http://localhost:8010"
FRONTEND_URL = "http://localhost:3010"
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "change-me-admin")


def request(method, path, token=None, body=None):
    url = f"{BASE_URL}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if data:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as response:
        raw = response.read()
        return json.loads(raw) if raw else None


def login(username, password):
    body = urllib.parse.urlencode({"username": username, "password": password}).encode()
    req = urllib.request.Request(f"{BASE_URL}/api/auth/login", data=body, method="POST")
    with urllib.request.urlopen(req) as response:
        return json.loads(response.read())["access_token"]


def main():
    print("== Logging in ==")
    token = login(ADMIN_USERNAME, ADMIN_PASSWORD)

    print("== Resolving the default organization ==")
    orgs = request("GET", "/api/iam/organization/?limit=50&offset=0", token=token)
    org_id = next(o["id"] for o in orgs["items"] if o["code"] == "default")

    print("== Fetching the domain graph and confirming seeded demo data is present ==")
    graph = request("GET", f"/api/graph/domain?organization_id={org_id}", token=token)
    labels = {n["label"] for n in graph["nodes"]}
    assert "Ahmed" in labels, f"Ahmed not found in nodes: {labels}"
    assert len(graph["edges"]) >= 3, f"expected at least 3 demo relationships, got {len(graph['edges'])}"

    employee_type = next(t for t in graph["entity_types"] if t["code"] == "employee-demo")
    works_for_type = next(t for t in graph["relationship_types"] if t["code"] == "works_for-demo")
    hierarchy = next(h for h in graph["hierarchies"] if h["code"] == "org-chart-demo")
    unit_node = next(n for n in graph["nodes"] if n["type"] == "unit-demo")

    print("== Creating a node via the Graph API (with hierarchy placement) ==")
    node = request(
        "POST",
        "/api/graph/domain/nodes",
        token=token,
        body={
            "organization_id": org_id,
            "entity_type_id": employee_type["id"],
            "name": "Smoke Test Person",
            "hierarchy_id": hierarchy["id"],
        },
    )
    assert node["label"] == "Smoke Test Person"
    assert node["parent"] is None

    print("== Creating an edge via the Graph API (type-validated) ==")
    edge = request(
        "POST",
        "/api/graph/domain/edges",
        token=token,
        body={
            "relationship_type_id": works_for_type["id"],
            "source_entity_id": node["id"],
            "target_entity_id": unit_node["id"],
        },
    )
    assert edge["type"] == "works_for-demo"

    print("== Updating the node's status via PATCH ==")
    updated = request("PATCH", f"/api/graph/domain/nodes/{node['id']}", token=token, body={"status": "ACTIVE"})
    assert updated["attributes"]["status"] == "ACTIVE"

    print("== Confirming delete is blocked (409) while the node still has an edge ==")
    try:
        request("DELETE", f"/api/graph/domain/nodes/{node['id']}", token=token)
        raise AssertionError("expected a 409 conflict, delete succeeded instead")
    except urllib.error.HTTPError as exc:
        assert exc.code == 409, f"expected 409, got {exc.code}"

    print("== Deleting the edge, then the now-unreferenced node ==")
    request("DELETE", f"/api/graph/domain/edges/{edge['id']}", token=token)
    request("DELETE", f"/api/graph/domain/nodes/{node['id']}", token=token)

    print("== Confirming the frontend serves the /graph route ==")
    req = urllib.request.Request(f"{FRONTEND_URL}/graph")
    with urllib.request.urlopen(req) as response:
        assert response.status == 200

    print("== All graph smoke checks passed ==")


if __name__ == "__main__":
    main()
