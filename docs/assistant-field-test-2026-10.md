# Assistant field test: the platform's Assistant and an independent solution of the same problem

4 October 2026. The *Describe a problem* Assistant (vLLM `qwen3.5`, 32k context), driven end to end on
the live platform as a user would: a problem in plain words, three attached CSV files, answers to its
questions, approval. In parallel the same problem was solved independently (Python + HiGHS) as a
reference. Three runs: before any change, after the first fixes, after the second.

## The problem

*"Which of our 5 candidate warehouses should we open, and which warehouse serves each of our 12
customers, as cheaply as possible?"*

| File | Rows | Columns |
|---|---|---|
| warehouses.csv | 5 | warehouse, latitude, longitude, capacity_tons_per_month, fixed_cost_egp_per_month |
| customers.csv | 12 | customer, latitude, longitude, demand_tons_per_month |
| lanes.csv | 60 | warehouse, customer, road_km, cost_egp_per_ton |

Given only in the conversation, when asked: at most 3 warehouses; no lane over 450 road km; each
customer served by exactly one warehouse, in full; capacity is hard; everything per month.

**Reference answer** (independent, HiGHS): open Cairo-6Oct, Tanta, Assiut; **1,338,765 EGP/month**
(fixed 860,000 + transport 478,765). Cairo-6Oct serves Cairo, Giza, Tanta, Zagazig, Suez, Ismailia
(885 t of 900); Tanta serves Alexandria, Mansoura, Port Said (490 of 500); Assiut serves Minya, Assiut,
Sohag (280 of 400). Sohag can only be reached from Assiut within 450 km, so Assiut must open.

## Results

| | Run 1 (before) | Run 2 (first fixes) | Run 3 (second fixes) |
|---|---|---|---|
| Interview | good questions; **2 arithmetic errors** | exact totals | exact totals |
| Model | **never produced** (looped to the length limit twice) | checked OK but **wrong goal** | **correct**, same as the reference |
| Solve | — | **every run crashed** (re-queued 12 times) | optimal in 0.01 s |
| Answer | — | — | **1,338,765 EGP, same warehouses, same 12 assignments** |
| Time to answer | — | — | about 15 minutes, mostly model thinking |

## Findings and changes

| # | Seen | Cause | Change | Where |
|---|---|---|---|---|
| 1 | Total capacity "2,450" (is 2,850); "11 lanes" over 450 km (are 13). | The model added and counted in its head. | Each attached sheet carries exact totals (sum/min/max per number column, distinct per text column). New tool `query_file`: filter, count, sum, group exactly. Prompt forbids mental arithmetic. | agent/files.py, core.py |
| 2 | Twice, 28,000 characters of "Actually... let me..." shown as the answer. | Qwen's thinking ran to the length limit with no tool call; the loop delivered whatever came back. | Such a reply is never shown and never enters the history: the step is asked again with thinking off, then the model is told; at the end one honest line. | core.py (`RAMBLED`) |
| 3 | Stuck on "only lanes ≤ 450 km". | No pattern for a value per pair. | Prompt pattern: `lane_km[w,c] * assign[w,c] <= 450` (and `>=` form); one file column per parameter. | core.py (PATTERNS) |
| 4 | Same call refused 3 times ("duplicate key entity_types"), then an empty answer. | Qwen splits a long list over two same-named keys; the model never sees its own broken call. | Two lists under one key are joined (objects merged), and the model told; two different values still refused, naming both. JSON errors say where they broke. Empty answer sent back. | agent/toolcall.py, core.py |
| 5 | (Earlier) spec written in the reply. | — | In model mode a spec in the reply is run through `check_spec` for the model. | core.py |
| 6 | **Plan passed every check with the wrong goal**: `delivery_cost_egp[w,c]`, default 999,999,999, never loaded. Every lane cost the same; transport would not have mattered; the summary claimed "cost/ton × demand". | Nothing checks that a parameter the model reads has data. | A parameter indexed by records that the model uses and nothing loads is refused, with how to compute it instead (nested `mul`). | core.py (`_empty_parameters`) |
| 7 | **Every run crashed**: "current transaction is aborted". | A platform defect: `numeric(15, 6)` (migration 0015) holds 9 integer digits, not 15; an objective of 12,000,849,988 could not be saved. The status read after the failure then hid the real error. | Migration **0107**: quantities `numeric(24, 6)` (18 integer digits) on parameter values and defaults, run objective, constraint results, suite nightly. API still takes 15 significant digits. The worker rolls back before its last read, so the real error is recorded. | alembic 0107, models, api/quantity.py, solve/service.py |
| 8 | Failed run re-queued 12 times until the 30-step limit. | The model never read the run's error. | A scenario can be queued at most twice per turn; a failed run comes back with a note to report its error. Prompt: never re-queue unchanged. | core.py |
| 9 | "mul has exactly two factors" three times in a row. | The message said what, not how. | The message shows the fix: `a*b*c = {"mul":[{"mul":[a,b]},c]}` (server and Model Editor alike). | ir/validate.py, frontend ir/validate.ts |

Tests: `backend/tests/test_agent_field_test.py` (12): exact totals and `query_file`; the problem written
with the pattern **builds and solves on the platform to 1,338,765**; rambling, spec-as-text, empty
answer, joined keys; the unloaded parameter refused; an objective past a billion saved; no endless
re-queue.

## Still open (not changed)

- **Speed.** Qwen thinks 1-5 minutes per step; one thinking step ran 5 minutes before the guard cut it.
  Options: `LLM_THINKING=off` for the Describe tab (faster, possibly weaker models), or a thinking budget
  if the vLLM build supports one.
- **Report quality.** The final table showed demand for only 2 of 12 customers ("-" for the rest) and
  an odd "255 km slack". The answer was right; the report could join the run's assignments with the
  records' fields itself.
- **Leftovers in the workspace.** Run 3 found run 2's domain and reused its limits as defaults. It asked
  before using them, which is right, but a test should start from an empty organization.
- A CSV with latitude/longitude is treated as a map file (extra feature/kind/geometry columns). Harmless
  here, but noisy for a plain data sheet.

## Second field test: a week's nurse roster

A harder class: time (7 days × 3 shifts), a rule across consecutive days, a pay factor by shift, days-off
requests as a soft goal, and two goals in order. Files: nurses.csv (9 nurses: grade, wage, max shifts),
cover.csv (21 day/shift rows: nurses and seniors needed), requests_off.csv (8 days off asked for).
Rules given when asked: at most one shift a day; no morning right after a night (within the week); cover
and seniors are minimums; night pays 1.3×; first break as few requests as possible, then cheapest.

**Reference** (HiGHS, lexicographic): **2 requests broken** (Friday: 3 of the 4 seniors asked off, every
shift needs a senior), then **37,650 EGP**. The platform solves the same model to the same answer when
written with the patterns below (`test_the_roster_built_with_the_patterns_solves_to_the_reference`).

| Run | What happened |
|---|---|
| 1 | Good interview (found the Friday problem itself; one slip, "24" senior shifts for 23). Then three long specs refused for JSON errors (closers in the wrong order; an invented `if/else`), and the turn ended in empty replies. |
| 2 | Numbers all exact via query_file. Over-asked (a coordinate system for a roster). After 20 minutes, a plan **that passed every check but was wrong**: the goal "fewest broken requests" counted every shift worked (it came out as 47), the requests it loaded were never read, and a Saturday→Sunday link wrapped the week. Then the turn crashed: the history (four 10,000-character specs) overflowed the 32k context. |
| 3 | After the fixes below: see the end of this section. |

| # | Seen | Change |
|---|---|---|
| 10 | Report listed demand for 2 of 12 customers ("-" for the rest). | New tool **`read_result`** (`GET /api/v1/agent/result/{run}`): goal and its parts, each decision joined with its records' names and numbers, totals per record, rules held / tight / broken; the model reports from it. |
| 11 | `}]}}]}}}}}}` ending a 10,000-character spec, three times. | `toolcall.fix_closers`: only the final run of closing brackets is rebuilt from what is open; for check_spec / propose_plan only (checked and reviewed before anything is built). |
| 12 | A file that only lists pairs (days off asked) had no value column to load. | `parameter_values_from_file` takes `"value": 1` (a number for every row): a 0/1 parameter. |
| 13 | No idea how to write "no morning after a night", "night pays 1.3". | Prompt patterns: relationship `next_day` + `via`; `where id = "night"`; a parameter by kind (`pay_factor[shift]`); requests as a 0/1 parameter counted in a goal. |
| 14 | `work[n, d, "night"]`, refused again and again. | The Assistant binds a record named by its key: `k_night` over shift where id = "night" (one record, nothing else changes). The validator's message now shows that binding too. |
| 15 | Three broken calls used the shared budget of 3 corrections; an empty reply then ended the turn. | Each kind of correction has its own budget (3), with 8 in all. A call left inside Qwen's thinking (`reasoning_content`) is taken from there. |
| 16 | 42 identical "no parameter named 'nurses_needed'" lines; `has no column "None"`; "a filter names an attribute…"; "this names none of them". | Each says what was given and how to fix it, once. |
| 17 | Asked for a coordinate system, a domain name, and things already answered. | Prompt: ask only what changes the model; after "nothing else / go ahead", propose with assumptions. |
| 18 | **Wrong goal passed every check** (requests loaded, never read). | A parameter that holds data no rule or goal reads is refused, with how to use it. |
| 19 | **Context overflow** ended the turn (24,577 + 8,192 > 32,768). | Earlier check_spec specs are shortened like earlier plans; 2.0 characters a token, not 2.5; a "context length" refusal is retried with a smaller reply allowance or a shorter history. |

Still open: the Saturday→Sunday wrap (a modelling choice against what the user said) cannot be caught by a
check; the plan summary must show the links so the person can see it. Qwen still takes 2–5 minutes per
spec; a roster spec is 10,000 characters, and every correction costs another such reply.
