# Spatial Region Partitioning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a planner generate a square or hex grid over a boundary, group its cells into K contiguous zones each split into M contiguous sub-zones (both decided in one solve), and see and export the partition on a map — with spatial data living in ordinary, mixed GIS/non-GIS domains.

**Architecture:** Geometry is a new attribute type (GeoJSON in the entity's JSONB `attrs`), so any entity can be spatial. A domain operation (the grid generator, Shapely + pyproj) writes cells and an `adjacent` relationship as ordinary entities and edges. A new IR rule kind, `connected`, states contiguity; the compiler turns it into an exact single-commodity flow, so every existing backend solves it. A run's partition is served as GeoJSON and drawn by a `spatial-map` GenUI component.

**Tech Stack:** FastAPI, SQLAlchemy, Postgres 16 (plpgsql triggers), Alembic; Shapely 2 and pyproj 3 (new); OR-Tools CP-SAT, HiGHS, SCIP; React 18 + TypeScript + Tailwind; Vitest; pytest in the `solver-backend-test` image.

**Spec:** `docs/superpowers/specs/2026-09-24-spatial-region-partitioning-design.md`

## Global Constraints

- IR contract changes: an optional key on **version 2** only (the `connected` rule), with rules in `backend/app/ir/contract.json`, both validators (`backend/app/ir/validate.py`, `frontend/src/ir/validate.ts`) checking in the same order, fixtures in `backend/tests/ir_fixtures.json`, and parity tests green.
- Geometry: GeoJSON `Point`, `Polygon`, `MultiPolygon` only; rings closed; **at most 10,000 vertices per geometry**.
- Domain CRS: setting `spatial.crs`, an EPSG code, **default 4326**; all lengths and areas in the UTM zone of the boundary's centroid.
- Grid: `shape` is `square` or `hex`; `size_m` is the square side or the hex flat-to-flat width in metres; **at most 20,000 cells**; upload **at most 20 MB**; `keep` is `centre` or `overlap`.
- Cell keys: square `c_r{row}_c{col}`; hex `h_q{q}_r{r}` with negative axial coordinates written `m` (`h_qm3_r2`), because keys must stay usable in URLs and scenario patches.
- Adjacency: relationship type `adjacent` on the cell type, **one edge per unordered pair** (from the lower key to the higher), attribute `shared_m` (number).
- `connected` rule: hard, unconditional, variable binary and indexed exactly by (units set, groups set), `via` a relationship from the units' type to itself, `empty` is `forbidden` or `allowed` (default `forbidden`).
- Every refusal names its cause (the vertex, the count, the key); never a bare 400.
- No PostGIS. No basemap tiles. No new frontend dependency.
- Tests run as the project does: `bash scripts/check.sh` green before every commit; one pytest file with `MSYS_NO_PATHCONV=1 docker run --rm --network solver_solver_net -v "D:/solver/backend:/app" -w /app --env-file D:/solver/.env -e CLICKHOUSE_HOST=clickhouse solver-backend-test sh -c 'TEST_DATABASE_URL=${DATABASE_URL}_test pytest -q tests/<file>'`; after changing `requirements.txt`, rebuild the test image (`docker build -t solver-backend-test backend`) and run `SOLVER_BACKEND_IMAGE=solver-backend-test bash scripts/check.sh`.
- Migrations: check `git log` for the latest number before numbering (0047 at the time of writing); rehearse up/down/up on a copy of the live database before deploying.
- C: disk is nearly full: `docker image prune -f` after every image build; check `%LOCALAPPDATA%\Temp\wsl-crashes` if C: shrinks.
- Commit by path; never `git add -A`.

## Review Focus

- **A boundary crossing the antimeridian or straddling two UTM zones** — a planner expects the grid to be made or refused by name, never a grid of skewed cells: the generator refuses a boundary wider than 6° of longitude or crossing ±180° (test in Task 3).
- **A grid over a MultiPolygon boundary with a hole (a lake)** — cells in the hole must not be kept, and cells on either side of it must not be adjacent through it: covered by the lake test in Task 3.
- **A `connected` model where a zone cannot be connected** (the grid itself is in two pieces and every zone must reach both) — expected: the run is `infeasible`, and the explanation names the `connected` rule: test in Task 6.
- **Re-running the grid generator while a scenario uses the old cells** — expected: a 409 that states the cell count and the scenarios, and nothing changed until `replace: true`: test in Task 4.
- **A geometry attribute read by arithmetic or a filter** — expected: the IR refuses it (`attribute_not_arithmetic`, `where_operator_not_offered`) exactly as it refuses `text`: test in Task 1.

---

## File Structure

**Backend**
- `backend/alembic/versions/0047_geometry_attribute.py` — enum value, SQL type checks, `spatial.crs` setting key.
- `backend/app/spatial/__init__.py` — package marker.
- `backend/app/spatial/geometry.py` — GeoJSON validation, the one place geometry shape is judged in Python.
- `backend/app/spatial/project.py` — CRS handling: UTM choice, transforms.
- `backend/app/spatial/grid.py` — pure grid construction (cells, adjacency, layer sums). No database.
- `backend/app/api/grids.py` — `POST /api/v1/domains/{id}/grids`, writing the grid in one transaction.
- `backend/app/api/run_map.py` — `GET /api/v1/runs/{id}/map` (GeoJSON of a run's partition).
- `backend/app/solve/connected.py` — the `connected` rule compiled to flow rows.
- Modified: `app/api/entity_types.py` (AttrType, defaults), `app/api/entities.py` (geometry validation on write), `app/expressions/catalogue.json` (`geometry: []` operators), `app/ir/contract.json`, `app/ir/contract.py`, `app/ir/validate.py`, `app/ir/models.py`, `app/solve/compile.py`, `app/solve/classify.py`, `app/solve/backends.py`, `app/solve/fingerprint.py`, `app/genui/protocol.json`, `app/genui/translate.py`, `app/api/genui.py`, `app/showcase.py`, `app/api/templates.py` (grids step), `app/main.py`, `requirements.txt`.
- Tests: `backend/tests/test_geometry_attribute.py`, `test_spatial_grid.py`, `test_grid_api.py`, `test_connected.py`, `test_run_map.py`, `test_region_template.py`; fixtures in `tests/ir_fixtures.json`.
- Bench: `backend/bench/families.py` (`districting`), report `backend/bench/results/2026-09-2x-districting.md`.

**Frontend**
- `frontend/src/components/GeometryPreview.tsx` — small SVG of a GeoJSON geometry.
- `frontend/src/components/GridGeneratorForm.tsx` — the grid form on the entity-types page.
- `frontend/src/model/ConnectedEditor.tsx` — the `connected` rule editor.
- `frontend/src/genui/components/SpatialMap.tsx` — map component (SVG ≤ 5,000 cells, canvas beyond).
- Modified: `src/api/v1.ts`, `src/ir/contract.ts`, `src/ir/validate.ts`, `src/expressions/*` (operators by type), `src/components/attrTypes.tsx`, `src/pages/EntityRecord.tsx`, `src/pages/EntityTypes.tsx`, `src/model/terms.ts`, `src/model/ModelEditor` rule list, `src/genui/protocol/types.ts`, `src/genui/registry/componentRegistry.ts`, `src/pages/Runs.tsx`.

---

### Task 1: The `geometry` attribute type

**Files:**
- Create: `backend/alembic/versions/0047_geometry_attribute.py`, `backend/app/spatial/__init__.py`, `backend/app/spatial/geometry.py`, `backend/tests/test_geometry_attribute.py`, `frontend/src/components/GeometryPreview.tsx`, `frontend/src/components/GeometryPreview.test.tsx`
- Modify: `backend/app/api/entity_types.py:97` (AttrType), `:145-176` (`_default_value_matches`), `:204-211` (`_DEFAULT_SHAPE`); `backend/app/api/entities.py` (write path); `backend/app/models/v1_domain.py:59-68` (ATTR_TYPE); `backend/app/expressions/catalogue.json` (`operatorsByType`); `frontend/src/api/v1.ts:113`; `frontend/src/expressions/operators.ts` (by-type table); `frontend/src/components/attrTypes.tsx`; `frontend/src/pages/EntityRecord.tsx`

**Interfaces:**
- Produces: `app.spatial.geometry.validate_geometry(value: object) -> str | None` (None when valid, else a sentence naming the fault); `app.spatial.geometry.GEOMETRY_TYPES = ("Point", "Polygon", "MultiPolygon")`; `app.spatial.geometry.MAX_VERTICES = 10_000`; SQL `attr_value_matches_type` accepting `'geometry'`; React `<GeometryPreview geometry={object} size={number} />`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_geometry_attribute.py
"""A geometry attribute: validated on write, stored as given, refused by arithmetic."""
from __future__ import annotations

import pytest
from sqlalchemy import text

from app.spatial.geometry import MAX_VERTICES, validate_geometry
from tests.test_v1_problem_run import db, make_domain, make_entity_type  # noqa: F401

SQUARE = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}


@pytest.mark.parametrize(
    "value, fault",
    [
        (SQUARE, None),
        ({"type": "Point", "coordinates": [31.2, 30.0]}, None),
        ({"type": "MultiPolygon", "coordinates": [SQUARE["coordinates"]]}, None),
        ({"type": "LineString", "coordinates": [[0, 0], [1, 1]]}, "a geometry is a Point, Polygon or MultiPolygon, not LineString"),
        ({"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0.5]]]}, "ring 0 is not closed: it starts at [0, 0] and ends at [0, 0.5]"),
        ({"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [0, 0]]]}, "ring 0 has 3 positions; a ring needs at least 4 (the first repeated last)"),
        ({"type": "Point", "coordinates": [200, 0]}, "position [200, 0] is outside longitude -180..180 or latitude -90..90"),
        ({"type": "Point", "coordinates": ["a", 0]}, "position ['a', 0] is not two numbers"),
        ("POLYGON((0 0,1 0,1 1,0 0))", "a geometry is a GeoJSON object, not text"),
    ],
)
def test_each_fault_is_named(value, fault):
    assert validate_geometry(value) == fault


def test_too_many_vertices_is_refused_with_the_count():
    ring = [[i * 1e-6, 0] for i in range(MAX_VERTICES)] + [[0, 1e-3], [0, 0]]
    assert validate_geometry({"type": "Polygon", "coordinates": [ring]}) == (
        f"this geometry has {MAX_VERTICES + 2} positions; the limit is {MAX_VERTICES}"
    )


def test_the_database_accepts_a_geometry_and_refuses_text_for_one(db):
    domain = make_domain(db, "geo")
    area = make_entity_type(db, domain, "area", "other")
    db.execute(text("INSERT INTO attribute_def (entity_type_id, name, data_type) VALUES (:t, 'shape', 'geometry')"), {"t": area})
    db.execute(text("INSERT INTO entity (entity_type_id, key, attrs) VALUES (:t, 'a', CAST(:g AS jsonb))"),
               {"t": area, "g": '{"shape": {"type": "Point", "coordinates": [31, 30]}}'})
    with pytest.raises(Exception, match='attribute "shape" must be geometry'):
        db.execute(text("INSERT INTO entity (entity_type_id, key, attrs) VALUES (:t, 'b', CAST(:g AS jsonb))"),
                   {"t": area, "g": '{"shape": "POINT(31 30)"}'})
    db.rollback()


def test_the_api_names_a_bad_ring(tenants, db):  # noqa: F811
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    domain = client.post("/api/public/domain", json={"name": "geo-api"}, headers=tenants["a"]).json()["id"]
    area = client.post("/api/v1/entity-types", json={"domain_id": domain, "name": "area"}, headers=tenants["a"]).json()["id"]
    made = client.post(f"/api/v1/entity-types/{area}/attributes", json={"name": "shape", "data_type": "geometry"}, headers=tenants["a"])
    assert made.status_code == 201, made.text
    open_ring = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0.5]]]}
    refused = client.post("/api/v1/entities", json={"entity_type_id": area, "key": "a", "attrs": {"shape": open_ring}}, headers=tenants["a"])
    assert refused.status_code == 422
    assert "attrs.shape" in refused.text and "ring 0 is not closed" in refused.text
    kept = client.post("/api/v1/entities", json={"entity_type_id": area, "key": "b", "attrs": {"shape": SQUARE}}, headers=tenants["a"])
    assert kept.status_code == 201 and kept.json()["attrs"]["shape"] == SQUARE
```

Add `from tests.test_tenancy import tenants  # noqa: F401` to the file's imports. The domain-creation path (`/api/public/domain`) is the generic-layer route the existing tests use; if `tests/test_tenancy.py` creates domains another way, use that one.

```python
# frontend/src/components/GeometryPreview.test.tsx
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import GeometryPreview from "./GeometryPreview";

describe("GeometryPreview", () => {
  it("draws a polygon inside its box, north up", () => {
    const { container } = render(
      <GeometryPreview geometry={{ type: "Polygon", coordinates: [[[0, 0], [2, 0], [2, 1], [0, 1], [0, 0]]] }} size={100} />
    );
    const d = container.querySelector("path")!.getAttribute("d")!;
    expect(d.startsWith("M")).toBe(true);
    // North up: latitude 1 (top) has the smaller y.
    expect(container.querySelector("svg")!.getAttribute("aria-label")).toBe("Polygon, 5 positions");
  });

  it("says what it cannot draw instead of drawing nothing", () => {
    const { getByText } = render(<GeometryPreview geometry={"not geojson" as unknown as object} size={80} />);
    expect(getByText("No shape to draw")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run them to see them fail**

Run the backend file with the docker command in Global Constraints (`tests/test_geometry_attribute.py`) — expected: `ModuleNotFoundError: No module named 'app.spatial'`. Run `npx vitest run src/components/GeometryPreview.test.tsx` in `frontend/` — expected: cannot resolve `./GeometryPreview`.

- [ ] **Step 3: Write the migration**

```python
# backend/alembic/versions/0047_geometry_attribute.py
"""The `geometry` attribute type (GeoJSON), and the domain setting `spatial.crs`.

A geometry is a GeoJSON Point, Polygon or MultiPolygon stored in `attrs`
as given. The database judges its shape coarsely (an object with one of the
three types and an array of coordinates); `app.spatial.geometry` judges it
fully on every API write, naming the ring or position at fault.
"""
import sqlalchemy as sa
from alembic import op

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None

_GEOMETRY_CASE = """
    WHEN 'geometry' THEN jsonb_typeof(p_value) = 'object'
                         AND p_value ->> 'type' IN ('Point', 'Polygon', 'MultiPolygon')
                         AND jsonb_typeof(p_value -> 'coordinates') = 'array'
"""


def _matches(with_geometry: bool) -> str:
    return f"""
        CREATE OR REPLACE FUNCTION attr_value_matches_type(p_type attr_type, p_enum_values text[], p_value jsonb)
        RETURNS boolean LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
            SELECT coalesce(CASE p_type::text
                WHEN 'integer' THEN CASE WHEN jsonb_typeof(p_value) = 'number'
                                         THEN (p_value #>> '{{}}')::numeric % 1 = 0
                                         ELSE false END
                WHEN 'number'  THEN jsonb_typeof(p_value) = 'number'
                WHEN 'boolean' THEN jsonb_typeof(p_value) = 'boolean'
                WHEN 'enum'    THEN jsonb_typeof(p_value) = 'string'
                                    AND (p_value #>> '{{}}') = ANY (p_enum_values)
                {_GEOMETRY_CASE if with_geometry else ""}
                ELSE                jsonb_typeof(p_value) = 'string'
            END, false)
        $$;
    """


# entity_validate as migration 0006 wrote it, with its inline CASE replaced by
# the one shared judgement -- so entities, relationships and defaults can
# never disagree about what a value of a type is.
_ENTITY_VALIDATE = """
    CREATE OR REPLACE FUNCTION entity_validate() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE d attribute_def; v jsonb; k text;
    BEGIN
        FOR k IN SELECT jsonb_object_keys(NEW.attrs) LOOP
            IF NOT EXISTS (SELECT 1 FROM attribute_def
                           WHERE entity_type_id = NEW.entity_type_id AND name = k) THEN
                RAISE EXCEPTION 'entity %: unknown attribute "%"', NEW.key, k
                    USING ERRCODE = '23514',
                          DETAIL  = jsonb_build_object('kind', 'unknown_attribute', 'field', k, 'record', NEW.key)::text;
            END IF;
        END LOOP;
        FOR d IN SELECT * FROM attribute_def WHERE entity_type_id = NEW.entity_type_id LOOP
            v := NEW.attrs -> d.name;
            IF v IS NULL AND d.default_value IS NOT NULL THEN
                NEW.attrs := NEW.attrs || jsonb_build_object(d.name, d.default_value);
                v := d.default_value;
            END IF;
            IF v IS NULL OR v = 'null' THEN
                IF d.required THEN
                    RAISE EXCEPTION 'entity %: attribute "%" is required', NEW.key, d.name
                        USING ERRCODE = '23514',
                              DETAIL  = jsonb_build_object('kind', 'required_attribute', 'field', d.name, 'record', NEW.key)::text;
                END IF;
                CONTINUE;
            END IF;
            IF NOT attr_value_matches_type(d.data_type, d.enum_values, v) THEN
                RAISE EXCEPTION 'entity %: attribute "%" must be %', NEW.key, d.name, d.data_type
                    USING ERRCODE = '23514',
                          DETAIL  = jsonb_build_object('kind', 'attribute_type', 'field', d.name,
                                                       'record', NEW.key, 'expected', d.data_type::text)::text;
            END IF;
        END LOOP;
        RETURN NEW;
    END $$;
"""


def upgrade() -> None:
    # A new enum value cannot be used in the transaction that adds it; the
    # functions below only name it as text, which is resolved when they run.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE attr_type ADD VALUE IF NOT EXISTS 'geometry'")
    op.execute(_matches(with_geometry=True))
    op.execute(_ENTITY_VALIDATE)
    op.get_bind().execute(sa.text(
        "INSERT INTO setting_key (key, value_type, default_value, description) VALUES"
        " ('spatial.crs', 'integer', CAST('4326' AS jsonb),"
        "  'The EPSG code of the coordinates this domain''s geometry is written in')"
    ))


def downgrade() -> None:
    op.execute("DELETE FROM setting WHERE key = 'spatial.crs'")
    op.execute("DELETE FROM setting_key WHERE key = 'spatial.crs'")
    # Refused while anything is a geometry: dropping the type would orphan it.
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM attribute_def WHERE data_type::text = 'geometry') THEN
                RAISE EXCEPTION 'geometry attributes exist; delete them before downgrading 0047';
            END IF;
        END $$;
    """)
    op.execute(_matches(with_geometry=False))
    op.execute(_ENTITY_VALIDATE)
    # Postgres cannot drop an enum value: rebuild the type without it.
    op.execute("""
        ALTER TYPE attr_type RENAME TO attr_type_0047;
        CREATE TYPE attr_type AS ENUM ('integer', 'number', 'text', 'boolean', 'enum', 'time', 'date');
        ALTER TABLE attribute_def ALTER COLUMN data_type TYPE attr_type USING data_type::text::attr_type;
    """)
    op.execute(_matches(with_geometry=False).replace("CREATE OR REPLACE", "CREATE OR REPLACE"))
    op.execute("DROP TYPE attr_type_0047")
```

Before writing `downgrade`'s type rebuild, run `\d attribute_def` and `SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'attribute_def'::regclass` against the live database: every constraint and function whose signature names `attr_type` (`attr_value_matches_type(attr_type, ...)`) must be dropped before `ALTER COLUMN ... TYPE` and re-created after. Write those exact `DROP`/`CREATE` statements into the migration, then rehearse up/down/up on a copy of the live database (Global Constraints).

- [ ] **Step 4: Write `validate_geometry`**

```python
# backend/app/spatial/geometry.py
"""GeoJSON geometry, judged once, in words (spec §2).

The database checks only that a geometry is an object of one of the three
types (migration 0047); this names the ring or position at fault, which is
what a planner fixing a file needs.
"""
from __future__ import annotations

from typing import Any

GEOMETRY_TYPES = ("Point", "Polygon", "MultiPolygon")
MAX_VERTICES = 10_000


def _position(p: Any) -> str | None:
    if not (isinstance(p, list) and len(p) in (2, 3) and all(isinstance(n, (int, float)) and not isinstance(n, bool) for n in p)):
        return f"position {p!r} is not two numbers"
    lon, lat = p[0], p[1]
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        return f"position {p!r} is outside longitude -180..180 or latitude -90..90"
    return None


def _ring(ring: Any, n: int) -> tuple[str | None, int]:
    if not isinstance(ring, list):
        return f"ring {n} is not an array of positions", 0
    for p in ring:
        fault = _position(p)
        if fault:
            return fault, 0
    if len(ring) < 4:
        return f"ring {n} has {len(ring)} positions; a ring needs at least 4 (the first repeated last)", len(ring)
    if ring[0][:2] != ring[-1][:2]:
        return f"ring {n} is not closed: it starts at {ring[0]} and ends at {ring[-1]}", len(ring)
    return None, len(ring)


def _polygon(rings: Any, count: list[int]) -> str | None:
    if not isinstance(rings, list) or not rings:
        return "a polygon is a non-empty array of rings"
    for n, ring in enumerate(rings):
        fault, size = _ring(ring, n)
        count[0] += size
        if fault:
            return fault
    return None


def validate_geometry(value: Any) -> str | None:
    """None when `value` is a geometry this platform stores, else why not."""
    if not isinstance(value, dict):
        return "a geometry is a GeoJSON object, not text" if isinstance(value, str) else "a geometry is a GeoJSON object"
    kind = value.get("type")
    if kind not in GEOMETRY_TYPES:
        return f"a geometry is a Point, Polygon or MultiPolygon, not {kind}"
    coordinates = value.get("coordinates")
    count = [0]
    if kind == "Point":
        return _position(coordinates)
    if kind == "Polygon":
        fault = _polygon(coordinates, count)
    else:
        if not isinstance(coordinates, list) or not coordinates:
            return "a multipolygon is a non-empty array of polygons"
        fault = next((f for f in (_polygon(p, count) for p in coordinates) if f), None)
    if fault:
        return fault
    if count[0] > MAX_VERTICES:
        return f"this geometry has {count[0]} positions; the limit is {MAX_VERTICES}"
    return None
```

`backend/app/spatial/__init__.py`: a one-line docstring, `"""Spatial data: geometry, projection, grids (spec 2026-09-24)."""`.

- [ ] **Step 5: Wire the type through**

In `backend/app/api/entity_types.py`: `AttrType = Literal["integer", "number", "text", "boolean", "enum", "time", "date", "geometry"]`; in `_default_value_matches` add, before the final `return isinstance(value, str)`:

```python
    if data_type == "geometry":
        from app.spatial.geometry import validate_geometry

        return validate_geometry(value) is None
```

and `_DEFAULT_SHAPE["geometry"] = "GeoJSON Point, Polygon or MultiPolygon"`. In `backend/app/models/v1_domain.py` add `"geometry"` to `ATTR_TYPE`. In `backend/app/api/entities.py`, in the create and patch handlers after the entity type's attribute definitions are loaded, add:

```python
for definition in definitions:
    value = (body.attrs or {}).get(definition.name)
    if definition.data_type == "geometry" and value is not None:
        fault = validate_geometry(value)
        if fault:
            raise field_error(f"attrs.{definition.name}", fault, None)
```

(`field_error` is the helper `entity_types.py` already imports from `app.api.validation`; import it the same way.) In `backend/app/expressions/catalogue.json` add `"geometry": []` to `operatorsByType` (a geometry offers no filter operator), and the same key in the frontend by-type table the parity test compares (`frontend/src/expressions/operators.ts`).

In `frontend/src/api/v1.ts:113` add `"geometry"` to `AttrType`; in `frontend/src/components/attrTypes.tsx` add the label `geometry: "shape (GeoJSON)"` and, where attribute inputs are chosen by type, render a `<textarea>` that parses JSON on blur and shows `validate`-style errors from the server's 422, plus `<GeometryPreview>` beside it. In `frontend/src/pages/EntityRecord.tsx`, show geometry values as `<GeometryPreview geometry={value} size={96} />` instead of text.

- [ ] **Step 6: Write `GeometryPreview`**

```tsx
// frontend/src/components/GeometryPreview.tsx
/** A GeoJSON geometry drawn small, north up, fitted to its box -- never raw JSON on a page. */
type Position = [number, number];
type Geometry = { type: string; coordinates: unknown };

function rings(g: Geometry): Position[][] {
  if (g.type === "Polygon") return g.coordinates as Position[][];
  if (g.type === "MultiPolygon") return (g.coordinates as Position[][][]).flat();
  if (g.type === "Point") return [[g.coordinates as Position]];
  return [];
}

export default function GeometryPreview({ geometry, size = 96 }: { geometry: object; size?: number }) {
  const g = geometry as Geometry;
  const all = g && typeof g === "object" && typeof g.type === "string" ? rings(g) : [];
  const points = all.flat();
  if (points.length === 0) return <span className="text-xs text-slate-500">No shape to draw</span>;
  const xs = points.map((p) => p[0]);
  const ys = points.map((p) => p[1]);
  const [minX, maxX, minY, maxY] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const span = Math.max(maxX - minX, maxY - minY) || 1;
  const pad = 4;
  const x = (v: number) => pad + ((v - minX) / span) * (size - 2 * pad);
  const y = (v: number) => size - pad - ((v - minY) / span) * (size - 2 * pad);
  const d = all.map((ring) => ring.map((p, i) => `${i ? "L" : "M"}${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join(" ") + " Z").join(" ");
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={`${g.type}, ${points.length} positions`} className="rounded border border-slate-200 bg-slate-50">
      {g.type === "Point" ? (
        <circle cx={x(points[0][0])} cy={y(points[0][1])} r={3} className="fill-blue-600" />
      ) : (
        <path d={d} className="fill-blue-100 stroke-blue-700" strokeWidth={1} fillRule="evenodd" />
      )}
    </svg>
  );
}
```

- [ ] **Step 7: Add the arithmetic/filter refusal test** (Review Focus 5)

Add to `backend/tests/test_geometry_attribute.py`:

```python
def test_a_geometry_is_not_a_number_to_the_ir(db):
    from app.ir.validate import validate_ir  # the domain-aware entry point used by publish
    domain = make_domain(db, "geo-ir")
    area = make_entity_type(db, domain, "area", "other")
    db.execute(text("INSERT INTO attribute_def (entity_type_id, name, data_type) VALUES (:t, 'shape', 'geometry')"), {"t": area})
    db.commit()
    ir = {"version": 2, "sets": ["area"], "parameters": {}, "variables": {"x": {"index": ["area"], "domain": "binary"}},
          "constraints": [], "objective": {"sense": "maximize", "terms": [{"id": "o", "weight": 1, "expression":
              {"sum": {"mul": [{"attr": {"of": "a", "name": "shape"}}, {"var": "x", "index": ["a"]}]},
               "over": [{"index": "a", "set": "area"}]}}]}}
    refusal = validate_ir(db, domain, ir)
    assert refusal.code == "attribute_not_arithmetic"
```

Use the actual function name `app.ir.validate` exposes for the domain check (the one `POST /problems/{id}/versions` calls); keep the assertion on the code.

- [ ] **Step 8: Run all of it, then the full check**

Run the backend test file and `npx vitest run src/components/GeometryPreview.test.tsx src/expressions` — expected: PASS. Rehearse the migration up/down/up on a copy of the live database. Run `bash scripts/check.sh` — expected: `ALL CHECKS PASSED`.

- [ ] **Step 9: Commit**

```bash
git add backend/alembic/versions/0047_geometry_attribute.py backend/app/spatial backend/app/api/entity_types.py backend/app/api/entities.py backend/app/models/v1_domain.py backend/app/expressions/catalogue.json backend/tests/test_geometry_attribute.py frontend/src/api/v1.ts frontend/src/expressions frontend/src/components/attrTypes.tsx frontend/src/components/GeometryPreview.tsx frontend/src/components/GeometryPreview.test.tsx frontend/src/pages/EntityRecord.tsx
git commit -m "feat(domain): a geometry attribute type -- GeoJSON validated by ring and position, drawn not printed (migration 0047)"
```

---

### Task 2: Projection and the pure grid

**Files:**
- Create: `backend/app/spatial/project.py`, `backend/app/spatial/grid.py`, `backend/tests/test_spatial_grid.py`
- Modify: `backend/requirements.txt` (add `shapely==2.0.6`, `pyproj==3.7.0`)

**Interfaces:**
- Consumes: nothing from Task 1 except the GeoJSON shapes.
- Produces:
  - `app.spatial.project.Projection(crs: int, around: tuple[float, float])` with `.forward(geom) -> shapely geometry in metres`, `.back(geom) -> shapely geometry in the domain CRS`, `.epsg_metres: int`.
  - `app.spatial.project.OutOfRange(ValueError)` raised for a boundary wider than 6° of longitude or crossing ±180°.
  - `app.spatial.grid.Cell` dataclass: `key: str, row: int, col: int, geometry: dict (GeoJSON, domain CRS), centroid: dict (GeoJSON Point), area_m2: float, coverage: float`.
  - `app.spatial.grid.Edge` dataclass: `a: str, b: str, shared_m: float` with `a < b`.
  - `app.spatial.grid.make_grid(boundary: dict, *, crs: int, shape: Literal["square","hex"], size_m: float, keep: Literal["centre","overlap"], max_cells: int = 20_000) -> tuple[list[Cell], list[Edge], int]` — the int is the number of candidate cells dropped at the boundary.
  - `app.spatial.grid.TooManyCells(ValueError)` with attribute `count: int`.
  - `app.spatial.grid.sum_points(cells: list[Cell], points: list[tuple[float, float, dict[str, float]]], crs: int) -> tuple[dict[str, dict[str, float]], dict[str, float]]` — per-cell sums by column, and each column's total that fell outside every cell.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_spatial_grid.py
"""The grid, worked by hand on boundaries whose answers are known.

The boundary is drawn in metres around a point on the equator, where one
degree of longitude is 111,319.49 m in UTM zone 31N's neighbourhood, so a
1,000 m square boundary holds exactly 4 cells of 500 m.
"""
from __future__ import annotations

import math

import pytest

from app.spatial.grid import TooManyCells, make_grid, sum_points
from app.spatial.project import OutOfRange, Projection


def _square_boundary(side_m: float, at=(3.0, 0.0)) -> dict:
    """A square of `side_m` metres, drawn in UTM around `at` and returned in lon/lat."""
    from shapely.geometry import box, mapping

    p = Projection(4326, around=at)
    x0, y0 = p.forward_point(at)
    square = box(x0, y0, x0 + side_m, y0 + side_m)
    return mapping(p.back(square))


def test_a_square_boundary_holds_exactly_the_cells_that_fit():
    cells, edges, dropped = make_grid(_square_boundary(1000), crs=4326, shape="square", size_m=500, keep="centre")
    assert sorted(c.key for c in cells) == ["c_r0_c0", "c_r0_c1", "c_r1_c0", "c_r1_c1"]
    assert all(c.area_m2 == pytest.approx(250_000, rel=1e-6) for c in cells)
    # A 2x2 block: four sides shared, each 500 m.
    assert sorted((e.a, e.b) for e in edges) == [("c_r0_c0", "c_r0_c1"), ("c_r0_c0", "c_r1_c0"),
                                                  ("c_r0_c1", "c_r1_c1"), ("c_r1_c0", "c_r1_c1")]
    assert all(e.shared_m == pytest.approx(500, rel=1e-6) for e in edges)
    assert dropped == 0


def test_hex_cells_have_six_neighbours_in_the_middle():
    cells, edges, _ = make_grid(_square_boundary(5000), crs=4326, shape="hex", size_m=500, keep="centre")
    degree: dict[str, int] = {}
    for e in edges:
        degree[e.a] = degree.get(e.a, 0) + 1
        degree[e.b] = degree.get(e.b, 0) + 1
    assert max(degree.values()) == 6 and min(degree.values()) >= 2
    # A hex of flat-to-flat width w has area (sqrt(3)/2) w^2.
    assert all(c.area_m2 == pytest.approx(math.sqrt(3) / 2 * 500**2, rel=1e-6) for c in cells)
    assert all(e.shared_m == pytest.approx(500 / math.sqrt(3), rel=1e-6) for e in edges)
    assert all(c.key.startswith("h_q") for c in cells)


def test_a_lake_keeps_its_cells_out_and_its_shores_apart():
    """Review Focus 2: a hole is not land, and cells either side are not neighbours through it."""
    from shapely.geometry import box, mapping

    p = Projection(4326, around=(3.0, 0.0))
    x0, y0 = p.forward_point((3.0, 0.0))
    land = box(x0, y0, x0 + 1500, y0 + 500).difference(box(x0 + 500, y0, x0 + 1000, y0 + 500))
    cells, edges, _ = make_grid(mapping(p.back(land)), crs=4326, shape="square", size_m=500, keep="centre")
    assert sorted(c.key for c in cells) == ["c_r0_c0", "c_r0_c2"]
    assert edges == []


def test_overlap_keeps_edge_cells_with_their_share():
    cells, _, _ = make_grid(_square_boundary(750), crs=4326, shape="square", size_m=500, keep="overlap")
    shares = sorted(round(c.coverage, 3) for c in cells)
    assert shares == [0.25, 0.5, 0.5, 1.0]


def test_too_many_cells_is_refused_with_the_count():
    with pytest.raises(TooManyCells) as caught:
        make_grid(_square_boundary(10_000), crs=4326, shape="square", size_m=50, keep="centre", max_cells=20_000)
    assert caught.value.count == 40_000


@pytest.mark.parametrize("boundary", [
    {"type": "Polygon", "coordinates": [[[179, 0], [-179, 0], [-179, 1], [179, 1], [179, 0]]]},
    {"type": "Polygon", "coordinates": [[[0, 0], [8, 0], [8, 1], [0, 1], [0, 0]]]},
])
def test_a_boundary_the_projection_cannot_hold_is_refused(boundary):
    """Review Focus 1."""
    with pytest.raises(OutOfRange):
        make_grid(boundary, crs=4326, shape="square", size_m=500, keep="centre")


def test_points_are_summed_into_their_cells_and_the_rest_reported():
    cells, _, _ = make_grid(_square_boundary(1000), crs=4326, shape="square", size_m=500, keep="centre")
    by_key = {c.key: c for c in cells}
    inside = by_key["c_r0_c0"].centroid["coordinates"]
    outside = (inside[0] + 1.0, inside[1])
    sums, lost = sum_points(cells, [(inside[0], inside[1], {"population": 120}),
                                    (inside[0], inside[1], {"population": 30}),
                                    (outside[0], outside[1], {"population": 7})], crs=4326)
    assert sums["c_r0_c0"] == {"population": 150}
    assert sums.get("c_r1_c1", {}).get("population", 0) == 0
    assert lost == {"population": 7}
```

- [ ] **Step 2: Add the dependencies and rebuild the test image**

Add to `backend/requirements.txt`:

```
shapely==2.0.6
pyproj==3.7.0
```

Run: `docker build -t solver-backend-test backend && docker image prune -f`. Then run `tests/test_spatial_grid.py` — expected: FAIL, `ModuleNotFoundError: No module named 'app.spatial.grid'`.

- [ ] **Step 3: Write the projection**

```python
# backend/app/spatial/project.py
"""From the domain's CRS to metres and back (spec §2): the UTM zone of the
boundary's centroid, so "a 500 m cell" is 500 m on the ground."""
from __future__ import annotations

from pyproj import CRS, Transformer
from shapely.ops import transform

MAX_WIDTH_DEG = 6.0  # one UTM zone


class OutOfRange(ValueError):
    """A boundary one UTM zone cannot hold."""


def utm_epsg(lon: float, lat: float) -> int:
    zone = int((lon + 180) // 6) + 1
    return (32600 if lat >= 0 else 32700) + zone


class Projection:
    def __init__(self, crs: int, around: tuple[float, float]):
        self.source = CRS.from_epsg(crs)
        to_lonlat = Transformer.from_crs(self.source, CRS.from_epsg(4326), always_xy=True)
        lon, lat = to_lonlat.transform(*around)
        self.epsg_metres = utm_epsg(lon, lat)
        metres = CRS.from_epsg(self.epsg_metres)
        self._fwd = Transformer.from_crs(self.source, metres, always_xy=True)
        self._back = Transformer.from_crs(metres, self.source, always_xy=True)

    def forward(self, geom):
        return transform(self._fwd.transform, geom)

    def back(self, geom):
        return transform(self._back.transform, geom)

    def forward_point(self, point: tuple[float, float]) -> tuple[float, float]:
        return self._fwd.transform(*point)


def check_extent(lonlat_bounds: tuple[float, float, float, float]) -> None:
    """Refuse a boundary crossing ±180° or wider than one UTM zone."""
    min_lon, _, max_lon, _ = lonlat_bounds
    if max_lon - min_lon > 180:
        raise OutOfRange("the boundary crosses longitude 180; split it at the antimeridian")
    if max_lon - min_lon > MAX_WIDTH_DEG:
        raise OutOfRange(
            f"the boundary is {max_lon - min_lon:.1f} degrees of longitude wide; one grid covers at most "
            f"{MAX_WIDTH_DEG:.0f} (one UTM zone) -- split it into parts"
        )
```

- [ ] **Step 4: Write the grid**

```python
# backend/app/spatial/grid.py
"""Square and hex grids over a boundary: cells, adjacency and layer sums.

Pure: GeoJSON in, cells and edges out; the API writes them (Task 3). Built
in metres (`Projection`), stored in the domain's CRS.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from pyproj import CRS, Transformer
from shapely.geometry import Point, Polygon, mapping
from shapely.geometry import shape as to_shape  # not `shape`: make_grid has a parameter of that name
from shapely.strtree import STRtree

from app.spatial.project import Projection, check_extent


class TooManyCells(ValueError):
    def __init__(self, count: int, limit: int):
        super().__init__(f"this grid would have {count} cells; the limit is {limit} -- use a larger cell")
        self.count = count


@dataclass(frozen=True)
class Cell:
    key: str
    row: int
    col: int
    geometry: dict
    centroid: dict
    area_m2: float
    coverage: float


@dataclass(frozen=True)
class Edge:
    a: str
    b: str
    shared_m: float


def _axial(n: int) -> str:
    return f"m{-n}" if n < 0 else str(n)


def _lonlat_bounds(boundary, crs: int) -> tuple[float, float, float, float]:
    to = Transformer.from_crs(CRS.from_epsg(crs), CRS.from_epsg(4326), always_xy=True)
    minx, miny, maxx, maxy = boundary.bounds
    (a, b), (c, d) = to.transform(minx, miny), to.transform(maxx, maxy)
    return (min(a, c), min(b, d), max(a, c), max(b, d))


def _square_cells(minx, miny, maxx, maxy, size):
    rows = math.ceil((maxy - miny) / size)
    cols = math.ceil((maxx - minx) / size)
    for r in range(rows):
        for c in range(cols):
            x, y = minx + c * size, miny + r * size
            yield f"c_r{r}_c{c}", r, c, Polygon([(x, y), (x + size, y), (x + size, y + size), (x, y + size)])


def _hex_cells(minx, miny, maxx, maxy, size):
    """Pointy-top hexes; `size` is the flat-to-flat width, so the circumradius is size/sqrt(3)."""
    radius = size / math.sqrt(3)
    dy = 1.5 * radius
    rows = math.ceil((maxy - miny) / dy) + 1
    cols = math.ceil((maxx - minx) / size) + 1
    for r in range(rows):
        for c in range(cols):
            q = c - (r // 2)  # odd-r offset to axial
            cx = minx + size * (q + r / 2)
            cy = miny + dy * r
            corners = [(cx + radius * math.cos(math.radians(60 * k - 30)), cy + radius * math.sin(math.radians(60 * k - 30))) for k in range(6)]
            yield f"h_q{_axial(q)}_r{_axial(r)}", r, q, Polygon(corners)


def make_grid(boundary: dict, *, crs: int, shape: Literal["square", "hex"], size_m: float,
              keep: Literal["centre", "overlap"], max_cells: int = 20_000) -> tuple[list[Cell], list[Edge], int]:
    area = to_shape(boundary)
    check_extent(_lonlat_bounds(area, crs))
    projection = Projection(crs, around=(area.centroid.x, area.centroid.y))
    land = projection.forward(area)
    minx, miny, maxx, maxy = land.bounds
    candidates = list((_square_cells if shape == "square" else _hex_cells)(minx, miny, maxx, maxy, size_m))
    if len(candidates) > max_cells:
        raise TooManyCells(len(candidates), max_cells)
    kept: list[tuple[str, int, int, Polygon, float]] = []
    for key, row, col, poly in candidates:
        inside = poly.intersection(land).area / poly.area
        if (keep == "centre" and land.contains(poly.centroid)) or (keep == "overlap" and inside > 0):
            kept.append((key, row, col, poly, inside))
    cells = [
        Cell(key, row, col, mapping(projection.back(poly)), mapping(projection.back(poly.centroid)),
             poly.area, round(inside, 6))
        for key, row, col, poly, inside in kept
    ]
    tree = STRtree([poly for _, _, _, poly, _ in kept])
    edges: list[Edge] = []
    for i, (key, _, _, poly, _) in enumerate(kept):
        for j in tree.query(poly):
            if j <= i:
                continue
            shared = poly.intersection(kept[j][3])
            # A shared side, not a touching corner -- and not through water:
            # the shared side must lie on land.
            if shared.length > 1e-6 and shared.intersection(land).length > 1e-6 * shared.length:
                a, b = sorted((key, kept[j][0]))
                edges.append(Edge(a, b, round(shared.length, 6)))
    return cells, sorted(edges, key=lambda e: (e.a, e.b)), len(candidates) - len(kept)


def sum_points(cells: list[Cell], points: list[tuple[float, float, dict[str, float]]], crs: int):
    polys = [to_shape(c.geometry) for c in cells]
    tree = STRtree(polys)
    sums: dict[str, dict[str, float]] = {}
    lost: dict[str, float] = {}
    for x, y, values in points:
        hit = next((int(i) for i in tree.query(Point(x, y)) if polys[int(i)].covers(Point(x, y))), None)
        for name, amount in values.items():
            if hit is None:
                lost[name] = lost.get(name, 0) + amount
            else:
                bucket = sums.setdefault(cells[hit].key, {})
                bucket[name] = bucket.get(name, 0) + amount
    return sums, lost
```

- [ ] **Step 5: Run the tests**

Run `tests/test_spatial_grid.py` — expected: PASS (8 tests). If the lake test keeps an edge, the land check in the edge loop is wrong — fix it, do not loosen the test.

- [ ] **Step 6: Commit**

```bash
git add backend/requirements.txt backend/app/spatial/project.py backend/app/spatial/grid.py backend/tests/test_spatial_grid.py
git commit -m "feat(spatial): square and hex grids over a boundary, in metres, with adjacency and point sums"
```

---

### Task 3: The grid generator endpoint

**Files:**
- Create: `backend/app/api/grids.py`, `backend/tests/test_grid_api.py`, `frontend/src/components/GridGeneratorForm.tsx`, `frontend/src/components/GridGeneratorForm.test.tsx`
- Modify: `backend/app/main.py` (router), `frontend/src/api/v1.ts` (`makeGrid`), `frontend/src/pages/EntityTypes.tsx` (form)

**Interfaces:**
- Consumes: `make_grid`, `sum_points`, `TooManyCells`, `OutOfRange` (Task 2); `validate_geometry` (Task 1).
- Produces: `POST /api/v1/domains/{domain_id}/grids` with body `GridRequest` and response `GridReport`:

```python
class GridRequest(BaseModel):
    boundary_entity_id: int | None = None
    boundary: dict | None = None          # GeoJSON, when no entity is named
    shape: Literal["square", "hex"]
    size_m: float = Field(gt=0)
    entity_type: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    keep: Literal["centre", "overlap"] = "centre"
    layers: list[dict] = []               # [{"lon":..,"lat":..,"<col>": number}, ...] or a GeoJSON FeatureCollection of Points
    replace: bool = False

class GridReport(BaseModel):
    entity_type_id: int
    relationship_type_id: int
    cells: int
    edges: int
    dropped: int
    layer_totals: dict[str, float]        # inside the grid, per column
    layer_outside: dict[str, float]       # outside every cell, per column
```

  Frontend: `makeGrid(domainId: Id, body: GridRequest) => Promise<GridReport>` and `useMakeGrid()`.

- [ ] **Step 1: Write the failing API tests**

```python
# backend/tests/test_grid_api.py
"""POST /domains/{id}/grids: one transaction, caps, and a replace that says what it replaces."""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from tests.test_spatial_grid import _square_boundary
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


def _domain(db, headers) -> int:
    return TestClient(app).post("/api/public/domain", json={"name": "grid-api"}, headers=headers).json()["id"]


def test_a_grid_is_cells_and_adjacency_in_the_domain(tenants, db):  # noqa: F811
    client = TestClient(app)
    domain = _domain(db, tenants["a"])
    body = {"boundary": _square_boundary(1000), "shape": "square", "size_m": 500, "entity_type": "cell",
            "layers": [{"lon": 3.001, "lat": 0.001, "population": 40}]}
    report = client.post(f"/api/v1/domains/{domain}/grids", json=body, headers=tenants["a"])
    assert report.status_code == 201, report.text
    r = report.json()
    assert (r["cells"], r["edges"], r["dropped"]) == (4, 4, 0)
    assert r["layer_totals"] == {"population": 40} and r["layer_outside"] == {}
    keys = db.execute(text("SELECT key FROM entity WHERE entity_type_id = :t ORDER BY key"), {"t": r["entity_type_id"]}).scalars().all()
    assert keys == ["c_r0_c0", "c_r0_c1", "c_r1_c0", "c_r1_c1"]
    attrs = db.execute(text("SELECT attrs FROM entity WHERE entity_type_id = :t AND key = 'c_r0_c0'"), {"t": r["entity_type_id"]}).scalar_one()
    assert attrs["geometry"]["type"] == "Polygon" and attrs["centroid"]["type"] == "Point"
    assert round(attrs["area_m2"]) == 250000 and attrs["population"] == 40


def test_regenerating_a_grid_in_use_is_refused_until_replace(tenants, db):  # noqa: F811
    """Review Focus 4."""
    client = TestClient(app)
    domain = _domain(db, tenants["a"])
    body = {"boundary": _square_boundary(1000), "shape": "square", "size_m": 500, "entity_type": "cell"}
    first = client.post(f"/api/v1/domains/{domain}/grids", json=body, headers=tenants["a"]).json()
    # A scenario whose frozen dataset uses the cells: create a problem, a version over `cell`, a scenario.
    # (Use the helpers tests/test_tenancy.py uses for its own scenario.)
    again = client.post(f"/api/v1/domains/{domain}/grids", json={**body, "size_m": 250}, headers=tenants["a"])
    assert again.status_code == 409
    assert again.json()["detail"]["cells"] == 4
    replaced = client.post(f"/api/v1/domains/{domain}/grids", json={**body, "size_m": 250, "replace": True}, headers=tenants["a"])
    assert replaced.status_code == 201 and replaced.json()["cells"] == 16
    assert replaced.json()["entity_type_id"] == first["entity_type_id"]


def test_caps_and_bad_input_are_named(tenants, db):  # noqa: F811
    client = TestClient(app)
    domain = _domain(db, tenants["a"])
    base = {"boundary": _square_boundary(10_000), "shape": "square", "entity_type": "cell"}
    too_many = client.post(f"/api/v1/domains/{domain}/grids", json={**base, "size_m": 50}, headers=tenants["a"])
    assert too_many.status_code == 422 and "40000 cells" in too_many.text
    open_ring = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1]]]}
    bad = client.post(f"/api/v1/domains/{domain}/grids", json={**base, "size_m": 500, "boundary": open_ring}, headers=tenants["a"])
    assert bad.status_code == 422 and "ring 0" in bad.text
    other = client.post(f"/api/v1/domains/{domain}/grids", json={**base, "size_m": 500}, headers=tenants["b"])
    assert other.status_code == 404
```

Fill the scenario creation in the second test with the exact helper calls `tests/test_tenancy.py` uses (problem, model version over sets `["cell"]`, scenario), then assert `again.json()["detail"]["scenarios"]` lists that scenario's id.

- [ ] **Step 2: Run to see them fail** — expected: 404 on the new route.

- [ ] **Step 3: Write the endpoint**

```python
# backend/app/api/grids.py
"""A grid over a boundary, written into the domain (spec §3).

One transaction: the cell entity type and its attributes (created if
missing), one entity per cell, the `adjacent` relationship type and one edge
per shared side. A grid whose cells a scenario already uses is replaced
only when asked, after saying what would go.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_capability
from app.core.db import get_db
from app.spatial.geometry import validate_geometry
from app.spatial.grid import TooManyCells, make_grid, sum_points
from app.spatial.project import OutOfRange

router = APIRouter(prefix="/api/v1", tags=["spatial"])

_ATTRS = [("geometry", "geometry"), ("centroid", "geometry"), ("area_m2", "number"),
          ("row", "integer"), ("col", "integer"), ("coverage", "number")]


class GridRequest(BaseModel):
    boundary_entity_id: int | None = None
    boundary: dict | None = None
    shape: Literal["square", "hex"]
    size_m: float = Field(gt=0)
    entity_type: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    keep: Literal["centre", "overlap"] = "centre"
    layers: list[dict] = []
    replace: bool = False


class GridReport(BaseModel):
    entity_type_id: int
    relationship_type_id: int
    cells: int
    edges: int
    dropped: int
    layer_totals: dict[str, float]
    layer_outside: dict[str, float]


def _points(layers: list[dict]) -> list[tuple[float, float, dict[str, float]]]:
    out = []
    for i, row in enumerate(layers):
        if row.get("type") == "Feature":
            x, y = row["geometry"]["coordinates"][:2]
            values = row.get("properties") or {}
        else:
            x, y, values = row.get("lon"), row.get("lat"), {k: v for k, v in row.items() if k not in ("lon", "lat")}
        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            raise HTTPException(422, f"layer row {i} has no numeric lon/lat")
        out.append((x, y, {k: float(v) for k, v in values.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}))
    return out


@router.post("/domains/{domain_id}/grids", status_code=201, response_model=GridReport)
def make_domain_grid(domain_id: int, body: GridRequest, db: Session = Depends(get_db),
                     _=Depends(require_capability("domain.edit"))) -> GridReport:
    if db.execute(text("SELECT 1 FROM domain WHERE id = :d"), {"d": domain_id}).first() is None:
        raise HTTPException(404, "domain not found")
    boundary = body.boundary
    if body.boundary_entity_id is not None:
        boundary = db.execute(text(
            "SELECT e.attrs -> ad.name FROM entity e JOIN attribute_def ad ON ad.entity_type_id = e.entity_type_id"
            " WHERE e.id = :e AND ad.data_type::text = 'geometry' ORDER BY ad.sort_order LIMIT 1"), {"e": body.boundary_entity_id}).scalar_one_or_none()
    if boundary is None:
        raise HTTPException(422, "name a boundary: an entity with a geometry, or GeoJSON in `boundary`")
    fault = validate_geometry(boundary)
    if fault or boundary.get("type") == "Point":
        raise HTTPException(422, f"boundary: {fault or 'a boundary is a polygon, not a point'}")
    crs = int(db.execute(text("SELECT coalesce((SELECT value FROM setting WHERE scope = 'domain' AND scope_id = :d AND key = 'spatial.crs'),"
                              " (SELECT default_value FROM setting_key WHERE key = 'spatial.crs'))"), {"d": domain_id}).scalar_one())
    try:
        cells, edges, dropped = make_grid(boundary, crs=crs, shape=body.shape, size_m=body.size_m, keep=body.keep)
    except (TooManyCells, OutOfRange) as exc:
        raise HTTPException(422, str(exc)) from exc
    sums, lost = sum_points(cells, _points(body.layers), crs)
    columns = sorted({name for values in sums.values() for name in values} | set(lost))

    type_id = db.execute(text("SELECT id FROM entity_type WHERE domain_id = :d AND name = :n"),
                         {"d": domain_id, "n": body.entity_type}).scalar_one_or_none()
    if type_id is not None:
        existing = db.execute(text("SELECT count(*) FROM entity WHERE entity_type_id = :t"), {"t": type_id}).scalar_one()
        if existing and not body.replace:
            scenarios = db.execute(text(
                "SELECT DISTINCT s.id FROM scenario s JOIN problem p ON p.id = s.problem_id WHERE p.domain_id = :d"
                " ORDER BY s.id"), {"d": domain_id}).scalars().all()
            raise HTTPException(409, {"message": f"{body.entity_type} already has {existing} cells; send replace: true to regenerate",
                                      "cells": existing, "scenarios": scenarios})
        db.execute(text("DELETE FROM entity WHERE entity_type_id = :t"), {"t": type_id})
    else:
        type_id = db.execute(text("INSERT INTO entity_type (domain_id, name, role) VALUES (:d, :n, 'other') RETURNING id"),
                             {"d": domain_id, "n": body.entity_type}).scalar_one()
    have = set(db.execute(text("SELECT name FROM attribute_def WHERE entity_type_id = :t"), {"t": type_id}).scalars())
    for name, kind in [*_ATTRS, *((c, "number") for c in columns)]:
        if name not in have:
            db.execute(text("INSERT INTO attribute_def (entity_type_id, name, data_type) VALUES (:t, :n, CAST(:k AS attr_type))"),
                       {"t": type_id, "n": name, "k": kind})
    ids: dict[str, int] = {}
    for n, cell in enumerate(cells):
        attrs = {"geometry": cell.geometry, "centroid": cell.centroid, "area_m2": cell.area_m2, "row": cell.row,
                 "col": cell.col, "coverage": cell.coverage, **{c: sums.get(cell.key, {}).get(c, 0) for c in columns}}
        ids[cell.key] = db.execute(text(
            "INSERT INTO entity (entity_type_id, key, label, sort_order, attrs) VALUES (:t, :k, :k, :s, CAST(:a AS jsonb)) RETURNING id"),
            {"t": type_id, "k": cell.key, "s": n, "a": _json(attrs)}).scalar_one()
    rel_id = db.execute(text("SELECT id FROM relationship_type WHERE domain_id = :d AND name = 'adjacent'"), {"d": domain_id}).scalar_one_or_none()
    if rel_id is None:
        rel_id = db.execute(text(
            "INSERT INTO relationship_type (domain_id, name, from_type_id, to_type_id, cardinality, is_hierarchy)"
            " VALUES (:d, 'adjacent', :t, :t, 'many_to_many', false) RETURNING id"), {"d": domain_id, "t": type_id}).scalar_one()
        db.execute(text("INSERT INTO attribute_def (relationship_type_id, name, data_type) VALUES (:r, 'shared_m', 'number')"), {"r": rel_id})
    for e in edges:
        db.execute(text("INSERT INTO relationship (relationship_type_id, from_entity_id, to_entity_id, attrs)"
                        " VALUES (:r, :a, :b, CAST(:x AS jsonb))"),
                   {"r": rel_id, "a": ids[e.a], "b": ids[e.b], "x": _json({"shared_m": e.shared_m})})
    db.commit()
    totals = {c: sum(v.get(c, 0) for v in sums.values()) for c in columns}
    return GridReport(entity_type_id=type_id, relationship_type_id=rel_id, cells=len(cells), edges=len(edges),
                      dropped=dropped, layer_totals=totals, layer_outside=lost)


def _json(value) -> str:
    import json

    return json.dumps(value)
```

Before running: open `backend/app/api/deps.py` and use the capability dependency's real name (the one `api/runs.py` uses for `run.submit`); open the `relationship_type.cardinality` enum (migration 0006) and use its exact value for many-to-many; check the delete of cells also removes their relationships (FK `ON DELETE CASCADE` on `relationship.from_entity_id` — if not cascading, delete the `adjacent` edges of those entities first). Register the router in `app/main.py` beside `run_events_router`.

- [ ] **Step 4: Run the tests** — expected: PASS.

- [ ] **Step 5: The form**

```tsx
// frontend/src/components/GridGeneratorForm.tsx
/** Make a grid over a boundary: shape, size, and a preview of how many cells before anything is written. */
import { useState } from "react";
import { formatApiError } from "../api/errors";
import { useMakeGrid, type GridReport } from "../api/v1";

export default function GridGeneratorForm({ domainId, boundaries }: {
  domainId: number;
  /** Entities with a geometry attribute, to draw the grid over. */
  boundaries: { id: number; label: string }[];
}) {
  const make = useMakeGrid();
  const [boundary, setBoundary] = useState<number | "">(boundaries[0]?.id ?? "");
  const [shape, setShape] = useState<"square" | "hex">("hex");
  const [size, setSize] = useState("500");
  const [name, setName] = useState("cell");
  const [report, setReport] = useState<GridReport | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [replace, setReplace] = useState<{ cells: number; scenarios: number[] } | null>(null);

  function submit(withReplace = false) {
    setFailure(null);
    make.mutate(
      { domainId, body: { boundary_entity_id: Number(boundary), shape, size_m: Number(size), entity_type: name, replace: withReplace } },
      {
        onSuccess: (r) => { setReport(r); setReplace(null); },
        onError: (error: unknown) => {
          const detail = (error as { detail?: { cells?: number; scenarios?: number[] } }).detail;
          if (detail?.cells !== undefined) setReplace({ cells: detail.cells, scenarios: detail.scenarios ?? [] });
          else setFailure(formatApiError(error));
        },
      }
    );
  }

  return (
    <form className="space-y-2 text-sm" onSubmit={(e) => { e.preventDefault(); submit(); }} aria-label="Make a grid">
      <label className="block">Boundary
        <select className="ml-2 rounded border px-2 py-1" value={boundary} onChange={(e) => setBoundary(Number(e.target.value))}>
          {boundaries.map((b) => <option key={b.id} value={b.id}>{b.label}</option>)}
        </select>
      </label>
      <label className="block">Cells
        <select className="ml-2 rounded border px-2 py-1" value={shape} onChange={(e) => setShape(e.target.value as "square" | "hex")}>
          <option value="hex">hexagons</option><option value="square">squares</option>
        </select>
      </label>
      <label className="block">Cell width (metres)
        <input className="ml-2 w-24 rounded border px-2 py-1" inputMode="decimal" value={size} onChange={(e) => setSize(e.target.value)} />
      </label>
      <label className="block">Entity type
        <input className="ml-2 w-32 rounded border px-2 py-1" value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      <button type="submit" className="rounded bg-blue-600 px-3 py-1 text-white" disabled={!boundary || make.isPending}>
        {make.isPending ? "Making the grid…" : "Make the grid"}
      </button>
      {replace && (
        <div role="alert" className="rounded bg-amber-50 p-2">
          {name} already has {replace.cells} cells{replace.scenarios.length ? `, used by scenarios ${replace.scenarios.join(", ")}` : ""}.
          Runs already made keep their frozen data.
          <button type="button" className="ml-2 underline" onClick={() => submit(true)}>Replace them</button>
        </div>
      )}
      {failure && <p role="alert" className="text-rose-700">{failure}</p>}
      {report && (
        <p role="status">
          Made {report.cells} cells and {report.edges} adjacencies ({report.dropped} dropped at the boundary).
          {Object.entries(report.layer_outside).map(([k, v]) => ` ${v} of ${k} fell outside the grid.`)}
        </p>
      )}
    </form>
  );
}
```

Add `GridRequest`, `GridReport`, `makeGrid` and `useMakeGrid` to `frontend/src/api/v1.ts` following `createRun`/`useCreateRun`, and place the form on `EntityTypes.tsx` in a "Make a grid" disclosure shown when the domain has any geometry attribute. Test (`GridGeneratorForm.test.tsx`, with the page tests' mocked `apiFetch`): submitting posts `{"shape":"hex","size_m":500,...}`; a 409 body with `cells: 4, scenarios: [7]` shows "cell already has 4 cells, used by scenarios 7" and "Replace them" posts `replace: true`; a 201 shows "Made 16 cells".

- [ ] **Step 6: Full check and commit**

```bash
git add backend/app/api/grids.py backend/app/main.py backend/tests/test_grid_api.py frontend/src/api/v1.ts frontend/src/components/GridGeneratorForm.tsx frontend/src/components/GridGeneratorForm.test.tsx frontend/src/pages/EntityTypes.tsx
git commit -m "feat(spatial): make a grid over a boundary -- cells, adjacency and layer sums in one transaction"
```

---

### Task 4: The `connected` rule in the contract

**Files:**
- Modify: `backend/app/ir/contract.json` (rules), `backend/app/ir/contract.py:83-95` (`CONSTRAINT_KEYS`, new `CONNECTED_KEYS`), `backend/app/ir/validate.py` (`check_constraints` dispatch + `_check_connected`), `backend/app/ir/models.py` (Pydantic `Connected`), `backend/tests/ir_fixtures.json`, `backend/tests/test_ir_models.py` (STRUCTURAL/SEMANTIC), `frontend/src/ir/contract.ts`, `frontend/src/ir/validate.ts`, `docs/contracts/problem-ir.md` (§4.4)

**Interfaces:**
- Produces: constraint kind `connected` with body keys exactly `assign`, `units`, `groups`, `via`, and optional `empty`; contract rule codes `connected_needs_version_2`, `connected_malformed`, `connected_not_binary`, `connected_index_mismatch`, `connected_via_invalid`, `connected_on_soft`; Python `CONNECTED_KEYS = frozenset({"assign", "units", "groups", "via", "empty"})`.

- [ ] **Step 1: Add the fixtures** (they are the failing tests; both validators read them)

Append to `valid` in `backend/tests/ir_fixtures.json`:

```json
{
  "name": "districts_connected",
  "why": "A connected rule (version 2): each district's cells form one piece over `adjacent`.",
  "ir": {
    "version": 2,
    "sets": ["cell", "district"],
    "relationships": ["adjacent"],
    "parameters": {},
    "variables": {"assign": {"index": ["cell", "district"], "domain": "binary"}},
    "constraints": [
      {"id": "c_one_each", "forall": [{"index": "u", "set": "cell"}],
       "left": {"sum": {"var": "assign", "index": ["u", "z"]}, "over": [{"index": "z", "set": "district"}]},
       "relation": "=", "right": {"const": 1}, "severity": "hard"},
      {"id": "c_connected", "severity": "hard",
       "connected": {"assign": {"var": "assign", "index": ["u", "z"]}, "units": {"index": "u", "set": "cell"},
                     "groups": {"index": "z", "set": "district"}, "via": "adjacent"}}
    ],
    "objective": {"sense": "minimize", "terms": [{"id": "o_none", "weight": 1, "expression": {"const": 0}}]}
  }
}
```

and one invalid fixture per code, each a copy of that IR with one change: `version: 1` (`connected_needs_version_2`, loc `["constraints", 1]`); a body missing `via` (`connected_malformed`, loc `["constraints", 1, "connected"]`); the variable declared `"domain": "integer"` (`connected_not_binary`, loc `["constraints", 1, "connected", "assign", "var"]`); `"index": ["z", "u"]` in `assign` (`connected_index_mismatch`, loc `[..., "assign", "index"]`); `"via": "nope"` (`connected_via_invalid`, loc `[..., "via"]`); `"severity": "soft", "weight": 5` (`connected_on_soft`, loc `["constraints", 1, "severity"]`). Add the six codes to `contract.json` `rules` (`"where": "shape"`) with texts:

- `connected_needs_version_2` — "a `connected` rule appears only in a version 2 document"
- `connected_malformed` — "a `connected` names `assign`, `units`, `groups` and `via`, and optionally `empty` (`forbidden` or `allowed`)"
- `connected_not_binary` — "a `connected` rule's variable is declared binary"
- `connected_index_mismatch` — "a `connected` rule's variable is indexed by its units' index, then its groups' index"
- `connected_via_invalid` — "a `connected` rule's `via` is a declared relationship"
- `connected_on_soft` — "a `connected` rule is hard and unconditional"

Mirror the six in `frontend/src/ir/contract.ts` (`IR_RULES`) and add `"connected"` to its `CONSTRAINT_KEYS`. In `backend/tests/test_ir_models.py`, put `connected_malformed` in `STRUCTURAL` and the other five in `SEMANTIC`.

- [ ] **Step 2: Run the IR tests to see them fail** — `tests/test_ir_models.py tests/test_ir_contract.py tests/test_ir_validate.py` and `npx vitest run src/ir`: expected failures naming the new fixtures.

- [ ] **Step 3: Write the Python check** (in `validate.py`, dispatched from `check_constraints` before the scheduling check: `if "connected" in constraint: problem = self._check_connected(constraint, at, identifier)`)

```python
    def _check_connected(self, constraint: dict[str, Any], at: Loc, identifier: str):
        """`connected`: for every group, the units assigned to it are one piece over `via` (spec §4)."""
        if self.ir.get("version") == 1:
            return Refusal("connected_needs_version_2", at,
                           f"the constraint {identifier!r} is a connected rule, which version 1 does not have; publish it as version 2")
        body = constraint["connected"]
        loc: Loc = [*at, "connected"]
        required = {"assign", "units", "groups", "via"}
        if (not isinstance(body, dict) or not required <= set(body) or set(body) - CONNECTED_KEYS
                or body.get("empty", "forbidden") not in ("forbidden", "allowed")
                or any(k in constraint for k in ("left", "relation", "right", "forall"))):
            return Refusal("connected_malformed", loc,
                           "a connected rule names assign, units, groups and via, and optionally empty (forbidden or allowed)")
        if constraint.get("severity") != "hard" or "weight" in constraint or "when" in constraint:
            key = "when" if "when" in constraint else "severity"
            return Refusal("connected_on_soft", [*at, key],
                           f"the connected rule {identifier!r} is hard and unconditional")
        scope = {}
        for part in ("units", "groups"):
            binding = body[part]
            inner = self.check_bindings([binding], [*loc, part], scope)
            if isinstance(inner, Refusal):
                return inner
            scope = inner
        assign = body["assign"]
        problem = self._reference(assign, [*loc, "assign"], scope, "var", self.variables)
        if problem:
            return problem
        if self.ir["variables"][assign["var"]].get("domain") != "binary":
            return Refusal("connected_not_binary", [*loc, "assign", "var"],
                           f"{assign['var']!r} must be binary: a unit is in a group or not")
        if assign["index"] != [body["units"]["index"], body["groups"]["index"]]:
            return Refusal("connected_index_mismatch", [*loc, "assign", "index"],
                           f"{assign['var']!r} is indexed by the units' index then the groups' index: "
                           f"[{body['units']['index']}, {body['groups']['index']}]")
        if body["via"] not in (self.ir.get("relationships") or []):
            return Refusal("connected_via_invalid", [*loc, "via"],
                           f"{json.dumps(body['via'])} is not a relationship this model declares")
        return None
```

`check_bindings` and `_reference` are the validator's own helpers (used by `_check_scheduling`); reuse them as they are. The domain check (`via` joins the units' type to itself) goes in the domain-aware pass that already checks `binding_via_rel_not_declared`: add, in that pass, `connected_via_invalid` when the relationship type's `from_type` and `to_type` are not both the units set's entity type.

- [ ] **Step 4: The TypeScript check** — `termConnected` in `frontend/src/ir/validate.ts`, the same checks in the same order with the same messages, dispatched at the same point as in Python.

- [ ] **Step 5: Pydantic** — in `backend/app/ir/models.py`:

```python
class ConnectedBody(_Model):
    assign: VarRef
    units: Binding
    groups: Binding
    via: Name
    empty: Literal["forbidden", "allowed"] = "forbidden"
```

and `connected: Optional[ConnectedBody] = None` on `Constraint` (with `left`/`relation`/`right` already optional for scheduling rules); add `ConnectedBody` to the `model_rebuild` loop.

- [ ] **Step 6: Document it** — `docs/contracts/problem-ir.md` gets §4.4 "`connected` (version 2)": the JSON above, the meaning sentence from the spec §4, and the six refusals.

- [ ] **Step 7: Run, full check, commit**

Expected: IR tests PASS in both languages, parity green.

```bash
git add backend/app/ir backend/tests/ir_fixtures.json backend/tests/test_ir_models.py frontend/src/ir docs/contracts/problem-ir.md
git commit -m "feat(ir): a connected rule -- each group's units one piece over a relationship (contract, both validators)"
```

---

### Task 5: `connected` compiled to an exact flow

**Files:**
- Create: `backend/app/solve/connected.py`, `backend/tests/test_connected.py`
- Modify: `backend/app/solve/compile.py:569` (dispatch), `backend/app/solve/compile.py` (`Compiled.connectivity: list[str]`), `backend/app/solve/classify.py` (`needs.add("connected")`), `backend/app/solve/backends.py` (`"connected"` in `provides` of cp-sat, highs, milp, scip), `backend/app/solve/fingerprint.py` (`rows_connectivity`, `VERSION = 2`)

**Interfaces:**
- Consumes: the validated rule shape (Task 4); `Compiled`, `Constraint`, `Linear`, `Variable` from `app.solve.compile`; the dataset's `relationships[via]` edges `[{"from": key, "to": key}]`.
- Produces: `app.solve.connected.expand(compiler, spec) -> None` appending rows and variables to the compiler; auxiliary variable names `__root` (binary) and `__flow` (continuous, `[0, n-1]`); every row's constraint id is the rule's id.

- [ ] **Step 1: Write the failing tests** — brute force over every partition of a 3×3 grid (Review Focus 3 included)

```python
# backend/tests/test_connected.py
"""`connected`, exact: checked against every partition of small grids on every backend."""
from __future__ import annotations

import itertools
import random

import pytest

from app.solve import compile_model
from app.solve.backends import by_name
from app.solve.service import solve_compiled


def _grid(rows: int, cols: int, cut: set[tuple[str, str]] = frozenset()):
    keys = [f"c{r}{c}" for r in range(rows) for c in range(cols)]
    edges = []
    for r in range(rows):
        for c in range(cols):
            for dr, dc in ((0, 1), (1, 0)):
                if r + dr < rows and c + dc < cols:
                    pair = (f"c{r}{c}", f"c{r + dr}{c + dc}")
                    if pair not in cut:
                        edges.append({"from": pair[0], "to": pair[1]})
    return keys, edges


def _model(keys, edges, groups: int, weights: dict[tuple[str, int], int], empty="forbidden"):
    ir = {
        "version": 2, "sets": ["cell", "zone"], "relationships": ["adjacent"], "parameters": {"w": {"index": ["cell", "zone"]}},
        "variables": {"assign": {"index": ["cell", "zone"], "domain": "binary"}},
        "constraints": [
            {"id": "c_one_each", "forall": [{"index": "u", "set": "cell"}],
             "left": {"sum": {"var": "assign", "index": ["u", "z"]}, "over": [{"index": "z", "set": "zone"}]},
             "relation": "=", "right": {"const": 1}, "severity": "hard"},
            {"id": "c_connected", "severity": "hard",
             "connected": {"assign": {"var": "assign", "index": ["u", "z"]}, "units": {"index": "u", "set": "cell"},
                           "groups": {"index": "z", "set": "zone"}, "via": "adjacent", "empty": empty}},
        ],
        "objective": {"sense": "maximize", "terms": [{"id": "o", "weight": 1, "expression": {
            "sum": {"mul": [{"par": "w", "index": ["u", "z"]}, {"var": "assign", "index": ["u", "z"]}]},
            "over": [{"index": "u", "set": "cell"}, {"index": "z", "set": "zone"}]}}]},
    }
    data = {
        "sets": {"cell": [{"id": k} for k in keys], "zone": [{"id": f"z{g}"} for g in range(groups)]},
        "parameters": {"w": [{"cell": k, "zone": f"z{g}", "value": weights[(k, g)]} for k in keys for g in range(groups)]},
        "parameter_defaults": {}, "relationships": {"adjacent": edges},
    }
    return ir, data


def _connected(members: list[str], edges) -> bool:
    if not members:
        return True
    adj = {m: set() for m in members}
    for e in edges:
        if e["from"] in adj and e["to"] in adj:
            adj[e["from"]].add(e["to"]); adj[e["to"]].add(e["from"])
    seen, stack = {members[0]}, [members[0]]
    while stack:
        for n in adj[stack.pop()] - seen:
            seen.add(n); stack.append(n)
    return len(seen) == len(members)


def _brute(keys, edges, groups, weights, empty):
    best = None
    for labels in itertools.product(range(groups), repeat=len(keys)):
        parts = [[k for k, l in zip(keys, labels) if l == g] for g in range(groups)]
        if empty == "forbidden" and any(not p for p in parts):
            continue
        if all(_connected(p, edges) for p in parts):
            value = sum(weights[(k, l)] for k, l in zip(keys, labels))
            best = value if best is None else max(best, value)
    return best


@pytest.mark.parametrize("seed", range(12))
@pytest.mark.parametrize("backend", ["cp-sat", "highs", "milp", "scip"])
def test_the_flow_agrees_with_every_partition(seed, backend):
    rnd = random.Random(seed)
    keys, edges = _grid(3, 3)
    groups = rnd.choice([2, 3])
    empty = rnd.choice(["forbidden", "allowed"])
    # Weights that reward scattering, so a model without contiguity would split zones.
    weights = {(k, g): rnd.randint(-5, 9) for k in keys for g in range(groups)}
    ir, data = _model(keys, edges, groups, weights, empty)
    result, _ = solve_compiled(by_name(backend), compile_model(ir, data), time_limit=30, seed=1)
    expected = _brute(keys, edges, groups, weights, empty)
    assert result.status == "optimal", (seed, result.status)
    assert round(float(result.objective)) == expected, (seed, result.objective, expected)
    chosen = [tuple(i) for i in result.chosen("assign")]
    for g in range(groups):
        assert _connected([u for u, z in chosen if z == f"z{g}"], edges), (seed, g)


def test_a_zone_that_cannot_be_connected_is_infeasible_and_names_the_rule():
    """Review Focus 3: the grid is two islands; with 1 zone, it cannot be one piece."""
    keys, edges = _grid(1, 4, cut={("c01", "c02")})
    ir, data = _model(keys, edges, 1, {(k, 0): 1 for k in keys})
    result, _ = solve_compiled(by_name("cp-sat"), compile_model(ir, data), time_limit=10, seed=1)
    assert result.status == "infeasible"
    # And the explanation (app.solve.diagnose) names c_connected among the conflicting rules --
    # assert through the run path in test_run_map.py's run fixture, where conflicts are recorded.


def test_the_rows_are_counted_as_connectivity():
    from app.solve.fingerprint import fingerprint

    keys, edges = _grid(2, 2)
    ir, data = _model(keys, edges, 2, {(k, g): 1 for k in keys for g in range(2)})
    fp = fingerprint(compile_model(ir, data))
    assert fp["version"] == 2 and fp["rows_connectivity"] > 0
```

- [ ] **Step 2: Run to see them fail** — expected: `Unsupported: unknown constraint kind` / the compiler raising on `connected`.

- [ ] **Step 3: Write the expansion**

```python
# backend/app/solve/connected.py
"""`connected`, compiled: an exact single-commodity flow per group (spec §4).

For group z: one root among its units; flow runs only between two units of
the group, along `via` edges in either direction; every assigned unit that
is not the root takes in one unit more than it sends on. A group is
connected exactly when this flow exists -- every unit is reached from the
root -- so the rows are exact, linear, and taken by every backend.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

ROOT, FLOW = "__root", "__flow"


def expand(compiler: Any, spec: dict[str, Any]) -> None:
    from app.solve.compile import Constraint, Linear, Unsupported, Variable

    body = spec["connected"]
    rule = spec["id"]
    var = body["assign"]["var"]
    units = [row["id"] for row in compiler.sets.get(body["units"]["set"], [])]
    groups = [row["id"] for row in compiler.sets.get(body["groups"]["set"], [])]
    allowed = body.get("empty", "forbidden") == "allowed"
    known = set(units)
    pairs = sorted({tuple(sorted((e["from"], e["to"]))) for e in compiler.edges.get(body["via"], [])
                    if e["from"] in known and e["to"] in known and e["from"] != e["to"]})
    arcs = [*pairs, *((b, a) for a, b in pairs)]
    n = Decimal(len(units))
    one = Decimal(1)
    for z in groups:
        x = {u: (var, (u, z)) for u in units}
        missing = [k for k in x.values() if k not in compiler.variables]
        if missing:  # pragma: no cover -- the validator pins the index
            raise Unsupported(f"{rule}: no variable {missing[0]}")
        root = {u: (ROOT, (rule, u, z)) for u in units}
        for key in root.values():
            compiler.variables[key] = Variable(key, "binary", Decimal(0), one)
        flow = {(a, b): (FLOW, (rule, a, b, z)) for a, b in arcs}
        for key in flow.values():
            compiler.variables[key] = Variable(key, "continuous", Decimal(0), n - one)
        index = {body["groups"]["index"]: z}

        def row(left: Linear, relation: str, right: Linear) -> None:
            compiler.constraints.append(Constraint(rule, dict(index), left, relation, right))

        roots = Linear(coeffs={k: one for k in root.values()})
        row(roots, "<=" if allowed else "=", Linear(const=one))
        for u in units:
            row(Linear(coeffs={root[u]: one, x[u]: -one}), "<=", Linear())
            if allowed:
                # A group with any unit has a root.
                row(Linear(coeffs={x[u]: one}).add(roots, factor=-1), "<=", Linear())
        for (a, b), f in flow.items():
            row(Linear(coeffs={f: one, x[a]: -(n - one)}), "<=", Linear())
            row(Linear(coeffs={f: one, x[b]: -(n - one)}), "<=", Linear())
        for u in units:
            balance = Linear()
            for (a, b), f in flow.items():
                if b == u:
                    balance.add(Linear(coeffs={f: one}))
                if a == u:
                    balance.add(Linear(coeffs={f: -one}))
            # inflow - outflow >= x[u] - n * root[u]
            balance.add(Linear(coeffs={x[u]: -one, root[u]: n}))
            row(balance, ">=", Linear())
    compiler.connectivity.append(rule)
```

In `compile.py`: at `_expand_constraint`, before the scheduling dispatch, add

```python
        if "connected" in spec:
            from app.solve.connected import expand

            expand(self, spec)
            return
```

add `self.connectivity: list[str] = []` to `_Compiler.__init__`, `connectivity: list[str] = field(default_factory=list)` to `Compiled`, and `connectivity=self.connectivity` in `run()`. In `classify.py` add, after the scheduling block: `if any(isinstance(c, dict) and "connected" in c for c in ir.get("constraints", [])): needs.add("connected"); reasons.append("a rule keeps each group's units in one connected piece, which a solver holds as a flow over their adjacency"); planner.append("some groups must be one connected piece")`. Add `"connected"` to the `provides` of CP_SAT, HIGHS, MILP and SCIP in `backends.py`. In `fingerprint.py` bump `VERSION = 2`, classify a row as `"connectivity"` when `c.id in compiled.connectivity` (first line of `row_type`), and add `"connectivity"` to the list of reported row kinds; update `tests/test_fingerprint.py`'s version assertion to 2.

- [ ] **Step 4: Run** — `tests/test_connected.py tests/test_fingerprint.py tests/test_blocks.py` — expected: PASS. If a backend disagrees with brute force, print the seed's partition and the solver's; the rows, not the test, are wrong.

- [ ] **Step 5: Full check and commit**

```bash
git add backend/app/solve/connected.py backend/app/solve/compile.py backend/app/solve/classify.py backend/app/solve/backends.py backend/app/solve/fingerprint.py backend/tests/test_connected.py backend/tests/test_fingerprint.py
git commit -m "feat(solve): connected compiled to an exact single-commodity flow -- every partition of 3x3 grids checked on four backends"
```

---

### Task 6: The `connected` rule in the editor

**Files:**
- Create: `frontend/src/model/ConnectedEditor.tsx`, `frontend/src/model/ConnectedEditor.test.tsx`
- Modify: `frontend/src/model/terms.ts` (`describeConnected`), the model editor's rule list (where `SchedulingEditor` is chosen for `no_overlap`), `frontend/src/lib/modelBlocks.ts` (a read-only block)

**Interfaces:**
- Consumes: `ModelContext` (`variables`, `sets`, `relationships`) from `frontend/src/model/terms.ts`.
- Produces: `describeConnected(rule): string | null` → `"each zone is one connected piece of its cell over adjacent"`; `<ConnectedEditor value onChange context />`.

- [ ] **Step 1: Failing test**

```tsx
// frontend/src/model/ConnectedEditor.test.tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import ConnectedEditor from "./ConnectedEditor";
import { describeConnected } from "./terms";

const CONTEXT = {
  sets: ["cell", "zone", "employee"], setIds: {}, attributes: {},
  variables: { assign: { index: ["cell", "zone"], domain: "binary" }, hours: { index: ["employee"], domain: "integer" } },
  parameters: {},
  relationships: [{ name: "adjacent", from: "cell", to: "cell" }, { name: "works_in", from: "employee", to: "zone" }],
};

function Harness() {
  const [rule, setRule] = useState<Record<string, unknown>>({ id: "c_connected", severity: "hard", connected: {} });
  return (<><ConnectedEditor value={rule} onChange={setRule} context={CONTEXT} /><output data-testid="rule">{JSON.stringify(rule)}</output></>);
}

describe("ConnectedEditor", () => {
  it("offers only binary variables over two sets, and self-relationships of the units' set", () => {
    render(<Harness />);
    const variable = screen.getByLabelText("Assignment") as HTMLSelectElement;
    expect([...variable.options].map((o) => o.value)).toEqual(["assign"]);
    fireEvent.change(variable, { target: { value: "assign" } });
    const via = screen.getByLabelText("Connected over") as HTMLSelectElement;
    expect([...via.options].map((o) => o.value)).toEqual(["adjacent"]);
    fireEvent.change(via, { target: { value: "adjacent" } });
    expect(JSON.parse(screen.getByTestId("rule").textContent!).connected).toEqual({
      assign: { var: "assign", index: ["u", "z"] }, units: { index: "u", set: "cell" },
      groups: { index: "z", set: "zone" }, via: "adjacent", empty: "forbidden",
    });
  });

  it("reads back in words", () => {
    expect(describeConnected({ connected: { units: { set: "cell" }, groups: { set: "zone" }, via: "adjacent" } }))
      .toBe("each zone is one connected piece of cell over adjacent");
  });
});
```

- [ ] **Step 2: Run to see it fail.**

- [ ] **Step 3: Implement**

```tsx
// frontend/src/model/ConnectedEditor.tsx
/** A `connected` rule: pick the assignment, the relationship; indices are named for the reader. */
import type { ModelContext } from "./terms";

type Rule = Record<string, unknown>;

export default function ConnectedEditor({ value, onChange, context }: { value: Rule; onChange: (r: Rule) => void; context: ModelContext }) {
  const body = (value.connected ?? {}) as { assign?: { var?: string }; via?: string; empty?: string };
  const candidates = Object.entries(context.variables).filter(([, v]) => v.domain === "binary" && v.index.length === 2);
  const chosen = candidates.find(([name]) => name === body.assign?.var) ?? candidates[0];
  const [unitSet, groupSet] = chosen ? chosen[1].index : ["", ""];
  const vias = context.relationships.filter((r) => r.from === unitSet && r.to === unitSet);
  const set = (next: { var?: string; via?: string; empty?: string }) => {
    const name = next.var ?? chosen?.[0] ?? "";
    const [units, groups] = context.variables[name]?.index ?? ["", ""];
    onChange({
      ...value,
      connected: {
        assign: { var: name, index: ["u", "z"] }, units: { index: "u", set: units }, groups: { index: "z", set: groups },
        via: next.via ?? body.via ?? vias[0]?.name ?? "", empty: next.empty ?? body.empty ?? "forbidden",
      },
    });
  };
  return (
    <div className="space-y-2 text-sm">
      <label className="block">Assignment
        <select className="ml-2 rounded border px-2 py-1" value={chosen?.[0] ?? ""} onChange={(e) => set({ var: e.target.value })}>
          {candidates.map(([name, v]) => <option key={name} value={name}>{name} ({v.index.join(" × ")})</option>)}
        </select>
      </label>
      <label className="block">Connected over
        <select className="ml-2 rounded border px-2 py-1" value={body.via ?? ""} onChange={(e) => set({ via: e.target.value })}>
          {vias.length === 0 && <option value="">no relationship joins {unitSet || "the units"} to itself</option>}
          {vias.map((r) => <option key={r.name} value={r.name}>{r.name}</option>)}
        </select>
      </label>
      <label className="block">
        <input type="checkbox" checked={body.empty === "allowed"} onChange={(e) => set({ empty: e.target.checked ? "allowed" : "forbidden" })} />{" "}
        A {groupSet || "group"} may be left empty
      </label>
    </div>
  );
}
```

In `terms.ts`:

```ts
export function describeConnected(rule: { connected?: unknown }): string | null {
  const c = rule.connected as { units?: { set?: string }; groups?: { set?: string }; via?: string } | undefined;
  if (!c) return null;
  return `each ${c.groups?.set ?? "group"} is one connected piece of ${c.units?.set ?? "units"} over ${c.via ?? "?"}`;
}
```

Wire it where the rule list picks `SchedulingEditor` (search `schedulingKind(` in `frontend/src/model`): a rule with `connected` renders `ConnectedEditor` and its summary line uses `describeConnected`; the "add a rule" menu gains "a connected rule". In `modelBlocks.ts`, a `connected` rule is a read-only block labelled with `describeConnected`.

- [ ] **Step 4: Run** `npx vitest run src/model src/lib` — PASS. **Step 5:** full check, commit (`feat(model): the connected rule in the editor`).

---

### Task 7: The map — GeoJSON of a run, the `spatial-map` component, export

**Files:**
- Create: `backend/app/api/run_map.py`, `backend/tests/test_run_map.py`, `frontend/src/genui/components/SpatialMap.tsx`, `frontend/src/genui/components/SpatialMap.test.tsx`
- Modify: `backend/app/genui/protocol.json` (`"spatial-map"`), `backend/app/genui/translate.py` (emit at settle when spatial), `backend/app/api/genui.py` (tell the translator the run is spatial), `backend/app/main.py`, `frontend/src/genui/protocol/types.ts`, `frontend/src/genui/registry/componentRegistry.ts`, `frontend/src/pages/Runs.tsx` (map + export in `RunDetail`), `frontend/src/api/v1.ts` (`getRunMap`)

**Interfaces:**
- Consumes: the run's frozen dataset (units' `geometry` attributes), its model version IR (`connected` rules), its solution assignments (`solution.assignments[var]` = list of index tuples).
- Produces: `GET /api/v1/runs/{id}/map` → GeoJSON `FeatureCollection`, one Feature per unit with `properties: {key, group, subgroup, <numeric attrs>}`; `?dissolve=true` → one Feature per group (and per subgroup) with `properties: {group, subgroup, cells, <numeric attr totals>}`; `404` with `"this run has no connected rule over units with a geometry"` when not spatial. Translator: `Translator(..., spatial: bool)`; at `settle`, when spatial and the run has an answer, `component.created` of type `spatial-map` with `data: {"source": "run", "runId": <id>}` then `component.completed`.

- [ ] **Step 1: Failing backend tests**

```python
# backend/tests/test_run_map.py
"""A spatial run's partition as GeoJSON, per cell and dissolved by zone."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


def test_a_partition_comes_back_per_cell_and_per_zone(tenants, db):  # noqa: F811
    """Make a 2x2 grid (POST /grids), publish the districts model of ir_fixtures `districts_connected`
    with two districts and population balance, solve it, then read the map."""
    client = TestClient(app)
    run_id = _solved_grid_run(client, tenants["a"])  # helper below, built from the Task 3 and fixture pieces
    cells = client.get(f"/api/v1/runs/{run_id}/map", headers=tenants["a"]).json()
    assert cells["type"] == "FeatureCollection" and len(cells["features"]) == 4
    groups = {f["properties"]["group"] for f in cells["features"]}
    assert groups == {"d0", "d1"}
    zones = client.get(f"/api/v1/runs/{run_id}/map?dissolve=true", headers=tenants["a"]).json()
    assert len(zones["features"]) == 2
    assert sorted(f["properties"]["cells"] for f in zones["features"]) == [2, 2]
    assert all(f["geometry"]["type"] in ("Polygon", "MultiPolygon") for f in zones["features"])


def test_a_run_without_a_map_says_so(tenants, db):  # noqa: F811
    from tests.test_run_events import _knapsack, _run

    run_id = _run(db, _knapsack(10), "no-map")
    missing = TestClient(app).get(f"/api/v1/runs/{run_id}/map", headers=tenants["a"])
    assert missing.status_code == 404 and "no connected rule" in missing.text
```

Write `_solved_grid_run(client, headers) -> int` in the same file: create a domain, `POST /grids` with the 1,000 m square (4 cells) and a population layer of one point per cell (population 10 each), create entity type `district` with entities `d0`, `d1`, publish the `districts_connected` IR plus a rule `c_balance` (`forall z: sum(population[u] * assign[u,z]) <= 20`), create a scenario, `POST /scenarios/{id}/runs`, and call `work_once(db)` until the run settles (as `tests/test_run_events.py::_run` does).

- [ ] **Step 2: Run to see them fail.**

- [ ] **Step 3: Write the endpoint**

```python
# backend/app/api/run_map.py
"""A spatial run's answer on a map (spec §6): GeoJSON from the run's own records."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from shapely.geometry import mapping, shape
from shapely.ops import unary_union
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models.v1_problem import Run

router = APIRouter(prefix="/api/v1", tags=["spatial"])
NOT_SPATIAL = "this run has no connected rule over units with a geometry"


@router.get("/runs/{run_id}/map")
def run_map(run_id: int, dissolve: bool = Query(default=False), db: Session = Depends(get_db),
            _=Depends(get_current_user)) -> dict[str, Any]:
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    ir, data, assignments = db.execute(text(
        "SELECT mv.ir, d.data, sol.assignments FROM run r JOIN scenario s ON s.id = r.scenario_id"
        " JOIN model_version mv ON mv.id = s.model_version_id JOIN dataset d ON d.id = r.dataset_id"
        " LEFT JOIN solution sol ON sol.run_id = r.id WHERE r.id = :r"), {"r": run_id}).one()
    rules = [c["connected"] for c in ir.get("constraints", []) if isinstance(c, dict) and "connected" in c]
    if not rules or not assignments:
        raise HTTPException(404, NOT_SPATIAL)
    top, sub = rules[0], (rules[1] if len(rules) > 1 else None)
    rows = {row["id"]: row for row in data["sets"].get(top["units"]["set"], [])}
    geometry_attr = next((k for row in rows.values() for k, v in row.items()
                          if isinstance(v, dict) and v.get("type") in ("Polygon", "MultiPolygon") and k != "centroid"), None)
    if geometry_attr is None:
        raise HTTPException(404, NOT_SPATIAL)
    group = {u: z for u, z in assignments.get(top["assign"]["var"], [])}
    subgroup = {u: s for u, s in assignments.get(sub["assign"]["var"], [])} if sub else {}
    numeric = lambda row: {k: v for k, v in row.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}  # noqa: E731
    features = [{"type": "Feature", "geometry": row[geometry_attr],
                 "properties": {"key": u, "group": group.get(u), "subgroup": subgroup.get(u), **numeric(row)}}
                for u, row in rows.items()]
    if not dissolve:
        return {"type": "FeatureCollection", "features": features}
    by: dict[tuple, list[dict]] = {}
    for f in features:
        by.setdefault((f["properties"]["group"], f["properties"]["subgroup"]), []).append(f)
    out = []
    for (g, s), members in sorted(by.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1]))):
        totals: dict[str, float] = {}
        for m in members:
            for k, v in m["properties"].items():
                if isinstance(v, (int, float)) and not isinstance(v, bool) and k not in ("row", "col", "coverage"):
                    totals[k] = totals.get(k, 0) + v
        out.append({"type": "Feature", "geometry": mapping(unary_union([shape(m["geometry"]) for m in members])),
                    "properties": {"group": g, "subgroup": s, "cells": len(members), **totals}})
    return {"type": "FeatureCollection", "features": out}
```

Register the router in `app/main.py`. Check the real shape of `solution.assignments` for a two-index variable (`[["c_r0_c0", "d0"], ...]` — `result.chosen("assign")`) and adjust the unpacking if it is keyed differently.

- [ ] **Step 4: GenUI** — add `"spatial-map"` to `componentTypes` in `backend/app/genui/protocol.json` and `COMPONENT_TYPES` in `frontend/src/genui/protocol/types.ts` (parity test enforces both). `Translator.__init__` takes `spatial: bool = False`; in `settle`, after the summary and when `spatial and status in _ENDED_WELL`: `out += self._create("map", "spatial-map", state="hydrated", props={"title": "The partition", "runId": self.run_id}, data={"source": "run", "runId": self.run_id}); out += self._complete("map")`. In `app/api/genui.py` set `spatial` from the run's model version IR: `any("connected" in c for c in ir["constraints"] if isinstance(c, dict))`. Add a translator test in `tests/test_genui.py` asserting the `spatial-map` component appears only when `spatial=True` and the run ended well.

- [ ] **Step 5: The component**

```tsx
// frontend/src/genui/components/SpatialMap.tsx
/** A run's partition: cells coloured by group, sub-group borders thinner, a totals table beside.
 * SVG up to 5,000 cells; a canvas beyond, where SVG would be thousands of nodes. */
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { getRunMap } from "../../api/v1";
import { Card, SkeletonCard, formatNumber, type GenUIProps } from "./shared";

// Twelve categorical colours checked for contrast against white and slate-900.
export const ZONE_COLOURS = ["#2563eb", "#d97706", "#059669", "#db2777", "#7c3aed", "#0891b2",
  "#65a30d", "#dc2626", "#4f46e5", "#ca8a04", "#0d9488", "#9333ea"];
const SVG_LIMIT = 5000;

type Feature = { geometry: { type: string; coordinates: unknown }; properties: Record<string, unknown> };

function project(features: Feature[], width: number, height: number) {
  const rings = features.flatMap((f) => (f.geometry.type === "Polygon" ? [f.geometry.coordinates as number[][][]]
    : (f.geometry.coordinates as number[][][][])));
  const pts = rings.flat(2) as unknown as number[][];
  const xs = pts.map((p) => p[0]); const ys = pts.map((p) => p[1]);
  const [minX, maxX, minY, maxY] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const k = Math.cos(((minY + maxY) / 2) * Math.PI / 180); // longitude shrinks with latitude
  const scale = Math.min(width / ((maxX - minX) * k || 1), height / ((maxY - minY) || 1));
  return (p: number[]) => [((p[0] - minX) * k) * scale, height - (p[1] - minY) * scale];
}

export default function SpatialMap({ record }: GenUIProps) {
  const runId = Number(record.props.runId);
  const cells = useQuery({ queryKey: ["run-map", runId], queryFn: () => getRunMap(runId, false) });
  const zones = useQuery({ queryKey: ["run-map", runId, "zones"], queryFn: () => getRunMap(runId, true) });
  const canvas = useRef<HTMLCanvasElement>(null);
  const features = (cells.data?.features ?? []) as Feature[];
  const groups = [...new Set(features.map((f) => String(f.properties.group)))].sort();
  const colour = (g: unknown) => ZONE_COLOURS[groups.indexOf(String(g)) % ZONE_COLOURS.length];
  const [w, h] = [640, 420];
  const at = features.length ? project(features, w, h) : null;

  useEffect(() => {
    if (!at || features.length <= SVG_LIMIT || !canvas.current) return;
    const ctx = canvas.current.getContext("2d")!;
    ctx.clearRect(0, 0, w, h);
    for (const f of features) {
      const polys = f.geometry.type === "Polygon" ? [f.geometry.coordinates as number[][][]] : (f.geometry.coordinates as number[][][][]);
      ctx.fillStyle = colour(f.properties.group);
      for (const rings of polys) {
        ctx.beginPath();
        for (const ring of rings) ring.forEach((p, i) => { const [x, y] = at(p); if (i) ctx.lineTo(x, y); else ctx.moveTo(x, y); });
        ctx.fill("evenodd");
      }
    }
  });

  if (cells.isLoading) return <SkeletonCard title={String(record.props.title ?? "The partition")} rows={6} />;
  if (cells.isError) return <Card title="The partition" tone="warn"><p>The map could not be loaded.</p></Card>;
  const path = (f: Feature) => {
    const polys = f.geometry.type === "Polygon" ? [f.geometry.coordinates as number[][][]] : (f.geometry.coordinates as number[][][][]);
    return polys.map((rings) => rings.map((ring) => ring.map((p, i) => { const [x, y] = at!(p); return `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`; }).join(" ") + "Z").join(" ")).join(" ");
  };
  const totals = (zones.data?.features ?? []) as Feature[];
  return (
    <Card title={String(record.props.title ?? "The partition")}>
      {features.length > SVG_LIMIT ? (
        <canvas ref={canvas} width={w} height={h} className="w-full" role="img" aria-label={`${features.length} cells in ${groups.length} groups`} />
      ) : (
        <svg viewBox={`0 0 ${w} ${h}`} className="w-full" role="img" aria-label={`${features.length} cells in ${groups.length} groups`}>
          {features.map((f) => (
            <path key={String(f.properties.key)} d={path(f)} fill={colour(f.properties.group)} fillOpacity={0.75}
              stroke="white" strokeWidth={0.4} fillRule="evenodd">
              <title>{`${f.properties.key}: ${f.properties.group}${f.properties.subgroup ? ` / ${f.properties.subgroup}` : ""}`}</title>
            </path>
          ))}
        </svg>
      )}
      <table className="mt-2 w-full text-xs">
        <caption className="sr-only">Totals by group</caption>
        <thead><tr><th className="text-left">Group</th><th className="text-right">Cells</th>
          {Object.keys(totals[0]?.properties ?? {}).filter((k) => !["group", "subgroup", "cells"].includes(k)).map((k) => <th key={k} className="text-right">{k}</th>)}</tr></thead>
        <tbody>{totals.map((z) => (
          <tr key={`${z.properties.group}-${z.properties.subgroup}`}>
            <td><span className="mr-1 inline-block h-2 w-2 rounded-sm" style={{ background: colour(z.properties.group) }} />
              {String(z.properties.group)}{z.properties.subgroup ? ` / ${String(z.properties.subgroup)}` : ""}</td>
            <td className="text-right">{formatNumber(z.properties.cells)}</td>
            {Object.entries(z.properties).filter(([k]) => !["group", "subgroup", "cells"].includes(k)).map(([k, v]) => <td key={k} className="text-right">{formatNumber(v)}</td>)}
          </tr>))}</tbody>
      </table>
      <a className="mt-2 inline-block text-blue-700 underline" href={`/api/v1/runs/${runId}/map?dissolve=true`} download={`run-${runId}-zones.geojson`}>
        Export the zones (GeoJSON)
      </a>
    </Card>
  );
}
```

The export link above cannot carry the bearer token; replace the `<a>` with a button that calls `getRunMap(runId, true)`, turns the result into a `Blob` (`application/geo+json`) and downloads it through a temporary object URL. Register `"spatial-map": { component: SpatialMap, skeleton: SpatialMapSkeleton, expandable: true }` (a `SkeletonCard` with 6 rows) in `componentRegistry.ts`; add `getRunMap(id, dissolve)` to `api/v1.ts`. In `Runs.tsx` `RunDetail`, when `data.params.classified_as` and the model has a `connected` rule (`version.ir.constraints.some(c => "connected" in c)`), render the same `SpatialMap` with a synthetic record (`{ props: { runId, title: "The partition" }, ... }`).

`SpatialMap.test.tsx`: with `getRunMap` mocked to four square cells in two groups, the SVG has four `path`s with two distinct `fill`s, the table shows two rows with `cells` 2 and 2, and "Export the zones" requests `getRunMap(runId, true)`; with 6,000 generated cells a `canvas` is rendered instead of an `svg`.

- [ ] **Step 6: Run, full check, commit** (`feat(spatial): a run's partition on a map -- per cell and per zone, GenUI component, GeoJSON export`).

---

### Task 8: `region_partitioning` template and the `districting` bench

**Files:**
- Modify: `backend/app/showcase.py` (`REGION_PARTITIONING`, seed + IR), `backend/app/api/templates.py` (a seed's `grids` step), `backend/bench/families.py` (`districting`, in `COMPARISON_ONLY`)
- Create: `backend/tests/test_region_template.py`, `backend/bench/results/2026-09-2x-districting.md`

**Interfaces:**
- Consumes: the grid endpoint's function (Task 3 — factor its body into `app.api.grids.write_grid(db, domain_id, body: GridRequest) -> GridReport` so the template can call it without HTTP), `connected` (Tasks 4–5).
- Produces: template `region_partitioning`; a seed key `grids: [GridRequest-shaped dict]` honoured by template apply after entities; bench family `districting(size, instance)`.

- [ ] **Step 1: Failing test**

```python
# backend/tests/test_region_template.py
"""The region_partitioning template solves: 4 zones x 2 sub-zones over a hex grid, every piece connected."""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from tests.test_connected import _connected
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401
from app.worker import work_once


def test_the_template_solves_with_every_zone_and_sub_zone_connected(tenants, db):  # noqa: F811
    client = TestClient(app)
    template = next(t for t in client.get("/api/template/?limit=50", headers=tenants["a"]).json()["items"]
                    if t["name"] == "region_partitioning")
    applied = client.post(f"/api/v1/templates/{template['id']}/apply", json={"domain_name": "regions"}, headers=tenants["a"]).json()
    cells = db.execute(text("SELECT count(*) FROM entity e JOIN entity_type t ON t.id = e.entity_type_id"
                            " WHERE t.domain_id = :d AND t.name = 'cell'"), {"d": applied["domain_id"]}).scalar_one()
    assert 300 <= cells <= 500
    scenario = client.post("/api/v1/scenarios", json={"problem_id": applied["problem_id"], "model_version_id": applied["model_version_id"],
                                                      "name": "base"}, headers=tenants["a"]).json()
    run = client.post(f"/api/v1/scenarios/{scenario['id']}/runs", json={"time_limit_s": 120}, headers=tenants["a"]).json()
    for _ in range(5):
        if work_once(db) == run["id"]:
            break
    solved = client.get(f"/api/v1/runs/{run['id']}", headers=tenants["a"]).json()
    assert solved["status"] in ("optimal", "feasible")
    cells_map = client.get(f"/api/v1/runs/{run['id']}/map", headers=tenants["a"]).json()
    edges = [{"from": a, "to": b} for a, b in db.execute(text(
        "SELECT fe.key, te.key FROM relationship r JOIN entity fe ON fe.id = r.from_entity_id JOIN entity te ON te.id = r.to_entity_id"
        " JOIN relationship_type rt ON rt.id = r.relationship_type_id WHERE rt.domain_id = :d AND rt.name = 'adjacent'"),
        {"d": applied["domain_id"]}).all()]
    for key in ("group", "subgroup"):
        for value in {f["properties"][key] for f in cells_map["features"]}:
            members = [f["properties"]["key"] for f in cells_map["features"] if f["properties"][key] == value]
            assert _connected(members, edges), (key, value)
```

Use the apply response's real field names (`problem_id`, and the published version id — check `app/api/templates.py`).

- [ ] **Step 2: The template** — in `showcase.py`, `REGION_PARTITIONING_SEED` with entity types `area` (attribute `boundary: geometry`), `zone` (entities `z1..z4`), `subzone` (entities `z1a, z1b, …, z4b`) and relationship `belongs_to` (subzone → zone, one edge each); one `area` entity whose boundary is a 10 km × 8 km rectangle near 31.2°E, 30.0°N; `grids: [{"boundary_entity": ["area", "region"], "shape": "hex", "size_m": 500, "entity_type": "cell", "layers": <deterministic population points: random.Random(7), 400 points, population 50–500>}]`. The IR: `assign[cell, zone]`, `assign_sub[cell, subzone]`; exactly one zone and one sub-zone per cell; `assign_sub[u,s] <= assign[u,z]` for `s` reached from `z` through `belongs_to` (a `via` binding); population per zone within ±10% of total/4 and per sub-zone within ±15% of total/8 (as `par` targets computed by the seed); `connected` over `adjacent` at both levels; goal: fewest cut edges (`cut[u,v,z] >= assign[u,z] - assign[v,z]`, via `adjacent`, minimised). In `templates.py` apply, after entities and relationships: for each `grids` entry, resolve `boundary_entity` to its id and call `write_grid`.

- [ ] **Step 3: Bench** — `districting(size, instance)` in `families.py` builds the same model on a square grid of S 10×10 (4 zones), M 20×20 (8), L 40×40 (12), XL 63×63 (16), with seeded populations and adjacency in `data["relationships"]["adjacent"]`; add it to `FAMILIES` and `COMPARISON_ONLY`. Run `python -m bench.run --families districting --sizes S,M,L --instances 2 --time-limit 120` in the test image and write `bench/results/2026-09-2x-districting.md`: per size and backend, status, time, gap; the conclusion states the largest size solved to optimality within 120 s and whether approach C (cuts) is needed.

- [ ] **Step 4: Run** `tests/test_region_template.py` — PASS (allow up to 120 s). Full check.

- [ ] **Step 5: Commit** (`feat(templates,bench): region partitioning template and the districting bench family`), then deploy (migrate first), `docker image prune -f`, and verify live in a browser: apply the template, see the grid on the entity page, solve on the Workspace page, watch the partition hydrate on the map, export the zones, and open the GeoJSON to check each feature is one polygon per zone.

---

## Self-review notes (for the executor)

- Spec §2 → Task 1 (type, CRS setting) and Task 2 (projection). §3 → Tasks 2–3 (+ form). §4 → Tasks 4–5 (nesting, balance, compactness exercised in Task 8's template and test). §5 → Tasks 6 (editor), 3 (form), 1 (preview), 8 (template). §6 → Task 7. §7 → Task 5 (routing, fingerprint) and Task 8 (bench). §8 → caps and named refusals in Tasks 1–3; dependencies in Task 2. §9 → the test files listed per task.
- Names used across tasks: `validate_geometry`, `make_grid`, `sum_points`, `TooManyCells`, `OutOfRange`, `Projection`, `write_grid`, `GridRequest`, `GridReport`, `app.solve.connected.expand`, `Compiled.connectivity`, `ROOT`/`FLOW`, `describeConnected`, `ConnectedEditor`, `getRunMap`, `SpatialMap`, `ZONE_COLOURS` — each defined once, in the task that produces it.
