# Spatial region partitioning — design

**Date:** 2026-09-24 · **Status:** design approved in conversation (sections 1–2); sections 3–9
are Claude's recommendations, taken on the user's instruction "go with your recommendations, for a
general professional platform". This document is for the user's review before an implementation
plan is written.

## 1. Goal

Let the platform solve **spatial layout problems** the way it already solves rotas and blends: a
domain describes the world, a problem says what is decided, the IR is the contract, the compiler
turns intent into exact mathematics, and the solvers stay general. The first problem class is
**region partitioning**: group the cells of a generated grid into **K contiguous zones**, and each zone
into **M contiguous sub-zones** — both levels decided in one solve — balancing quantities such as
population or demand and keeping zones compact.

**Spatial is a capability of ordinary entities, not a separate kind of domain.** A domain and a
problem may mix GIS and non-GIS entities and rules freely: a `zone` can carry a boundary and a
`staff` count; one model can require zones to be connected *and* each zone's workload to fit its
team.

### Decisions taken

| Question | Decision | Why |
|---|---|---|
| First problem class | Region partitioning | the user's choice |
| Where units come from | A generated grid (square or hex) over a boundary | the user's choice; adjacency is known by construction |
| Nesting | Both levels decided in one solve | the user's choice |
| Contiguity | A `connected` IR rule compiled to an exact single-commodity flow (approach B) | exact on every backend; readable intent in the document |
| Rejected: users write flow rules by hand (A) | — | opaque, easy to get silently wrong |
| Deferred: contiguity cuts during search (C) | only if B does not scale on the bench | needs backend-specific callbacks; breaks one-model-per-child |
| Map | SVG/canvas over the cells, no basemap in phase 1 | no network dependency, no tile-provider account |

## 2. Spatial data in ordinary domains (approved)

**A `geometry` attribute type** beside `integer`, `number`, `text`, `boolean`, `enum`, `time`,
`date`. GeoJSON geometry (`Point`, `Polygon`, `MultiPolygon`) stored in the entity's JSONB `attrs`,
validated on write: well-formed coordinates, closed rings, at most 10,000 vertices per geometry.
Any entity type may have one; a geometry attribute is never read by arithmetic (the IR refuses
`attr` of a geometry, as it refuses `text`).

**Coordinates and CRS.** A domain has a setting `spatial.crs` (an EPSG code, default 4326).
Geometry is stored as given. Every length, area and grid size is computed in a **projected** CRS:
the UTM zone of the boundary's centroid (pyproj), so "a 500 m cell" means 500 m. No PostGIS: the
database only stores GeoJSON, and every geometric operation (clip, contain, union, area) is Shapely
in the backend — one engine, the same in tests and production.

## 3. The grid generator

A **domain operation** (capability `domain.edit`), not part of a model: it writes entities and
relationships, which a scenario then freezes like any other data.

`POST /api/v1/domains/{id}/grids`

| Input | Meaning |
|---|---|
| `boundary` | an entity id whose geometry is the area, or uploaded GeoJSON |
| `shape` | `square` or `hex` |
| `size_m` | cell width (square) or flat-to-flat width (hex), metres |
| `entity_type` | name of the cell type, created if missing (e.g. `cell`) |
| `layers` (optional) | point GeoJSON or CSV with `lon, lat, <attr>...`; each numeric column summed per cell |
| `keep` | `centre` (a cell whose centre lies inside the boundary) or `overlap` (any overlap, with `coverage` = share inside) |

In one transaction it creates:

- one entity per cell, key `c_r{row}_c{col}` (hex: axial `q,r`), label, attributes `geometry`,
  `centroid` (Point), `area_m2`, `row`, `col`, `coverage`, and every summed layer column;
- a relationship type `adjacent` on the cell type (symmetric; created if missing) with one edge per
  shared side — 4-neighbourhood for squares, 6 for hexes — and an attribute `shared_m` (edge length).

**Limits.** At most 20,000 cells per grid (refused by name, with the count it would make); the
upload at most 20 MB. **Re-running** for the same entity type replaces its cells and edges after a
confirmation stating how many cells and which scenarios reference them; frozen datasets keep old
runs reproducible, as today. The response reports cells made, cells dropped at the boundary, and
the sum of each layer inside versus outside the grid (so a planner sees what the boundary cut off).

## 4. The `connected` rule (approved)

An optional version-2 rule kind, like `no_overlap`:

```json
{ "id": "c_zone_connected",
  "connected": { "assign": {"var": "assign", "index": ["u", "z"]},
                 "units":  {"index": "u", "set": "cell"},
                 "groups": {"index": "z", "set": "zone"},
                 "via": "adjacent",
                 "empty": "forbidden" } }
```

**Meaning:** for every group `z`, the units with `assign[u,z] = 1` form one connected piece over
`via`. `empty`: `forbidden` (each group at least one unit) or `allowed`.

**Validation** (contract rules, both validators, shared fixtures, parity): the variable is binary and
indexed by exactly (units set, groups set); `via` is a relationship from the units' type to itself;
the rule is hard and unconditional; version 2 only. Codes: `connected_needs_version_2`,
`connected_malformed`, `connected_not_binary`, `connected_index_mismatch`, `connected_via_invalid`,
`connected_on_soft`.

**Compilation — exact single-commodity flow per group:**

- `root[u,z] ∈ {0,1}`; `Σ_u root[u,z] = 1` (`≤ 1` when empty groups are allowed, with
  `Σ_u root[u,z] ≥ assign[u',z]` for every `u'`); `root[u,z] ≤ assign[u,z]`.
- `flow[u→v,z] ≥ 0` on both directions of each edge; `flow[u→v,z] ≤ (n−1)·assign[u,z]` and
  `≤ (n−1)·assign[v,z]`, `n` the number of units.
- For each unit: `inflow − outflow ≥ assign[u,z] − n·root[u,z]`.

A group is connected exactly when every assigned unit receives flow from the group's root. Linear,
exact, taken by CP-SAT, HiGHS, MILP and SCIP. The classification adds `needs: connected` and names
the rule; the fingerprint counts the flow rows under a new row type `connectivity`.

**Nesting** needs no second construct: sub-zone labels get a fixed parent through an ordinary
`belongs_to` relationship (with the same number M of sub-zones in every zone the labels are
interchangeable, so fixing parents removes no partition; a zone with its own sub-zone count is the
same model with its own labels);
`assign_sub[u,s] ≤ assign[u, parent(s)]` keeps each sub-zone inside its zone, and a second
`connected` rule keeps each sub-zone connected.

**Balance and compactness** are today's IR: `Σ_u pop[u]·assign[u,z]` within bounds; compactness as
fewest cut edges (`cut[u,v] ≥ assign[u,z] − assign[v,z]` per edge and zone, minimised) or least
distance from each unit to its zone's root.

## 5. Authoring

- **Template `region_partitioning`**: a sample boundary, a hex grid of about 400 cells with a
  population layer, zones and sub-zones with `belongs_to`, and the model above with balance ±10% and
  cut-edge compactness — a working example to copy.
- **Model editor**: a `connected` rule editor (pick the assignment variable, the units and groups sets
  it is indexed by, the relationship) that offers only admissible choices, like the scheduling
  editor; the rule reads back in words ("each zone is one connected piece over adjacent").
- **Domain pages**: `geometry` attributes show as a small map preview, never as raw JSON; the grid
  generator is a form on the entity-types page with a preview of the cell count before it runs.

## 6. The map view and GenUI

- A **`spatial-map`** GenUI component (added to `protocol.json` and the registry): the grid's cells
  as SVG polygons up to 5,000 cells, canvas beyond; coloured by zone (a categorical palette checked
  for contrast in light and dark), sub-zone borders drawn thinner; hover a cell for its attributes,
  click a zone for its totals against the balance targets.
- A run's partition **hydrates on the map**: the translator emits the map skeleton at `compiled`
  and the assignment at `settled` (from the stored solution — never from a guess mid-solve).
- The same map is on the Runs page for a spatial run, and **Export** downloads GeoJSON: each zone and
  sub-zone as the union (Shapely) of its cells, with its totals as properties.
- Reduced motion: no transitions on recolouring; the zone totals are also a table.

## 7. Routing, bench and scale

- `connected` is supported by every backend; the classifier leaves routing to the existing rules
  (an all-binary partition goes to CP-SAT; with continuous parts, HiGHS).
- **Bench family `districting`** (S: 100 cells/4 zones, M: 400/8, L: 1,600/12, XL: 4,000/16, with
  and without sub-zones), comparison-only until its times are known. Its report states how far exact
  flow contiguity scales and whether approach C is needed.
- Separable blocks do not split a `connected` model across zones (the flow links them), and say why.

## 8. Security, limits, errors

- All new data lives in existing tables (entities, relationships, attributes) under the existing
  tenant RLS; the grid endpoint needs `domain.edit`; uploads are parsed server-side with size and
  vertex caps, and never written to disk outside the request.
- Every refusal names its cause: an invalid geometry (which ring, which vertex), a grid over the cap
  (the count), a `connected` rule whose variable is not indexed by the units and groups sets.
- New dependencies: `shapely`, `pyproj` (backend; image grows about 30 MB — built on D:-hosted source,
  pruned after deploy per the C: disk warning).

## 9. Testing and delivery

**Tests that pin behaviour:** geometry validation (closed rings, winding, caps); the grid generator
on a hand-drawn boundary (exact cell counts, keys, adjacency degree 4/6, `shared_m`, layer sums
inside and outside); UTM projection distances within 0.1% of known values; `connected` validation in
both validators with fixtures; the flow compiled on small grids and **checked against brute force
over every partition** (3×3 grid, 2–3 zones, on every backend); nesting hand-worked on a 4×4 grid;
the map component (colours by zone, totals table, reduced motion); the template solving live.

**Queue items (in order):**

1. (GIS 1) Geometry attribute type + CRS setting — done when geometry attributes are validated,
   stored, refused in arithmetic, and previewed on entity pages.
2. (GIS 2) Grid generator — done when square and hex grids with adjacency and layer sums are made
   by the endpoint and form, exact on hand-drawn boundaries, within the caps.
3. (GIS 3) `connected` rule — done when it is in the contract, both validators and the editor,
   compiled to exact flow, and matches brute force on every backend.
4. (GIS 4) Map view + GeoJSON export — done when a spatial run's partition hydrates on the
   `spatial-map` GenUI component and on the Runs page, and exports as zone polygons.
5. (GIS 5) `region_partitioning` template + `districting` bench — done when the template solves live
   with nesting, and the bench report says how far exact contiguity scales.

**Out of scope for now:** imported polygon units (census blocks, parcels) and their adjacency from
shared borders; raster layers (slope, elevation); basemap tiles; free-form placement of shapes
(2-D non-overlap); contiguity cuts (approach C). Each is a later item once this is in use.
