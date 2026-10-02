# Five-problem benchmark — unified gap analysis and to-do plan

**Date:** 2026-10-02 · **Base commit:** `529520c` · **Status:** Phases 0–4 done; re-tested (§6)

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
- [x] B2 Solving a scenario left on an older version moves it to the latest first; "Solve version N
      as it is" keeps it — `59b9bd8`.
- [x] B3 Exports: one row per decision cell with its real value — `59b9bd8`.
- [x] B4 A record typed in full in a picker is taken (the scenario change was dropped) — `59b9bd8`.
- [x] B7 Large uploads: rows written together, faster record check (migration 0101), "Writing N
      rows…" — `f968cbb`.
- [x] B8 No copy-to-keep question when the server copy is the same model; a draft already
      published is let go — `3a58d4f`.
- [x] B9, B16, B24 fresh guided form; renamed items followed in every view; `[c, c2]` — `90fca40`.
- [x] B22 a rule card asks whether its note still fits once the rule's arithmetic changes —
      `a29a85a`.
- [x] B10 a block the solver leaves empty keeps a start that holds; route rules no longer
      refused on the runs page — `714e2fa`.
- [x] B11 workbook download with map shapes; message when there are no kinds — B15, B17, B23 —
      `83a1395`, `72d0fbe`.
- [x] B14 runs record the model version they solved (migration 0102) — `472418e`.
- [x] B19 map layers to records: an id-like key, a name property for labels — `472418e`.
- [x] B20 lines kept as lines: the geometry field holds LineString and MultiLineString (migration
      0103); a road overlaps a zone by the metres inside it; maps and reports draw lines.

### Phase 1 — highest lift (target: coverage ≈ 88%)
- [x] **G1a Predictors in models:** formulas may call any trained predictor of the workspace; the
      document declares those it calls on publish; the data section lists them with their inputs —
      `76635d0`. (A rule calling `predict m(field[p], field[c])` scores every parcel × crop in place,
      so no separate "score into a data value" step was needed.)
- [x] **G1b Forecasts:** in the Data menu at both levels; "Predict and keep" writes predictions into
      a number field (all records, or those with no target yet); number fields made from a date
      (weekday, month, day of year), a text (one yes/no per value) or a linked record's number —
      `a3f3be1`.
- [x] **G4a Import safety:** key guessed from stored keys; case/space-insensitive key match; the
      check says how many it makes and updates; a warning when the key matches none of the stored
      records; lat/lon → places (B5); bulk delete — `ca92a35`.
- [x] **G6a Solve settings:** "Look for" beside every Solve (10 s … 30 min, remembered); runs may
      take up to 1,800 s — `890f16b`. (A gap target was not added: the time choice covered the need.)
- [x] **G8a Errors in words:** no raw JSON; plain validation phrases; road/terrain messages say
      what to do; the join limit shown up front — `a92be2a`.

### Phase 2 — modelling reach (target: coverage ≈ 92%)
- [x] **G3a Division of data and scalar data values:** a field computed from a record's numbers
      (`volume / capacity`, kept as data, so models stay linear); data values may be one number
      (migration 0104) read as `budget` — `c5bc682`, `209da97`.
- [x] **G3b Index comparisons in rule conditions** (`b > a`, `b != a`) in every view, and the shape
      "chosen items at least d apart" — `74bf1c5`.
- [x] **G3c Describe → draft model:** in the model editor, "Describe the problem in words" picks the
      recipe the words call for, fills it from the workspace's kinds, fields and data values and
      the numbers written (a budget, "at most 3"), says why for each choice and what is missing,
      and writes it into the draft on request — `0dc011a`.
- [x] **G3d New recipes:** projects within a budget (at most N, always-chosen flag); supply network
      (open, capacity, one supplier each, shortage at a price, vehicles by type); phasing over
      periods with each period's budget, sooner worth more. Each solves to the hand-worked answer
      (`tests/test_recipes.py`) — `da05fee`.
- [x] **G4b Computed joins:** a data value read through a link (`suit[parcel, crop]` from
      `suitability[soil, crop]`) or 1/0 by comparison (`rotation_ok`); totals/counts/means of
      linked records into a field; several key columns make one key; values uploads read columns
      as mapped, with a preview that guesses the index columns from their keys — `2c38f76`,
      `166524c`, `7cba819`, `9c8539b`.
- [x] **G7a Scenario "scale a field"** for all or filtered records (+30 % demand) — `f1976eb`.

### Phase 3 — GIS and results depth (target: coverage ≈ 95%)
- [x] **G2a Keep line geometry end to end:** lines kept as lines (B20); the records' glance map draws
      roads and areas as themselves; a line is in the area holding most of its length; new "From the
      map → the areas each line passes through" links each line to the areas it crosses, with the
      metres inside each — `2256630`.
- [x] **G2b Road network from an imported lines layer:** with no road tiles set, road distances and
      times use the workspace's own lines layer (and say so); a line property that closes a road, one
      of minutes of delay, and a kind of areas no route may enter (flood zones) — each a field of the
      "From the map" form, so a scenario's closures are a second data value computed with them —
      `20cd6eb`.
- [x] **G5a Objective breakdown:** each goal term's value and share, and the records it comes from,
      recorded on every run; shown on the run page, as a "Goal" sheet in Excel and a table in the
      PDF/print report — `2256630`.
- [x] **G5b Result map overlays:** "Show under it" puts any imported map data under the answer;
      "Flows along" draws each flow along the chosen lines layer's roads instead of straight —
      `eac7df4`.
- [x] **G6b Routing:** `depot_of` gives each vehicle its own depot (several depots; a depot of
      another kind through a parent kind holding both); the routing start scales fractional
      distances instead of refusing them — `da4a78a`.

### Phase 4 — navigation (target: UX ≈ 78%)
- [x] **G8b Simple-mode entry points and one vocabulary:** Workspace, Data values and Forecasts at
      both levels (menus, page titles, headings; the page search still finds "domain", "parameters",
      "predictors"); Simple's menus gain "Links between records", and its view switch the Equation
      view, with a one-line hint on the view shown; Simple opens on sentences and remembers its own
      choice — `3b807ab`.
- [x] **G8c Home "What can this app do":** the 16 steps in four stages, each linked to its page in
      the selected workspace (a problem's pages to the problem list until one is open); closing it
      is remembered — `001aaa1`.
- [x] B21 the equation help stays on screen and open when clicked; B23 was fixed in Phase 0 —
      `001aaa1`.

### Re-test
- [x] Re-run the same five problems with fresh testers, same brief and rubric, after Phase 4 (one
      round instead of two): scores in §6.

## 5. Expected effect

| After | Coverage | Navigation/UX |
| --- | --- | --- |
| Today | 79.7% | 65.4% |
| Phase 0 (P4 can finish a solve) | ~83% | ~67% |
| Phase 1 | ~88% | ~71% |
| Phase 2 | ~92% | ~73% |
| Phase 3 | ~95% | ~75% |
| Phase 4 | ~95% | ~78% |

These are estimates from the per-point lifts above, not measurements; the re-test (§6) measured
**89.4% coverage and 76.6% navigation/UX** after Phase 4.

**Not planned here** (outside the app's scope today): raster import (satellite NDVI, elevation),
traffic user-equilibrium assignment, queueing models for ambulance counts, live data feeds.

## 6. Re-test after Phase 4 (round 2)

Five fresh testers, the same five problems, brief and rubric; each made its own data and workspace
("RETEST n — …") and worked only through the UI on the code after Phase 4 (`cfaf53c`). Raw
results: `/tmp/claude-0/bench2/<n>/result.json` and `notes.md` (not in the repository).

| Problem | Coverage R1 → R2 | Navigation/UX R1 → R2 |
| --- | --- | --- |
| 1. Emergency base and supply deployment | 82.8% → **89.1%** | 68.6% → **75.0%** |
| 2. Ambulance and hospital network | 82.8% → **93.8%** | 67.9% → **79.3%** |
| 3. City traffic and infrastructure | 85.9% → **89.1%** | 67.1% → **79.3%** |
| 4. Precision irrigation and crop planning | 62.5% → **81.2%** | 56.4% → **70.0%** |
| 5. National warehouse and distribution | 84.4% → **93.8%** | 67.1% → **79.3%** |
| **Overall** | **79.7% → 89.4%** | **65.4% → 76.6%** |

No point scored Available or Missing in round 2 (round 1: four). Per point, average of five:

| # | Point | R1 | R2 | | # | Point | R1 | R2 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Understand the app | 75 | **100** | | 9 | Constraints | 85 | 85 |
| 2 | Import data | 80 | 80 | | 10 | Verbal → equations | 75 | **70** |
| 3 | Tabular + GIS | 90 | 95 | | 11 | Run optimization | 85 | **100** |
| 4 | Explore | 75 | 85 | | 12 | Prediction / ML | 60 | 75 |
| 5 | Relationships / joins | 85 | **80** | | 13 | What-if | 80 | 95 |
| 6 | GIS layers | 80 | 95 | | 14 | Solution on the map | 70 | 85 |
| 7 | Variables | 100 | 100 | | 15 | Understand the result | 70 | **100** |
| 8 | Objectives | 85 | 90 | | 16 | Export / share | 80 | 95 |

UX sub-scores, R1 → R2: orientation 69 → **88**, finding features 58 → **75**, wording 74 → 77,
feedback 71 → 74, consistency 61 → 67, speed 59 → 71, results 66 → **84**.

### What did not move, and why
- **Point 10, words → equations (75 → 70).** "Describe the problem in words" knows four recipes;
  crop allocation (P4), traffic flow (P3) and coverage-with-capacity (P1) fell outside them, and it
  misread "zone" (P3: construction zones; P1: restricted zones as the thing to cover) and a budget's
  units (P3: EGP vs mEGP). Testers then wrote the model by hand — usable, but the drafter did not help.
- **Point 5, joins (85 → 80).** Joining two tables on a matching code column still needs a links
  file made outside the app (P1, P2, P4); "read through a link" listed only link fields, not links
  made from the map (P2 — fixed below); a table keyed by two columns was refused where the composite
  key exists but was not found (P1, P4).
- **Point 2, import (80).** Same causes as point 5; the values upload took an extra column for an
  index (P5 — fixed below).

### Gaps found in round 2 (R2a–R2h)
- **R2a Join on a matching field** (done: "Link records by a code they hold" under Records → Compute and
  join, matching another kind's key, name or a field, case and spaces aside, listing what did not match): link records of two kinds where a field of one equals the key
  (or a field) of the other — call history to districts by `dist_code`, yield history to parcels —
  without a links file. (P1, P2, P4)
- **R2b Describe → draft for more shapes** (done in part: an allocation recipe — land among crops, a
  shared limit, where allowed, least and most shares — in words and as a form; coverage covers what the
  reach data joins the sites to and seats people where sites have a capacity; a budget typed in pounds
  is read in the costs' units, millions or thousands. Network flow with an origin–destination table
  is still to do): allocation of an area/amount among options (crops),
  coverage with capacity and cost, network flow with an origin–destination table; read units and
  the thing to cover from the data's own names, not only from words. (P1, P3, P4)
- **R2c Forecasts as data per record:** a forecast's inputs read from the record and its links
  (road attributes through a link; customer fields), written as a data value per record and period
  to drive the plan — today a rule calls it with constants. Time-series features (lags, horizons).
  (P2, P3, P5)
- **R2d What-ifs that recompute map data** (done: a scenario that scales a distance or a travel time
  makes the "within" 0/1 data computed from it again, in its units -- `rederive` -- and a scaled data
  value's default is now scaled too; per-period road speeds still to do): a scenario that scales travel times should recompute
  the 0/1 "within 30 minutes" data, or let reach be written as `travel_min <= 30` over the scaled
  times; per-period road speeds. (P1)
- **R2e Multi-product inventory and routing tied to location:** stock and flows per product; vehicle
  routes from the depots the location model opens. (P5)
- **R2f Water as a decision feeding a yield model** (a predictor over a decision). (P4)
- **R2g Make the existing joins findable** (done: the records' panel is "Compute and join" and points to
  the computed data values; the import says two columns can make one key when a key's values repeat): the composite key ("several columns read as the key"),
  computed data values and "read through a link" were not found by two testers who needed them.
- **R2h Analytics banner** (done: hidden until it is back): "the analytics store reported an error" shows on every page when
  ClickHouse is not running (all five); say it once, where analytics are used.

### Bugs from round 2, and what was fixed after it
- [x] "The dataset carries no predictor … frozen before the model declared it" on the problem
      Overview and a scenario's pre-solve check, with no Solve (P3, P4, P5): the checks built
      today's data without the trained models — `live_data` now carries them.
- [x] "See what stops it" seemed to do nothing (P3, P4): it now scrolls, focuses and lights the check.
- [x] A goal weight of 0.5 was reset to 1 (P4, P5): weights are any number, in the contract, both
      validators and the editor.
- [x] "Read through a link" offered no links where kinds were linked by relationships (P2): it reads
      relationships from either end, a record with several linked ones taking their mean.
- [x] "Flows along" drew straight lines (P5): places up to 20 km off the roads now join them; the
      caption says how many flows follow the roads; drawn ways simplified (10,000 points → 13).
- [x] A values upload read an extra column as an index and failed (P5): unmatched columns are left out.
- [x] Make records with "grid cell" refused the layer with only a headline (P2): kinds named in
      words become names, and every refusal lists its faults.
- [x] Run comparison: list "3 added" vs map "+13" (P2, P3) — one direction; "Objective change 0"
      when a second goal doubled (P1) — every goal's change is listed.
- [x] The GeoJSON and map gave each parcel the value 1, not its planted area, and the map could not
      show the crop per parcel (P4): each place carries its total, its amount per crop and its main
      crop; "Colour areas by: largest …" colours by it, with a key.
- [x] PDF numbers like 6.52646e+07 (P4): written 65,264,600.
- [x] The sweep accepted text and offered "Solve 0 times" (P1); "Approve" with no reason did nothing
      (P3): both say what they need.
- [x] The Start page's description was not carried into "Describe the problem in words" (P1, P5).
- [x] A new blank rule opened in Boxes with Equation chosen (P3, P5): it opens as an equation.
- [x] Read-back dropped brackets (P2, P3) and said "whose after c" (P1).
- [x] A note kept "at least 10000 apart" after the rule became 5 (P1): a note follows its rule's one
      changed number.
- [x] HTTP 409 on draft saves when adding rules quickly (P1, P4, P5): saves go one at a time per problem.
- [x] Import preview repeated a sparse column's first value (P3): its different values, and how many rows are filled.
- [x] Empty browser dialogs when leaving the model editor (P2): no prompt for a draft kept in the browser.
- [x] A queued run named a solver it did not use (P2): "chosen when it starts".

