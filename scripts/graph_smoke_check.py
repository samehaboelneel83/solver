"""Full-stack smoke check for the Graph Editor, schema v1.

Rewritten for schema v1 in Task 15. The v0 version called
`/api/graph/domain?organization_id=` and the graph's own node/edge write
routes; Task 7 replaced the read with `/api/v1/graph?domain_id=` and
**deleted** the writes, so the editor now writes through
`/api/v1/entities` and `/api/v1/relationships`. It also pointed at
`localhost:8010`/`3010`, which is the *user's* running stack; the default
here is the isolated verification stack on `8011`/`3011` instead, and
both are overridable.

Run the seed first, then this from the host:

    docker exec -e PYTHONPATH=/app solver-e2e-backend python -m app.seed
    python scripts/graph_smoke_check.py

Environment: `SMOKE_API_URL` (default http://localhost:8011),
`SMOKE_WEB_URL` (default http://localhost:3011), `ADMIN_USERNAME`,
`ADMIN_PASSWORD`.

What it checks, all against the seeded Workforce demo: the graph read
returns the demo's nodes, edges, types and hierarchies; hierarchy
placement turns `reports_to` rows into compound parents; a new entity and
a new relationship can be created through the v1 routers; the
`entity_validate` and `relationship_validate` triggers still refuse bad
data with a 422 naming the field; and the frontend serves `/graph`. It
cleans up everything it creates.
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = os.environ.get("SMOKE_API_URL", "http://localhost:8011").rstrip("/")
FRONTEND_URL = os.environ.get("SMOKE_WEB_URL", "http://localhost:3011").rstrip("/")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "change-me-admin")

DOMAIN_NAME = "Workforce"


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


def expect_error(method, path, token=None, body=None, status=422):
    """Assert the call fails with `status`, and return the parsed body."""
    try:
        request(method, path, token=token, body=body)
    except urllib.error.HTTPError as exc:
        assert exc.code == status, f"expected {status}, got {exc.code}"
        return json.loads(exc.read())
    raise AssertionError(f"expected a {status} from {method} {path}, it succeeded instead")


def login(username, password):
    body = urllib.parse.urlencode({"username": username, "password": password}).encode()
    req = urllib.request.Request(f"{BASE_URL}/api/auth/login", data=body, method="POST")
    with urllib.request.urlopen(req) as response:
        return json.loads(response.read())["access_token"]


def main():
    print(f"== Logging in at {BASE_URL} ==")
    token = login(ADMIN_USERNAME, ADMIN_PASSWORD)

    print(f"== Resolving the {DOMAIN_NAME!r} domain ==")
    domains = request("GET", "/api/domain/?limit=100&offset=0", token=token)
    domain = next(
        (d for d in domains["items"] if d["name"] == DOMAIN_NAME),
        None,
    )
    assert domain is not None, (
        f"domain {DOMAIN_NAME!r} not found -- run the seed first: "
        "docker exec -e PYTHONPATH=/app solver-e2e-backend python -m app.seed"
    )
    domain_id = domain["id"]

    print("== Reading the domain graph and confirming the seeded demo is present ==")
    graph = request("GET", f"/api/v1/graph?domain_id={domain_id}", token=token)
    labels = {n["label"] for n in graph["nodes"]}
    assert "Ahmed Salah" in labels, f"seeded employee not found in nodes: {sorted(labels)[:10]}"
    assert len(graph["edges"]) >= 5, f"expected the seeded relationships, got {len(graph['edges'])}"

    employee_type = next(t for t in graph["entity_types"] if t["name"] == "employee")
    works_in = next(t for t in graph["relationship_types"] if t["name"] == "works_in")
    reports_to = next(h for h in graph["hierarchies"] if h["name"] == "reports_to")

    print("== Confirming types carry their colours (Task 14b) ==")
    assert employee_type["colour"], "entity_type.colour missing from the graph payload"
    assert works_in["colour"], "relationship_type.colour missing from the graph payload"

    print("== Confirming hierarchy placement makes `reports_to` rows compound parents ==")
    placed = request(
        "GET",
        f"/api/v1/graph?domain_id={domain_id}&hierarchy_type_id={reports_to['id']}",
        token=token,
    )
    parents = {n["id"]: n["parent"] for n in placed["nodes"]}
    assert any(p is not None for p in parents.values()), "no node was given a parent"
    unplaced = {n["id"]: n["parent"] for n in graph["nodes"]}
    assert all(p is None for p in unplaced.values()), "parents set without a hierarchy_type_id"

    depot = next(n for n in placed["nodes"] if n["label"] == "North Depot")
    region = next(n for n in placed["nodes"] if n["label"] == "North Region")
    assert depot["parent"] == region["id"], "North Depot is not under North Region"

    created_entity = created_relationship = None
    try:
        print("== Rejecting an unknown attribute (entity_validate -> 422) ==")
        body = expect_error(
            "POST",
            "/api/v1/entities",
            token=token,
            body={
                "entity_type_id": int(employee_type["id"]),
                "key": "smoke_bad",
                "attrs": {"full_name": "Smoke", "nonesuch": 1},
            },
        )
        assert isinstance(body["detail"], list), "Ruling 19: every 422 is list-shaped"
        assert body["detail"][0]["loc"][-1] == "nonesuch", body["detail"]

        print("== Creating an entity through /api/v1/entities ==")
        created_entity = request(
            "POST",
            "/api/v1/entities",
            token=token,
            body={
                "entity_type_id": int(employee_type["id"]),
                "key": "smoke_person",
                "label": "Smoke Test Person",
                "attrs": {"full_name": "Smoke Test Person", "hours_per_week": 12},
            },
        )
        # attribute_def defaults are materialised by the trigger, not by us.
        assert created_entity["attrs"]["grade"] == "mid", created_entity["attrs"]
        assert created_entity["attrs"]["hours_per_week"] == 12

        print("== Creating a relationship through /api/v1/relationships ==")
        head_office = next(n for n in graph["nodes"] if n["label"] == "Head Office")
        created_relationship = request(
            "POST",
            "/api/v1/relationships",
            token=token,
            body={
                "relationship_type_id": int(works_in["id"]),
                "from_entity_id": created_entity["id"],
                "to_entity_id": int(head_office["id"]),
            },
        )

        print("== Refusing a second works_in for the same employee (cardinality -> 422) ==")
        north = next(n for n in graph["nodes"] if n["label"] == "North Region")
        body = expect_error(
            "POST",
            "/api/v1/relationships",
            token=token,
            body={
                "relationship_type_id": int(works_in["id"]),
                "from_entity_id": created_entity["id"],
                "to_entity_id": int(north["id"]),
            },
        )
        assert any(d.get("kind") == "cardinality" for d in body["detail"]), body["detail"]

        print("== Refusing an edge whose endpoints have the wrong types (422) ==")
        expect_error(
            "POST",
            "/api/v1/relationships",
            token=token,
            body={
                "relationship_type_id": int(works_in["id"]),
                "from_entity_id": int(head_office["id"]),
                "to_entity_id": int(north["id"]),
            },
        )

        print("== Confirming the new node and edge appear in the graph ==")
        after = request("GET", f"/api/v1/graph?domain_id={domain_id}", token=token)
        assert "Smoke Test Person" in {n["label"] for n in after["nodes"]}
        assert len(after["edges"]) == len(graph["edges"]) + 1
    finally:
        if created_relationship is not None:
            request(
                "DELETE",
                f"/api/v1/relationships/{created_relationship['id']}",
                token=token,
            )
        if created_entity is not None:
            request("DELETE", f"/api/v1/entities/{created_entity['id']}", token=token)

    print("== Confirming the graph is back to its seeded state ==")
    restored = request("GET", f"/api/v1/graph?domain_id={domain_id}", token=token)
    assert len(restored["nodes"]) == len(graph["nodes"])
    assert len(restored["edges"]) == len(graph["edges"])

    print(f"== Confirming {FRONTEND_URL} serves the /graph route ==")
    with urllib.request.urlopen(urllib.request.Request(f"{FRONTEND_URL}/graph")) as response:
        assert response.status == 200

    print("== All graph smoke checks passed ==")


if __name__ == "__main__":
    main()
