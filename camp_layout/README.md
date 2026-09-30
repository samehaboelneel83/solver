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
pip install -e .            # ortools, shapely, numpy, scipy, pyproj
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
