# Camp Layout Optimization Engine

Place as many beds as fit in a camp of any shape, with corridors at least a
given width that reach a door from every bed, then shorten the walks, trim the
corridors and keep door zones and bed sizes as specified where possible.
The model is solver-independent; every answer is re-checked with exact
geometry before it counts.

- **Model**: [`docs/MODEL.md`](docs/MODEL.md) -- sets, variables, constraints,
  objectives, connectivity, paradigm, decomposition, complexity, worked example,
  pseudocode.
- **Complex example output**: [`examples/complex/`](examples/complex/) --
  GeoJSON of the input and the layout (local metres and WGS84), `report.json`,
  and `viewer.html`, an interactive site plan (open it in a browser).

## Run

```bash
pip install -e .            # ortools, shapely, numpy, scipy, pyproj, ezdxf, openpyxl (in backend/camp_layout)
python -m camp_layout complex --solver cpsat --beds-seconds 300 --seconds 120 --out examples/complex
python -m camp_layout small --solver scip          # the same model on a MILP solver
python -m camp_layout complex --solver heuristic   # Stage 0 only, about a second
python -m pytest
```

```python
from camp_layout import solve, examples, export
run = solve(examples.complex_camp(), solver="cpsat", stage_limits={"beds": 300}, time_limit=120)
print(len(run.layout.beds), run.validation.ok)
export.write(run, "out/")
```

Solvers: `cpsat` (OR-Tools CP-SAT), `scip`, `highs`, `cbc` (MILP through
OR-Tools), `heuristic`. A new solver is one file in `camp_layout/adapters/`.

## In the platform

Camps are **map data**: each domain's *Map data* page has two tabs, *Drawings*
(imported CAD drawings) and *Camps* (`/domains/:id/map-data/camps`).

**A camp is records of its domain** (`app/camp/domain.py`), planted the first
time a camp is made there:

| Kind | What |
|---|---|
| record types | `camp` (boundary, origin, bearing, goals, solve settings), `door` (location, width_m, frame_depth_m), `closed_area`, `no_beds_area`, `bed_zone` (shape), `bed_type` (sizes, ranges, may_rotate, side_gap_m) |
| relationships | `door_of`, `closed_area_of`, `no_beds_area_of`, `bed_zone_of` (to the camp), `camp_uses` (camp -> bed types), `must_go_in` (bed type -> zone) |
| parameters | `corridor_width_m[camp]`, `grid_m[camp]`, `door_capacity[door]`, `zone_depth_m`, `zone_max_depth_m`, `zone_step_m`, `zone_margin_m`, `zone_area_per_bed_m2[door]`, `min_beds` / `max_beds[camp, bed_type]`, `bed_priority[bed_type]` |

The Records, Relationships and Parameters pages show and edit them, and the
next solve reads what they say. Shapes are stored on the Earth; the camp's
`origin` and `bearing` (how far its grid is turned from north) put them back
on the camp's own grid, so a camp drawn at an angle keeps straight walls.
Only the layouts asked for are kept outside the records (`camp_solve`).

In the camp editor:

- **Draw** on the map, over satellite or street imagery: the camp boundary
  (polygon or rectangle), doors (a click on a horizontal or vertical wall),
  closed areas (polygon, rectangle or circle), no-beds areas and bed zones.
  Select a shape to drag its corners, insert a corner from the dot between
  two, slide a door along its wall, or type every coordinate in the panel.
  Snap to 0.1-1 m; Shift keeps walls straight; Ctrl+Z / Ctrl+Y undo and redo.
- **Set** what a drawing cannot show: door capacities and clear zones, bed
  types (sizes, ranges, counts, zones, priority), corridor width, the goals
  and their order, and where the camp is (type or paste a position, or drag
  it over the imagery with *Place on map*).
- **Check** as you draw: the server (`POST /api/v1/camps/check`) names the
  shape at fault and the door zones are drawn before any solve.
- **Lay out** in the worker (`app/camp/jobs.py`, one child process per solve)
  and see the answer on the same map: beds coloured by type, door or walk,
  corridors, grown door zones, the route of the bed under the pointer, door
  loads against capacities, the 18 independent checks, and downloads:
  GeoJSON in WGS84 and local metres, the report, and a standalone map.
- **Import** a `.dxf` or `.xlsx` into the editor; **export** the camp as a
  workbook, a DXF or JSON.
- **From map data**: any drawing imported under *Map data* (the general
  DXF → GIS pipeline, `docs/map-data.md`) can start a camp. Point at its
  boundary layer and the layers holding doors, closed areas, no-bed areas and
  bed zones (`app/camp/from_gis.py`).

Imagery comes from the tile index named by the `spatial.tiles_index` setting,
and otherwise from Esri World Imagery and OpenStreetMap, which the viewer's
browser must be able to reach. Without them the drawing works on a plain
background.

## From a CAD drawing

```
plan.dxf  --dxf2xlsx-->  camp.xlsx (review, add bed types)  --run-->  best layout + map
```

```bash
python -m camp_layout dxf2xlsx plan.dxf camp.xlsx --crs EPSG:32636   # crs optional
python -m camp_layout run camp.xlsx --solver cpsat --out out/
python -m camp_layout template templates/                           # blank drawing + workbook
```

Layers the converter reads (upper or lower case):

| Layer | What it is | Drawn as |
|---|---|---|
| `CAMP_BOUNDARY` (`BOUNDARY`, `CAMP`, `SITE`) | the camp outline; the largest closed shape | closed polyline |
| `DOORS` (`DOOR`, `GATES`, `ENTRANCES`) | each opening, on an axis-aligned wall; a text nearby names it | line along the wall, or a door block |
| `OBSTACLES` (`CLOSED`, `FIXED`) | pillars, tanks, fixed rooms; a text inside names it | closed polyline, circle, hatch |
| `NO_BEDS` (`PROHIBITED`, `FIRE_BREAK`, `KEEP_CLEAR`) | walkable, but no beds | closed shape |
| `ZONE_<NAME>` | where beds with `zone = <name>` must go | closed shape |

Every other layer is ignored and listed in the notes. Units come from the
drawing (`$INSUNITS`) or `--units mm|cm|m`; surveyed coordinates are moved to a
local origin, and with `--crs` the map is placed where the drawing is. Door
blocks (leaf and swing arc) give the stretch of wall they cover. The workbook
shades every value the drawing did not give (door capacities, bed types, zone
depths) for review before solving.

## The chain

```
ProblemDefinition (problem.py)
  -> Geometry (geometry.py, exact polygons)
  -> Grid: cells, bed placements, corridor tiles, zone bands (discretize.py)
  -> MathematicalModel (model.py) built by ModelBuilder (builder.py)
  -> Stage 0 constructive start (heuristic.py)
  -> SolverAdapter (adapters/) under a lexicographic or weighted driver (optimize.py)
  -> LayoutResult: shapes only (result.py)
  -> Validation: exact geometry, clearance paths, walking distances, door capacities (validate.py)
  -> GeoJSON, report, map (export.py)
```

## GIS

`*_wgs84.geojson` open directly in QGIS, geojson.io or kepler.gl over
imagery; `*_local.geojson` are in metres (x east, y north) for CAD. Every
feature has a `layer` property: `boundary`, `door`, `door_zone`,
`door_zone_max`, `obstacle`, `prohibited`, `placement_zone`, `bed`,
`corridor`, `path`.
