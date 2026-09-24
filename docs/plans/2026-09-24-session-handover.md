# Development session handover — 2026-09-24 (updated after R3)

For an AI coding assistant continuing this project with no memory of the session. **The code is the authority; this document is a map.** Where it says "uncertain", verify before relying on it.

Companion documents in the repo (read in this order after this one):

1. `docs/plans/2026-09-22-execution-queue.md` — the work queue; every item ticked with its commits and what was verified live.
2. `docs/plans/2026-09-22-handover.md` — the standing handover (state line, procedures, gotchas). Its **State:** line names the deployed commit.
3. `docs/superpowers/plans/2026-09-24-blockly-edit-mode.md` — the Blockly edit-mode plan (Blocks 0–4 all done).
4. `docs/superpowers/specs/2026-09-24-blockly-edit-mode-design.md`, `docs/superpowers/specs/2026-09-24-spatial-region-partitioning-design.md` — the approved designs.
5. `docs/contracts/problem-ir.md` — the IR contract (the model document every part of the platform reads).

---

## 1. Project overview

**Name / purpose.** "Problem Solver" — an optimisation-as-a-service platform (repository `D:\solver`). A planner describes a domain (entity types, entities, relationships, parameters), writes a model as an IR document (sets, decisions, rules, goal) in forms or blocks, publishes immutable model versions, and runs scenarios; a worker compiles the model and solves it on the best-suited solver, streaming progress. Multi-tenant: **a tenant is an organization**.

**Stack.**

| Layer | Technology |
|---|---|
| API | Python 3.12, FastAPI, SQLAlchemy, Pydantic 2, Alembic |
| Database | PostgreSQL 16 with row-level security (the app runs as role `solver_runtime`); ClickHouse for analytics (`run_fact`, fed through an outbox) |
| Queue / worker | Postgres `SKIP LOCKED` queue, fair claiming per organization; **one solve per sandboxed subprocess** (forkserver child, RLIMIT_AS/CPU, `PR_SET_DUMPABLE 0`) |
| Solvers | OR-Tools CP-SAT, GLOP, pywraplp MILP; HiGHS (in a child program `highs_worker`); SCIP (pyscipopt 6.2.1, quadratic/nonlinear) |
| Spatial | Shapely 2.0.6, pyproj 3.7.0, Pillow 11.0.0 (all added this session; Pillow reads terrain-RGB tiles) |
| Frontend | React 18, TypeScript, Vite, Tailwind, TanStack Query, react-router, Blockly 12 (`zelos`), Framer Motion 11 (added this session), Cytoscape, Rete.js, React Flow |
| Tests | pytest (backend, against a `solver_test` database), Vitest + jsdom (frontend), Playwright with system Chrome for live browser checks (installed with `--no-save`, not a dependency) |
| Hosting | Docker Compose on a Windows 11 machine (Docker Desktop / WSL2); nothing is pushed to a remote |

**Architecture in one paragraph.** The IR (`backend/app/ir/contract.json`, contract version 2) is validated twice in parity — `backend/app/ir/validate.py` and `frontend/src/ir/validate.ts` — against shared fixtures (`backend/tests/ir_fixtures.json`). A run freezes a dataset snapshot, `app/solve/classify.py` names the model class and needs, `app/solve/backends.py` picks a backend whose `provides` covers the needs, `app/solve/compile.py` compiles IR + data into linear/quadratic rows, and the backend solves in a sandbox. Settings (platform → domain → problem) live in `setting_key` / `setting`; several solve techniques are switched by settings whose defaults were decided by benchmark (`backend/bench/`).

## 2. Current objective

The session ran the execution queue autonomously under the user's standing instruction **"go with your recommendations"** (a `/loop`): one queue item at a time, each built with tests, full check green, deployed from a clean worktree, verified live in a browser, ticked in the queue and handover.

At the moment of handover (after R3) the next items are, in queue order:

- **R4–R12 — the optimization target roadmap's remaining open items** (`docs/plans/2026-09-22-optimization-target-roadmap.md`), queued (`3712016`) on the user's "go ahead on the roadmap". **R4 (near-separable detection) is next.** The GPU lane and LLM/NL→IR stay out (standing defaults).
- R1 (PDLP), R2 (portfolio racing) and R3 (LNS) are done; R2 and R3 are off by the bench. Blocks 3–4 were moved ahead of R2 when the user asked to "create and edit well using blocks" (with a screenshot of the optimization view's read-only blocks showing "(choose)"), and are done.

Acceptance criteria for everything in the queue: full check green (`bash scripts/check.sh`), migration rehearsed up/down/up on a copy of the live database, deployed, verified live in Chrome (API and UI), test data cleaned up, queue + handover updated, committed by path.

## 3. Work completed in this session

The session is long and was compacted several times. By the session's own summary it began at the **function catalogue** (commit `0c89b46`); commits before that on 2026-09-23 (Phases 8–15: tracing, run facts, sandbox, IR v2, conditional rules, piecewise curves, scheduling, IIS/cores, result cache, warm starts, symmetry, solver options, Pareto front, uncertainty, robust solving) **appear to be from earlier sessions — uncertain**; they are in the queue either way. Range of this session: `0c89b46~1..HEAD` — 168 files, +22,355 / −2,494 lines.

Every item below was tested (unit + full check) and verified live unless it says otherwise.

| # | What | Why | Key files | Notes |
|---|---|---|---|---|
| 1 | Function catalogue (`fn`: exp, log, sqrt, abs, sin, cos with curvature labels), solved by SCIP | Phase 16 | `app/ir/contract.json`, `app/solve/compile.py`, `frontend/src/ir/contract.ts` | domain checks of arguments from variable bounds |
| 2 | DCP curvature detection; McCormick for binary×bounded products; SOCP recognition | Phase 16 | `app/solve/dcp.py`, `mccormick.py`, `socp.py`, `convexity.py` | an import cycle (contract→expressions→models→contract) was found and fixed; `tests/test_imports.py` imports every module in a fresh interpreter |
| 3 | Separable blocks: find independent parts and solve them at once | Phase 14 | `app/solve/blocks.py`, `bench/separable.py` | on by the bench (3.3–17×), migration 0046 |
| 4 | No core dumps from killed solves | WSL crash dumps filled C: (13.8 GB) | `app/solve/nodump.py`, `sandbox.py`, `highs_worker.py` | `PR_SET_DUMPABLE 0` in the sandbox child and again in `highs_worker` (exec resets it) |
| 5 | Run fingerprint (row kinds, sizes, density…) stored on the run and in `run_fact` | Phase 17 | `app/solve/fingerprint.py`, `analytics.py`, `clickhouse_schema.py` | now `VERSION = 2` (adds `rows_connectivity`) |
| 6 | GenUI phase 1: the solve pipeline told as typed events; a Workspace page renders them | user's GenUI spec | `app/genui/protocol.json`, `translate.py`, `app/api/genui.py`, `frontend/src/genui/*`, `pages/Workspace.tsx` | real backend events drive it (no LLM); Framer Motion shared-layout expansion; reduced motion |
| 7 | Per-problem memory: the next run takes the solver that proved this problem fastest | alternative to fingerprint routing | `app/solve/memory.py`, `bench/memory.py` | on (migration 0047), 1.3–2.8× on 5 of 7 families |
| 8 | Probe race: with nothing remembered, probe each admissible solver briefly | same | `app/solve/race.py`, `bench/race.py` | **off** (migration 0048): 2× slower on facility L |
| 9 | **GIS 1** geometry attribute type (GeoJSON) | spatial spec | migration 0049, `app/spatial/geometry.py`, `GeometryPreview.tsx`, `AttrsForm.tsx` | ring/position validation; drawn, not printed; setting `spatial.crs` (default 4326) |
| 10 | **GIS 2** square/hex grids in metres over a boundary, adjacency, point sums | spatial spec | `app/spatial/grid.py`, `project.py` | UTM zone of the centroid; refuses antimeridian / >6° wide; hex corners rounded to µm so shared sides are not double-counted |
| 11 | **GIS 3** grid generator endpoint + form | spatial spec | `app/api/grids.py`, `GridGeneratorForm.tsx`, `pages/EntityTypes.tsx` | one transaction; 409 names cells and scenarios before `replace` |
| 12 | **GIS 4** `connected` IR rule | spatial spec | contract, both validators, `app/ir/models.py` | 7 codes (6 shape, 1 domain `connected_via_not_self`) |
| 13 | **GIS 5** `connected` compiled to an exact single-commodity flow | spatial spec | `app/solve/connected.py` | integer flow (not continuous) so CP-SAT keeps the model; checked against every partition of 3×3 grids on 4 backends |
| 14 | **GIS 6** connected rule in the Model editor, graph and blocks | spatial spec | `model/ConnectedEditor.tsx`, `model/terms.ts`, `lib/modelGraph.ts` | also fixed: relationships walked by scheduling rules were not declared on publish |
| 15 | **GIS 7** a run's partition as GeoJSON; `spatial-map` GenUI component; export | spatial spec | `app/api/run_map.py`, `genui/components/SpatialMap.tsx`, `pages/Runs.tsx` | SVG ≤ 5,000 cells, canvas beyond; dissolved zones with totals |
| 16 | **GIS 8** `region_partitioning` template; `districting` bench | spatial spec | `app/regions.py`, `app/showcase.py`, `app/seed.py` (`grids` seed step), `bench/families.py` | 90 one-km hexes, 4 zones × 2 sub-zones; see §6 for the two deviations |
| 17 | **Blocks 0** Blockly edit-mode implementation plan | user request | `docs/superpowers/plans/2026-09-24-blockly-edit-mode.md` | spiked first: headless Blockly works in Vitest |
| 18 | **Blocks 1** one shared unpublished draft per problem | Blockly spec §2 | `model/draftStore.ts`, `model/draftIr.ts`, `model/DraftBar.tsx`, `pages/ModelEditor.tsx` | localStorage, survives reloads, Continue/Start again, badge, Discard confirm |
| 19 | **Blocks 2** editable block vocabulary, exact IR↔blocks round trip, Model editor Blocks tab; read-only view on the same blocks | Blockly spec §3–4 | `lib/irBlocks/*`, `components/BlocksEditor.tsx`, `modelStyles/BlocklyView.tsx`; `lib/modelBlocks.ts` **deleted** | exact over all 23 valid fixtures + 5 templates |
| 20 | **GIS 9** basemaps from the user's tile server | user request | migration 0050, `lib/tiles.ts`, `hooks/useBasemaps.ts`, `SpatialMap.tsx` | Satellite/Topo under the partition map; setting set live |
| 21 | Fix: connected models could not be solved from the Runs page | found in GIS 9's screenshot | `pages/Runs.tsx` `unexpressedRules` | a connected rule was taken for a pre-contract sketch; Solve was hidden |
| 22 | **GIS 10** each grid cell's elevation and slope from terrain-RGB tiles | user request (their `egypt_terrain` tileset) | `app/spatial/terrain.py`, `app/api/grids.py` (`elevation`, `_terrain`), `GridGeneratorForm.tsx`, `requirements.txt` (+Pillow) | `c27889c`; live: 81 one-km cells Giza→Mokattam, 18.4–197.6 m (Nile cells 23–29 m, Mokattam up to 196 m) |
| 23 | Roadmap open items queued as R1–R12 | user: "go ahead on the roadmap" | `docs/plans/2026-09-22-execution-queue.md` | `3712016`; ordered by value against cost |
| 24 | Fix: the read-only blocks showed "(choose)" over sets, data and attributes | the user's screenshot | `lib/irBlocks/vocabulary.ts` (`OpenDropdown.getOptions`) | `21a2257`; Blockly cached the options before the value loaded |
| 25 | **R1** PDLP for very large LPs; `approximate` optimality | roadmap Phase 14 | migration 0051, `app/solve/pdlp.py`, `lp.py`, `backends.py`, `service.py`, `genui/translate.py`, `api/runs.py`, `pages/Runs.tsx`, `bench/pdlp.py` | `fc88049` + read-back fix; `solve.pdlp` off by the bench; live 43.5317 shown "optimal to within a tolerance" |
| 26 | Symmetry detection made linear | found by the R1 bench | `app/solve/symmetry.py` (`_by_member`) | `716b0b5`; 250k-decision compile 213 s → 4.7 s |
| 27 | **Blocks 3** every construct as its own block | Blockly plan Task 6 | `lib/irBlocks/{vocabulary,toBlocks,toIr,catalogue}.ts` | `3feccaa`, `4762dc0`; no opaque block for any fixture/template; live workshop makespan 9 → 8 after a size edit by mouse |
| 30 | **R3** large-neighbourhood search | roadmap Phase 13 | migration 0053, `app/solve/lns.py`, `sandbox.py` (`lns_in_child`), `service.py`, `bench/lns.py` | `50e00f3`; `solve.lns` off by the bench; live: 16 rounds on a knapsack, answer recorded feasible/none |
| 29 | **R2** portfolio racing; `sandbox.run(abandon=)` | roadmap Phase 13 | migration 0052, `app/solve/race.py` (`run_portfolio`, `should_portfolio`), `service.py`, `sandbox.py`, `genui/translate.py`, `bench/portfolio.py` | `36428ae`; `solve.portfolio` off by the bench; live: 4 solvers raced, SCIP's answer kept |
| 28 | **Blocks 4** validate route, refusals on blocks, Edit mode in the optimization view | Blockly plan Tasks 7–9 | `api/problems.py` (`validate_version`), `model/useDraftRefusal.ts`, `components/BlocksEditor.tsx` (`showRefusal`), `modelStyles/BlocklyEdit.tsx`, `GraphEditor.tsx`, `irBlocks/buildByBlocks.test.ts` | `2a06560`, `0ea6a8f`, `d504070`; live mouse checks in §11 |

## 4. Current project state

**Deployed:** code at the Blocks 4 commits (see the standing handover's **State:** line for the exact commit); database at **migration 0053** (R3).

### ✅ Completed
- Everything in §3.
- The whole spatial region-partitioning plan (GIS 1–8), GIS 9 (basemaps) and GIS 10 (elevation and slope per cell).
- Blocks 0–4 of the Blockly edit mode: the whole plan.
- R1 (PDLP), R2 (portfolio racing), R3 (LNS).

### 🟡 Partially completed
- Nothing mid-item. (An opaque block remains only for a shape the blocks could not write back exactly -- e.g. a `connected` rule whose decision is indexed [group, unit], a curve of more than 12 points, an `add` of one term.)

### ❌ Not completed
- R4–R12 (the roadmap's remaining open items) — queued; R4 near-separable detection is next.
- Connectivity at scale ("approach C": cuts or a heuristic warm start) — not queued as an item yet; recorded as the bench's conclusion.
- Vector tiles (`egypt_osm`, `pbf`) — not rendered anywhere.
- GeometryPreview thumbnails have no basemap (deliberately, 64–96 px).

### ⚠️ Known problems
- **Exact connectivity flow does not scale**: with balance binding, proven at ~100 cells, mixed at 196, nothing feasible at 400+ cells in 120 s on any backend (`backend/bench/results/2026-09-24-districting.md`). This is why the template uses 1 km cells (90), not 500 m (360).
- On the region template SCIP finds nothing in 60 s (CP-SAT 3–20 s, HiGHS ~7 s prove it).
- `spatial.tiles_index` is set to `http://localhost:8080/index.json` — works only in a browser on the host machine (the browser fetches tiles itself).
- The tile server's metadata text is double-encoded (UTF-8 read as Windows-1252); repaired for display only. The fix belongs in the user's `.mbtiles` metadata.
- `Blockly.inject` cannot run under jsdom (canvas text measurement); the editor's logic is tested on a headless workspace and the injected editor only in live browser checks.
- Renaming a decision in blocks does not rename blocks that reference it; those references then show the stale name and are refused (`reference_undeclared`) — by design; the refusal now shows as a warning on the referencing block.
- Every rule block shows an empty "only when" slot (the `when` condition): visual weight on models that never use it.
- `solve.pdlp` is off: at the sizes this platform builds (≤ ~2M nonzeros under the 4 GB ceiling) GLOP still proves the optimum (`backend/bench/results/2026-09-24-pdlp.md`).
- The Runs page asks every solved run for its map; a non-spatial run answers 404 by design (console shows one 404).
- **Slope on built-up ground reads 4–6 %** even where the land is flat: Copernicus GLO-30 is a *surface* model (buildings and trees count). Not a bug in `terrain.py`; say so to users reading `slope_pct` in cities.
- **C: disk ~15 GB free (96 %)**; Docker's disk image and WSL crash dumps live there.

### 🔧 Temporary workarounds
- `test_bench.py`'s small-size agreement test excludes `districting` (`_NOT_SMALL`): its S instance is sized to be hard (HiGHS up to 72 s). Exactness is covered by `tests/test_connected.py`'s brute force.

## 5. Files changed (this session, `0c89b46~1..HEAD`)

Grouped; A = added, M = modified, D = deleted. Test files accompany almost every row.

| File | Change | Status | Important notes |
|---|---|---|---|
| `backend/alembic/versions/0046_setting_separable.py` … `0050_setting_tiles_index.py` | A | deployed | 0046 separable (on), 0047 memory (on), 0048 probe (off), 0049 geometry type + `spatial.crs`, 0050 `spatial.tiles_index` |
| `backend/app/spatial/{geometry,grid,project}.py` | A | done | pure functions; `make_grid`, `sum_points`, `Projection`, `validate_geometry` |
| `backend/app/api/grids.py` | A | done | `write_grid(db, domain_id, body, *, commit=True)` |
| `backend/app/api/run_map.py` | A | done | `GET /api/v1/runs/{id}/map[?dissolve=true]` |
| `backend/app/api/genui.py`, `app/genui/{protocol.json,translate.py}` | A | done | SSE of GenUI events; `Translator(..., spatial=bool)` |
| `backend/app/solve/{connected,dcp,mccormick,socp,blocks,memory,race,fingerprint,nodump}.py` | A | done | see §3 |
| `backend/app/solve/{compile,classify,backends,service,sandbox,highs,highs_worker,scip,robust,pywraplp_model,convexity}.py` | M | done | `Compiled.connectivity`; `"connected"` in the provides of cp-sat/highs/milp/scip |
| `backend/app/ir/{contract.json,contract.py,validate.py,models.py}` | M | done | `connected`, `fn`; `CONNECTED_KEYS` |
| `backend/app/regions.py` | A | done | the region template's seed and IR, `sample_dataset()` for the bench |
| `backend/app/showcase.py`, `app/seed.py` | M | done | template registered; seed `grids` step (`_plant_grid`) |
| `backend/bench/{families.py,memory.py,race.py,separable.py}`, `bench/results/2026-09-2*.md` | A/M | done | `districting` family is comparison-only |
| `backend/tests/template_irs.json`, `tests/test_template_irs.py` | A | done | every template's IR for the frontend round trip; compared as data (CRLF-safe); refresh with `SOLVER_WRITE_TEMPLATE_IRS=1` |
| `backend/tests/ir_fixtures.json` | M | done | 23 valid / 129+ invalid; `cell`, `district`, `adjacent` added to its domain block |
| `backend/requirements.txt` | M | done | + `shapely==2.0.6`, `pyproj==3.7.0`, `Pillow==11.0.0` |
| `backend/app/spatial/terrain.py`, `backend/tests/test_terrain.py` | A | done (GIS 10) | terrain-RGB decoding, host rewrite for containers, per-cell sampling |
| `frontend/package.json` | M | done | + `framer-motion ^11.18.2` |
| `frontend/src/lib/irBlocks/{catalogue,vocabulary,toBlocks,toIr,readOnly}.ts` | A | done (Blocks 2) | the block system; §6 |
| `frontend/src/lib/modelBlocks.ts`, `modelBlocks.test.ts` | **D** | done | replaced by `irBlocks` |
| `frontend/src/components/BlocksEditor.tsx` | A | done | `showIr`, `bindWorkspace` exported for headless tests |
| `frontend/src/model/{draftStore,draftIr,DraftBar}.ts(x)` | A | done (Blocks 1) | |
| `frontend/src/pages/ModelEditor.tsx` | M | done | on the draft store; Forms/Blocks tabs (`?view=blocks`) |
| `frontend/src/pages/Runs.tsx` | M | done | map on the run page; `unexpressedRules` fix |
| `frontend/src/genui/**`, `pages/Workspace.tsx` | A | done | GenUI runtime, registry, stream manager, cards, `SpatialMap` |
| `frontend/src/lib/tiles.ts`, `hooks/useBasemaps.ts` | A | done (GIS 9) | |
| `frontend/src/components/{GeometryPreview,GridGeneratorForm}.tsx`, `model/ConnectedEditor.tsx` | A | done | |
| `frontend/src/ir/{contract,validate}.ts`, `lib/modelGraph.ts`, `model/{terms,declarations}.ts` | M | done | connected, fn, curvature labels |
| `docs/superpowers/{specs,plans}/2026-09-24-*.md` | A | approved / executing | |
| `docs/contracts/problem-ir.md` | M | done | §4.3 `fn`, §4.4 `connected`, rule counts |
| `frontend/_browser_check_*.mjs` | A (gitignored) | local only | live checks; not committed by design |

## 6. Important implementation details

**Connected rule → exact flow** (`backend/app/solve/connected.py`). Per group `z`: binary `__root[rule,u,z]` (exactly one, or ≤1 with `empty: allowed` plus "any member ⇒ a root"), `root ≤ assign`; integer flow `__flow[rule,a,b,z] ∈ [0, n−1]` on both directions of each `via` edge, `flow ≤ (n−1)·assign` at both ends; balance `inflow − outflow ≥ assign − n·root`. Integer, not continuous: supplies are whole, so an integer flow exists whenever any does, and CP-SAT keeps the model. Auxiliary names start `__` (reporting skips them).

**Region template** (`backend/app/regions.py`). Compactness is the **least moment of inertia about fixed centres**, not the fewest cut edges: a cut variable would be declared over `cell × cell × zone` (≈ half a million). On axial hex coordinates (q = `col`, r = `row`), 4·distance² = (2Δq + Δr)² + 3Δr² — whole numbers, so CP-SAT stays eligible. Cells are 1 km (measured: 1 km proven in 3–20 s; 750 m nothing in 60 s; 500 m nothing in 120 s).

**Blocks — the two conversions** (`frontend/src/lib/irBlocks/`):
```ts
irToBlocks(ir, { editable?, title?, ids?: (loc: IrLoc) => string | undefined }): Workspace   // root id "model-root"
blocksToIr(savedWorkspace): { ir; paths: Map<blockId, IrLoc>; outside: number }
blockForLoc(paths, loc): string | null      // longest-prefix match: where a refusal belongs (Task 8 uses it)
loadBlocks(workspace, json)                 // load with name rules off (see below)
```
- `OpenDropdown` accepts any string and always lists its current value — a stale or renamed value is shown and later refused, never blanked. Name/number validators are skipped while `loadBlocks` runs, so a draft loads exactly as it is.
- An empty socket becomes `{"const": null}`; an unchosen dropdown `""` — refused by name, never silently dropped.
- Round-trip canonicalisations (the only two): `relationships` compared as a set (derived from walked `via.rel` and `connected.via`), `objective.mode: "weighted"` ≡ absent.
- `BlocksEditor`: `showIr` loads with `Blockly.Events.disable()` (showing is not an edit); `bindWorkspace` ignores UI events and coalesces a burst into one report per animation frame; the editor ignores its own echo from the draft (`lastEmitted`).
- Blockly delivers change events asynchronously — tests must wait (`vi.waitFor`), not assume.

**Draft store** (`frontend/src/model/draftStore.ts`): key `solver_model_draft_<problemId>`; `{problemId, base: "scratch"|"version-<id>", baseVersion, ir, editedAt, persisted}`; `updateDraftIr` always starts from the store's current value (another tab may have written); memory fallback when storage throws (`persisted: false`, the badge says so). A draft exists only once something is edited.

**Basemaps** (`frontend/src/lib/tiles.ts`): offers only picture tilesets (`png/jpg/jpeg/webp`, no `encoding`); `repairText` reverses UTF-8-read-as-Windows-1252; `fitView` picks the deepest zoom within the tileset's range that fits, Web Mercator, north up. The map switches to Web Mercator only over a basemap with degree coordinates.

## 7. Database changes (this session)

| Migration | Change | Downgrade |
|---|---|---|
| 0046 | `setting_key` `solve.separable` (boolean, **true**) | deletes key and settings |
| 0047 | `setting_key` `solve.memory` (boolean, **true**) | same |
| 0048 | `setting_key` `solve.probe` (boolean, **false**) | same |
| 0049 | enum `attr_type` += `geometry` (autocommit block); `attr_value_matches_type` and `entity_validate` judge GeoJSON; `setting_key` `spatial.crs` (number, 4326) | refuses while geometry attributes exist; leaves the enum value |
| 0050 | `setting_key` `spatial.tiles_index` (string, `""`) | deletes key and settings |
| 0053 | `setting_key` `solve.lns` (boolean, **false**) | deletes key and settings |
| 0052 | `setting_key` `solve.portfolio` (boolean, **false**) | deletes key and settings |
| 0051 | `run_optimality_known` CHECK allows `approximate`; `setting_key` `solve.pdlp` (boolean, **false**) | refuses while approximate runs exist; deletes key and settings |

All rehearsed up → down → up on a copy of the live database (`pg_dump | psql` into `solver_migtest`, then dropped). **Live data change:** `setting` row `platform / spatial.tiles_index = "http://localhost:8080/index.json"` (set through the API in GIS 9's check; intended to stay). `setting_key.value_type` allows only `number | string | boolean`. Pending DB work: none.

## 8. APIs / integrations

New endpoints (all under the existing JWT bearer auth; tenant isolation by RLS — another organization gets 404):

| Method / path | Purpose | Notes |
|---|---|---|
| `POST /api/v1/domains/{id}/grids` | make a grid | body `GridRequest {boundary_entity_id? | boundary?, shape: square|hex, size_m (0, 1e6], entity_type, keep: centre|overlap, layers ≤ 200k points, replace}` → 201 `GridReport {entity_type_id, relationship_type_id, cells, edges, dropped, layer_totals, layer_outside}`; 409 `{message, cells, scenarios}` when cells exist and `replace` is false; 422 named causes (>20,000 cells, bad ring, too wide) ; requires `domain.edit` |
| `GET /api/v1/runs/{id}/map[?dissolve=true]` | GeoJSON of a run's partition | per unit `{key, group, subgroup, <numbers>}`; dissolved per group `{group, subgroup, cells, <totals>}`; 404 "this run has no connected rule over units with a geometry" |
| `GET /api/v1/runs/{id}/genui` | SSE GenUI events | `spatial-map` component at settle for a spatial run that ended well; an `approximate` optimum is a warning, "optimal to within a small tolerance -- not proven the best" |
| `POST /api/v1/problems/{id}/versions/validate` | dry-run publish | body `{ir}` → `{ok: true}` or the exact 422 publish gives; writes nothing; requires `model.publish` |

Changed: `RunSummary.optimality` (`GET /api/v1/runs…`) may be `approximate` (R1); a request may name solver `pdlp`.

Existing endpoints used: `POST /api/v1/problems/{id}/versions`, `POST /api/v1/scenarios/{id}/runs` (`time_limit_s ≤ 60`), `GET/PUT /api/v1/settings`, `POST /api/v1/templates/{id}/apply`, `POST /api/v1/classify`.

External integration: the **user's tile server** `http://localhost:8080` (TileJSON index `/index.json`, CORS `*`, gzip `Content-Encoding`): `egypt_satellite` (jpg z1–11), `egypt_topo` (jpg z1–12), `egypt_terrain` (png terrain-RGB, `encoding: mapbox`, z0–12), `egypt_osm` (pbf vector, z0–12). From a container it is `http://host.docker.internal:8080` (verified reachable). Terrain-RGB height: `-10000 + (R·65536 + G·256 + B) · 0.1` m.

No LLM integration: `LLM_ENABLED=false`; a vLLM endpoint the user described earlier was not found on this machine.

## 9. Configuration / environment

| Item | Value |
|---|---|
| Frontend | `http://localhost:3010` (nginx in `solver-frontend-1`) |
| API | `http://localhost:8010` |
| Postgres | `127.0.0.1:5544` (compose service `postgres`) |
| ClickHouse | `127.0.0.1:8123`, `9000` |
| Tile server | `http://localhost:8080` (user-run, outside compose) |
| Compose services | `postgres`, `clickhouse`, `backend`, `worker`, `frontend` (network `solver_solver_net`) |
| Images | live tags `solver-backend:latest`, `solver-frontend:latest`; `solver-backend-test` for tests when requirements change |
| Secrets | `D:\solver\.env` (`DATABASE_URL`, `JWT_SECRET`, `ADMIN_PASSWORD`, …) and `.env.runtime` (runtime role). **Claude cannot read `.env` (denied by policy)** — pass it with `--env-file`, never print it. Admin login `admin` / `<ADMIN_PASSWORD>` |
| Worker knob | `SOLVE_MEMORY_MB` (default 4096) |
| Frontend storage keys | `solver_token`, `solver_domain_id`, `solver_model_draft_<problemId>`, `solver_map_basemap` |

## 10. Errors and problems (unresolved)

1. **Connectivity at scale.** No feasible answer at ≥400 cells in 120 s (all four backends) once balance binds. Cause: the flow formulation's big-M (n−1) coupling and free roots. Tried: nothing beyond measuring. Recommended: lazy connectivity cuts on the incumbent's disconnected pieces, or fix each zone's root at its centre cell (an IR extension of `connected`), or a heuristic balanced partition grown from the centres as a warm start.
2. **SCIP on the region template:** "unknown" at 60 s where HiGHS proves it in ~7 s. Not investigated; routing already prefers CP-SAT/HiGHS.
3. *(resolved)* Terrain decoding needed Pillow — added (`Pillow==11.0.0`). The first image build failed (most likely a Docker Hub timeout) and a second was killed by piping `docker build` into `head`: **never pipe a build into `head`**; log it to a file.
4. **Mojibake in the tile metadata** — user-side data; display repaired.

## 11. Testing

| What | Command | Result at handover |
|---|---|---|
| Everything | `bash scripts/check.sh` (`SOLVER_BACKEND_IMAGE=solver-backend-test` when requirements change) | green after R1, and after Blocks 3–4 (see §4 for the run). `EntitiesExpression.test.tsx` "does not show a 422 as a generic list failure" is a known load flake (5 s timeout under load). |
| One backend file | `MSYS_NO_PATHCONV=1 docker run --rm --network solver_solver_net -v "D:/solver/backend:/app" -w /app --env-file D:/solver/.env -e CLICKHOUSE_HOST=clickhouse solver-backend-test sh -c 'TEST_DATABASE_URL=${DATABASE_URL}_test pytest -q tests/<file>'` | |
| Frontend | `cd frontend && npx vitest run [src/<path>]` | 2,019 tests in 103 files, green |
| Backend | pytest | green (R1 added `test_pdlp.py`, Blocks 4 `test_validate_version.py`) |
| Live checks | `cd frontend && SHOTS=<dir> node _browser_check_<name>.mjs` (gitignored) | each creates its own domain and deletes it |

Known to work live (this session): grid form, connected editor, partition map + export, region template from the Dashboard, draft persistence, Blocks tab edits, basemaps (Satellite, Topo) with solving from the Runs page, grids with elevation and slope from the real terrain tiles; a PDLP run chosen on the Runs page (43.5317, shown approximate); the read-only blocks showing their values; Edit mode in the optimization view (toolbox, a block dragged by mouse beside the model holds Publish, a mouse edit published as a new version); the workshop template edited as blocks (interval size by keyboard, published, solved: makespan 9 → 8); a refusal shown on the block that caused it (`_browser_check_refusal.mjs`).

Still needs testing:
- dragging a block **into** a socket by mouse (the live checks drop onto empty canvas, type into fields and pick from dropdowns; connecting is covered headless by `buildByBlocks.test.ts`);
- **GIS 10's reprojection branch** (`_terrain` when `spatial.crs` != 4326, `Transformer.from_crs(crs, 4326, always_xy=True)`): every fixture and live domain is 4326, so it has never run.

**Test gotchas learned:** Blockly change events are async (`vi.waitFor`); `localStorage` must be cleared between Model editor tests (`clearDraft(1)` also empties the in-memory fallback); a nested `beforeEach` runs after the file's own; the machine's default locale is Arabic (use explicit `en-GB` for clock times in English sentences); `git core.autocrlf=true` rewrites JSON fixtures with CRLF on checkout (compare fixtures as data); Playwright `networkidle` can resolve before React renders new requests — wait for the specific response.

## 12. Decisions and constraints (do not violate)

- A tenant is an organization; one solve per subprocess; a local optimum is shown with a warning, never called optimal; no Redis; no GPU lane; no LLM/NL→IR work.
- Ask the user only if a choice is irreversible, costs money, or contradicts the plan; otherwise "go with your recommendations".
- IR contract changes go into **both** validators, the shared fixtures, the Pydantic models and `docs/contracts/problem-ir.md`, with parity tests green.
- Model versions are immutable; publishing always writes a new version.
- The Blockly edit mode: **the draft IR is the only truth** (approach A); block positions are not saved; one draft per problem shared by forms, Blocks tab and the optimization view's Edit mode; the round trip must stay exact over every valid fixture and template, with no opaque block for any of them.
- `optimality` is `global | local | approximate | none`; only `global` answers enter the result cache, per-problem memory and the probe race.
- Solver techniques are switched by settings whose defaults are decided by benchmark (`backend/bench/`), not by preference.
- Commit by path — **never `git add -A`**; throwaway probes are gitignored (`frontend/_browser_check_*.mjs`); don't commit `bench/_*.json`.
- Migrations: check `git log` for the latest number before numbering; rehearse up/down/up on a live copy; migrate **before** restarting.
- Deploy from a clean detached worktree (`git worktree add -f ../solver-deploy HEAD --detach`), then `docker image prune -f` (C: is nearly full).
- New dependencies are allowed when justified; pin versions; when requirements change, build `solver-backend-test` and run `SOLVER_BACKEND_IMAGE=solver-backend-test bash scripts/check.sh`.
- Never read `.env`; never print secrets.

## 13. Pending tasks

**High priority**

1. **R4–R12** in queue order: R4 near-separable detection is next, then near-separable detection, Lagrangian bounds, IPOPT local lane, two-stage stochastic, chance constraints, rolling horizon, tuning search, learned selector in shadow mode, per-template decomposition.

**Medium priority**

1. Connectivity at scale (approach C) — queue it as its own item with a bench gate.
2. Vector tiles (`egypt_osm`): a MapLibre-based background would need a style; decide whether the partition map should move to MapLibre GL.

**Low priority**

1. Basemap under `GeometryPreview` in the entity form (larger preview).
2. Ask the user to fix the double-encoded text in their `.mbtiles` metadata.

## 14. Recommended next step

Start **R4 (near-separable detection)**: read the R4 line in `docs/plans/2026-09-22-execution-queue.md` and the roadmap's Phase 14 bullet, then `backend/app/solve/blocks.py` (exact separability, `solve.separable`, on): R4 extends it to models that split into blocks except for a few linking rules. Test-first, a bench-gated setting.

## 15. Continuation instructions

- Read `docs/plans/2026-09-22-execution-queue.md` and the standing handover first; then inspect the actual files before changing them.
- Continue from the current implementation; do not rebuild completed work (every ticked queue item is deployed and verified).
- Preserve the architecture and the decisions in §12 unless there is a clear, stated reason.
- Verify every assumption in this document against the code (`git log`, the files, the running containers).
- Do not repeat approaches proven unsuccessful: a cut-edge compactness objective (variable blow-up), 500 m template cells (no answer in 120 s), continuous flow variables (drops CP-SAT), `Blockly.inject` under jsdom, byte-comparing JSON fixtures on this Windows checkout.
- Work one queue item at a time: tests that pin behaviour, full check, deploy, live browser check (screenshots), queue + handover update, commit by path.
- Ask the user only when a decision is irreversible, costs money, or contradicts the plan.

## 16. Copy/paste starter prompt

```
You are continuing an existing development session on the "Problem Solver" optimisation platform in D:\solver (FastAPI + Postgres/RLS + OR-Tools/HiGHS/SCIP backend, React/Vite/Blockly frontend, Docker Compose on Windows). First read the handover below, then inspect the actual project files to verify the current state. Do not assume the handover is more authoritative than the code. Continue from the current implementation and complete the next pending task.

Handover: docs/plans/2026-09-24-session-handover.md (then docs/plans/2026-09-22-execution-queue.md and docs/plans/2026-09-22-handover.md).

State: deployed, database at migration 0053. Done this session: spatial region partitioning (GIS 1-8), basemaps from my tile server at http://localhost:8080 (GIS 9), elevation and slope per grid cell from its terrain tiles (GIS 10), the whole Blockly edit mode (Blocks 0-4: shared draft, Blocks tab, every construct as a block, refusals on blocks, Edit mode in the optimization view) R1 (PDLP, answers shown as approximate), R2 (portfolio racing) and R3 (LNS), both off by the bench. Next: the optimization target roadmap's remaining items R4-R12 in queue order, starting with R4 (near-separable detection).

Rules: go with your recommendations; ask me only if a choice is irreversible, costs money, or contradicts the plan. Full check (bash scripts/check.sh) green before commit; commit by path, never git add -A; rehearse migrations up/down/up on a copy of the live DB; deploy from a clean worktree and prune Docker images (C: is nearly full); verify live in a browser; never read .env.
```
