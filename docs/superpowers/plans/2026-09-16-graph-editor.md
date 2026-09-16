# Graph Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a domain-graph editor: a normalized graph contract, a backend Graph API with atomic multi-table writes and type-aware edge validation, and a Cytoscape.js-based React editor with hierarchy-driven compound-node nesting, a property panel, and a filter bar — on top of the already-built platform skeleton (31-table generic CRUD, auth, `domain`/`problem`/`iam` schemas, all on `master`).

**Architecture:** A new `GraphService` module assembles/mutates the graph by querying and writing the existing `domain.entity`/`entity_type`/`relationship`/`relationship_type`/`hierarchy`/`hierarchy_node`/`entity_attribute`/`attribute_definition` tables directly (not through the generic CRUD factory, since node/edge writes span multiple tables atomically). A thin FastAPI router exposes it at `/api/graph/domain`. The frontend adds a `<GraphEditor/>` (Cytoscape.js + ELK layout), `<PropertyPanel/>`, and `<FilterBar/>`, all reading from one `GET /api/graph/domain` call and writing through dedicated mutation hooks, following the same `apiFetch`/React-Query patterns the platform skeleton already established.

**Tech Stack:** Backend — same as the skeleton (FastAPI, SQLAlchemy 2.x, Pydantic v2, pytest). Frontend — same as the skeleton (React, TypeScript, TanStack Query) plus `cytoscape`, `cytoscape-elk`, `elkjs` (new dependencies).

**Spec:** `docs/superpowers/specs/2026-09-16-graph-editor-design.md`

## Global Constraints

- Domain schema only this phase — no `problem`-schema graph view (spec §2, §8).
- `relationship_type` has no `organization_id` column in the schema (verified against `backend/app/models/domain.py`) — relationship types are global, not org-scoped; `GraphService` returns all of them unfiltered.
- Every route depends on `get_current_user`, same as every existing route — no new auth mechanism (spec §4.2).
- List/read responses are never bare arrays elsewhere in this codebase, but `GraphResponse` is a single object (`{nodes, edges, entity_types, relationship_types, hierarchies, attribute_definitions}`), not a list — this is intentional (spec §3), don't wrap it in `{"items": ..., "total": ...}` like the generic CRUD list endpoints.
- `delete_node`/`delete_edge` must map a Postgres FK conflict to **HTTP 409**, not an unhandled 500 (spec §4.1 — a deliberate fix of a pattern the platform skeleton's final review already flagged once).
- `create_edge` must validate `relationship_type.source_entity_type`/`target_entity_type` (when set) against the two entities' actual types, rejecting a mismatch with **HTTP 422** (spec §4.1).
- All UUIDs are stringified in the graph contract (`GraphNode.id`, `GraphEdge.source`, etc. are `str`, matching how the rest of the platform's API already serializes UUIDs).
- No per-test DB reset fixture exists in this codebase — every test that writes a UNIQUE-constrained value (an entity_type/relationship_type/hierarchy `code`) MUST suffix it with `uuid.uuid4().hex[:8]`, from the first task onward. This was a real, repeated problem retrofitted late in the prior plan — bake it in from the start here.
- Seed demo data (`seed_graph_demo.py`) is NOT run at application startup — it's a manual script, run only on request (spec §6).
- Frontend tests verify the React wrapper's props/hooks/callbacks, not Cytoscape's actual canvas rendering, which jsdom can't meaningfully check (spec §7).

---

## Task 1: Graph contract types (backend Pydantic schemas)

**Files:**
- Create: `backend/app/graph/__init__.py`
- Create: `backend/app/graph/schemas.py`
- Test: `backend/tests/test_graph_schemas.py`

**Interfaces:**
- Produces: `GraphNode`, `GraphEdge`, `EntityTypeOption`, `RelationshipTypeOption`, `HierarchyOption`, `AttributeDefinitionOption`, `GraphResponse` — all Pydantic `BaseModel` classes in `app.graph.schemas`. Every later backend task (2-4) constructs and returns these; every frontend task (6+) mirrors their field names exactly in TypeScript.

- [ ] **Step 1: Write `backend/app/graph/__init__.py`** (empty)

- [ ] **Step 2: Write the failing test `backend/tests/test_graph_schemas.py`**

```python
from app.graph.schemas import (
    AttributeDefinitionOption,
    EntityTypeOption,
    GraphEdge,
    GraphNode,
    GraphResponse,
    HierarchyOption,
    RelationshipTypeOption,
)


def test_graph_node_defaults():
    node = GraphNode(id="e1", type="Employee", label="Ahmed")
    assert node.parent is None
    assert node.attributes == {}


def test_graph_node_with_parent_and_attributes():
    node = GraphNode(id="e1", type="Employee", label="Ahmed", parent="u1", attributes={"rank": "Captain"})
    assert node.parent == "u1"
    assert node.attributes == {"rank": "Captain"}


def test_graph_edge_defaults():
    edge = GraphEdge(id="r1", source="e1", target="u1", type="works_for", label="Works For")
    assert edge.attributes == {}


def test_graph_response_round_trip():
    response = GraphResponse(
        nodes=[GraphNode(id="e1", type="Employee", label="Ahmed")],
        edges=[GraphEdge(id="r1", source="e1", target="u1", type="works_for", label="Works For")],
        entity_types=[EntityTypeOption(id="t1", code="employee", name="Employee", is_abstract=False)],
        relationship_types=[
            RelationshipTypeOption(
                id="rt1", code="works_for", name="Works For", is_directed=True,
                source_entity_type="employee", target_entity_type="unit",
            )
        ],
        hierarchies=[HierarchyOption(id="h1", code="org-chart", name="Org Chart")],
        attribute_definitions=[
            AttributeDefinitionOption(id="a1", entity_type_id="t1", code="rank", name="Rank", data_type="string")
        ],
    )
    dumped = response.model_dump()
    assert dumped["nodes"][0]["id"] == "e1"
    restored = GraphResponse.model_validate(dumped)
    assert restored.edges[0].source == "e1"
```

Run: `docker compose exec -T backend pytest tests/test_graph_schemas.py -v`
Expected: FAIL (`ModuleNotFoundError: app.graph`)

- [ ] **Step 3: Write `backend/app/graph/schemas.py`**

```python
from typing import Any

from pydantic import BaseModel


class GraphNode(BaseModel):
    id: str
    type: str
    label: str
    parent: str | None = None
    attributes: dict[str, Any] = {}


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    type: str
    label: str
    attributes: dict[str, Any] = {}


class EntityTypeOption(BaseModel):
    id: str
    code: str
    name: str
    is_abstract: bool


class RelationshipTypeOption(BaseModel):
    id: str
    code: str
    name: str
    is_directed: bool
    source_entity_type: str | None = None
    target_entity_type: str | None = None


class HierarchyOption(BaseModel):
    id: str
    code: str
    name: str


class AttributeDefinitionOption(BaseModel):
    id: str
    entity_type_id: str
    code: str
    name: str
    data_type: str


class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    entity_types: list[EntityTypeOption]
    relationship_types: list[RelationshipTypeOption]
    hierarchies: list[HierarchyOption]
    attribute_definitions: list[AttributeDefinitionOption]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec -T backend pytest tests/test_graph_schemas.py -v`
Expected: PASS (no DB needed — pure Pydantic construction)

- [ ] **Step 5: Commit**

```bash
git add backend/app/graph/__init__.py backend/app/graph/schemas.py backend/tests/test_graph_schemas.py
git commit -m "feat: graph contract Pydantic schemas"
```

---

## Task 2: `GraphService.get_domain_graph` + `GET /api/graph/domain`

**Files:**
- Create: `backend/app/graph/service.py`
- Create: `backend/app/api/graph.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_graph_read.py`

**Interfaces:**
- Consumes: `GraphNode`/`GraphEdge`/`EntityTypeOption`/`RelationshipTypeOption`/`HierarchyOption`/`AttributeDefinitionOption`/`GraphResponse` (Task 1); `app.models.domain.{Entity,EntityType,EntityAttribute,AttributeDefinition,Relationship,RelationshipType,Hierarchy,HierarchyNode}` (already exist on `master`); `app.api.deps.get_current_user`, `app.core.db.get_db` (already exist).
- Produces: `get_domain_graph(db: Session, *, organization_id: uuid.UUID, hierarchy_id: uuid.UUID | None = None) -> GraphResponse` in `app.graph.service` — Task 3/4 do not call this directly but establish the module other functions live in. `GET /api/graph/domain?organization_id=<uuid>&hierarchy_id=<uuid|omit>` returning `GraphResponse` as a single JSON object (not `{"items":...,"total":...}`).

- [ ] **Step 1: Write `backend/app/graph/service.py`**

```python
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.graph.schemas import (
    AttributeDefinitionOption,
    EntityTypeOption,
    GraphEdge,
    GraphNode,
    GraphResponse,
    HierarchyOption,
    RelationshipTypeOption,
)
from app.models.domain import (
    AttributeDefinition,
    Entity,
    EntityAttribute,
    EntityType,
    Hierarchy,
    HierarchyNode,
    Relationship,
    RelationshipType,
)


def _node_label(entity: Entity) -> str:
    return entity.name or entity.code or str(entity.id)


def _attribute_value(row: EntityAttribute) -> Any:
    for column in ("value_string", "value_number", "value_boolean", "value_date", "value_datetime", "value_json"):
        value = getattr(row, column)
        if value is not None:
            return value
    return None


def get_domain_graph(
    db: Session, *, organization_id: uuid.UUID, hierarchy_id: uuid.UUID | None = None
) -> GraphResponse:
    """Assemble the full domain graph for one organization.

    hierarchy_id, if given, determines each node's `parent` (for Cytoscape
    compound-node nesting) from that hierarchy's hierarchy_node rows.
    relationship_type has no organization_id column (verified against the
    model) -- it is a global taxonomy, so all relationship types are
    returned regardless of organization.
    """
    entities = db.query(Entity).filter(Entity.organization_id == organization_id).all()
    entity_type_by_id = {
        et.id: et for et in db.query(EntityType).filter(EntityType.organization_id == organization_id).all()
    }
    entity_ids = [e.id for e in entities]

    parent_by_entity_id: dict[uuid.UUID, uuid.UUID | None] = {}
    if hierarchy_id is not None and entity_ids:
        nodes_in_hierarchy = (
            db.query(HierarchyNode)
            .filter(HierarchyNode.hierarchy_id == hierarchy_id, HierarchyNode.entity_id.in_(entity_ids))
            .all()
        )
        node_by_id = {n.id: n for n in nodes_in_hierarchy}
        for n in nodes_in_hierarchy:
            parent_entity_id = None
            if n.parent_node_id is not None:
                parent_node = node_by_id.get(n.parent_node_id)
                if parent_node is not None:
                    parent_entity_id = parent_node.entity_id
            parent_by_entity_id[n.entity_id] = parent_entity_id

    attributes_by_entity_id: dict[uuid.UUID, dict] = {}
    if entity_ids:
        attr_rows = db.query(EntityAttribute).filter(EntityAttribute.entity_id.in_(entity_ids)).all()
        attr_def_ids = {row.attribute_id for row in attr_rows}
        attribute_defs_by_id = {}
        if attr_def_ids:
            attribute_defs_by_id = {
                d.id: d for d in db.query(AttributeDefinition).filter(AttributeDefinition.id.in_(attr_def_ids)).all()
            }
        for row in attr_rows:
            definition = attribute_defs_by_id.get(row.attribute_id)
            if definition is None:
                continue
            attributes_by_entity_id.setdefault(row.entity_id, {})[definition.code] = _attribute_value(row)

    nodes = []
    for entity in entities:
        entity_type = entity_type_by_id.get(entity.entity_type_id)
        attrs: dict[str, Any] = {
            "code": entity.code,
            "status": entity.status,
            "description": entity.description,
        }
        attrs.update(attributes_by_entity_id.get(entity.id, {}))
        parent_entity_id = parent_by_entity_id.get(entity.id)
        nodes.append(
            GraphNode(
                id=str(entity.id),
                type=entity_type.code if entity_type else "",
                label=_node_label(entity),
                parent=str(parent_entity_id) if parent_entity_id else None,
                attributes=attrs,
            )
        )

    relationships = []
    if entity_ids:
        relationships = db.query(Relationship).filter(Relationship.source_entity_id.in_(entity_ids)).all()
    relationship_type_by_id = {rt.id: rt for rt in db.query(RelationshipType).all()}

    edges = []
    for rel in relationships:
        rel_type = relationship_type_by_id.get(rel.relationship_type_id)
        edges.append(
            GraphEdge(
                id=str(rel.id),
                source=str(rel.source_entity_id),
                target=str(rel.target_entity_id),
                type=rel_type.code if rel_type else "",
                label=rel_type.name if rel_type else "",
                attributes=rel.attributes or {},
            )
        )

    entity_types = [
        EntityTypeOption(id=str(et.id), code=et.code, name=et.name, is_abstract=et.is_abstract)
        for et in entity_type_by_id.values()
    ]
    relationship_types = [
        RelationshipTypeOption(
            id=str(rt.id),
            code=rt.code,
            name=rt.name,
            is_directed=rt.is_directed,
            source_entity_type=(
                entity_type_by_id[rt.source_entity_type].code
                if rt.source_entity_type in entity_type_by_id
                else None
            ),
            target_entity_type=(
                entity_type_by_id[rt.target_entity_type].code
                if rt.target_entity_type in entity_type_by_id
                else None
            ),
        )
        for rt in relationship_type_by_id.values()
    ]
    hierarchies = [
        HierarchyOption(id=str(h.id), code=h.code, name=h.name)
        for h in db.query(Hierarchy).filter(Hierarchy.organization_id == organization_id).all()
    ]
    attribute_definitions = []
    if entity_type_by_id:
        attribute_definitions = [
            AttributeDefinitionOption(
                id=str(d.id), entity_type_id=str(d.entity_type_id), code=d.code, name=d.name, data_type=d.data_type
            )
            for d in db.query(AttributeDefinition)
            .filter(AttributeDefinition.entity_type_id.in_(entity_type_by_id.keys()))
            .all()
        ]

    return GraphResponse(
        nodes=nodes,
        edges=edges,
        entity_types=entity_types,
        relationship_types=relationship_types,
        hierarchies=hierarchies,
        attribute_definitions=attribute_definitions,
    )
```

- [ ] **Step 2: Write `backend/app/api/graph.py`**

```python
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.graph.schemas import GraphResponse
from app.graph.service import get_domain_graph
from app.models.iam import UserAccount

router = APIRouter(prefix="/api/graph/domain", tags=["graph"])


@router.get("")
def read_domain_graph(
    organization_id: uuid.UUID = Query(...),
    hierarchy_id: uuid.UUID | None = Query(None),
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
) -> GraphResponse:
    return get_domain_graph(db, organization_id=organization_id, hierarchy_id=hierarchy_id)
```

- [ ] **Step 3: Write the failing test `backend/tests/test_graph_read.py`**

```python
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
```

Run: `docker compose exec -T backend pytest tests/test_graph_read.py -v`
Expected: FAIL (404s — no `/api/graph/domain` route yet)

- [ ] **Step 4: Wire the graph router into `backend/app/main.py`**

```python
from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.api.graph import router as graph_router
from app.api.health import router as health_router
from app.api.meta import router as meta_router
from app.api.routers import router as crud_router
from app.clickhouse_schema import create_analytics_schema
from app.core.db import SessionLocal, get_clickhouse_client
from app.seed import seed_admin
import logging

logger = logging.getLogger(__name__)

app = FastAPI(title="Problem Solver Platform API")

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(meta_router)
app.include_router(crud_router)
app.include_router(graph_router)


@app.on_event("startup")
def on_startup() -> None:
    try:
        create_analytics_schema(get_clickhouse_client())
    except Exception:
        logger.exception("Could not create ClickHouse analytics schema; continuing")
    db = SessionLocal()
    try:
        seed_admin(db)
    except Exception:
        db.rollback()
        logger.warning(
            "Skipped admin seeding — have you run `alembic upgrade head`? "
            "Run: docker compose run --rm --no-deps -T backend alembic upgrade head",
            exc_info=True,
        )
    finally:
        db.close()
```

(This is the current real content of `main.py` after the platform skeleton's final review fix, with only `graph_router` newly added — copy it exactly as shown, don't drop the try/except startup guard.)

- [ ] **Step 5: Run tests against the real containers to verify they pass**

Run:
```bash
docker compose build backend && docker compose up -d backend
docker compose exec -T backend pytest tests/test_graph_read.py -v
```
Expected: PASS

- [ ] **Step 6: Run the full backend suite to confirm no regressions**

Run: `docker compose exec -T backend pytest -v`
Expected: all tests pass (the platform skeleton's existing 48 plus these 2 new ones)

- [ ] **Step 7: Commit**

```bash
git add backend/app/graph/service.py backend/app/api/graph.py backend/app/main.py backend/tests/test_graph_read.py
git commit -m "feat: GraphService read path and GET /api/graph/domain"
```

---

## Task 3: Node writes — `create_node`/`update_node`/`delete_node` + node endpoints

**Files:**
- Modify: `backend/app/graph/service.py` (append)
- Modify: `backend/app/api/graph.py` (append)
- Test: `backend/tests/test_graph_nodes.py`

**Interfaces:**
- Consumes: everything from Tasks 1-2.
- Produces: `create_node(db, *, organization_id, entity_type_id, name, code=None, status=None, description=None, attributes: dict | None = None, hierarchy_id=None, parent_entity_id=None) -> GraphNode`, `update_node(db, entity_id, *, name=None, code=None, status=None, description=None, attributes: dict | None = None, hierarchy_id=None, parent_entity_id=None) -> GraphNode`, `delete_node(db, entity_id) -> None`, plus exceptions `GraphNotFoundError`, `GraphConflictError`, `GraphValidationError` (all in `app.graph.service`). `POST/PATCH/DELETE /api/graph/domain/nodes[/{entity_id}]`. Note one deliberate simplification from the spec's wording: `update_node` distinguishes "leave hierarchy placement alone" (omit `hierarchy_id`) from "move to root" (`hierarchy_id` given, `parent_entity_id=None`) using `hierarchy_id` itself as the touch/don't-touch signal — no separate sentinel is needed, since `parent_entity_id` is only ever interpreted when `hierarchy_id` is present.

- [ ] **Step 1: Write the failing test `backend/tests/test_graph_nodes.py`**

```python
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


def test_create_node_writes_attributes_and_hierarchy_placement(auth_headers, organization_id):
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]

    et_response = client.post(
        "/api/domain/entity_type/",
        json={"organization_id": organization_id, "code": f"employee-{suffix}", "name": "Employee"},
        headers=auth_headers,
    )
    entity_type_id = et_response.json()["id"]

    attr_response = client.post(
        "/api/domain/attribute_definition/",
        json={
            "entity_type_id": entity_type_id,
            "code": "rank",
            "name": "Rank",
            "data_type": "string",
            "is_required": False,
            "is_multi_value": False,
        },
        headers=auth_headers,
    )
    assert attr_response.status_code == 201

    hierarchy_response = client.post(
        "/api/domain/hierarchy/",
        json={"organization_id": organization_id, "code": f"org-chart-{suffix}", "name": "Org Chart"},
        headers=auth_headers,
    )
    hierarchy_id = hierarchy_response.json()["id"]

    node_response = client.post(
        "/api/graph/domain/nodes",
        json={
            "organization_id": organization_id,
            "entity_type_id": entity_type_id,
            "name": "Ahmed",
            "code": f"ahmed-{suffix}",
            "attributes": {"rank": "Captain"},
            "hierarchy_id": hierarchy_id,
        },
        headers=auth_headers,
    )
    assert node_response.status_code == 201
    body = node_response.json()
    assert body["label"] == "Ahmed"
    assert body["attributes"]["rank"] == "Captain"
    assert body["parent"] is None

    entity_id = body["id"]

    child_node_response = client.post(
        "/api/graph/domain/nodes",
        json={
            "organization_id": organization_id,
            "entity_type_id": entity_type_id,
            "name": "Sara",
            "hierarchy_id": hierarchy_id,
            "parent_entity_id": entity_id,
        },
        headers=auth_headers,
    )
    assert child_node_response.status_code == 201
    assert child_node_response.json()["parent"] == entity_id


def test_update_node_edits_fields(auth_headers, organization_id):
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]

    et_response = client.post(
        "/api/domain/entity_type/",
        json={"organization_id": organization_id, "code": f"employee-{suffix}", "name": "Employee"},
        headers=auth_headers,
    )
    entity_type_id = et_response.json()["id"]

    node_response = client.post(
        "/api/graph/domain/nodes",
        json={"organization_id": organization_id, "entity_type_id": entity_type_id, "name": "Ahmed"},
        headers=auth_headers,
    )
    entity_id = node_response.json()["id"]

    update_response = client.patch(
        f"/api/graph/domain/nodes/{entity_id}",
        json={"name": "Ahmed Updated", "status": "ACTIVE"},
        headers=auth_headers,
    )
    assert update_response.status_code == 200
    assert update_response.json()["label"] == "Ahmed Updated"
    assert update_response.json()["attributes"]["status"] == "ACTIVE"


def test_update_node_returns_404_for_missing_entity(auth_headers):
    client = TestClient(app)
    response = client.patch(
        f"/api/graph/domain/nodes/{uuid.uuid4()}",
        json={"name": "Nope"},
        headers=auth_headers,
    )
    assert response.status_code == 404


def test_delete_node_returns_409_when_still_referenced(auth_headers, organization_id):
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]

    et_response = client.post(
        "/api/domain/entity_type/",
        json={"organization_id": organization_id, "code": f"employee-{suffix}", "name": "Employee"},
        headers=auth_headers,
    )
    entity_type_id = et_response.json()["id"]

    rel_type_response = client.post(
        "/api/domain/relationship_type/",
        json={"code": f"reports_to-{suffix}", "name": "Reports To", "is_directed": True},
        headers=auth_headers,
    )
    relationship_type_id = rel_type_response.json()["id"]

    node_a = client.post(
        "/api/graph/domain/nodes",
        json={"organization_id": organization_id, "entity_type_id": entity_type_id, "name": "A"},
        headers=auth_headers,
    ).json()
    node_b = client.post(
        "/api/graph/domain/nodes",
        json={"organization_id": organization_id, "entity_type_id": entity_type_id, "name": "B"},
        headers=auth_headers,
    ).json()

    relationship_response = client.post(
        "/api/domain/relationship/",
        json={
            "relationship_type_id": relationship_type_id,
            "source_entity_id": node_a["id"],
            "target_entity_id": node_b["id"],
        },
        headers=auth_headers,
    )
    assert relationship_response.status_code == 201

    delete_response = client.delete(f"/api/graph/domain/nodes/{node_a['id']}", headers=auth_headers)
    assert delete_response.status_code == 409
    assert "relationship" in delete_response.json()["detail"].lower()


def test_delete_node_succeeds_when_unreferenced(auth_headers, organization_id):
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]

    et_response = client.post(
        "/api/domain/entity_type/",
        json={"organization_id": organization_id, "code": f"employee-{suffix}", "name": "Employee"},
        headers=auth_headers,
    )
    entity_type_id = et_response.json()["id"]

    node_response = client.post(
        "/api/graph/domain/nodes",
        json={"organization_id": organization_id, "entity_type_id": entity_type_id, "name": "Solo"},
        headers=auth_headers,
    )
    entity_id = node_response.json()["id"]

    delete_response = client.delete(f"/api/graph/domain/nodes/{entity_id}", headers=auth_headers)
    assert delete_response.status_code == 204
```

Run: `docker compose exec -T backend pytest tests/test_graph_nodes.py -v`
Expected: FAIL (404s — no node routes yet)

- [ ] **Step 2: Append to `backend/app/graph/service.py`**

```python
class GraphNotFoundError(Exception):
    """Raised when a write targets an entity/relationship id that doesn't
    exist. Mapped to HTTP 404 by the route layer."""


class GraphConflictError(Exception):
    """Raised when a write would violate a DB relationship (e.g. deleting
    a still-referenced entity). Mapped to HTTP 409 by the route layer."""


class GraphValidationError(Exception):
    """Raised when a write fails a domain-level validation (e.g. an
    edge's relationship_type doesn't match the two entities' types).
    Mapped to HTTP 422 by the route layer."""


def _entity_to_node(db: Session, entity: Entity, *, hierarchy_id: uuid.UUID | None) -> GraphNode:
    entity_type = db.get(EntityType, entity.entity_type_id)
    attrs: dict[str, Any] = {
        "code": entity.code,
        "status": entity.status,
        "description": entity.description,
    }
    attr_rows = db.query(EntityAttribute).filter(EntityAttribute.entity_id == entity.id).all()
    for row in attr_rows:
        definition = db.get(AttributeDefinition, row.attribute_id)
        if definition is not None:
            attrs[definition.code] = _attribute_value(row)

    parent_entity_id = None
    if hierarchy_id is not None:
        node = (
            db.query(HierarchyNode)
            .filter(HierarchyNode.hierarchy_id == hierarchy_id, HierarchyNode.entity_id == entity.id)
            .first()
        )
        if node is not None and node.parent_node_id is not None:
            parent_node = db.get(HierarchyNode, node.parent_node_id)
            if parent_node is not None:
                parent_entity_id = parent_node.entity_id

    return GraphNode(
        id=str(entity.id),
        type=entity_type.code if entity_type else "",
        label=_node_label(entity),
        parent=str(parent_entity_id) if parent_entity_id else None,
        attributes=attrs,
    )


def _write_entity_attributes(
    db: Session, *, entity_id: uuid.UUID, entity_type_id: uuid.UUID, attributes: dict[str, Any]
) -> None:
    if not attributes:
        return
    definitions = {
        d.code: d
        for d in db.query(AttributeDefinition).filter(AttributeDefinition.entity_type_id == entity_type_id).all()
    }
    for code, value in attributes.items():
        definition = definitions.get(code)
        if definition is None:
            continue  # unknown attribute code for this entity type -- silently skip
        existing = (
            db.query(EntityAttribute)
            .filter(EntityAttribute.entity_id == entity_id, EntityAttribute.attribute_id == definition.id)
            .first()
        )
        row = existing or EntityAttribute(entity_id=entity_id, attribute_id=definition.id)
        row.value_string = None
        row.value_number = None
        row.value_boolean = None
        row.value_date = None
        row.value_datetime = None
        row.value_json = None
        if definition.data_type == "string":
            row.value_string = str(value)
        elif definition.data_type == "number":
            row.value_number = value
        elif definition.data_type == "boolean":
            row.value_boolean = bool(value)
        elif definition.data_type == "date":
            row.value_date = value
        elif definition.data_type == "datetime":
            row.value_datetime = value
        else:
            row.value_json = value
        if existing is None:
            db.add(row)


def create_node(
    db: Session,
    *,
    organization_id: uuid.UUID,
    entity_type_id: uuid.UUID,
    name: str,
    code: str | None = None,
    status: str | None = None,
    description: str | None = None,
    attributes: dict[str, Any] | None = None,
    hierarchy_id: uuid.UUID | None = None,
    parent_entity_id: uuid.UUID | None = None,
) -> GraphNode:
    entity = Entity(
        organization_id=organization_id,
        entity_type_id=entity_type_id,
        name=name,
        code=code,
        status=status,
        description=description,
    )
    db.add(entity)
    db.flush()  # populate entity.id before using it below

    _write_entity_attributes(db, entity_id=entity.id, entity_type_id=entity_type_id, attributes=attributes or {})

    if hierarchy_id is not None:
        parent_node_id = None
        if parent_entity_id is not None:
            parent_node = (
                db.query(HierarchyNode)
                .filter(HierarchyNode.hierarchy_id == hierarchy_id, HierarchyNode.entity_id == parent_entity_id)
                .first()
            )
            parent_node_id = parent_node.id if parent_node else None
        db.add(HierarchyNode(hierarchy_id=hierarchy_id, entity_id=entity.id, parent_node_id=parent_node_id, level=0))

    db.commit()
    db.refresh(entity)
    return _entity_to_node(db, entity, hierarchy_id=hierarchy_id)


def update_node(
    db: Session,
    entity_id: uuid.UUID,
    *,
    name: str | None = None,
    code: str | None = None,
    status: str | None = None,
    description: str | None = None,
    attributes: dict[str, Any] | None = None,
    hierarchy_id: uuid.UUID | None = None,
    parent_entity_id: uuid.UUID | None = None,
) -> GraphNode:
    entity = db.get(Entity, entity_id)
    if entity is None:
        raise GraphNotFoundError(f"entity {entity_id} not found")

    if name is not None:
        entity.name = name
    if code is not None:
        entity.code = code
    if status is not None:
        entity.status = status
    if description is not None:
        entity.description = description

    if attributes:
        _write_entity_attributes(db, entity_id=entity.id, entity_type_id=entity.entity_type_id, attributes=attributes)

    if hierarchy_id is not None:
        # hierarchy_id being given at all is the "touch placement" signal;
        # parent_entity_id=None within that means "move to root".
        node = (
            db.query(HierarchyNode)
            .filter(HierarchyNode.hierarchy_id == hierarchy_id, HierarchyNode.entity_id == entity.id)
            .first()
        )
        parent_node_id = None
        if parent_entity_id is not None:
            parent_node = (
                db.query(HierarchyNode)
                .filter(HierarchyNode.hierarchy_id == hierarchy_id, HierarchyNode.entity_id == parent_entity_id)
                .first()
            )
            parent_node_id = parent_node.id if parent_node else None
        if node is None:
            db.add(
                HierarchyNode(
                    hierarchy_id=hierarchy_id, entity_id=entity.id, parent_node_id=parent_node_id, level=0
                )
            )
        else:
            node.parent_node_id = parent_node_id

    db.commit()
    db.refresh(entity)
    return _entity_to_node(db, entity, hierarchy_id=hierarchy_id)


def delete_node(db: Session, entity_id: uuid.UUID) -> None:
    entity = db.get(Entity, entity_id)
    if entity is None:
        raise GraphNotFoundError(f"entity {entity_id} not found")

    relationship_count = (
        db.query(Relationship)
        .filter((Relationship.source_entity_id == entity_id) | (Relationship.target_entity_id == entity_id))
        .count()
    )
    hierarchy_node_rows = db.query(HierarchyNode).filter(HierarchyNode.entity_id == entity_id).all()
    child_count = 0
    for node in hierarchy_node_rows:
        child_count += db.query(HierarchyNode).filter(HierarchyNode.parent_node_id == node.id).count()

    if relationship_count or child_count:
        parts = []
        if relationship_count:
            parts.append(f"{relationship_count} relationship(s)")
        if child_count:
            parts.append(f"{child_count} child hierarchy placement(s)")
        raise GraphConflictError(f"entity still has {' and '.join(parts)} — remove them first")

    # entity_attribute rows are the entity's own data, not a connection to
    # something else -- delete them automatically rather than blocking on them.
    db.query(EntityAttribute).filter(EntityAttribute.entity_id == entity_id).delete()
    for node in hierarchy_node_rows:
        db.delete(node)
    db.delete(entity)
    db.commit()
```

- [ ] **Step 3: Append to `backend/app/api/graph.py`**

```python
from fastapi import HTTPException
from pydantic import BaseModel

from app.graph.service import (
    GraphConflictError,
    GraphNotFoundError,
    create_node,
    delete_node,
    update_node,
)


class CreateNodeRequest(BaseModel):
    organization_id: uuid.UUID
    entity_type_id: uuid.UUID
    name: str
    code: str | None = None
    status: str | None = None
    description: str | None = None
    attributes: dict = {}
    hierarchy_id: uuid.UUID | None = None
    parent_entity_id: uuid.UUID | None = None


@router.post("/nodes", status_code=201)
def create_node_route(
    payload: CreateNodeRequest,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
):
    return create_node(
        db,
        organization_id=payload.organization_id,
        entity_type_id=payload.entity_type_id,
        name=payload.name,
        code=payload.code,
        status=payload.status,
        description=payload.description,
        attributes=payload.attributes,
        hierarchy_id=payload.hierarchy_id,
        parent_entity_id=payload.parent_entity_id,
    )


class UpdateNodeRequest(BaseModel):
    name: str | None = None
    code: str | None = None
    status: str | None = None
    description: str | None = None
    attributes: dict | None = None
    hierarchy_id: uuid.UUID | None = None
    parent_entity_id: uuid.UUID | None = None


@router.patch("/nodes/{entity_id}")
def update_node_route(
    entity_id: uuid.UUID,
    payload: UpdateNodeRequest,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
):
    try:
        return update_node(
            db,
            entity_id,
            name=payload.name,
            code=payload.code,
            status=payload.status,
            description=payload.description,
            attributes=payload.attributes,
            hierarchy_id=payload.hierarchy_id,
            parent_entity_id=payload.parent_entity_id,
        )
    except GraphNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/nodes/{entity_id}", status_code=204)
def delete_node_route(
    entity_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
) -> None:
    try:
        delete_node(db, entity_id)
    except GraphNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GraphConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
```

(Append these imports/routes below the existing `GET ""` route from Task 2 — don't duplicate the `router = APIRouter(...)` line or the existing imports, just add to them.)

- [ ] **Step 4: Run tests against the real containers to verify they pass**

Run:
```bash
docker compose build backend && docker compose up -d backend
docker compose exec -T backend pytest tests/test_graph_nodes.py -v
docker compose exec -T backend pytest -v
```
Expected: all PASS, no regressions

- [ ] **Step 5: Commit**

```bash
git add backend/app/graph/service.py backend/app/api/graph.py backend/tests/test_graph_nodes.py
git commit -m "feat: atomic node create/update/delete with 409-on-conflict"
```

---

## Task 4: Edge writes — `create_edge`/`update_edge`/`delete_edge` with type validation

**Files:**
- Modify: `backend/app/graph/service.py` (append)
- Modify: `backend/app/api/graph.py` (append)
- Test: `backend/tests/test_graph_edges.py`

**Interfaces:**
- Consumes: `GraphValidationError`, `GraphNotFoundError` (Task 3); `RelationshipType`, `Relationship` (already imported in `service.py` from Task 2).
- Produces: `create_edge(db, *, relationship_type_id, source_entity_id, target_entity_id, attributes: dict | None = None) -> GraphEdge`, `update_edge(db, relationship_id, *, attributes: dict | None = None) -> GraphEdge`, `delete_edge(db, relationship_id) -> None` in `app.graph.service`. `POST/PATCH/DELETE /api/graph/domain/edges[/{relationship_id}]`. This completes the Graph API — Task 6+ (frontend) consumes all of it.

- [ ] **Step 1: Write the failing test `backend/tests/test_graph_edges.py`**

```python
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


def test_create_edge_accepts_matching_types(auth_headers, organization_id):
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]

    employee_type = client.post(
        "/api/domain/entity_type/",
        json={"organization_id": organization_id, "code": f"employee-{suffix}", "name": "Employee"},
        headers=auth_headers,
    ).json()
    unit_type = client.post(
        "/api/domain/entity_type/",
        json={"organization_id": organization_id, "code": f"unit-{suffix}", "name": "Unit"},
        headers=auth_headers,
    ).json()

    rel_type = client.post(
        "/api/domain/relationship_type/",
        json={
            "code": f"works_for-{suffix}",
            "name": "Works For",
            "is_directed": True,
            "source_entity_type": employee_type["id"],
            "target_entity_type": unit_type["id"],
        },
        headers=auth_headers,
    ).json()

    employee = client.post(
        "/api/graph/domain/nodes",
        json={"organization_id": organization_id, "entity_type_id": employee_type["id"], "name": "Ahmed"},
        headers=auth_headers,
    ).json()
    unit = client.post(
        "/api/graph/domain/nodes",
        json={"organization_id": organization_id, "entity_type_id": unit_type["id"], "name": "Unit A"},
        headers=auth_headers,
    ).json()

    edge_response = client.post(
        "/api/graph/domain/edges",
        json={
            "relationship_type_id": rel_type["id"],
            "source_entity_id": employee["id"],
            "target_entity_id": unit["id"],
            "attributes": {"since": "2026"},
        },
        headers=auth_headers,
    )
    assert edge_response.status_code == 201
    body = edge_response.json()
    assert body["type"] == rel_type["code"]
    assert body["source"] == employee["id"]
    assert body["target"] == unit["id"]
    assert body["attributes"]["since"] == "2026"


def test_create_edge_rejects_type_mismatch(auth_headers, organization_id):
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]

    employee_type = client.post(
        "/api/domain/entity_type/",
        json={"organization_id": organization_id, "code": f"employee-{suffix}", "name": "Employee"},
        headers=auth_headers,
    ).json()
    unit_type = client.post(
        "/api/domain/entity_type/",
        json={"organization_id": organization_id, "code": f"unit-{suffix}", "name": "Unit"},
        headers=auth_headers,
    ).json()

    rel_type = client.post(
        "/api/domain/relationship_type/",
        json={
            "code": f"works_for-{suffix}",
            "name": "Works For",
            "is_directed": True,
            "source_entity_type": employee_type["id"],
            "target_entity_type": unit_type["id"],
        },
        headers=auth_headers,
    ).json()

    employee_a = client.post(
        "/api/graph/domain/nodes",
        json={"organization_id": organization_id, "entity_type_id": employee_type["id"], "name": "Ahmed"},
        headers=auth_headers,
    ).json()
    employee_b = client.post(
        "/api/graph/domain/nodes",
        json={"organization_id": organization_id, "entity_type_id": employee_type["id"], "name": "Sara"},
        headers=auth_headers,
    ).json()

    # target should be a Unit, not an Employee -- must be rejected
    edge_response = client.post(
        "/api/graph/domain/edges",
        json={
            "relationship_type_id": rel_type["id"],
            "source_entity_id": employee_a["id"],
            "target_entity_id": employee_b["id"],
            "attributes": {},
        },
        headers=auth_headers,
    )
    assert edge_response.status_code == 422


def test_create_edge_allows_unconstrained_relationship_type(auth_headers, organization_id):
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]

    any_type = client.post(
        "/api/domain/entity_type/",
        json={"organization_id": organization_id, "code": f"thing-{suffix}", "name": "Thing"},
        headers=auth_headers,
    ).json()
    rel_type = client.post(
        "/api/domain/relationship_type/",
        json={"code": f"related_to-{suffix}", "name": "Related To", "is_directed": False},
        headers=auth_headers,
    ).json()

    a = client.post(
        "/api/graph/domain/nodes",
        json={"organization_id": organization_id, "entity_type_id": any_type["id"], "name": "A"},
        headers=auth_headers,
    ).json()
    b = client.post(
        "/api/graph/domain/nodes",
        json={"organization_id": organization_id, "entity_type_id": any_type["id"], "name": "B"},
        headers=auth_headers,
    ).json()

    edge_response = client.post(
        "/api/graph/domain/edges",
        json={
            "relationship_type_id": rel_type["id"],
            "source_entity_id": a["id"],
            "target_entity_id": b["id"],
            "attributes": {},
        },
        headers=auth_headers,
    )
    assert edge_response.status_code == 201


def test_update_edge_replaces_attributes(auth_headers, organization_id):
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]

    any_type = client.post(
        "/api/domain/entity_type/",
        json={"organization_id": organization_id, "code": f"thing-{suffix}", "name": "Thing"},
        headers=auth_headers,
    ).json()
    rel_type = client.post(
        "/api/domain/relationship_type/",
        json={"code": f"related_to-{suffix}", "name": "Related To", "is_directed": False},
        headers=auth_headers,
    ).json()
    a = client.post(
        "/api/graph/domain/nodes",
        json={"organization_id": organization_id, "entity_type_id": any_type["id"], "name": "A"},
        headers=auth_headers,
    ).json()
    b = client.post(
        "/api/graph/domain/nodes",
        json={"organization_id": organization_id, "entity_type_id": any_type["id"], "name": "B"},
        headers=auth_headers,
    ).json()
    edge = client.post(
        "/api/graph/domain/edges",
        json={
            "relationship_type_id": rel_type["id"],
            "source_entity_id": a["id"],
            "target_entity_id": b["id"],
            "attributes": {"weight": 1},
        },
        headers=auth_headers,
    ).json()

    update_response = client.patch(
        f"/api/graph/domain/edges/{edge['id']}",
        json={"attributes": {"weight": 2}},
        headers=auth_headers,
    )
    assert update_response.status_code == 200
    assert update_response.json()["attributes"]["weight"] == 2


def test_delete_edge_succeeds(auth_headers, organization_id):
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]

    any_type = client.post(
        "/api/domain/entity_type/",
        json={"organization_id": organization_id, "code": f"thing-{suffix}", "name": "Thing"},
        headers=auth_headers,
    ).json()
    rel_type = client.post(
        "/api/domain/relationship_type/",
        json={"code": f"related_to-{suffix}", "name": "Related To", "is_directed": False},
        headers=auth_headers,
    ).json()
    a = client.post(
        "/api/graph/domain/nodes",
        json={"organization_id": organization_id, "entity_type_id": any_type["id"], "name": "A"},
        headers=auth_headers,
    ).json()
    b = client.post(
        "/api/graph/domain/nodes",
        json={"organization_id": organization_id, "entity_type_id": any_type["id"], "name": "B"},
        headers=auth_headers,
    ).json()
    edge = client.post(
        "/api/graph/domain/edges",
        json={
            "relationship_type_id": rel_type["id"],
            "source_entity_id": a["id"],
            "target_entity_id": b["id"],
            "attributes": {},
        },
        headers=auth_headers,
    ).json()

    delete_response = client.delete(f"/api/graph/domain/edges/{edge['id']}", headers=auth_headers)
    assert delete_response.status_code == 204
```

Run: `docker compose exec -T backend pytest tests/test_graph_edges.py -v`
Expected: FAIL (404s — no edge routes yet)

- [ ] **Step 2: Append to `backend/app/graph/service.py`**

```python
def _relationship_to_edge(db: Session, relationship: Relationship) -> GraphEdge:
    rel_type = db.get(RelationshipType, relationship.relationship_type_id)
    return GraphEdge(
        id=str(relationship.id),
        source=str(relationship.source_entity_id),
        target=str(relationship.target_entity_id),
        type=rel_type.code if rel_type else "",
        label=rel_type.name if rel_type else "",
        attributes=relationship.attributes or {},
    )


def create_edge(
    db: Session,
    *,
    relationship_type_id: uuid.UUID,
    source_entity_id: uuid.UUID,
    target_entity_id: uuid.UUID,
    attributes: dict[str, Any] | None = None,
) -> GraphEdge:
    relationship_type = db.get(RelationshipType, relationship_type_id)
    if relationship_type is None:
        raise GraphNotFoundError(f"relationship_type {relationship_type_id} not found")

    source_entity = db.get(Entity, source_entity_id)
    target_entity = db.get(Entity, target_entity_id)
    if source_entity is None or target_entity is None:
        raise GraphNotFoundError("source or target entity not found")

    if (
        relationship_type.source_entity_type is not None
        and relationship_type.source_entity_type != source_entity.entity_type_id
    ):
        raise GraphValidationError(
            "source entity's type does not match this relationship type's required source type"
        )
    if (
        relationship_type.target_entity_type is not None
        and relationship_type.target_entity_type != target_entity.entity_type_id
    ):
        raise GraphValidationError(
            "target entity's type does not match this relationship type's required target type"
        )

    relationship = Relationship(
        relationship_type_id=relationship_type_id,
        source_entity_id=source_entity_id,
        target_entity_id=target_entity_id,
        attributes=attributes or {},
    )
    db.add(relationship)
    db.commit()
    db.refresh(relationship)
    return _relationship_to_edge(db, relationship)


def update_edge(db: Session, relationship_id: uuid.UUID, *, attributes: dict[str, Any] | None = None) -> GraphEdge:
    relationship = db.get(Relationship, relationship_id)
    if relationship is None:
        raise GraphNotFoundError(f"relationship {relationship_id} not found")
    if attributes is not None:
        relationship.attributes = attributes
    db.commit()
    db.refresh(relationship)
    return _relationship_to_edge(db, relationship)


def delete_edge(db: Session, relationship_id: uuid.UUID) -> None:
    relationship = db.get(Relationship, relationship_id)
    if relationship is None:
        raise GraphNotFoundError(f"relationship {relationship_id} not found")
    db.delete(relationship)
    db.commit()
```

- [ ] **Step 3: Append to `backend/app/api/graph.py`**

```python
from app.graph.service import (
    GraphValidationError,
    create_edge,
    delete_edge,
    update_edge,
)


class CreateEdgeRequest(BaseModel):
    relationship_type_id: uuid.UUID
    source_entity_id: uuid.UUID
    target_entity_id: uuid.UUID
    attributes: dict = {}


@router.post("/edges", status_code=201)
def create_edge_route(
    payload: CreateEdgeRequest,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
):
    try:
        return create_edge(
            db,
            relationship_type_id=payload.relationship_type_id,
            source_entity_id=payload.source_entity_id,
            target_entity_id=payload.target_entity_id,
            attributes=payload.attributes,
        )
    except GraphNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GraphValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class UpdateEdgeRequest(BaseModel):
    attributes: dict | None = None


@router.patch("/edges/{relationship_id}")
def update_edge_route(
    relationship_id: uuid.UUID,
    payload: UpdateEdgeRequest,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
):
    try:
        return update_edge(db, relationship_id, attributes=payload.attributes)
    except GraphNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/edges/{relationship_id}", status_code=204)
def delete_edge_route(
    relationship_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
) -> None:
    try:
        delete_edge(db, relationship_id)
    except GraphNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
```

(Append below the node routes from Task 3, reusing the same `router`, `HTTPException`, `BaseModel`, `Depends`, `Session`, `get_db`, `get_current_user`, `UserAccount` imports already present — don't re-import them.)

- [ ] **Step 4: Run tests against the real containers to verify they pass**

Run:
```bash
docker compose build backend && docker compose up -d backend
docker compose exec -T backend pytest tests/test_graph_edges.py -v
docker compose exec -T backend pytest -v
```
Expected: all PASS, no regressions. This completes the backend Graph API.

- [ ] **Step 5: Commit**

```bash
git add backend/app/graph/service.py backend/app/api/graph.py backend/tests/test_graph_edges.py
git commit -m "feat: edge create/update/delete with type-aware validation"
```

---

## Task 5: Seed demo data (`seed_graph_demo.py`)

**Files:**
- Create: `backend/app/seed_graph_demo.py`
- Test: `backend/tests/test_seed_graph_demo.py`

**Interfaces:**
- Consumes: `app.models.domain.{EntityType,Entity,RelationshipType,Relationship,Hierarchy,HierarchyNode}`, `app.models.iam.Organization`, `app.core.db.SessionLocal` (all already exist).
- Produces: `seed_graph_demo(db: Session) -> None` in `app.seed_graph_demo`, idempotent. Run manually via `docker compose exec -T backend python -m app.seed_graph_demo` — **not** wired into `main.py`'s startup hook (spec §6). Later tasks (frontend demo page, Task 12's integration check) rely on this producing entities with `code` values ending in `-demo` and specifically `ahmed-demo`/`unit-a-demo` existing with a `works_for`-type relationship and hierarchy placement between them.

- [ ] **Step 1: Write the failing test `backend/tests/test_seed_graph_demo.py`**

```python
from app.core.db import SessionLocal
from app.models.domain import Entity, HierarchyNode, Relationship
from app.seed import seed_admin
from app.seed_graph_demo import seed_graph_demo


def test_seed_graph_demo_is_idempotent_and_wires_relationships_and_hierarchy():
    db = SessionLocal()
    try:
        seed_admin(db)
        seed_graph_demo(db)
        seed_graph_demo(db)  # run twice -- must not duplicate rows

        demo_entities = db.query(Entity).filter(Entity.code.like("%-demo")).all()
        assert len(demo_entities) == 5

        ahmed = next(e for e in demo_entities if e.code == "ahmed-demo")
        unit_a = next(e for e in demo_entities if e.code == "unit-a-demo")

        relationship = (
            db.query(Relationship)
            .filter(Relationship.source_entity_id == ahmed.id, Relationship.target_entity_id == unit_a.id)
            .first()
        )
        assert relationship is not None

        hierarchy_node = db.query(HierarchyNode).filter(HierarchyNode.entity_id == ahmed.id).first()
        assert hierarchy_node is not None
        assert hierarchy_node.parent_node_id is not None
    finally:
        db.close()
```

Run: `docker compose exec -T backend pytest tests/test_seed_graph_demo.py -v`
Expected: FAIL (`ModuleNotFoundError: app.seed_graph_demo`)

- [ ] **Step 2: Write `backend/app/seed_graph_demo.py`**

```python
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.models.domain import Entity, EntityType, Hierarchy, HierarchyNode, Relationship, RelationshipType
from app.models.iam import Organization


def _get_or_create_entity_type(db: Session, organization_id, *, code: str, name: str) -> EntityType:
    existing = (
        db.query(EntityType).filter(EntityType.organization_id == organization_id, EntityType.code == code).first()
    )
    if existing:
        return existing
    row = EntityType(organization_id=organization_id, code=code, name=name)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _get_or_create_relationship_type(
    db: Session, *, code: str, name: str, is_directed: bool, source_entity_type, target_entity_type
) -> RelationshipType:
    existing = db.query(RelationshipType).filter(RelationshipType.code == code).first()
    if existing:
        return existing
    row = RelationshipType(
        code=code,
        name=name,
        is_directed=is_directed,
        source_entity_type=source_entity_type,
        target_entity_type=target_entity_type,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _get_or_create_hierarchy(db: Session, organization_id, *, code: str, name: str) -> Hierarchy:
    existing = db.query(Hierarchy).filter(Hierarchy.organization_id == organization_id, Hierarchy.code == code).first()
    if existing:
        return existing
    row = Hierarchy(organization_id=organization_id, code=code, name=name)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _get_or_create_entity(db: Session, organization_id, entity_type_id, *, code: str, name: str) -> Entity:
    existing = (
        db.query(Entity)
        .filter(
            Entity.organization_id == organization_id,
            Entity.entity_type_id == entity_type_id,
            Entity.code == code,
        )
        .first()
    )
    if existing:
        return existing
    row = Entity(organization_id=organization_id, entity_type_id=entity_type_id, code=code, name=name)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _get_or_create_relationship(db: Session, relationship_type_id, source_entity_id, target_entity_id) -> Relationship:
    existing = (
        db.query(Relationship)
        .filter(
            Relationship.relationship_type_id == relationship_type_id,
            Relationship.source_entity_id == source_entity_id,
            Relationship.target_entity_id == target_entity_id,
        )
        .first()
    )
    if existing:
        return existing
    row = Relationship(
        relationship_type_id=relationship_type_id,
        source_entity_id=source_entity_id,
        target_entity_id=target_entity_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _get_or_create_hierarchy_node(db: Session, hierarchy_id, entity_id, *, parent_node_id, level: int) -> HierarchyNode:
    existing = (
        db.query(HierarchyNode)
        .filter(HierarchyNode.hierarchy_id == hierarchy_id, HierarchyNode.entity_id == entity_id)
        .first()
    )
    if existing:
        return existing
    row = HierarchyNode(hierarchy_id=hierarchy_id, entity_id=entity_id, parent_node_id=parent_node_id, level=level)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def seed_graph_demo(db: Session) -> None:
    """Create a small Employee/Unit demo dataset for the graph editor.
    Idempotent -- safe to run more than once. Requires the platform's
    normal admin seed (seed_admin) to have already run, for the default
    organization."""
    org = db.query(Organization).filter(Organization.code == "default").first()
    if org is None:
        raise RuntimeError("default organization not found -- run app.seed.seed_admin first")

    employee_type = _get_or_create_entity_type(db, org.id, code="employee-demo", name="Employee")
    unit_type = _get_or_create_entity_type(db, org.id, code="unit-demo", name="Unit")
    works_for = _get_or_create_relationship_type(
        db,
        code="works_for-demo",
        name="Works For",
        is_directed=True,
        source_entity_type=employee_type.id,
        target_entity_type=unit_type.id,
    )
    hierarchy = _get_or_create_hierarchy(db, org.id, code="org-chart-demo", name="Org Chart")

    unit_a = _get_or_create_entity(db, org.id, unit_type.id, code="unit-a-demo", name="Engineering")
    unit_b = _get_or_create_entity(db, org.id, unit_type.id, code="unit-b-demo", name="Operations")

    ahmed = _get_or_create_entity(db, org.id, employee_type.id, code="ahmed-demo", name="Ahmed")
    sara = _get_or_create_entity(db, org.id, employee_type.id, code="sara-demo", name="Sara")
    mostafa = _get_or_create_entity(db, org.id, employee_type.id, code="mostafa-demo", name="Mostafa")

    _get_or_create_relationship(db, works_for.id, ahmed.id, unit_a.id)
    _get_or_create_relationship(db, works_for.id, sara.id, unit_a.id)
    _get_or_create_relationship(db, works_for.id, mostafa.id, unit_b.id)

    unit_a_node = _get_or_create_hierarchy_node(db, hierarchy.id, unit_a.id, parent_node_id=None, level=0)
    unit_b_node = _get_or_create_hierarchy_node(db, hierarchy.id, unit_b.id, parent_node_id=None, level=0)
    _get_or_create_hierarchy_node(db, hierarchy.id, ahmed.id, parent_node_id=unit_a_node.id, level=1)
    _get_or_create_hierarchy_node(db, hierarchy.id, sara.id, parent_node_id=unit_a_node.id, level=1)
    _get_or_create_hierarchy_node(db, hierarchy.id, mostafa.id, parent_node_id=unit_b_node.id, level=1)


if __name__ == "__main__":
    db = SessionLocal()
    try:
        seed_graph_demo(db)
        print("Graph demo data seeded.")
    finally:
        db.close()
```

- [ ] **Step 3: Run tests against the real container to verify they pass**

Run:
```bash
docker compose build backend && docker compose up -d backend
docker compose exec -T backend pytest tests/test_seed_graph_demo.py -v
docker compose exec -T backend pytest -v
```
Expected: all PASS, no regressions

- [ ] **Step 4: Manually run the seed script and confirm it works from the CLI**

Run: `docker compose exec -T backend python -m app.seed_graph_demo`
Expected: prints `Graph demo data seeded.`; running it again prints the same with no errors (idempotent).

- [ ] **Step 5: Commit**

```bash
git add backend/app/seed_graph_demo.py backend/tests/test_seed_graph_demo.py
git commit -m "feat: idempotent seed script for graph editor demo data"
```

---

## Task 6: Frontend graph types + API hooks

**Files:**
- Create: `frontend/src/types/graph.ts`
- Create: `frontend/src/api/graph.ts`
- Test: `frontend/src/api/graph.test.ts`

**Interfaces:**
- Consumes: `apiFetch` (`frontend/src/api/client.ts`, already exists).
- Produces: TypeScript types `GraphNode`, `GraphEdge`, `EntityTypeOption`, `RelationshipTypeOption`, `HierarchyOption`, `AttributeDefinitionOption`, `GraphResponse` in `src/types/graph.ts`, mirroring the backend Pydantic schemas from Task 1 field-for-field. `graphQueryPath(organizationId, hierarchyId): string`, `useGraph(organizationId, hierarchyId)`, `useCreateNode(organizationId, hierarchyId)`, `useUpdateNode(organizationId, hierarchyId)`, `useDeleteNode(organizationId, hierarchyId)`, `useCreateEdge(organizationId, hierarchyId)`, `useUpdateEdge(organizationId, hierarchyId)`, `useDeleteEdge(organizationId, hierarchyId)` in `src/api/graph.ts` — every later frontend task (7-11) uses these, no other data-fetching path. Note: unlike the platform skeleton's `entities.ts`/`meta.ts` (which had no dedicated hook-level test file, only page-level tests), this task tests the one non-trivial piece of logic (`graphQueryPath`'s query-string construction) directly as a small pure function — the hooks themselves remain thin wrappers verified indirectly in Task 7+'s component tests, matching the established pattern.

- [ ] **Step 1: Write `frontend/src/types/graph.ts`**

```typescript
export type GraphNode = {
  id: string;
  type: string;
  label: string;
  parent: string | null;
  attributes: Record<string, unknown>;
};

export type GraphEdge = {
  id: string;
  source: string;
  target: string;
  type: string;
  label: string;
  attributes: Record<string, unknown>;
};

export type EntityTypeOption = {
  id: string;
  code: string;
  name: string;
  is_abstract: boolean;
};

export type RelationshipTypeOption = {
  id: string;
  code: string;
  name: string;
  is_directed: boolean;
  source_entity_type: string | null;
  target_entity_type: string | null;
};

export type HierarchyOption = {
  id: string;
  code: string;
  name: string;
};

export type AttributeDefinitionOption = {
  id: string;
  entity_type_id: string;
  code: string;
  name: string;
  data_type: string;
};

export type GraphResponse = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  entity_types: EntityTypeOption[];
  relationship_types: RelationshipTypeOption[];
  hierarchies: HierarchyOption[];
  attribute_definitions: AttributeDefinitionOption[];
};
```

- [ ] **Step 2: Write the failing test `frontend/src/api/graph.test.ts`**

```typescript
import { describe, expect, it } from "vitest";
import { graphQueryPath } from "./graph";

describe("graphQueryPath", () => {
  it("includes hierarchy_id when given", () => {
    expect(graphQueryPath("org-1", "hier-1")).toBe("/api/graph/domain?organization_id=org-1&hierarchy_id=hier-1");
  });

  it("omits hierarchy_id when null", () => {
    expect(graphQueryPath("org-1", null)).toBe("/api/graph/domain?organization_id=org-1");
  });
});
```

Run: `cd frontend && npm test -- graph.test.ts`
Expected: FAIL (`Cannot find module './graph'`)

- [ ] **Step 3: Write `frontend/src/api/graph.ts`**

```typescript
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./client";
import type { GraphEdge, GraphNode, GraphResponse } from "../types/graph";

export function graphQueryPath(organizationId: string, hierarchyId: string | null): string {
  const params = new URLSearchParams({ organization_id: organizationId });
  if (hierarchyId) {
    params.set("hierarchy_id", hierarchyId);
  }
  return `/api/graph/domain?${params.toString()}`;
}

function graphQueryKey(organizationId: string, hierarchyId: string | null) {
  return ["graph", "domain", organizationId, hierarchyId];
}

export function useGraph(organizationId: string, hierarchyId: string | null) {
  return useQuery({
    queryKey: graphQueryKey(organizationId, hierarchyId),
    queryFn: () => apiFetch<GraphResponse>(graphQueryPath(organizationId, hierarchyId)),
    enabled: Boolean(organizationId),
  });
}

export type CreateNodePayload = {
  organization_id: string;
  entity_type_id: string;
  name: string;
  code?: string;
  status?: string;
  description?: string;
  attributes?: Record<string, unknown>;
  hierarchy_id?: string;
  parent_entity_id?: string;
};

export function useCreateNode(organizationId: string, hierarchyId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateNodePayload) =>
      apiFetch<GraphNode>("/api/graph/domain/nodes", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: graphQueryKey(organizationId, hierarchyId) }),
  });
}

export type UpdateNodePayload = Partial<Omit<CreateNodePayload, "organization_id" | "entity_type_id">>;

export function useUpdateNode(organizationId: string, hierarchyId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ entityId, payload }: { entityId: string; payload: UpdateNodePayload }) =>
      apiFetch<GraphNode>(`/api/graph/domain/nodes/${entityId}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: graphQueryKey(organizationId, hierarchyId) }),
  });
}

export function useDeleteNode(organizationId: string, hierarchyId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (entityId: string) => apiFetch(`/api/graph/domain/nodes/${entityId}`, { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: graphQueryKey(organizationId, hierarchyId) }),
  });
}

export type CreateEdgePayload = {
  relationship_type_id: string;
  source_entity_id: string;
  target_entity_id: string;
  attributes?: Record<string, unknown>;
};

export function useCreateEdge(organizationId: string, hierarchyId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateEdgePayload) =>
      apiFetch<GraphEdge>("/api/graph/domain/edges", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: graphQueryKey(organizationId, hierarchyId) }),
  });
}

export function useUpdateEdge(organizationId: string, hierarchyId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ relationshipId, attributes }: { relationshipId: string; attributes: Record<string, unknown> }) =>
      apiFetch<GraphEdge>(`/api/graph/domain/edges/${relationshipId}`, {
        method: "PATCH",
        body: JSON.stringify({ attributes }),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: graphQueryKey(organizationId, hierarchyId) }),
  });
}

export function useDeleteEdge(organizationId: string, hierarchyId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (relationshipId: string) =>
      apiFetch(`/api/graph/domain/edges/${relationshipId}`, { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: graphQueryKey(organizationId, hierarchyId) }),
  });
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && npm test -- graph.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types/graph.ts frontend/src/api/graph.ts frontend/src/api/graph.test.ts
git commit -m "feat: graph TypeScript types and API hooks"
```

---

## Task 7: `GraphEditor` base rendering (Cytoscape + ELK, compound nesting, hierarchy dropdown)

**Files:**
- Modify: `frontend/package.json` / `package-lock.json` (new dependencies)
- Create: `frontend/src/components/GraphEditor.tsx`
- Test: `frontend/src/components/GraphEditor.test.tsx`

**Interfaces:**
- Consumes: `useGraph` (Task 6), `GraphResponse`/`GraphNode`/`GraphEdge` types (Task 6).
- Produces: `<GraphEditor organizationId={string} />` component. Task 8 modifies this same file to add write interactions (drag-connect, create-node). Task 9-10 (`PropertyPanel`, `FilterBar`) are separate components Task 11 composes alongside this one on the demo page — this task does not render them itself.
- This task is **read-only**: pan/zoom/select only, no create/edit/delete yet (that's Task 8).

- [ ] **Step 1: Add the new dependencies to `frontend/package.json`**

Add to `dependencies`: `"cytoscape": "^3.30.4"`, `"cytoscape-elk": "^2.3.0"`, `"elkjs": "^0.9.3"`. Add to `devDependencies`: `"@types/cytoscape": "^3.21.4"`.

Run: `cd frontend && npm install`
Expected: installs cleanly, `package-lock.json` updates. If any of these exact versions fail to resolve, install the latest compatible version instead and note the actual version installed in your report — the exact patch version isn't load-bearing, only that `cytoscape.use(elk)` (Step 3) works.

- [ ] **Step 2: Write the failing test `frontend/src/components/GraphEditor.test.tsx`**

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import GraphEditor from "./GraphEditor";

const mockCytoscapeInstance = {
  layout: vi.fn(() => ({ run: vi.fn() })),
  fit: vi.fn(),
  destroy: vi.fn(),
  on: vi.fn(),
};

const mockCytoscape: any = vi.fn(() => mockCytoscapeInstance);
mockCytoscape.use = vi.fn();

vi.mock("cytoscape", () => ({ default: mockCytoscape }));
vi.mock("cytoscape-elk", () => ({ default: {} }));

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

import { apiFetch } from "../api/client";

function renderWithProviders(organizationId = "org-1") {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <GraphEditor organizationId={organizationId} />
    </QueryClientProvider>
  );
}

describe("GraphEditor", () => {
  beforeEach(() => {
    mockCytoscape.mockClear();
    (apiFetch as any).mockResolvedValue({
      nodes: [
        { id: "e1", type: "employee", label: "Ahmed", parent: null, attributes: {} },
        { id: "e2", type: "employee", label: "Sara", parent: "e1", attributes: {} },
      ],
      edges: [{ id: "r1", source: "e1", target: "e2", type: "manages", label: "Manages", attributes: {} }],
      entity_types: [],
      relationship_types: [],
      hierarchies: [{ id: "h1", code: "org-chart", name: "Org Chart" }],
      attribute_definitions: [],
    });
  });

  it("initializes Cytoscape with nodes and edges mapped from the graph response", async () => {
    renderWithProviders();

    await waitFor(() => expect(mockCytoscape).toHaveBeenCalled());

    const callArgs = mockCytoscape.mock.calls[0][0];
    const nodeIds = callArgs.elements.filter((el: any) => !el.data.source).map((el: any) => el.data.id);
    const edgeIds = callArgs.elements.filter((el: any) => el.data.source).map((el: any) => el.data.id);
    expect(nodeIds).toEqual(["e1", "e2"]);
    expect(edgeIds).toEqual(["r1"]);

    const childNode = callArgs.elements.find((el: any) => el.data.id === "e2");
    expect(childNode.data.parent).toBe("e1");
  });

  it("renders a hierarchy-select option per hierarchy in the response", async () => {
    renderWithProviders();

    await waitFor(() => expect(screen.getByTestId("hierarchy-select")).toBeInTheDocument());
    expect(screen.getByText("Org Chart")).toBeInTheDocument();
  });
});
```

Run: `cd frontend && npm test -- GraphEditor.test.tsx`
Expected: FAIL (`Cannot find module './GraphEditor'`)

- [ ] **Step 3: Write `frontend/src/components/GraphEditor.tsx`**

```tsx
import { useEffect, useRef, useState } from "react";
import cytoscape, { Core } from "cytoscape";
// @ts-expect-error -- cytoscape-elk ships no bundled type declarations
import elk from "cytoscape-elk";
import { useGraph } from "../api/graph";
import type { GraphResponse } from "../types/graph";

cytoscape.use(elk);

type GraphEditorProps = {
  organizationId: string;
};

function toElements(graph: GraphResponse) {
  const nodeElements = graph.nodes.map((node) => ({
    data: {
      id: node.id,
      label: node.label,
      type: node.type,
      parent: node.parent ?? undefined,
    },
  }));
  const edgeElements = graph.edges.map((edge) => ({
    data: {
      id: edge.id,
      source: edge.source,
      target: edge.target,
      label: edge.label,
      type: edge.type,
    },
  }));
  return [...nodeElements, ...edgeElements];
}

const ELK_LAYOUT = { name: "elk", elk: { algorithm: "layered" } } as const;

export default function GraphEditor({ organizationId }: GraphEditorProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const [hierarchyId, setHierarchyId] = useState<string | null>(null);

  const { data, isLoading, error } = useGraph(organizationId, hierarchyId);

  useEffect(() => {
    if (!containerRef.current || !data) {
      return;
    }

    const cy = cytoscape({
      container: containerRef.current,
      elements: toElements(data),
      style: [
        {
          selector: "node",
          style: {
            label: "data(label)",
            "background-color": "#0f172a",
            color: "#0f172a",
            "font-size": "10px",
            width: 30,
            height: 30,
          },
        },
        {
          selector: "$node > node",
          style: {
            "background-color": "#e2e8f0",
            "background-opacity": 0.4,
            "border-width": 1,
            "border-color": "#94a3b8",
          },
        },
        {
          selector: "edge",
          style: {
            label: "data(label)",
            "font-size": "9px",
            width: 2,
            "line-color": "#94a3b8",
            "target-arrow-color": "#94a3b8",
            "target-arrow-shape": "triangle",
            "curve-style": "bezier",
          },
        },
      ],
    });

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    cy.layout(ELK_LAYOUT as any).run();
    cyRef.current = cy;

    return () => {
      cy.destroy();
      cyRef.current = null;
    };
  }, [data]);

  function runLayout() {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    cyRef.current?.layout(ELK_LAYOUT as any).run();
  }

  function fit() {
    cyRef.current?.fit();
  }

  return (
    <div>
      <div className="mb-2 flex items-center gap-2">
        <select
          className="rounded-md border border-slate-300 px-2 py-1 text-sm"
          value={hierarchyId ?? ""}
          onChange={(e) => setHierarchyId(e.target.value || null)}
          data-testid="hierarchy-select"
        >
          <option value="">No hierarchy nesting</option>
          {data?.hierarchies.map((h) => (
            <option key={h.id} value={h.id}>
              {h.name}
            </option>
          ))}
        </select>
        <button onClick={runLayout} className="rounded-md border border-slate-300 px-2 py-1 text-sm" type="button">
          Layout
        </button>
        <button onClick={fit} className="rounded-md border border-slate-300 px-2 py-1 text-sm" type="button">
          Fit
        </button>
      </div>
      {isLoading && <p className="text-sm text-slate-400">Loading graph…</p>}
      {error && <p className="text-sm text-red-600">Failed to load graph</p>}
      <div ref={containerRef} data-testid="cytoscape-container" style={{ width: "100%", height: "600px" }} />
    </div>
  );
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && npm test -- GraphEditor.test.tsx`
Expected: PASS

- [ ] **Step 5: Run the full frontend suite and typecheck**

Run: `cd frontend && npm test && npm run build`
Expected: all tests pass, `tsc -b && vite build` succeeds with no type errors

- [ ] **Step 6: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/components/GraphEditor.tsx frontend/src/components/GraphEditor.test.tsx
git commit -m "feat: GraphEditor base rendering with Cytoscape + ELK and hierarchy nesting"
```

---

## Task 8: `GraphEditor` write interactions — drag-connect edges, create-node form, selection callback

**Files:**
- Modify: `frontend/package.json` / `package-lock.json` (add `cytoscape-edgehandles`)
- Modify: `frontend/src/components/GraphEditor.tsx` (rewrite)
- Modify: `frontend/src/components/GraphEditor.test.tsx` (rewrite — the mock Cytoscape instance's shape changes)

**Interfaces:**
- Consumes: `useCreateNode`, `useCreateEdge` (Task 6); everything from Task 7.
- Produces: `<GraphEditor organizationId={string} onSelectionChange?={(selection: {kind: "node"|"edge", id: string} | null) => void} />` — the `onSelectionChange` prop is new; Task 11 (demo page) passes a callback that stores the selection and renders `PropertyPanel` (Task 9) for it. Drag-connecting two nodes (via `cytoscape-edgehandles`'s `ehcomplete` event) opens an in-component relationship-type picker filtered to types whose `source_entity_type`/`target_entity_type` (when set) match the two nodes' actual types; confirming calls `useCreateEdge`. A toolbar "+ New Node" button reveals a form (entity type, name, code, and — only when a hierarchy is selected — an optional parent) that calls `useCreateNode`.

- [ ] **Step 1: Add `cytoscape-edgehandles` to `frontend/package.json`**

Add to `dependencies`: `"cytoscape-edgehandles": "^4.0.1"`.

Run: `cd frontend && npm install`
Expected: installs cleanly (adjust the version if it doesn't resolve, same as Task 7's note).

- [ ] **Step 2: Write the failing test — full replacement of `frontend/src/components/GraphEditor.test.tsx`**

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import GraphEditor from "./GraphEditor";

let registeredHandlers: Record<string, (...args: any[]) => void> = {};

const mockCytoscapeInstance: any = {
  layout: vi.fn(() => ({ run: vi.fn() })),
  fit: vi.fn(),
  destroy: vi.fn(),
  edgehandles: vi.fn(() => ({ destroy: vi.fn() })),
  on: vi.fn((event: string, selectorOrHandler: any, maybeHandler?: any) => {
    if (typeof selectorOrHandler === "function") {
      registeredHandlers[event] = selectorOrHandler;
    } else {
      registeredHandlers[`${event}:${selectorOrHandler}`] = maybeHandler;
    }
  }),
};

const mockCytoscape: any = vi.fn(() => mockCytoscapeInstance);
mockCytoscape.use = vi.fn();

vi.mock("cytoscape", () => ({ default: mockCytoscape }));
vi.mock("cytoscape-elk", () => ({ default: {} }));
vi.mock("cytoscape-edgehandles", () => ({ default: {} }));

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

import { apiFetch } from "../api/client";

function renderWithProviders(organizationId = "org-1") {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <GraphEditor organizationId={organizationId} />
    </QueryClientProvider>
  );
}

describe("GraphEditor", () => {
  beforeEach(() => {
    mockCytoscape.mockClear();
    registeredHandlers = {};
  });

  it("initializes Cytoscape with nodes and edges mapped from the graph response", async () => {
    (apiFetch as any).mockResolvedValue({
      nodes: [
        { id: "e1", type: "employee", label: "Ahmed", parent: null, attributes: {} },
        { id: "e2", type: "employee", label: "Sara", parent: "e1", attributes: {} },
      ],
      edges: [{ id: "r1", source: "e1", target: "e2", type: "manages", label: "Manages", attributes: {} }],
      entity_types: [],
      relationship_types: [],
      hierarchies: [{ id: "h1", code: "org-chart", name: "Org Chart" }],
      attribute_definitions: [],
    });

    renderWithProviders();
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalled());

    const callArgs = mockCytoscape.mock.calls[0][0];
    const nodeIds = callArgs.elements.filter((el: any) => !el.data.source).map((el: any) => el.data.id);
    const edgeIds = callArgs.elements.filter((el: any) => el.data.source).map((el: any) => el.data.id);
    expect(nodeIds).toEqual(["e1", "e2"]);
    expect(edgeIds).toEqual(["r1"]);

    const childNode = callArgs.elements.find((el: any) => el.data.id === "e2");
    expect(childNode.data.parent).toBe("e1");
  });

  it("renders a hierarchy-select option per hierarchy in the response", async () => {
    (apiFetch as any).mockResolvedValue({
      nodes: [],
      edges: [],
      entity_types: [],
      relationship_types: [],
      hierarchies: [{ id: "h1", code: "org-chart", name: "Org Chart" }],
      attribute_definitions: [],
    });

    renderWithProviders();

    await waitFor(() => expect(screen.getByTestId("hierarchy-select")).toBeInTheDocument());
    expect(screen.getByText("Org Chart")).toBeInTheDocument();
  });

  it("opens a type-filtered relationship picker when edgehandles completes a drag-connect, and creates the edge on confirm", async () => {
    (apiFetch as any).mockImplementation((path: string, options?: RequestInit) => {
      if (path.startsWith("/api/graph/domain?")) {
        return Promise.resolve({
          nodes: [
            { id: "e1", type: "employee", label: "Ahmed", parent: null, attributes: {} },
            { id: "e2", type: "unit", label: "Unit A", parent: null, attributes: {} },
          ],
          edges: [],
          entity_types: [],
          relationship_types: [
            {
              id: "rt1",
              code: "works_for",
              name: "Works For",
              is_directed: true,
              source_entity_type: "employee",
              target_entity_type: "unit",
            },
            {
              id: "rt2",
              code: "manages",
              name: "Manages",
              is_directed: true,
              source_entity_type: "unit",
              target_entity_type: "employee",
            },
          ],
          hierarchies: [],
          attribute_definitions: [],
        });
      }
      if (path === "/api/graph/domain/edges" && options?.method === "POST") {
        return Promise.resolve({
          id: "r1",
          source: "e1",
          target: "e2",
          type: "works_for",
          label: "Works For",
          attributes: {},
        });
      }
      return Promise.resolve({});
    });

    renderWithProviders();
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalled());

    const ehcompleteHandler = registeredHandlers["ehcomplete"];
    ehcompleteHandler(null, { id: () => "e1" }, { id: () => "e2" });

    await waitFor(() => expect(screen.getByTestId("edge-type-picker")).toBeInTheDocument());
    expect(screen.getByText("Works For")).toBeInTheDocument();
    expect(screen.queryByText("Manages")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("Works For"));

    await waitFor(() =>
      expect(apiFetch).toHaveBeenCalledWith(
        "/api/graph/domain/edges",
        expect.objectContaining({ method: "POST" })
      )
    );
  });

  it("submits the create-node form and calls the nodes endpoint", async () => {
    (apiFetch as any).mockImplementation((path: string, options?: RequestInit) => {
      if (path.startsWith("/api/graph/domain?")) {
        return Promise.resolve({
          nodes: [],
          edges: [],
          entity_types: [{ id: "t1", code: "employee", name: "Employee", is_abstract: false }],
          relationship_types: [],
          hierarchies: [],
          attribute_definitions: [],
        });
      }
      if (path === "/api/graph/domain/nodes" && options?.method === "POST") {
        return Promise.resolve({ id: "e1", type: "employee", label: "New Person", parent: null, attributes: {} });
      }
      return Promise.resolve({});
    });

    renderWithProviders();
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalled());

    fireEvent.click(screen.getByTestId("toggle-create-node"));
    await waitFor(() => expect(screen.getByTestId("create-node-form")).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("Type"), { target: { value: "t1" } });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "New Person" } });
    fireEvent.submit(screen.getByTestId("create-node-form"));

    await waitFor(() =>
      expect(apiFetch).toHaveBeenCalledWith(
        "/api/graph/domain/nodes",
        expect.objectContaining({ method: "POST" })
      )
    );
  });
});
```

Run: `cd frontend && npm test -- GraphEditor.test.tsx`
Expected: FAIL (the two new tests fail — `registeredHandlers["ehcomplete"]` is undefined, `toggle-create-node` doesn't exist)

- [ ] **Step 3: Rewrite `frontend/src/components/GraphEditor.tsx`**

```tsx
import { FormEvent, useEffect, useRef, useState } from "react";
import cytoscape, { Core, NodeSingular } from "cytoscape";
// @ts-expect-error -- cytoscape-elk ships no bundled type declarations
import elk from "cytoscape-elk";
// @ts-expect-error -- cytoscape-edgehandles ships no bundled type declarations
import edgehandles from "cytoscape-edgehandles";
import { useCreateEdge, useCreateNode, useGraph } from "../api/graph";
import type { GraphResponse, RelationshipTypeOption } from "../types/graph";

cytoscape.use(elk);
cytoscape.use(edgehandles);

type Selection = { kind: "node" | "edge"; id: string } | null;

type GraphEditorProps = {
  organizationId: string;
  onSelectionChange?: (selection: Selection) => void;
};

function toElements(graph: GraphResponse) {
  const nodeElements = graph.nodes.map((node) => ({
    data: {
      id: node.id,
      label: node.label,
      type: node.type,
      parent: node.parent ?? undefined,
    },
  }));
  const edgeElements = graph.edges.map((edge) => ({
    data: {
      id: edge.id,
      source: edge.source,
      target: edge.target,
      label: edge.label,
      type: edge.type,
    },
  }));
  return [...nodeElements, ...edgeElements];
}

const ELK_LAYOUT = { name: "elk", elk: { algorithm: "layered" } } as const;

export default function GraphEditor({ organizationId, onSelectionChange }: GraphEditorProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const [hierarchyId, setHierarchyId] = useState<string | null>(null);
  const [pendingEdge, setPendingEdge] = useState<{ sourceId: string; targetId: string } | null>(null);
  const [showCreateNode, setShowCreateNode] = useState(false);

  const { data, isLoading, error } = useGraph(organizationId, hierarchyId);
  const createNode = useCreateNode(organizationId, hierarchyId);
  const createEdge = useCreateEdge(organizationId, hierarchyId);

  useEffect(() => {
    if (!containerRef.current || !data) {
      return;
    }

    const cy = cytoscape({
      container: containerRef.current,
      elements: toElements(data),
      style: [
        {
          selector: "node",
          style: {
            label: "data(label)",
            "background-color": "#0f172a",
            color: "#0f172a",
            "font-size": "10px",
            width: 30,
            height: 30,
          },
        },
        {
          selector: "$node > node",
          style: {
            "background-color": "#e2e8f0",
            "background-opacity": 0.4,
            "border-width": 1,
            "border-color": "#94a3b8",
          },
        },
        {
          selector: "edge",
          style: {
            label: "data(label)",
            "font-size": "9px",
            width: 2,
            "line-color": "#94a3b8",
            "target-arrow-color": "#94a3b8",
            "target-arrow-shape": "triangle",
            "curve-style": "bezier",
          },
        },
      ],
    });

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    cy.layout(ELK_LAYOUT as any).run();

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const eh = (cy as any).edgehandles({});

    cy.on("tap", "node", (evt: any) => {
      onSelectionChange?.({ kind: "node", id: evt.target.id() });
    });
    cy.on("tap", "edge", (evt: any) => {
      onSelectionChange?.({ kind: "edge", id: evt.target.id() });
    });
    cy.on("tap", (evt: any) => {
      if (evt.target === cy) {
        onSelectionChange?.(null);
      }
    });
    cy.on("ehcomplete", (_event: unknown, sourceNode: NodeSingular, targetNode: NodeSingular) => {
      setPendingEdge({ sourceId: sourceNode.id(), targetId: targetNode.id() });
    });

    cyRef.current = cy;

    return () => {
      eh.destroy();
      cy.destroy();
      cyRef.current = null;
    };
  }, [data]);

  function runLayout() {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    cyRef.current?.layout(ELK_LAYOUT as any).run();
  }

  function fit() {
    cyRef.current?.fit();
  }

  function nodeEntityType(entityId: string): string | undefined {
    return data?.nodes.find((n) => n.id === entityId)?.type;
  }

  function validRelationshipTypesFor(sourceId: string, targetId: string): RelationshipTypeOption[] {
    const sourceType = nodeEntityType(sourceId);
    const targetType = nodeEntityType(targetId);
    return (data?.relationship_types ?? []).filter((rt) => {
      const sourceOk = rt.source_entity_type === null || rt.source_entity_type === sourceType;
      const targetOk = rt.target_entity_type === null || rt.target_entity_type === targetType;
      return sourceOk && targetOk;
    });
  }

  function handleConfirmEdge(relationshipTypeId: string) {
    if (!pendingEdge) {
      return;
    }
    createEdge.mutate({
      relationship_type_id: relationshipTypeId,
      source_entity_id: pendingEdge.sourceId,
      target_entity_id: pendingEdge.targetId,
    });
    setPendingEdge(null);
  }

  function handleCreateNode(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const entityTypeId = String(form.get("entity_type_id") ?? "");
    const name = String(form.get("name") ?? "");
    const code = String(form.get("code") ?? "") || undefined;
    const parentEntityId = String(form.get("parent_entity_id") ?? "") || undefined;
    if (!entityTypeId || !name) {
      return;
    }
    createNode.mutate({
      organization_id: organizationId,
      entity_type_id: entityTypeId,
      name,
      code,
      hierarchy_id: hierarchyId ?? undefined,
      parent_entity_id: parentEntityId,
    });
    setShowCreateNode(false);
  }

  return (
    <div>
      <div className="mb-2 flex items-center gap-2">
        <select
          className="rounded-md border border-slate-300 px-2 py-1 text-sm"
          value={hierarchyId ?? ""}
          onChange={(e) => setHierarchyId(e.target.value || null)}
          data-testid="hierarchy-select"
        >
          <option value="">No hierarchy nesting</option>
          {data?.hierarchies.map((h) => (
            <option key={h.id} value={h.id}>
              {h.name}
            </option>
          ))}
        </select>
        <button onClick={runLayout} className="rounded-md border border-slate-300 px-2 py-1 text-sm" type="button">
          Layout
        </button>
        <button onClick={fit} className="rounded-md border border-slate-300 px-2 py-1 text-sm" type="button">
          Fit
        </button>
        <button
          type="button"
          onClick={() => setShowCreateNode((v) => !v)}
          className="rounded-md bg-slate-900 px-2 py-1 text-sm text-white"
          data-testid="toggle-create-node"
        >
          + New Node
        </button>
      </div>

      {showCreateNode && data && (
        <form
          onSubmit={handleCreateNode}
          className="mb-2 flex flex-wrap items-end gap-2 rounded-md border border-slate-200 p-2"
          data-testid="create-node-form"
        >
          <label className="text-xs">
            Type
            <select name="entity_type_id" required className="block rounded-md border border-slate-300 px-2 py-1 text-sm">
              <option value="">—</option>
              {data.entity_types.map((et) => (
                <option key={et.id} value={et.id}>
                  {et.name}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs">
            Name
            <input name="name" required className="block rounded-md border border-slate-300 px-2 py-1 text-sm" />
          </label>
          <label className="text-xs">
            Code
            <input name="code" className="block rounded-md border border-slate-300 px-2 py-1 text-sm" />
          </label>
          {hierarchyId && (
            <label className="text-xs">
              Parent
              <select name="parent_entity_id" className="block rounded-md border border-slate-300 px-2 py-1 text-sm">
                <option value="">(root)</option>
                {data.nodes.map((n) => (
                  <option key={n.id} value={n.id}>
                    {n.label}
                  </option>
                ))}
              </select>
            </label>
          )}
          <button type="submit" className="rounded-md bg-slate-900 px-2 py-1 text-sm text-white">
            Create
          </button>
        </form>
      )}

      {pendingEdge && data && (
        <div className="mb-2 rounded-md border border-slate-200 p-2" data-testid="edge-type-picker">
          <p className="mb-1 text-xs text-slate-600">Choose a relationship type:</p>
          {validRelationshipTypesFor(pendingEdge.sourceId, pendingEdge.targetId).map((rt) => (
            <button
              key={rt.id}
              type="button"
              onClick={() => handleConfirmEdge(rt.id)}
              className="mr-2 rounded-md border border-slate-300 px-2 py-1 text-sm"
            >
              {rt.name}
            </button>
          ))}
          <button type="button" onClick={() => setPendingEdge(null)} className="text-sm text-slate-500">
            Cancel
          </button>
        </div>
      )}

      {isLoading && <p className="text-sm text-slate-400">Loading graph…</p>}
      {error && <p className="text-sm text-red-600">Failed to load graph</p>}
      <div ref={containerRef} data-testid="cytoscape-container" style={{ width: "100%", height: "600px" }} />
    </div>
  );
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && npm test -- GraphEditor.test.tsx`
Expected: PASS (4/4)

- [ ] **Step 5: Run the full frontend suite and typecheck**

Run: `cd frontend && npm test && npm run build`
Expected: all pass, clean build

- [ ] **Step 6: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/components/GraphEditor.tsx frontend/src/components/GraphEditor.test.tsx
git commit -m "feat: GraphEditor write interactions (drag-connect edges, create-node form)"
```

---

## Task 9: `PropertyPanel` — view/edit fixed fields, EAV attributes, and edge JSON

**Files:**
- Create: `frontend/src/components/PropertyPanel.tsx`
- Test: `frontend/src/components/PropertyPanel.test.tsx`

**Interfaces:**
- Consumes: `useUpdateNode`, `useDeleteNode`, `useUpdateEdge`, `useDeleteEdge` (Task 6); `GraphResponse` shape (Task 6); the `Selection` shape `{kind: "node"|"edge", id: string} | null` established by Task 8's `onSelectionChange`.
- Produces: `<PropertyPanel organizationId hierarchyId graph={GraphResponse} selection={Selection} onClose={() => void} />`. Task 11 (demo page) owns the `selection` state (set via `GraphEditor`'s `onSelectionChange`) and passes it here alongside the same `graph` data `GraphEditor` is already displaying (both come from the same `useGraph` call, lifted to the parent in Task 11).

- [ ] **Step 1: Write the failing test `frontend/src/components/PropertyPanel.test.tsx`**

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import PropertyPanel from "./PropertyPanel";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

import { apiFetch } from "../api/client";

const graph = {
  nodes: [
    {
      id: "e1",
      type: "employee",
      label: "Ahmed",
      parent: null,
      attributes: { code: "ahmed-1", status: "ACTIVE", description: null, rank: "Captain" },
    },
  ],
  edges: [{ id: "r1", source: "e1", target: "e1", type: "self", label: "Self", attributes: { weight: 1 } }],
  entity_types: [{ id: "t1", code: "employee", name: "Employee", is_abstract: false }],
  relationship_types: [],
  hierarchies: [],
  attribute_definitions: [{ id: "a1", entity_type_id: "t1", code: "rank", name: "Rank", data_type: "string" }],
};

function renderWithProviders(props: Record<string, unknown> = {}) {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <PropertyPanel
        organizationId="org-1"
        hierarchyId={null}
        graph={graph as any}
        selection={{ kind: "node", id: "e1" }}
        onClose={vi.fn()}
        {...props}
      />
    </QueryClientProvider>
  );
}

describe("PropertyPanel", () => {
  beforeEach(() => {
    (apiFetch as any).mockResolvedValue({});
  });

  it("shows a prompt when nothing is selected", () => {
    renderWithProviders({ selection: null });
    expect(screen.getByText(/select a node or edge/i)).toBeInTheDocument();
  });

  it("renders fixed fields and matching attribute_definitions for a selected node", () => {
    renderWithProviders();
    expect(screen.getByDisplayValue("Ahmed")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Captain")).toBeInTheDocument();
  });

  it("submits node edits via PATCH", async () => {
    renderWithProviders();
    fireEvent.change(screen.getByDisplayValue("Ahmed"), { target: { value: "Ahmed Updated" } });
    fireEvent.submit(screen.getByTestId("node-property-form"));

    await waitFor(() =>
      expect(apiFetch).toHaveBeenCalledWith(
        "/api/graph/domain/nodes/e1",
        expect.objectContaining({ method: "PATCH" })
      )
    );
  });

  it("renders the edge attributes as JSON and submits edits via PATCH", async () => {
    renderWithProviders({ selection: { kind: "edge", id: "r1" } });
    expect(screen.getByTestId("edge-property-form")).toBeInTheDocument();

    fireEvent.submit(screen.getByTestId("edge-property-form"));

    await waitFor(() =>
      expect(apiFetch).toHaveBeenCalledWith(
        "/api/graph/domain/edges/r1",
        expect.objectContaining({ method: "PATCH" })
      )
    );
  });

  it("calls DELETE when the node Delete button is clicked", async () => {
    renderWithProviders();
    fireEvent.click(screen.getByText("Delete"));

    await waitFor(() =>
      expect(apiFetch).toHaveBeenCalledWith(
        "/api/graph/domain/nodes/e1",
        expect.objectContaining({ method: "DELETE" })
      )
    );
  });
});
```

Run: `cd frontend && npm test -- PropertyPanel.test.tsx`
Expected: FAIL (`Cannot find module './PropertyPanel'`)

- [ ] **Step 2: Write `frontend/src/components/PropertyPanel.tsx`**

```tsx
import { FormEvent, useState } from "react";
import { useDeleteEdge, useDeleteNode, useUpdateEdge, useUpdateNode } from "../api/graph";
import type { GraphResponse } from "../types/graph";

type Selection = { kind: "node" | "edge"; id: string } | null;

type PropertyPanelProps = {
  organizationId: string;
  hierarchyId: string | null;
  graph: GraphResponse;
  selection: Selection;
  onClose: () => void;
};

export default function PropertyPanel({ organizationId, hierarchyId, graph, selection, onClose }: PropertyPanelProps) {
  const updateNode = useUpdateNode(organizationId, hierarchyId);
  const deleteNode = useDeleteNode(organizationId, hierarchyId);
  const updateEdge = useUpdateEdge(organizationId, hierarchyId);
  const deleteEdge = useDeleteEdge(organizationId, hierarchyId);
  const [error, setError] = useState<string | null>(null);

  if (!selection) {
    return <p className="text-sm text-slate-400">Select a node or edge to see its properties.</p>;
  }

  if (selection.kind === "node") {
    const node = graph.nodes.find((n) => n.id === selection.id);
    if (!node) {
      return null;
    }
    const entityType = graph.entity_types.find((et) => et.code === node.type);
    const definitions = graph.attribute_definitions.filter((d) => d.entity_type_id === entityType?.id);

    function handleSubmit(event: FormEvent<HTMLFormElement>) {
      event.preventDefault();
      setError(null);
      const form = new FormData(event.currentTarget);
      const name = String(form.get("name") ?? "");
      const status = String(form.get("status") ?? "") || undefined;
      const description = String(form.get("description") ?? "") || undefined;
      const attributes: Record<string, unknown> = {};
      for (const def of definitions) {
        const raw = form.get(`attr:${def.code}`);
        if (raw !== null && raw !== "") {
          attributes[def.code] = def.data_type === "boolean" ? raw === "true" : raw;
        }
      }
      updateNode.mutate(
        { entityId: node.id, payload: { name, status, description, attributes } },
        { onError: (err) => setError(err instanceof Error ? err.message : "Failed to save") }
      );
    }

    function handleDelete() {
      setError(null);
      deleteNode.mutate(node.id, {
        onError: (err) => setError(err instanceof Error ? err.message : "Failed to delete"),
      });
    }

    return (
      <div>
        <h3 className="mb-2 text-sm font-semibold text-slate-900">
          {node.type}: {node.label}
        </h3>
        {error && <p className="mb-2 text-sm text-red-600">{error}</p>}
        <form onSubmit={handleSubmit} className="space-y-2" data-testid="node-property-form">
          <label className="block text-xs">
            Name
            <input
              name="name"
              defaultValue={node.label}
              className="block w-full rounded-md border border-slate-300 px-2 py-1 text-sm"
            />
          </label>
          <label className="block text-xs">
            Status
            <input
              name="status"
              defaultValue={String(node.attributes.status ?? "")}
              className="block w-full rounded-md border border-slate-300 px-2 py-1 text-sm"
            />
          </label>
          <label className="block text-xs">
            Description
            <input
              name="description"
              defaultValue={String(node.attributes.description ?? "")}
              className="block w-full rounded-md border border-slate-300 px-2 py-1 text-sm"
            />
          </label>
          {definitions.map((def) => (
            <label key={def.id} className="block text-xs">
              {def.name}
              <input
                name={`attr:${def.code}`}
                defaultValue={String(node.attributes[def.code] ?? "")}
                className="block w-full rounded-md border border-slate-300 px-2 py-1 text-sm"
              />
            </label>
          ))}
          <div className="flex gap-2">
            <button type="submit" className="rounded-md bg-slate-900 px-3 py-1 text-sm text-white">
              Save
            </button>
            <button
              type="button"
              onClick={handleDelete}
              className="rounded-md border border-red-300 px-3 py-1 text-sm text-red-600"
            >
              Delete
            </button>
            <button type="button" onClick={onClose} className="text-sm text-slate-500">
              Close
            </button>
          </div>
        </form>
      </div>
    );
  }

  const edge = graph.edges.find((e) => e.id === selection.id);
  if (!edge) {
    return null;
  }

  function handleEdgeSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const form = new FormData(event.currentTarget);
    const raw = String(form.get("attributes") ?? "{}");
    let attributes: Record<string, unknown> = {};
    try {
      attributes = JSON.parse(raw);
    } catch {
      setError("Attributes must be valid JSON");
      return;
    }
    updateEdge.mutate(
      { relationshipId: edge.id, attributes },
      { onError: (err) => setError(err instanceof Error ? err.message : "Failed to save") }
    );
  }

  function handleEdgeDelete() {
    setError(null);
    deleteEdge.mutate(edge.id, {
      onError: (err) => setError(err instanceof Error ? err.message : "Failed to delete"),
    });
  }

  return (
    <div>
      <h3 className="mb-2 text-sm font-semibold text-slate-900">{edge.type}</h3>
      {error && <p className="mb-2 text-sm text-red-600">{error}</p>}
      <form onSubmit={handleEdgeSubmit} className="space-y-2" data-testid="edge-property-form">
        <label className="block text-xs">
          Attributes (JSON)
          <textarea
            name="attributes"
            defaultValue={JSON.stringify(edge.attributes ?? {}, null, 2)}
            rows={4}
            className="block w-full rounded-md border border-slate-300 px-2 py-1 font-mono text-xs"
          />
        </label>
        <div className="flex gap-2">
          <button type="submit" className="rounded-md bg-slate-900 px-3 py-1 text-sm text-white">
            Save
          </button>
          <button
            type="button"
            onClick={handleEdgeDelete}
            className="rounded-md border border-red-300 px-3 py-1 text-sm text-red-600"
          >
            Delete
          </button>
          <button type="button" onClick={onClose} className="text-sm text-slate-500">
            Close
          </button>
        </div>
      </form>
    </div>
  );
}
```

- [ ] **Step 3: Run the test to verify it passes**

Run: `cd frontend && npm test -- PropertyPanel.test.tsx`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/PropertyPanel.tsx frontend/src/components/PropertyPanel.test.tsx
git commit -m "feat: PropertyPanel for viewing/editing node and edge properties"
```

---

## Task 10: `FilterBar` — entity-type filter, search, one-hop highlight

**Files:**
- Create: `frontend/src/components/FilterBar.tsx`
- Test: `frontend/src/components/FilterBar.test.tsx`

**Interfaces:**
- Consumes: `EntityTypeOption`, `GraphEdge` types (Task 6).
- Produces: `<FilterBar entityTypes={EntityTypeOption[]} edges={GraphEdge[]} selectedNodeId={string | null} onChange={(criteria: FilterCriteria) => void} />` and the exported type `FilterCriteria = { selectedTypes: string[] | null; search: string; highlightIds: string[] | null }` in `src/components/FilterBar.tsx`. `selectedTypes: null` means "show all types" (the default — no filtering applied). This component is entirely self-contained (owns its own checkbox/search/highlight-toggle state) and does not call any API itself; Task 11 wires its `onChange` output into `GraphEditor`'s new `filter` prop.

- [ ] **Step 1: Write the failing test `frontend/src/components/FilterBar.test.tsx`**

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import FilterBar from "./FilterBar";

const entityTypes = [
  { id: "t1", code: "employee", name: "Employee", is_abstract: false },
  { id: "t2", code: "unit", name: "Unit", is_abstract: false },
];

const edges = [{ id: "r1", source: "e1", target: "e2", type: "works_for", label: "Works For", attributes: {} }];

describe("FilterBar", () => {
  it("emits selectedTypes=null when all types are checked (default)", () => {
    const onChange = vi.fn();
    render(<FilterBar entityTypes={entityTypes} edges={edges} selectedNodeId={null} onChange={onChange} />);

    fireEvent.change(screen.getByTestId("filter-search"), { target: { value: "ahmed" } });

    expect(onChange).toHaveBeenCalledWith({ selectedTypes: null, search: "ahmed", highlightIds: null });
  });

  it("emits the remaining selected type codes when one is unchecked", () => {
    const onChange = vi.fn();
    render(<FilterBar entityTypes={entityTypes} edges={edges} selectedNodeId={null} onChange={onChange} />);

    fireEvent.click(screen.getByTestId("filter-type-unit"));

    expect(onChange).toHaveBeenCalledWith({ selectedTypes: ["employee"], search: "", highlightIds: null });
  });

  it("computes one-hop neighbor ids when highlighting is toggled on with a selected node", () => {
    const onChange = vi.fn();
    render(<FilterBar entityTypes={entityTypes} edges={edges} selectedNodeId="e1" onChange={onChange} />);

    fireEvent.click(screen.getByTestId("filter-highlight-toggle"));

    expect(onChange).toHaveBeenCalledWith({
      selectedTypes: null,
      search: "",
      highlightIds: expect.arrayContaining(["e1", "e2"]),
    });
  });

  it("disables the highlight toggle when nothing is selected", () => {
    render(<FilterBar entityTypes={entityTypes} edges={edges} selectedNodeId={null} onChange={vi.fn()} />);
    expect(screen.getByTestId("filter-highlight-toggle")).toBeDisabled();
  });
});
```

Run: `cd frontend && npm test -- FilterBar.test.tsx`
Expected: FAIL (`Cannot find module './FilterBar'`)

- [ ] **Step 2: Write `frontend/src/components/FilterBar.tsx`**

```tsx
import { useState } from "react";
import type { EntityTypeOption, GraphEdge } from "../types/graph";

export type FilterCriteria = {
  selectedTypes: string[] | null;
  search: string;
  highlightIds: string[] | null;
};

type FilterBarProps = {
  entityTypes: EntityTypeOption[];
  edges: GraphEdge[];
  selectedNodeId: string | null;
  onChange: (criteria: FilterCriteria) => void;
};

export default function FilterBar({ entityTypes, edges, selectedNodeId, onChange }: FilterBarProps) {
  const [selected, setSelected] = useState<Set<string>>(new Set(entityTypes.map((et) => et.code)));
  const [search, setSearch] = useState("");
  const [highlighting, setHighlighting] = useState(false);

  function emit(types: Set<string>, searchValue: string, highlightingOn: boolean) {
    const allSelected = types.size === entityTypes.length;
    let highlightIds: string[] | null = null;
    if (highlightingOn && selectedNodeId) {
      const neighbors = new Set<string>([selectedNodeId]);
      for (const edge of edges) {
        if (edge.source === selectedNodeId) neighbors.add(edge.target);
        if (edge.target === selectedNodeId) neighbors.add(edge.source);
      }
      highlightIds = Array.from(neighbors);
    }
    onChange({ selectedTypes: allSelected ? null : Array.from(types), search: searchValue, highlightIds });
  }

  function toggleType(code: string) {
    const next = new Set(selected);
    if (next.has(code)) {
      next.delete(code);
    } else {
      next.add(code);
    }
    setSelected(next);
    emit(next, search, highlighting);
  }

  function handleSearchChange(value: string) {
    setSearch(value);
    emit(selected, value, highlighting);
  }

  function toggleHighlight() {
    const next = !highlighting;
    setHighlighting(next);
    emit(selected, search, next);
  }

  return (
    <div className="mb-2 flex flex-wrap items-center gap-3 rounded-md border border-slate-200 p-2 text-sm">
      <input
        type="text"
        placeholder="Search by label or code…"
        value={search}
        onChange={(e) => handleSearchChange(e.target.value)}
        className="rounded-md border border-slate-300 px-2 py-1 text-sm"
        data-testid="filter-search"
      />
      {entityTypes.map((et) => (
        <label key={et.id} className="flex items-center gap-1 text-xs">
          <input
            type="checkbox"
            checked={selected.has(et.code)}
            onChange={() => toggleType(et.code)}
            data-testid={`filter-type-${et.code}`}
          />
          {et.name}
        </label>
      ))}
      <button
        type="button"
        disabled={!selectedNodeId}
        onClick={toggleHighlight}
        className="rounded-md border border-slate-300 px-2 py-1 text-xs disabled:opacity-40"
        data-testid="filter-highlight-toggle"
      >
        {highlighting ? "Highlighting: On" : "Highlight connections"}
      </button>
    </div>
  );
}
```

- [ ] **Step 3: Run the test to verify it passes**

Run: `cd frontend && npm test -- FilterBar.test.tsx`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/FilterBar.tsx frontend/src/components/FilterBar.test.tsx
git commit -m "feat: FilterBar with entity-type filter, search, and one-hop highlight"
```

---

## Task 11: `GraphDemo` page — compose `GraphEditor` + `PropertyPanel` + `FilterBar`, wire the `/graph` route

**Files:**
- Modify: `frontend/src/components/GraphEditor.tsx` (rewrite — lift `hierarchyId` to a controlled prop, add `filter` prop application)
- Modify: `frontend/src/components/GraphEditor.test.tsx` (update `renderWithProviders` for the two new required props)
- Create: `frontend/src/pages/GraphDemo.tsx`
- Test: `frontend/src/pages/GraphDemo.test.tsx`
- Modify: `frontend/src/components/AppShell.tsx` (add a manual "Domain Graph" sidebar link)
- Modify: `frontend/src/App.tsx` (add the `/graph` route)

**Interfaces:**
- Consumes: `GraphEditor` (Tasks 7-8, modified here), `PropertyPanel` (Task 9), `FilterBar`/`FilterCriteria` (Task 10), `useGraph` (Task 6), `apiFetch` (already exists).
- Produces: the `/graph` route rendering the full demo page. This is the last task before Task 12's integration verification.
- **Design change from Tasks 7-8**: `GraphEditor`'s `hierarchyId` was previously internal `useState`. It's now a controlled prop pair (`hierarchyId: string | null`, `onHierarchyChange: (id: string | null) => void`), the same pattern already established for `onSelectionChange`. This is necessary because `GraphDemo` needs to know the current `hierarchyId` to pass a matching `useGraph` call to `PropertyPanel`/`FilterBar` (React Query dedupes identical `queryKey`s across components, so this doesn't cause extra network requests — it just needs the key to match).

- [ ] **Step 1: Rewrite `frontend/src/components/GraphEditor.tsx`**

```tsx
import { FormEvent, useEffect, useRef, useState } from "react";
import cytoscape, { Core, NodeSingular } from "cytoscape";
// @ts-expect-error -- cytoscape-elk ships no bundled type declarations
import elk from "cytoscape-elk";
// @ts-expect-error -- cytoscape-edgehandles ships no bundled type declarations
import edgehandles from "cytoscape-edgehandles";
import { useCreateEdge, useCreateNode, useGraph } from "../api/graph";
import type { GraphResponse, RelationshipTypeOption } from "../types/graph";
import type { FilterCriteria } from "./FilterBar";

cytoscape.use(elk);
cytoscape.use(edgehandles);

type Selection = { kind: "node" | "edge"; id: string } | null;

type GraphEditorProps = {
  organizationId: string;
  hierarchyId: string | null;
  onHierarchyChange: (id: string | null) => void;
  filter?: FilterCriteria;
  onSelectionChange?: (selection: Selection) => void;
};

function toElements(graph: GraphResponse) {
  const nodeElements = graph.nodes.map((node) => ({
    data: {
      id: node.id,
      label: node.label,
      type: node.type,
      parent: node.parent ?? undefined,
    },
  }));
  const edgeElements = graph.edges.map((edge) => ({
    data: {
      id: edge.id,
      source: edge.source,
      target: edge.target,
      label: edge.label,
      type: edge.type,
    },
  }));
  return [...nodeElements, ...edgeElements];
}

const ELK_LAYOUT = { name: "elk", elk: { algorithm: "layered" } } as const;

export default function GraphEditor({
  organizationId,
  hierarchyId,
  onHierarchyChange,
  filter,
  onSelectionChange,
}: GraphEditorProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const [pendingEdge, setPendingEdge] = useState<{ sourceId: string; targetId: string } | null>(null);
  const [showCreateNode, setShowCreateNode] = useState(false);

  const { data, isLoading, error } = useGraph(organizationId, hierarchyId);
  const createNode = useCreateNode(organizationId, hierarchyId);
  const createEdge = useCreateEdge(organizationId, hierarchyId);

  useEffect(() => {
    if (!containerRef.current || !data) {
      return;
    }

    const cy = cytoscape({
      container: containerRef.current,
      elements: toElements(data),
      style: [
        {
          selector: "node",
          style: {
            label: "data(label)",
            "background-color": "#0f172a",
            color: "#0f172a",
            "font-size": "10px",
            width: 30,
            height: 30,
          },
        },
        {
          selector: "$node > node",
          style: {
            "background-color": "#e2e8f0",
            "background-opacity": 0.4,
            "border-width": 1,
            "border-color": "#94a3b8",
          },
        },
        {
          selector: "edge",
          style: {
            label: "data(label)",
            "font-size": "9px",
            width: 2,
            "line-color": "#94a3b8",
            "target-arrow-color": "#94a3b8",
            "target-arrow-shape": "triangle",
            "curve-style": "bezier",
          },
        },
        { selector: ".graph-highlighted", style: { "border-width": 3, "border-color": "#2563eb" } },
        { selector: ".graph-dimmed", style: { opacity: 0.25 } },
      ],
    });

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    cy.layout(ELK_LAYOUT as any).run();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const eh = (cy as any).edgehandles({});

    cy.on("tap", "node", (evt: any) => {
      onSelectionChange?.({ kind: "node", id: evt.target.id() });
    });
    cy.on("tap", "edge", (evt: any) => {
      onSelectionChange?.({ kind: "edge", id: evt.target.id() });
    });
    cy.on("tap", (evt: any) => {
      if (evt.target === cy) {
        onSelectionChange?.(null);
      }
    });
    cy.on("ehcomplete", (_event: unknown, sourceNode: NodeSingular, targetNode: NodeSingular) => {
      setPendingEdge({ sourceId: sourceNode.id(), targetId: targetNode.id() });
    });

    cyRef.current = cy;

    return () => {
      eh.destroy();
      cy.destroy();
      cyRef.current = null;
    };
  }, [data]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || !data) {
      return;
    }
    const searchLower = (filter?.search ?? "").toLowerCase();
    const selectedTypes = filter?.selectedTypes ?? null;
    const highlightIds = filter?.highlightIds ?? null;

    cy.nodes().forEach((node) => {
      const graphNode = data.nodes.find((n) => n.id === node.id());
      if (!graphNode) {
        return;
      }
      const typeOk = selectedTypes === null || selectedTypes.includes(graphNode.type);
      const searchOk = !searchLower || graphNode.label.toLowerCase().includes(searchLower);
      node.style("display", typeOk && searchOk ? "element" : "none");
    });

    cy.edges().forEach((edge) => {
      const source = cy.getElementById(edge.data("source"));
      const target = cy.getElementById(edge.data("target"));
      const visible = source.style("display") !== "none" && target.style("display") !== "none";
      edge.style("display", visible ? "element" : "none");
    });

    cy.elements().removeClass("graph-highlighted graph-dimmed");
    if (highlightIds) {
      const highlightSet = new Set(highlightIds);
      cy.nodes().forEach((node) => {
        node.addClass(highlightSet.has(node.id()) ? "graph-highlighted" : "graph-dimmed");
      });
    }
  }, [filter, data]);

  function runLayout() {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    cyRef.current?.layout(ELK_LAYOUT as any).run();
  }

  function fit() {
    cyRef.current?.fit();
  }

  function nodeEntityType(entityId: string): string | undefined {
    return data?.nodes.find((n) => n.id === entityId)?.type;
  }

  function validRelationshipTypesFor(sourceId: string, targetId: string): RelationshipTypeOption[] {
    const sourceType = nodeEntityType(sourceId);
    const targetType = nodeEntityType(targetId);
    return (data?.relationship_types ?? []).filter((rt) => {
      const sourceOk = rt.source_entity_type === null || rt.source_entity_type === sourceType;
      const targetOk = rt.target_entity_type === null || rt.target_entity_type === targetType;
      return sourceOk && targetOk;
    });
  }

  function handleConfirmEdge(relationshipTypeId: string) {
    if (!pendingEdge) {
      return;
    }
    createEdge.mutate({
      relationship_type_id: relationshipTypeId,
      source_entity_id: pendingEdge.sourceId,
      target_entity_id: pendingEdge.targetId,
    });
    setPendingEdge(null);
  }

  function handleCreateNode(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const entityTypeId = String(form.get("entity_type_id") ?? "");
    const name = String(form.get("name") ?? "");
    const code = String(form.get("code") ?? "") || undefined;
    const parentEntityId = String(form.get("parent_entity_id") ?? "") || undefined;
    if (!entityTypeId || !name) {
      return;
    }
    createNode.mutate({
      organization_id: organizationId,
      entity_type_id: entityTypeId,
      name,
      code,
      hierarchy_id: hierarchyId ?? undefined,
      parent_entity_id: parentEntityId,
    });
    setShowCreateNode(false);
  }

  return (
    <div>
      <div className="mb-2 flex items-center gap-2">
        <select
          className="rounded-md border border-slate-300 px-2 py-1 text-sm"
          value={hierarchyId ?? ""}
          onChange={(e) => onHierarchyChange(e.target.value || null)}
          data-testid="hierarchy-select"
        >
          <option value="">No hierarchy nesting</option>
          {data?.hierarchies.map((h) => (
            <option key={h.id} value={h.id}>
              {h.name}
            </option>
          ))}
        </select>
        <button onClick={runLayout} className="rounded-md border border-slate-300 px-2 py-1 text-sm" type="button">
          Layout
        </button>
        <button onClick={fit} className="rounded-md border border-slate-300 px-2 py-1 text-sm" type="button">
          Fit
        </button>
        <button
          type="button"
          onClick={() => setShowCreateNode((v) => !v)}
          className="rounded-md bg-slate-900 px-2 py-1 text-sm text-white"
          data-testid="toggle-create-node"
        >
          + New Node
        </button>
      </div>

      {showCreateNode && data && (
        <form
          onSubmit={handleCreateNode}
          className="mb-2 flex flex-wrap items-end gap-2 rounded-md border border-slate-200 p-2"
          data-testid="create-node-form"
        >
          <label className="text-xs">
            Type
            <select name="entity_type_id" required className="block rounded-md border border-slate-300 px-2 py-1 text-sm">
              <option value="">—</option>
              {data.entity_types.map((et) => (
                <option key={et.id} value={et.id}>
                  {et.name}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs">
            Name
            <input name="name" required className="block rounded-md border border-slate-300 px-2 py-1 text-sm" />
          </label>
          <label className="text-xs">
            Code
            <input name="code" className="block rounded-md border border-slate-300 px-2 py-1 text-sm" />
          </label>
          {hierarchyId && (
            <label className="text-xs">
              Parent
              <select name="parent_entity_id" className="block rounded-md border border-slate-300 px-2 py-1 text-sm">
                <option value="">(root)</option>
                {data.nodes.map((n) => (
                  <option key={n.id} value={n.id}>
                    {n.label}
                  </option>
                ))}
              </select>
            </label>
          )}
          <button type="submit" className="rounded-md bg-slate-900 px-2 py-1 text-sm text-white">
            Create
          </button>
        </form>
      )}

      {pendingEdge && data && (
        <div className="mb-2 rounded-md border border-slate-200 p-2" data-testid="edge-type-picker">
          <p className="mb-1 text-xs text-slate-600">Choose a relationship type:</p>
          {validRelationshipTypesFor(pendingEdge.sourceId, pendingEdge.targetId).map((rt) => (
            <button
              key={rt.id}
              type="button"
              onClick={() => handleConfirmEdge(rt.id)}
              className="mr-2 rounded-md border border-slate-300 px-2 py-1 text-sm"
            >
              {rt.name}
            </button>
          ))}
          <button type="button" onClick={() => setPendingEdge(null)} className="text-sm text-slate-500">
            Cancel
          </button>
        </div>
      )}

      {isLoading && <p className="text-sm text-slate-400">Loading graph…</p>}
      {error && <p className="text-sm text-red-600">Failed to load graph</p>}
      <div ref={containerRef} data-testid="cytoscape-container" style={{ width: "100%", height: "600px" }} />
    </div>
  );
}
```

- [ ] **Step 2: Update `frontend/src/components/GraphEditor.test.tsx`'s `renderWithProviders` helper**

Replace the `renderWithProviders` function with one that supplies the two new required props (keep all four existing `it(...)` test bodies exactly as they are — only this helper changes):

```tsx
function renderWithProviders(props: Partial<React.ComponentProps<typeof GraphEditor>> = {}) {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <GraphEditor organizationId="org-1" hierarchyId={null} onHierarchyChange={vi.fn()} {...props} />
    </QueryClientProvider>
  );
}
```

- [ ] **Step 3: Run the GraphEditor test to verify it still passes**

Run: `cd frontend && npm test -- GraphEditor.test.tsx`
Expected: PASS (4/4, unchanged behavior, just the new controlled props supplied)

- [ ] **Step 4: Write the failing test `frontend/src/pages/GraphDemo.test.tsx`**

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import GraphDemo from "./GraphDemo";

const mockCytoscapeInstance: any = {
  layout: vi.fn(() => ({ run: vi.fn() })),
  fit: vi.fn(),
  destroy: vi.fn(),
  edgehandles: vi.fn(() => ({ destroy: vi.fn() })),
  on: vi.fn(),
  nodes: vi.fn(() => ({ forEach: vi.fn() })),
  edges: vi.fn(() => ({ forEach: vi.fn() })),
  elements: vi.fn(() => ({ removeClass: vi.fn() })),
  getElementById: vi.fn(() => ({ style: vi.fn(() => "element") })),
};

const mockCytoscape: any = vi.fn(() => mockCytoscapeInstance);
mockCytoscape.use = vi.fn();

vi.mock("cytoscape", () => ({ default: mockCytoscape }));
vi.mock("cytoscape-elk", () => ({ default: {} }));
vi.mock("cytoscape-edgehandles", () => ({ default: {} }));

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

import { apiFetch } from "../api/client";

function renderWithProviders() {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <GraphDemo />
    </QueryClientProvider>
  );
}

describe("GraphDemo", () => {
  beforeEach(() => {
    (apiFetch as any).mockImplementation((path: string) => {
      if (path.startsWith("/api/iam/organization/")) {
        return Promise.resolve({ items: [{ id: "org-1", code: "default" }], total: 1 });
      }
      if (path.startsWith("/api/graph/domain?")) {
        return Promise.resolve({
          nodes: [{ id: "e1", type: "employee", label: "Ahmed", parent: null, attributes: {} }],
          edges: [],
          entity_types: [{ id: "t1", code: "employee", name: "Employee", is_abstract: false }],
          relationship_types: [],
          hierarchies: [],
          attribute_definitions: [],
        });
      }
      return Promise.resolve({});
    });
  });

  it("resolves the default organization and renders the graph editor, filter bar, and property panel", async () => {
    renderWithProviders();

    await waitFor(() => expect(mockCytoscape).toHaveBeenCalled());

    expect(screen.getByTestId("filter-search")).toBeInTheDocument();
    expect(screen.getByText(/select a node or edge/i)).toBeInTheDocument();
  });
});
```

Run: `cd frontend && npm test -- GraphDemo.test.tsx`
Expected: FAIL (`Cannot find module './GraphDemo'`)

- [ ] **Step 5: Write `frontend/src/pages/GraphDemo.tsx`**

```tsx
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../api/client";
import GraphEditor from "../components/GraphEditor";
import PropertyPanel from "../components/PropertyPanel";
import FilterBar from "../components/FilterBar";
import type { FilterCriteria } from "../components/FilterBar";
import { useGraph } from "../api/graph";

type Selection = { kind: "node" | "edge"; id: string } | null;

function useDefaultOrganizationId() {
  return useQuery({
    queryKey: ["organizations", "default"],
    queryFn: async () => {
      const result = await apiFetch<{ items: { id: string; code: string }[]; total: number }>(
        "/api/iam/organization/?limit=50&offset=0"
      );
      const defaultOrg = result.items.find((item) => item.code === "default");
      return defaultOrg?.id ?? null;
    },
  });
}

export default function GraphDemo() {
  const { data: organizationId, isLoading: orgLoading } = useDefaultOrganizationId();
  const [hierarchyId, setHierarchyId] = useState<string | null>(null);
  const [selection, setSelection] = useState<Selection>(null);
  const [filter, setFilter] = useState<FilterCriteria | undefined>(undefined);

  const { data: graph } = useGraph(organizationId ?? "", hierarchyId);

  if (orgLoading || !organizationId) {
    return <p className="text-sm text-slate-400">Loading organization…</p>;
  }

  return (
    <div>
      <h1 className="mb-4 text-lg font-semibold text-slate-900">Domain Graph</h1>
      {graph && (
        <FilterBar
          entityTypes={graph.entity_types}
          edges={graph.edges}
          selectedNodeId={selection?.kind === "node" ? selection.id : null}
          onChange={setFilter}
        />
      )}
      <div className="flex gap-4">
        <div className="flex-1">
          <GraphEditor
            organizationId={organizationId}
            hierarchyId={hierarchyId}
            onHierarchyChange={setHierarchyId}
            filter={filter}
            onSelectionChange={setSelection}
          />
        </div>
        <div className="w-72 shrink-0 rounded-md border border-slate-200 p-3">
          {graph && (
            <PropertyPanel
              organizationId={organizationId}
              hierarchyId={hierarchyId}
              graph={graph}
              selection={selection}
              onClose={() => setSelection(null)}
            />
          )}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 6: Run the GraphDemo test to verify it passes**

Run: `cd frontend && npm test -- GraphDemo.test.tsx`
Expected: PASS

- [ ] **Step 7: Add the sidebar link in `frontend/src/components/AppShell.tsx`**

Find the existing `<Link to="/" ...>Dashboard</Link>` line and add immediately after it:

```tsx
<Link to="/graph" className="mb-4 block text-sm text-slate-600 hover:text-slate-900">
  Domain Graph
</Link>
```

- [ ] **Step 8: Add the route in `frontend/src/App.tsx`**

Add `import GraphDemo from "./pages/GraphDemo";` alongside the other page imports, and add this route inside the `AppShell`-nested children, alongside the existing `index`/`:schemaName/:tableName` routes:

```tsx
<Route path="graph" element={<GraphDemo />} />
```

- [ ] **Step 9: Run the full frontend suite and typecheck**

Run: `cd frontend && npm test && npm run build`
Expected: all tests pass, clean build

- [ ] **Step 10: Commit**

```bash
git add frontend/src/components/GraphEditor.tsx frontend/src/components/GraphEditor.test.tsx frontend/src/pages/GraphDemo.tsx frontend/src/pages/GraphDemo.test.tsx frontend/src/components/AppShell.tsx frontend/src/App.tsx
git commit -m "feat: GraphDemo page composing GraphEditor, PropertyPanel, and FilterBar"
```

---

## Task 12: Full-stack integration verification

**Files:**
- Create: `scripts/graph_smoke_check.py`

**Interfaces:**
- Consumes: everything from Tasks 1-11 — this task adds no new application code, it verifies the assembled Graph Editor works end-to-end against the real running stack (real Postgres, real HTTP, no mocks), the same role Task 24 played for the platform skeleton itself. This sub-project adds **no new database migrations** — it only adds application code over the domain schema tables that already exist.

- [ ] **Step 1: Write `scripts/graph_smoke_check.py`**

```python
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
```

- [ ] **Step 2: Run the full backend and frontend test suites one more time**

Run:
```bash
docker compose exec -T backend pytest -v
cd frontend && npm test && npm run build
```
Expected: all backend tests pass (the platform skeleton's existing suite plus all of Tasks 1-5's new tests), all frontend tests pass (the platform skeleton's existing suite plus all of Tasks 6-11's new tests), clean typecheck/build.

- [ ] **Step 3: Rebuild the stack with this sub-project's code and seed the demo data**

Run:
```bash
docker compose up -d --build backend frontend
docker compose exec -T backend python -m app.seed_graph_demo
```
Expected: both containers rebuild and come up healthy; the seed script prints `Graph demo data seeded.`

- [ ] **Step 4: Run the smoke check**

Run: `python scripts/graph_smoke_check.py` (or `python3 scripts/graph_smoke_check.py` if that's what resolves on your machine — same portability note as the platform skeleton's `scripts/smoke_test.sh`)
Expected: prints each step and ends with `== All graph smoke checks passed ==`, exit code 0.

- [ ] **Step 5: Manual-equivalent UI verification**

If a browser is available in your environment, open `http://localhost:3010/graph`, log in as `admin`/`change-me-admin` if not already, and confirm: the seeded Employee/Unit graph renders with Ahmed/Sara nested under Engineering and Mostafa under Operations (via the "Org Chart" hierarchy dropdown); clicking a node opens the property panel with its fields and any `rank`-style attributes; dragging from one node to another opens a type-filtered relationship picker; the entity-type filter checkboxes and search box narrow the visible nodes; deleting a still-connected node shows an error instead of silently failing.

If no browser is available in your environment, the API-level checks in Step 4 already exercise the identical backend behavior every one of those UI actions depends on — note in your report that the literal browser click-through wasn't performed but the underlying request/response flow was verified end-to-end via `graph_smoke_check.py`, the same accommodation used for the platform skeleton's own final integration task.

- [ ] **Step 6: Commit**

```bash
git add scripts/graph_smoke_check.py
git commit -m "test: add full-stack smoke check for the Graph Editor sub-project"
```

---

## Plan-level verification

Once all 12 tasks are complete, the Graph Editor sub-project should satisfy every requirement in the spec:

- Normalized graph contract, Pydantic + TypeScript, field-for-field matching (spec §3) — Tasks 1, 6.
- `GraphService` with atomic multi-table node/edge writes, 409-on-conflict, 422-on-type-mismatch (spec §4) — Tasks 2-4.
- `<GraphEditor/>` with pan/zoom/drag, hierarchy-driven compound nesting and collapse/expand (native to Cytoscape once `parent` is set), drag-connect edge creation, create-node form (spec §5.2) — Tasks 7-8.
- `<PropertyPanel/>` for fixed fields, EAV attributes, and edge JSON, with delete and inline error surfacing (spec §5.2) — Task 9.
- `<FilterBar/>` for entity-type filtering, search, and one-hop dependency highlighting (spec §5.2) — Task 10.
- Seeded Employee/Unit demo data, manually run, not auto-started (spec §6) — Task 5.
- The `/graph` demo page and sidebar link (spec §5.2) — Task 11.
- Real end-to-end verification against the live stack, not mocks (spec §7) — Task 12.
- Nothing from spec's out-of-scope list (NetworkX, Sigma.js, Problem view, solver/solution views, subgraph bookmarking) was built — confirmed by absence, not by a task.