# Five-problem benchmark — unified gap analysis and to-do plan

**Date:** 2026-10-02 · **Base commit:** `529520c` · **Status:** plan, not started

Five testers, each a new user with one hard real-world problem, worked only through the UI with no
prepared workflow. Each brought synthetic tabular data (CSV/Excel) and GIS data (GeoJSON points,
lines and polygons) from one region of Egypt, and scored 16 points of the problem-solving path on a
fixed scale: Sufficient 100, Usable 75, Discoverable 50, Available 25, Missing 0. Raw results:
`/tmp/claude-0/bench/<n>/result.json` and `notes.md` (not in the repository).

## 1. Scores

| Problem | Coverage | Navigation/UX |
| --- | --- | --- |
| 1. Emergency base and supply deployment (Sinai) | 82.8% | 68.6% |
| 2. Ambulance and hospital network (Giza) | 82.8% | 67.9% |
| 3. City traffic and infrastructure | 85.9% | 67.1% |
| 4. Precision irrigation and crop planning | 62.5% | 56.4% |
| 5. National warehouse and distribution | 84.4% | 67.1% |
| **Overall** | **79.7%** | **65.4%** |

Problem 4 is low mainly because the API froze on its first solve, so points 11 and 13–16 were never
really tested. That freeze, hit by four of the five testers, is fixed in `529520c` (the run-events
stream did database work on the event loop).

### Per point (S 100 · U 75 · D 50 · A 25)

| # | Point | P1 | P2 | P3 | P4 | P5 | Avg |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Understand what the app does | U | U | U | U | U | 75 |
| 2 | Import data | S | U | U | U | U | 80 |
| 3 | Combine tabular + GIS | U | S | S | U | S | 90 |
| 4 | Explore the data | U | U | U | U | U | 75 |
| 5 | Relationships / joins | S | U | S | U | U | 85 |
| 6 | GIS layers | U | U | U | U | S | 80 |
| 7 | Variables | S | S | S | S | S | 100 |
| 8 | Objectives | S | U | U | U | S | 85 |
| 9 | Constraints | U | U | S | U | S | 85 |
| 10 | Verbal problem → equations | U | U | U | U | U | 75 |
| 11 | Run optimization | S | S | S | D | U | 85 |
| 12 | Prediction / ML | D | D | U | D | U | **60** |
| 13 | What-if | S | U | S | A | S | 80 |
| 14 | Solution on the map | U | S | U | A | U | 70 |
| 15 | Understand the result | U | S | U | A | U | 70 |
| 16 | Export / share | U | S | S | D | U | 80 |

UX sub-scores (mean of five): orientation 69, finding features **58**, wording 74, feedback 71,
consistency 61, speed of doing a task **59**, clarity of results 66.

## 2. Unified gaps

Each gap is one root cause seen across problems. "Points" are the rubric points it holds down;
"Seen in" lists the problems. Claims were checked against the code where it mattered (noted).

### G1. Prediction does not reach the plan — points 12, 10 · seen in 1, 2, 3, 4, 5
- The IR already supports `predictors` and `predict name(...)` (`ir/validate.py`), but no control in
  the model editor (Guided form, Boxes, Blocks, data list) declares one, so every attempt ends in
  "X is not a predictor this model declares". Confirmed in code.
- Predictors page is in no menu (found by Ctrl-K only) and only in Expert mode.
- Features: numeric fields of the same record only. No categorical inputs (weather, soil code,
  incident type), no features through links (observation → road, yield → parcel), no date parts.
- No "predict for these records" view and no "score into a data value" (e.g. yield[parcel, crop],
  calls[district, day]), which is how a forecast would feed an optimization.

### G2. Line geometry and road travel — points 6, 14, 9 · seen in 1, 2, 3, 4, 5
- Line layers become records with a midpoint and a length; records table and result map show dots.
- "Along the roads" fails with raw JSON when `spatial.tiles_index` is unset (confirmed:
  `api/distances.py`); there is no fallback to an imported roads layer.
- "Along a lines layer" hides the distance box and always uses 5 km; a join distance over 20 km is a
  raw validation error with no hint of the maximum.
- Network travel ignores no-go polygons; per-road closures/delays can only be a global scale.
- No line-vs-polygon test (road widening inside a construction zone).

### G3. From words to a model — points 10, 8, 9, 1 · seen in all five
- "Describe the problem in your own words" returns keyword pointers, not a draft model.
- Beyond the coverage recipe, rules are built one dropdown at a time or typed in Expert mode.
- Missing expressiveness (confirmed: no division op in the IR contract): division of data
  (volume/capacity, length/speed), conditions comparing two indices (`a != b`, `a < b`), scalar
  data values, piecewise helper for congestion curves surfaced in the editor.
- Missing ready shapes: budgeted project selection (knapsack), network design (multi-commodity
  facility location with single sourcing, shortage and fleet by type), k-coverage, min distance
  between chosen sites, multi-period phasing.

### G4. Joins, imports and keys — points 2, 5, 4 · seen in 2, 3, 4, 5
- Key auto-guess picks the wrong column and duplicates records (3 testers); matching is
  case-sensitive (h001 vs H001); "Check only" says "all clean" in all of these cases.
- No bulk delete to undo it.
- Lat/lon columns in a records CSV do not become places, although the page says so (2 testers).
- Data-value (parameter) imports have no column mapping; composite keys need an artificial id.
- No computed joins: lookup table → data value (soil_code × suitability → suit[parcel, crop]),
  field comparison → 0/1 (prev_crop ≠ crop), total of linked records into a field (calls per
  district).
- The first 2,880-row upload silently wrote nothing; the second identical one worked.

### G5. Results depth — points 15, 14, 16 · seen in 1, 3, 5
- Only the objective total; no breakdown by goal term (fixed / transport / time / shortage) or per
  record (cost per warehouse, service per customer).
- Result map cannot overlay other layers (roads, zones, incidents) and draws flows as straight lines.
- Garbled goal sentence on the run page ("Peak volume vph and capacity vph and …").
- Comparison across model versions says "differ only by data".

### G6. Solver control and routing — point 11 · seen in 5 (and 3, 4)
- No time-limit or gap control: the UI always sends `time_limit_s: 30` (confirmed: `Runs.tsx`,
  `Scenarios.tsx`) while the run page advises "try a longer time limit".
- Vehicle routes: depot must be one of the stop records, single depot only, and a run that found a
  119-stop warm-start route ended "unknown" with no plan.

### G7. What-if breadth — point 13 · seen in 1, 2, 3
- No "scale a field for all records" (+30 % demand) in a scenario; a single-record change in a
  scenario did not save.
- Solving after publishing v2 silently runs the Base scenario on v1 until "Move this scenario".

### G8. Navigation and Expert-only features — UX finding/consistency · seen in all five
- Predictors, equations and relationships are reachable only in Expert mode; Expert renames
  Workspace → Domain and Data values → Parameters.
- Raw JSON errors in several places (tile index, name conflict, validation limits).
- Equation help closes when clicked; model editor 409 on a new browser session; publish 409 leaves a
  stale draft.

## 3. Bugs (from the testers, with the gap they belong to)

| # | Bug | Severity | Gap |
| --- | --- | --- | --- |
| B1 | API froze on solve (stream blocked the event loop) | Blocker | — **fixed `529520c`** |
| B2 | Solve uses the old version after publishing; scenario not moved | High | G7 |
| B3 | CSV/Excel export adds a spurious value-1 row per non-binary decision; Excel duplicates rows | High | G5 |
| B4 | Single-record change in a scenario not saved | High | G7 |
| B5 | Records CSV with lat/lon does not create places | High | G4 |
| B6 | Key auto-guess and case-sensitive match create duplicates; "Check only" says clean | High | G4 |
| B7 | First large CSV upload silently writes nothing | High | G4 |
| B8 | Model editor 409 on reopening in a new session; publish 409 leaves stale draft | High | G8 |
| B9 | Guided form keeps previous decision's index boxes ticked | Medium | G3 |
| B10 | Vehicle-routes run ends "unknown" despite a warm-start route | Medium | G6 |
| B11 | Workbook "With what is stored" 500; "Empty template" 404 with no kinds | Medium | G4 |
| B12 | "Along a lines layer" ignores the distance (5 km); >20 km is raw JSON | Medium | G2 |
| B13 | Raw JSON errors: tile index, name conflict, validation limits | Medium | G8 |
| B14 | Run comparison across versions says "differ only by data" | Medium | G5 |
| B15 | Garbled goal sentence on the run page | Medium | G5 |
| B16 | Renaming an index leaves dangling references | Medium | G3 |
| B17 | Names typed for map-computed values ignored ("area_of", "distance") | Medium | G2 |
| B18 | Link field name must be unique across the workspace (409) | Medium | G4 |
| B19 | Feature names lost when a map layer becomes records (label "—") | Medium | G2 |
| B20 | Line features shown as points in records | Low | G2 |
| B21 | Equation help disappears on click | Low | G8 |
| B22 | Recipe rule keeps its old note after editing | Low | G3 |
| B23 | After deleting a record, lands on another kind and refetches the deleted id | Low | G8 |
| B24 | Cost-goal shape pre-fills a diagonal index `cc_km[c, c]` | Low | G3 |

## 4. To-do plan

Ordered by coverage gained per unit of work. Each item lists its acceptance check. Estimates of
lift are per point, averaged over the five problems.

### Phase 0 — correctness (bugs that give wrong answers or lose work)
- [x] B1 API freeze on solve — `529520c`.
- [ ] B2 After publishing, offer to move every scenario on the old version (default yes); the solve
      button names the version it solves. *Check:* publish v2, Solve → run is on v2.
- [ ] B3 Exports: one row per decision cell with its real value; Excel sheets without duplicates.
      *Check:* export test on a model with integer + continuous + binary decisions.
- [ ] B4 Scenario record changes persist and apply. *Check:* scenario with one changed value solves
      differently, and Edit shows the change.
- [ ] B7 Large upload writes on the first try or says why not. *Check:* 3,000-row upload test.
- [ ] B8 Draft conflicts: no 409 when the same user reopens; publish after equation edits works.
- [ ] B9, B16, B22, B24 model-editor correctness (reset index boxes; renames propagate; notes
      follow edits; shape fills `[c, c2]`).
- [ ] B10 Routing returns the best route found (warm start) instead of "unknown".
- [ ] B11, B14, B15, B17, B19, B20, B23 smaller fixes.

### Phase 1 — highest lift (target: coverage ≈ 88%)
- [ ] **G1a Declare predictors in the model editor** (data list "Predictions" + a Boxes/Blocks
      term) and **score a predictor into a data value** for chosen records (e.g. every parcel ×
      crop). *Check:* yield predictor → `yield[parcel, crop]` → used in the crop-plan goal. Point
      12: 60 → ~80.
- [ ] **G1b Predictors in the menu (both levels)**, a "predict for these records" table, date parts
      as features. Point 12 → ~85; UX finding +.
- [ ] **G4a Import safety:** key guess prefers a column whose values match existing keys;
      case/space-insensitive match; "Check only" reports "will update N / create M" and warns
      when it would create duplicates; bulk delete of selected records; lat/lon → places (B5).
      Point 2: 80 → ~95.
- [ ] **G6a Solve settings:** time limit and gap target on Solve (Simple: "quick / thorough /
      until proven"). Point 11 +5.
- [ ] **G8a Errors in words:** map every 4xx `detail` to a sentence with the next step; field
      maxima shown up front (B12, B13). UX feedback +.

### Phase 2 — modelling reach (target: coverage ≈ 92%)
- [ ] **G3a Division of data and scalar data values** in formulas and the IR (data only, so models
      stay linear). *Check:* `volume[r] / capacity[r]` as a weight.
- [ ] **G3b Index comparisons in rule conditions** (`a != b`, `a < b`) and shapes for "at least k
      sites within reach" and "chosen sites at least d apart".
- [ ] **G3c Describe → draft model:** from the description and the workspace's kinds and computed
      data, propose sets, decisions, rules and goals (reusing recipes) for review, not just pointers.
      Point 10: 75 → ~90.
- [ ] **G3d New recipes:** budgeted project selection; network design (capacity, single sourcing,
      shortage, fleet by vehicle type); multi-period phasing with yearly budgets.
- [ ] **G4b Computed joins:** lookup table → data value; field comparison → 0/1; total/count of
      linked records into a field; composite keys and column mapping for data-value imports.
      Point 5: 85 → ~95.
- [ ] **G7a Scenario "scale a field"** for all or filtered records (+30 % demand). Point 13 +5.

### Phase 3 — GIS and results depth (target: coverage ≈ 95%)
- [ ] **G2a Keep line geometry end to end:** records keep LineStrings; records table, layers and
      result map draw lines; line-in-polygon test for rules.
- [ ] **G2b Road network from an imported lines layer** (snap, build graph, travel time with the
      user's threshold) as the fallback when no tile index is set; no-go polygons as barriers;
      per-road delay/closure fields used per scenario. Point 6: 80 → ~95.
- [ ] **G5a Objective breakdown** by goal term and per record on the run page, PDF and exports.
      Point 15: 70 → ~90.
- [ ] **G5b Result map overlays** of any layer (roads, zones, incident heat) and flows drawn along
      roads. Point 14: 70 → ~90.
- [ ] **G6b Routing:** depot from another kind, several depots, fractional distances.

### Phase 4 — navigation (target: UX ≈ 78%)
- [ ] **G8b Simple-mode entry points** for equations, predictors and relationships (with a one-line
      hint), and one vocabulary across levels (Workspace / Data values in Expert too).
- [ ] **G8c Home "What can this app do"** with the 16-step path and where each step lives
      (point 1: 75 → ~90; orientation +).
- [ ] B21 equation help stays open; consistent page after delete (B23).

### Re-test
- [ ] Re-run the same five problems with fresh testers after Phase 1 and after Phase 3, same brief
      and rubric, and add the scores to this document.

## 5. Expected effect

| After | Coverage | Navigation/UX |
| --- | --- | --- |
| Today | 79.7% | 65.4% |
| Phase 0 (P4 can finish a solve) | ~83% | ~67% |
| Phase 1 | ~88% | ~71% |
| Phase 2 | ~92% | ~73% |
| Phase 3 | ~95% | ~75% |
| Phase 4 | ~95% | ~78% |

These are estimates from the per-point lifts above, not measurements; the re-tests replace them.

**Not planned here** (outside the app's scope today): raster import (satellite NDVI, elevation),
traffic user-equilibrium assignment, queueing models for ambulance counts, live data feeds.
