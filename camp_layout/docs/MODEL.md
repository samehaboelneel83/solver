# Camp Layout Optimization Engine — the model

This document is the mathematical model behind the `camp_layout` package, in
the order the specification asked for (§10, items 1–17). Item 18, the
implementation, is the package itself; its map is at the end.

Units are metres. The camp lives in a flat local frame (x east, y north);
`origin_lonlat` places it on the Earth only for GIS output.

---

## 0. The idea in one paragraph

Continuous 2-D packing with free positions, rotations, flexible sizes *and*
a collision-free, minimum-width corridor network is not something any solver
takes directly: non-overlap between free rectangles needs O(N²) disjunctions,
and "there is a path at least w wide" is not an algebraic constraint at all.
The engine therefore works on a **grid of pitch g** (0.5 m by default). Beds
become **candidate placements** (type × size × orientation × anchor cell),
corridors become **overlapping w × w tiles** whose union is at least w wide
by construction, and access becomes a **single-commodity network flow** from
the doors through used tiles into used beds. Every hard rule is then linear,
the model has no pairwise constraints, and any MILP or CP solver can take it.
Because the grid is an approximation of the real geometry, a separate
**validator re-checks the answer with exact geometry** — including a real
path, w wide, from every bed to a door — and the layout counts as a success
only if that passes.

---

## 1–2. Sets and indices

| Set | Meaning |
|---|---|
| `C` | grid cells `c = (i, j)`, square `[x₀+ig, x₀+(i+1)g] × [y₀+jg, y₀+(j+1)g]` |
| `C_bed ⊆ C_walk ⊆ C` | cells where a bed may lie / where a person may walk |
| `D` | doors `j` |
| `L_j` | depth levels of door j's zone, `ℓ = 0` is the specified depth |
| `B_{jℓ} ⊆ C` | the band of cells door j's zone takes when it grows from level ℓ−1 to ℓ |
| `T` | bed types `τ` |
| `P` | candidate placements `p = (τ, size, orientation, anchor)`; `cells(p) ⊆ C_bed` |
| `P_τ ⊆ P` | placements of type τ |
| `K` | corridor tiles `k` (w × w squares anchored on the grid); `cells(k) ⊆ C_walk` |
| `K_j ⊆ K` | tiles wholly inside door j's specified zone (where walking starts) |
| `A ⊆ K × K` | directed tile arcs: anchors one cell apart horizontally or vertically |
| `E(p) ⊆ K` | access tiles of p: the tile standing at the middle of each long side |
| `P(c)` | placements covering cell c; `K(c)`: tiles covering c |

A placement exists only if its whole slot is on `C_bed` (so inside the camp,
off obstacles, prohibited areas, door frames and specified door zones) and,
for a zoned bed type, inside its placement zone. A tile exists only if all its
cells are walkable. **Boundary, obstacle, prohibited-area and placement-zone
rules are therefore enforced by the candidate sets, with no rows at all.**

## 3. Parameters

| Parameter | Meaning |
|---|---|
| `g` | grid pitch (m); `w` minimum corridor width, `s = w/g` tile side in cells |
| `L_τ, W_τ` | nominal bed length/width; `[L_τ⁻, L_τ⁺] × [W_τ⁻, W_τ⁺]` flexible range; `Σ_τ` allowed size variants |
| `gap_τ` | side clearance kept inside a bed's slot |
| `rot_τ` | rotation allowed |
| `n_τ⁻, n_τ⁺` | minimum / maximum count of type τ; `π_τ` priority |
| `dev_p` | `|L·W − L_τW_τ|` of placement p's size (m²) |
| `cap_j` | door j's capacity (beds); `a_j` zone area per bed (m²/bed) |
| `A_{jℓ}` | area of door j's zone at level ℓ |
| `U` | upper bound on beds: `⌊|C_bed| / min_p |cells(p)|⌋` |

## 4. Decision variables

| Variable | Domain | Meaning |
|---|---|---|
| `y_p` | {0,1} | placement p is used — this *is* `used_i, x_i, y_i, width_i, length_i, rotation_i` of the spec, discretised: choosing p chooses all of them at once |
| `t_k` | {0,1} | tile k is corridor |
| `u_c` | {0,1} | cell c is circulation |
| `e_{jℓ}` | {0,1} | door j's zone has depth level ℓ |
| `f_{kl}` | ℤ≥0, ≤ U (relaxable) | beds' walking flow on arc k→l |
| `σ_k` | ℤ≥0 (relaxable), k ∈ ∪K_j | flow entering at zone tile k |
| `α_{pk}` | {0,1} (relaxable), k ∈ E(p) | bed p is entered from tile k |
| `λ_j` | ℤ≥0 | beds served through door j |

`assigned_ij` of the spec is not a variable: a bed's unit of flow leaves
exactly one door, so its door is read off the flow (path decomposition), and
`Σ_j assigned_ij ≥ used_i` holds by flow conservation. If a model needs a
*named* door per bed (door-specific bed types, per-door walking limits), use
one commodity per door (§15).

"Relaxable": integrality is not needed — the flow part has integral optima
whenever demands are integral — so a MILP adapter makes these continuous,
which is much cheaper. CP-SAT keeps them integer.

## 5. Hard constraints

```
(cell)      Σ_{p ∈ P(c)} y_p + u_c ≤ 1                 ∀ c           beds never overlap each other or a corridor
(tile)      t_k ≤ u_c                                   ∀ k, c ∈ cells(k)
(source)    t_k = 1                                     ∀ k ∈ ∪ K_j   door zones are always walkable
(level)     Σ_ℓ e_{jℓ} = 1                              ∀ j
(zone)      Σ_{p ∈ P(c)} y_p + Σ_{ℓ' ≥ ℓ} e_{jℓ'} ≤ 1   ∀ c ∈ B_{jℓ}  a grown zone holds no bed
(access)    Σ_{k ∈ E(p)} α_{pk} = y_p                   ∀ p           a used bed is entered from a tile …
            α_{pk} ≤ t_k                                ∀ p, k ∈ E(p) … that is corridor
(flow)      Σ_{l:(l,k)∈A} f_{lk} + σ_k = Σ_{l:(k,l)∈A} f_{kl} + Σ_{p: k∈E(p)} α_{pk}     ∀ k
(capacity)  f_{kl} ≤ U·t_k,  f_{kl} ≤ U·t_l             ∀ (k,l) ∈ A   flow only on corridor
(door)      λ_j = Σ_{k ∈ K_j} σ_k,   λ_j ≤ cap_j        ∀ j
(zonearea)  a_j·λ_j ≤ Σ_ℓ A_{jℓ} e_{jℓ}                 ∀ j           a door zone big enough for the beds it serves
(count)     n_τ⁻ ≤ Σ_{p ∈ P_τ} y_p ≤ n_τ⁺               ∀ τ
```

Why (flow) proves accessibility: every used bed consumes one unit, units are
created only at door-zone tiles, and they move only between neighbouring used
tiles. So a used bed has a unit only if there is a chain of used tiles from a
door zone to the tile at its side — a path. **Why that path is at least w
wide**: each tile is a w × w square, and two neighbouring tiles are offset by
g < w, so any chain of tiles sweeps a band at least w wide; the path never
enters a bed (cell) or an obstacle (tiles exist only on walkable cells).

## 6. Soft constraints

The hard rules above are never traded. The preferences are objectives (§7)
rather than penalised violations, which keeps priorities explicit:

| Preference | Where it lives |
|---|---|
| short walks | objective `distance` |
| little circulation area | objective `corridor` |
| few modifications (grown zones, resized beds) | objective `modifications` |
| spacing between beds | `gap_τ` inside every slot (hard), more via a larger gap |
| preferred orientation / zones | a per-placement penalty added to `modifications` (a new term, no new rows) |
| maximum walk (soft) | `f`-weighted penalty on arcs beyond a distance label (see §15, extension) |

A soft rule that must be *allowed to break* at a price is written the usual
way: a slack `s ≥ 0` in the row and `ρ·s` in an objective.

## 7. Objective functions

```
beds          max  N = Σ_p π_τ(p) · y_p
distance      min  D = Σ_{(k,l)∈A} g · f_{kl}                total walking along corridors, all beds
corridor      min  R = g² · Σ_{c ∉ specified zones} u_c      circulation area (m²)
modifications min  M = Σ_{j,ℓ} (A_{jℓ} − A_{j0}) e_{jℓ} + Σ_p dev_p · y_p      m²
```

`D` is exact for the flow: each bed's unit crosses one arc per g metres of
its route, so `Σ g·f` is the sum over beds of each bed's path length along
tile centres. The *maximum* walk (spec §3.2) is not linear in `f`; it is
reported by the validator and can be bounded as an extension (§15).

**Lexicographic** (default): solve for `N`; add `N ≥ N*` (exactly — beds are
never given back unless `trade_beds`); solve for `D`, keep `D ≤ D*(1+ε_D)`;
solve for `R`, keep `R ≤ R*(1+ε_R)`; solve for `M`. Each stage starts from
the previous answer.

**Weighted**: `max Σ_i w_i · s_i · obj_i / scale_i`, `s_i = +1` for `N`,
`−1` for the others, `scale_i` the objective's typical size (U beds; U × camp
span metres; walkable area; zone growth plus U × 0.5 m²), so units do not
decide the trade-off.

## 8. Bed-to-door connectivity

The (access), (flow), (capacity), (source) and (door) rows above. Three
formulations were considered:

| | A. Grid + flow (chosen) | B. Visibility graph | C. Hybrid: optimise, then path-find |
|---|---|---|---|
| Accuracy | exact on the grid; validated on exact geometry | exact corners, but corridor *width* needs a buffered obstacle set that depends on the beds being decided | exact path, but found after the layout is fixed |
| Beds and paths decided together | yes | only with visibility edges that depend on bed variables — O(nodes²) conditional edges | no: a layout may be infeasible and has to be repaired |
| Formulation | linear, O(grid) rows | quadratic in candidate nodes, big-M per edge | simple optimisation + BFS |
| Solvers | any MILP / CP | MILP with many big-Ms | any |
| Scaling | tens of thousands of cells | hundreds of nodes | best |

The engine uses **A** for the model and **C** for its start (Stage 0,
`heuristic.py`) and for validation (a clearance-path check, exact geometry).

## 9. Collision / non-overlap

Pairwise non-overlap of N free rectangles needs, for each pair, four
disjunctive big-M rows (left/right/below/above) — O(N²) rows and a weak
relaxation. On the grid, **one row per cell** does it: at most one thing
covers a cell. With `|P|` placements each covering ~10 cells, the (cell) rows
hold ~10·|P| non-zeros and there are `|C|` of them — linear. Beds against
fixed objects need no rows (candidate generation), beds against corridors
share the same (cell) row through `u_c`.

## 10. Boundary

A cell is in `C_walk` only if the exact camp polygon contains it; a
placement or tile exists only on such cells. The camp may be any simple
polygon — non-convex, non-symmetric, with diagonal edges; cells cut by a
diagonal edge are simply not used (the grid loses at most one cell's width
along such an edge). Door zones are clipped to the camp; the validator
checks every bed, corridor and zone against the exact polygon.

## 11. Corridors

A corridor is the union of used tiles. Minimum width holds by construction
(§5). Where the spec asks for "corridor length", the model minimises
circulation *area* `R` (length × width for a w-wide corridor, and honest where
corridors widen). Door zones are corridors that are always there; their
growth is a decision (e), priced in `M`. A wider main corridor (width
w₂ = m·g > w) is a second tile size with its own tiles and arcs, joined to the
first where they overlap — an extension without new constraint types.

## 12. Recommended paradigm

**Discretised MILP / CP-SAT, driven lexicographically, warm-started by a
constructive heuristic, and validated by exact geometry.** Concretely:

- **CP-SAT** is the default. The model is almost all Booleans with covering,
  packing and implication rows — CP-SAT's home ground — and its LNS search
  improves a given start quickly.
- **MILP** (SCIP, HiGHS, CBC through the same model) is the second adapter:
  the flow part is exact as an LP, and a MILP solver gives dual bounds.
- **MINLP / global** solvers are not needed: nothing in the discretised model
  is non-linear. They become relevant only for continuous positions (§14).

## 13. Why

1. **Everything is linear and local**: no O(N²) disjunctions, no big-M between
   geometric objects, only the flow capacities.
2. **Width and access are guaranteed by construction** (tiles, flow), not
   approximated by a Euclidean distance.
3. **Solver independence**: the model is data (`model.py`); an adapter is a
   translation (`adapters/`).
4. **Quality is measurable**: the validator measures the real layout, and
   solver bounds say how far from proven optimal a stage is.
5. **Every extension in the spec is a new candidate filter, a new row group or
   a new objective term** (§17), never a rewrite.

## 14. What is hard to encode directly

- **Continuous positions and sizes.** Free x, y, width, length with rotation
  are bilinear (rotation × size) and need O(N²) disjunctions for non-overlap.
  The grid replaces them with a finite choice; a finer grid or a local
  continuous polish after solving (§15, Stage 4) recovers the difference.
- **"A path at least w wide exists".** Not algebraic; it is a topological
  statement about the free space. The tile + flow construction is a sufficient
  condition; the validator checks the real geometric statement.
- **Minimum or maximum walking distance per bed.** Needs per-bed distances:
  shortest-path labels `d_k` with big-M rows, or per-bed commodities.
  Reported by the validator; bounded as an extension.
- **Non-axis-aligned beds** (rotation other than 0/90°): a second grid
  rotated to the wall, or a continuous polish.
- **Grid access versus real access.** A bed's access tile is centred on the
  middle of its slot's long side; for a slot of an odd number of cells the
  tile's centre line runs half a cell (0.25 m) off the bed's own middle. The
  validator counts a walker beside the middle half of the long side as able to
  use the bed; an earlier version looked only straight out from the exact
  middle and rejected 21 of 172 beds that a person could in fact reach -- a
  reminder that the validator's definitions need the same care as the model's.
- **The LP bound on the bed count is weak**, because a fractional corridor can
  "reach" many beds at once. Stages can therefore stop at "feasible, gap x%";
  the report says so and never claims "optimal" that was not proved.

## 15. Decomposition

When the full model is too big (tens of thousands of cells), the same pieces
split cleanly:

| Stage | What | How |
|---|---|---|
| 0 | a good feasible layout | constructive rows + Steiner connection + greedy packing (`heuristic.py`) |
| 1 | maximise beds | full model, from Stage 0; or **by region**: fix corridors on the boundary between regions, solve regions separately, re-join |
| 2 | corridor network and assignment | fix `y`; solve (tile, flow) only: a Steiner-network / min-cost flow problem, far smaller |
| 3 | door assignment and zones | fix `y, t`; solve (flow, e, λ): an LP plus |D|·|L| binaries |
| 4 | validation and local improvement | validator; then relocate/resize/swap moves (LNS: free a window of cells, re-solve it with everything else fixed) |

Per-door commodities (named doors, per-door limits, walking limits by door)
multiply the flow part by |D|; with Stage 2/3 fixed layouts that is cheap.

**Complexity of the constraint groups** (`|C|` cells, `|P|` placements, `|K|`
tiles, `|A| ≈ 4|K|` arcs, s the tile side in cells, r the slot size in cells):

| Group | Rows | Non-zeros |
|---|---|---|
| cell | |C| | r·|P| + |C| |
| tile | s²·|K| | 2s²·|K| |
| access | |P| + Σ|E(p)| ≈ 3|P| | ≈ 5|P| |
| flow | |K| | ≈ 2|A| + Σ|E(p)| |
| capacity | 2|A| | 4|A| |
| zone, level, door, zonearea, count | O(|C| in bands + |D|·|L| + |T|) | small |

All linear in the grid; nothing is O(N²) or O(N·M·K).

## 16. A small numerical example

`examples.small_camp()`: a 14 × 9 m room, one door (1.5 m, south wall,
x 6–7.5), its zone 2 m deep and growable to 3 m (0.25 m² per bed), a 1 × 1 m
pillar at (9–10, 5–6), cots 2.0 × 0.9 m (+0.1 m side gap → slot 2.0 × 1.0 m, 4 × 2
cells), corridors 1.0 m (tiles of 2 × 2 cells), grid 0.5 m.

| Quantity | Value |
|---|---|
| walkable cells / bed cells | 500 / 480 |
| candidate placements | 744 (both orientations) |
| corridor tiles / arcs / access arcs | 450 / 1 700 / 1 320 |
| U (bed upper bound) | 480 / 8 = 60 |
| model | 4 729 variables, 8 219 constraints, 26 398 non-zeros |
| Stage 0 | 30 beds, corridors along x at offset 1 m, 0.04 s; 384 m walked, 37 m² corridor |
| CP-SAT, beds stage (30 s, *without* Stage 0) | 19 beds, bound 30 |
| CP-SAT from Stage 0, beds | 30 beds, **proven optimal** on the grid in 8 s (bound 30) |
| CP-SAT, later stages (30 s each) | walking 384 → 347.5 m, corridor 37 → 34.5 m², modifications 2.5 m² (optimal) |
| zone | grown 2 → 3 m (30 beds × 0.25 = 7.5 m² > the 5 m² of the specified zone) |
| validator | 18/18 checks; mean walk 10.8 m, longest 24.2 m |

The zone growth shows the constraint doing its job: the specified zone
(2.5 m × 2 m = 5 m²) holds 20 beds' worth; 30 beds need 7.5 m², so level 1
(3 m deep, 7.5 m²) is chosen, and `M` records the 2.5 m² of growth.

The complex example (`examples.complex_camp()`, 938.5 m², nine sides, four
doors, five obstacles, a fire break, a no-bed exhaust area, a medical zone
needing 4–6 wide beds) is run by `python -m camp_layout complex`; its GeoJSON,
`layout.json`, report and map are in `examples/complex/`.

| Quantity | Value |
|---|---|
| grid | 3 501 walkable / 3 211 bed cells; 10 657 placements; 3 295 tiles; 12 760 arcs; 20 174 access arcs |
| model | 50 460 variables, 76 194 constraints, ~299 000 non-zeros |
| Stage 0 | 167 beds in 1.4 s |
| CP-SAT, beds (300 s) | **169 beds** (165 cots, 4 medical), feasible; bound 377 (the weak LP bound of §14) |
| CP-SAT, distance / corridor / modifications (120 s each) | 2 566 m walked → corridor 235 m² → 39.1 m² of modifications, each stage keeping the ones before |
| zones | D1, D2, D4 grown 2 → 4 m, D3 2 → 3 m: the 0.25 m²/bed rule binds at every door |
| validator | **18/18 checks**; door loads 48/48/35/38; mean walk 13.8 m, longest 34.8 m |

CP-SAT's search is not deterministic across machines and thread timings: an
earlier run of the same model found 172 beds. A longer bed stage, more
threads, or the regional decomposition of §15 narrows that spread.

## 17. Solver-independent pseudocode

```
function LAYOUT(problem, solver, limits):
    assert problem.check() is empty
    geo    ← Geometry(problem)                         # exact polygons
    grid   ← DISCRETIZE(problem, geo)                  # cells, placements, tiles, arcs, bands
    model  ← BUILD(grid)                               # variables, rows by group, objectives
    start  ← STAGE0(grid) ; assert violations(model, start) = ∅
    x      ← start
    extra  ← []
    for obj in problem.objectives.order:               # lexicographic
        r ← solver.solve(model, obj, extra, time = limits[obj], hint = x)
        if r has no solution: break                    # keep the previous answer
        x ← r.values
        extra.append( obj ≥ r.value  if obj = beds and not trade_beds
                      else obj within tolerance of r.value )
    layout ← SHAPES(grid, x)                           # beds, corridor squares, zone depths
    report ← VALIDATE(problem, layout)                 # exact geometry, clearance paths, capacities
    return layout, report                              # success only if report.valid

function DISCRETIZE(problem, geo):
    for each cell: walk_ok if inside camp and off obstacles; bed_ok if also off no-bed areas
    for each door zone and level ℓ ≥ 1: band cells
    tiles  ← all w×w squares of walk_ok cells ; arcs between tiles one cell apart
    for each bed type τ, size, orientation, anchor:
        if slot ⊆ bed_ok cells and (τ.zone = none or slot ⊆ τ.zone) and access tiles exist:
            add placement

function STAGE0(grid):
    best ← none
    for orientation in {x, y}, offset in 0..period−1:
        lines ← tiles on every period-th row/column
        net   ← zone tiles ∪ (each piece of lines joined by a shortest tile path, nearest first)
        beds  ← greedy pack: mandatory types first, smallest slots first, row by row, next to net
        assign beds to nearest door with remaining capacity (door, zone area); drop the rest
        prune tiles no route uses; pack again; reassign; choose shallowest zones that fit
        keep if more beds (then less corridor) than best
    return variable values of best                       # complete and feasible

function VALIDATE(problem, layout):
    exact checks: beds ⊂ camp; beds pairwise disjoint; beds ∩ (obstacles ∪ prohibited ∪ doors ∪ zones) = ∅
                  sizes within ranges; zoned types in zones; counts; doors unchanged
                  corridors ⊂ camp, off obstacles and beds, pieces ≥ w
    walker     ← disc of diameter w (−1 cm tolerance)
    for region in {free floor, corridors ∪ zones ∪ door frames}:
        centres ← region eroded by w/2
        every bed: some point beside the middle half of a long side (out to w/2 + 0.2 m) lies in a
                   piece of centres that also holds a door's entry point
    distances ← Dijkstra on a 0.1 m raster of the corridor centre region
    capacities ← max-flow of beds → reachable doors → sink(capacity) must place every bed
```

---

## 18. Implementation map

```
camp_layout/
  problem.py      A  ProblemDefinition: Door, DoorZone, Obstacle, Prohibited, PlacementZone, BedType, CorridorSpec, ObjectiveSpec
  geometry.py     F  Geometry / collision engine (Shapely): exact polygons, inside / overlaps
  discretize.py      grid, placements, tiles, arcs, zone bands (candidate generation = boundary/obstacle rules)
  model.py        B–E solver-independent MathematicalModel: Var, Expr, Constraint(group), Objective; violations()
  builder.py         ConstraintBuilder + ObjectiveBuilder: the rows and objectives of §5 and §7
  heuristic.py       Stage 0 constructive layout → complete feasible start
  adapters/       H  SolverAdapter interface; cpsat.py (OR-Tools CP-SAT), mip.py (SCIP / HiGHS / CBC)
  optimize.py        lexicographic and weighted drivers
  result.py          LayoutResult: shapes only
  validate.py     G  GeometryValidator + PathValidator (clearance paths, walking distances, capacity max-flow)
  export.py          GeoJSON (local metres and WGS84), report.json, viewer.html
  pipeline.py        the chain of §11: solve(problem, solver=…)
  examples.py        small_camp, complex_camp
  dxf.py             CAD drawing (layers, units, surveyed offset, door blocks) → Drawing; problem → template DXF
  workbook.py        the problem as an .xlsx to review (defaults shaded) and read back; dxf_to_workbook
```

The CAD input enters before `problem.py`: `plan.dxf → dxf.py → camp.xlsx →
workbook.py → CampProblem`. Curves are flattened to within 5 mm of the arc;
a door block covers the stretch of the axis-aligned wall its extent touches;
doors off an axis-aligned wall are reported and skipped, never moved silently.

Adding a solver is one file in `adapters/`. Adding a rule is a candidate
filter (`discretize`), a row group (`builder`) or an objective term — see
the extension table below.

| Extension (spec §14) | Where |
|---|---|
| minimum distance between beds | larger `side_gap`, or a head gap in the slot |
| minimum distance from obstacles | buffer obstacles in `Geometry.no_beds` |
| different bed types / priorities | `BedType` (already: `priority`, counts, zones) |
| door capacities | `Door.capacity` (already) |
| different corridor widths | second tile family (§11) |
| accessibility (wide beds near a door) | a bed type with `zone`, `min_count` (already: medical) |
| zones with capacities | a `count`-style row over placements in the zone |
| fire safety: max walk | per-door commodities + distance labels, or a validator-driven cut loop |
| preferred orientation | a per-placement term in `modifications` |
| mandatory / prohibited zones | `PlacementZone`, `Prohibited` (already) |
| several camp areas / floors | one grid per area; doors between areas become shared source/sink tiles |
| relocating some fixed objects | an obstacle with candidate positions and a choice variable per position |
