# The Assistant as a modeller — a build protocol instead of a prompt

**11 October 2026.** The plan that follows the architecture review of the same day: the solver side is the
asset, the modelling side is the risk, and the way to a professional general-purpose solver is to stop asking the
language model for a whole model in one reply. It continues `2026-10-10-neutrality-plan.md` (whose rules and
"done when" stay in force) and `2026-10-11-issues-and-plan.md` (whose items A–F it absorbs).

**What changes, in one paragraph.** Today the Assistant writes the entire model (records, data, decisions, rules,
goal: ~30,000 characters of JSON) in one reply, and the platform validates only whole specs; around that sit
repairs, guards and nudges added one incident at a time. After this plan the Assistant builds in stages, each
stage a small reply the platform checks as it arrives; the modelling knowledge lives in the platform as a tested
library of constructs; every repair is one documented canonical form; and every change is judged in an hour on
a corpus that needs no language model, before it is judged on the hidden set.

**Principles that do not change:** domain-neutral (the build check fails on a field's word in anything the
Assistant or the person reads); general (every check and repair reads the shape of the model or the data, never
a name); isolated (nothing reaches outside the machine; the model is on the LAN); one image per measurement;
nothing deployed during a hidden run.

---

## Phase 0 — Measure fast and true (days 1–3)

Everything after this phase is judged by what this phase builds. Nothing here touches the live stack.

| # | Work item | Where | Verified by | Exit |
|---|---|---|---|---|
| 0.1 | **Parallel tuning runs.** A runner that drives up to 3 cases at once (3 browser contexts, distinct workspace names — already unique per case), each with its own run folder; the 20-minute limit becomes 25 under concurrency. | `backend/bench/phase1/run_parallel.sh` (new), `drive_case.mjs` (no change: one case per process) | three serial runs vs three parallel runs of the same image give right-counts within one case; per-case minutes recorded with the concurrency level | a 10-case set in ≤ 1 hour; three runs in an evening |
| 0.2 | **Gold models.** For every tuning case, the model that reaches the reference, captured from a right run (the problem's model version and frozen seed, through the API) into `bench/phase1/gold/<p>-S.json`; for the hidden set the same, captured blind (the tool prints nothing). | `backend/bench/phase1/gold.py` (new): `capture <run folder>`, `check [tag]` | `check` sends each gold through `/from-spec` with `dry_run` + `trial` and compares the trial's goal with `expected.json`; runs in the test image, no LLM | every tuning case has a gold that reaches its reference; `check` runs in < 5 minutes |
| 0.3 | **Mutation checks.** From each gold, known-wrong variants: drop one hard rule; give a loaded list its default's value; reverse the goal's sense; remove a parameter's values; read a pair parameter on an unlisted pair. For each variant, the platform's checks must raise a warning (shape findings, trial flags, unused numbers, used-without-data). | `backend/bench/phase1/mutate.py` (new); the table mutation × check in `docs/plans/mutation-coverage.md` (generated) | each (gold, mutation) pair: warned / not warned; a not-warned pair is a listed gap, never silent | every mutation class caught by at least one check, or on the gap list with an owner |
| 0.4 | **Time split per case.** The Assistant emits a `timing` event per model call (seconds, prompt and reply tokens, stage); the driver writes them to the run folder; `causes.py` splits each case's minutes into model time, platform time, waiting. | `app/agent/core.py` (`llm_chat` caller), `drive_case.mjs`, `causes.py` | the split adds up to the case's minutes within 5 % | every "not built" names its cause in counts |

Governance from here on: **no platform change is measured on the tuning set in the browser before it passes
0.2 and 0.3.** The corpus is the first gate, the browser the second, the hidden set the third.

## Phase 1 — One canonical form (days 4–6)

| # | Work item | Where | Verified by | Exit |
|---|---|---|---|---|
| 1.1 | **Inventory.** Every repair and inference now scattered: `repair.py` (spec_of, misplaced, joined_keys, repair, _scalar_indices, _bound_rules, _walk), `core.py` (bind_literal_keys, the guards), `toolcall.py` (mend_brackets, strict_loads), `files.py` (list default), `idioms.py`. Each classified: *canonicalisation* (one spelling → the contract's), *inference* (something the model left implicit, derivable from the spec), *heuristic* (a guess). | `docs/plans/canonical-form.md` (new) | the inventory lists every function with its class and the corpus case it came from | complete |
| 1.2 | **`canonical(spec) -> (spec, notes)`.** One ordered pass, each rule a small named function with a docstring, an example and a test; the pydantic contract applied after it. Canonicalisations and tested inferences move in; heuristics become notes to the model (never silent edits) or are deleted. | `app/agent/canon.py` (new); `repair.py` reduced to a thin call | unit test per rule; **fixed point on the corpus:** `canonical(gold) == gold` for every gold model; every mutation still warned after canonicalisation | complete (13 Oct: `repair.py` gone; no `re` in `canon.py`) |
| 1.3 | **Refusals that name the fix.** Every contract refusal the corpus can provoke carries the canonical spelling in its message (as the over-without-sum case should have). | `app/ir/validate.py`, `app/api/model_spec.py` | a test that every refusal kind seen in the runs' `causes` tables has a "write it as" clause | complete (13 Oct: `tests/test_refusals_name_the_fix.py`, the five kinds the tuning runs recorded) |

## Phase 2 — The constructs library (days 7–10)

The modelling knowledge in the platform, deterministic and tested, so the model *selects and fills* and never
hand-writes the algebra. `idioms.py` is the seed; it grows into a package.

| # | Construct | Expands to | Test (hand-worked optimum) | Mutation it must refuse |
|---|---|---|---|---|
| 2.1 | **carried** — a quantity carried between periods, starting amount in the first period, optional backlog | the period links, the balance, the end rule | 15 (exists) | the starting amount in every period |
| 2.2 | **allowed pairs** — complete list, or partial list restricting only the records it names | `amount <= most × pair[r,o]`, or `amount <= most × (1 − listed[r] + pair[r,o])` | a two-task assignment (exists for the complete form) | a partial list with default 1 |
| 2.3 | **largest_of** — overlapping effects, the best chosen counts | the `_best` binaries and three rules (exists) | 50 (exists) | `level >= value × pick` |
| 2.4 | **exactly_one / at_most_one** per group | one sum rule (exists) | 7 (exists) | — |
| 2.5 | **covering** — every requirement met by at least one chosen option | sum of open over the options that cover it ≥ 1 | a 4-site cover | — |
| 2.6 | **only_if** — an amount only when chosen, fixed charge | `amount <= most × chosen` and the charge in the goal (exists) | — | missing `most` |
| 2.7 | **share_of_total** — at least/at most a share of a mix | the linear form | a 3-ingredient blend | the division written as is |
| 2.8 | **next_in_order** — links from an ordering field | `relationships_in_order` (exists in the seed) | — | — |
| 2.9 | **used_only_where_given** — a decision kept to the pairs a parameter is given for | `amount <= most × given[r,o]` (given = 1 where the parameter has a cell) | the machine-times case | — |

Each construct: `app/agent/constructs/<name>.py` with its field schema, the expansion, the test, the refusal,
and a neutral one-paragraph description that the Phase 3 instructions include verbatim (the neutrality test
scans them). **Exit:** every hard rule of every tuning gold model is a construct or a plain linear rule; all
construct tests pass; the mutation table shows each construct's refusal.

## Phase 3 — The build protocol (days 11–18)

The Assistant builds in stages through tool calls; the platform holds the draft, checks each stage and
assembles the plan. Small replies, each checked; no 30,000-character JSON.

### 3.1 The stages and their tools

| Stage | Tool the Assistant calls | What the platform does at once | What it returns |
|---|---|---|---|
| Data | `stage_data({entity_types, parameters, *_from_file, entities, ...})` | loads (pasted tables and files), canonicalises, stores the draft's seed | the load report per entry (rows, kept, skipped, stored), the records per kind, each parameter's cells and default — and refusals per entry, not for the whole |
| Decisions | `stage_decisions({variables})` | checks every index set has records; bounds | the decisions as read back |
| Rules | `add_rule({sentence, rule})` — **one at a time**, the request's sentence quoted | canonicalises the one rule, compiles it against the staged data (its range, the data it reads), runs the shape checks on the draft so far | "rule c_x holds sentence '…', ranges over 24 pairs, reads cost and is_open" — or the refusal with the fix |
| Goal | `stage_goal({objective})` | compiles; checks every term's data | the goal as read back |
| Propose | `propose_plan({summary})` with **no spec** | assembles the spec from the draft, runs the trial, the shape and data checks, the unmatched-sentence check (3.2); builds the card | the card, or a send-back naming the stage to redo |

The old `propose_plan(spec)` with a full spec stays accepted (through the canonical form): no cliff for the
model, and the measurement can compare the two paths on the same image.

**Draft state:** held in the conversation as a platform message carrying the draft (the same mechanism as a
summary's `pasted` tables), so the browser round-trips it and nothing is stored server-side between turns;
stripped from what goes to the model's API (`to_wire`). Files: `app/agent/stages.py` (new), `core.py` (the
tools), `app/agent/draft.py` (new: the draft's shape and assembly).

### 3.2 Every sentence of the request mapped

The platform splits the person's request into sentences (the existing number and table readers already find the
prose); a sentence that states a rule or a goal (contains a limit, a must/never/at most/at least/only, a goal
word) and is claimed by no `add_rule` or `stage_goal` is a card line: **CHECK THIS: no rule holds "…"**. This is
the step 5 item "every rule sentence mapped", and the explainability item of the owner's checklist: on the card,
the request on the left, the model on the right. Files: `app/agent/sentences.py` (new), `readback.py`.

### 3.3 Instructions

The 34,000-character sheet becomes: the protocol (what each stage is for, ~3,000 characters), the constructs'
descriptions (from Phase 2, ~3,000), the contract's term language (~2,000). The PATTERNS block is retired once
the protocol's three-run tuning mean is at least the old path's. The neutrality test is unchanged and must pass.

### 3.4 Reply caps per stage

Each stage's reply is small: `LLM_REPLY_SECONDS` 120 for stage calls (a stage that takes longer is asked for
again, shorter), the plan-level cap stays for the old path. A slow model loses one stage, not the whole model.

### 3.5 The card

Load report (exists), decisions, **sentence ↔ rule table**, goal, trial line, warnings (exist), send-backs
(exist). The person sees what the model does against what they wrote, line by line.

### 3.6 Measurement and exit

- Corpus first: each stage tool tested on the gold models (a gold replayed stage by stage reaches its reference;
  each mutation is caught at the stage it belongs to, not only at the end).
- Then three parallel tuning runs (Phase 0.1) of the protocol path against three of the old path on the same
  image. **Exit:** tuning mean ≥ 7 of 10 right, 0 wrong answers without a warning, "not built" ≤ 1 of 10, and no
  case over 12 minutes on the model's own time.
- Then the hidden set, three runs, read blind.

## Phase 4 — Judge and harden (days 19–21, then ongoing)

| # | Work item | Exit |
|---|---|---|
| 4.1 | Hidden set, three runs on the protocol; defects by class from the aggregate and the `causes` tables; each class becomes a construct, a canonical rule or a check — with its mutation in the corpus first | the plan's "done when": within a few points of tuning, ≥ 90 % right first time, no unwarned wrong answer |
| 4.2 | `/api/health` reports the model (reachable, last latency) and the tile index; the egress smoke stays the acceptance on an isolated host | — |
| 4.3 | Nightly: the corpus (`gold check`, `mutate`) in `scripts/nightly.sh`; a red night blocks a deploy | — |
| 4.4 | Hand-over: `docs/handover.md` points at the protocol, the constructs, the canonical form and the corpus | — |

## Order, dependencies, estimate

```
Phase 0 (3 d) ──► Phase 1 (3 d) ──► Phase 2 (4 d) ──► Phase 3 (8 d) ──► Phase 4 (3 d + ongoing)
   │                                                      ▲
   └──── 0.1 parallel runs and 0.2 gold capture start tonight, beside step 5's measurement ──┘
```

About three weeks at today's pace. Phase 3 depends on 1 (the canonical form is what stage tools return) and 2
(the constructs are what `add_rule` accepts), and on 0 for its judgement; 1 and 2 can overlap after 0.2.
The neutrality plan's step 5 and step 3b measurements run on within Phase 0; their readings feed 0.3's gap list.

## Risks and what answers them

| Risk | Answer |
|---|---|
| The local model does not follow a multi-call protocol | each call is smaller and more constrained than today's single call, and the old path stays as the fallback on the same image; the first corpus replay shows which stages it manages |
| The draft carried through the browser grows large | it carries references to loaded files and the rules, not rows; `to_wire` strips it from the model's API |
| Three cases at once on one GPU slow each other | 0.1 measures it before it is relied on; the limit is 25 minutes under concurrency; serial stays available |
| A canonical rule changes a gold model's meaning | the fixed-point test (`canonical(gold) == gold`) fails the build |
| Adding constructs re-creates the step 3 drop | constructs enter the instructions as one-paragraph descriptions beside the formulas, measured over three runs, kept only if the mean does not drop (the step 3b rule) |

## What starts now

1. Phase 0.1: `run_parallel.sh` and a three-way timing comparison on the step 5 image once its serial runs are
   recorded (no deploy needed).
2. Phase 0.2: `gold.py capture` on the right runs of today (p01, p02, p09, p10 and the others as they come);
   `gold.py check` in the test image.
3. Phase 0.3: the first five mutations and their table.

## Progress

- **11 Oct, 19:45 — Phase 0.2 started.** `bench/phase1/gold.py`: `capture` (a run's model version by API, its
  frozen data from the dataset table; prints only the case id) and `check` (compile, solve, compare, in the test
  image, no model, no database). Six tuning golds captured from right runs (p01, p02, p09 under step 5; p04,
  p07, p10 under step 2): **6 pass of 6**, each at its reference, in about a minute. Remaining: p03 (layout:
  no right run yet), p05, p06, p08; the hidden golds, captured blind as right runs come.
- **11 Oct, 20:00 — Phase 0.3 started.** `bench/phase1/mutate.py`: for each gold, every hard rule dropped in
  turn, the goal reversed, each parameter's values removed, each 0/1 list's default set to 1; the platform's
  checks consulted (trial flags, shape, unused numbers, empty parameter, goal sense). First table: 27 caught,
  25 same goal, 25 missed, and two false positives on right models (the new no-data check on a list of
  exceptions; the numbers check without record counts). After fixing those and adding a goal-sense check
  (the request's "lowest"/"most" against the model's sense): **39 caught, 23 harmless, 15 missed, 0 false
  positives.** The 15: 13 dropped rules (Phase 3.2's sentence-to-rule mapping is the answer) and 2 partial
  lists. The table is the gap list the plan asked for.
- **11 Oct, 21:55.** Golds for p03 (the layout, first right run ever, under step 5 run 2) and p06: **8 pass of
  8**. Mutations on them: 13 caught (a reversed goal on the layout is refused by its solver, which counts), 4
  harmless, 4 missed -- all dropped rules on the timetable, the Phase 3.2 gap. The harness now counts a refused
  solve as a catch, and the platform's unused-numbers check counts an attachment's sizes (a drawing's layers and
  features, a sheet's rows) as held: "layer PROTECTED holds 14 areas" is not a number of the model.
- **12 Oct, 16:20 — Phase 1.1 done.** `docs/plans/canonical-form.md`: every repair inventoried with its
  incident and class. Almost all are canonicalisations (one spelling, one meaning); three are inferences the
  spec determines; no silent heuristic remains. The order of the single pass is written down; Phase 1.2
  (`app/agent/canon.py`, one function, one note list, one test file, the fixed-point test on the golds) follows.
- **13 Oct, 07:20 — Phase 1.2 done.** `app/agent/canon.py` holds the pass: `canonical(args, messages, load,
  domain_id, notes) -> (spec, notes)` in the inventory's order (where the spec is → the draft merge →
  `misplaced` → `joined_keys` → the caller's load → the idioms → the twelve rules of `RULES`, each a named
  function with its docstring and incident: `uncertainty_declared_in_ir`, `complete_list_default`,
  `declared_from_values`, `relationships_by_name`, `sets_stated`, `forall_shape`, `decision_shape`,
  `hard_by_default`, `scalar_indices`, `term_shapes`, `bound_rules`, `literal_keys`). `repair.py` is gone;
  `bind_literal_keys` left `core.py`; `Agent._spec` is the one call. Every note string is as it was (the
  neutrality scan now reads `canon`). `tests/test_canon.py`: **the fixed point holds on all 8 golds**
  (`canonical(gold) == gold`, no notes), one pass on a spec written every wrong way at once reaches a fixed
  point, the notes said before a refusal stay with the caller, the draft merge is a step of the pass. The
  mutation check (`bench.phase1.mutate`) now canonicalises each variant first: its table is identical before
  and after (**52 caught, 27 same goal, 19 missed**). 189 tests pass across the touched files. The step-3b
  reverse patch (`git show fe687b8 -- backend/app/agent/core.py | git apply -R`) still applies to `core.py`,
  so the deploy recipe is unchanged. Not deployed: the loop's measurement series is paused, and the pass is a
  refactor with no behaviour change. Next: 1.3 (refusals that name the fix), then Phase 2.
- **13 Oct, 09:40 — Phase 1.3 done.** The tuning runs' `causes` tables (base, step 2, steps 4–7) record five
  refusal kinds in all, each now naming the fix: a `null` index name (3 times) says to write
  `{"index": "i", "set": ...}`; an unknown key says the node's canonical shape (a rule, a term, a goal term,
  a binding, a declaration: `validate._SHAPES`); a wrong subscript count says
  `{"var": name, "index": [<an index over a>, ...]}`; an undeclared relationship names those declared (or how
  to declare one), at its four sites through `_write_a_relationship`; the order check's "no value is loaded"
  already said what to load. `tests/test_refusals_name_the_fix.py` provokes each on a minimal model and
  requires a "write it as" / "Load it with" clause; 489 validator and refusal tests pass, and the Assistant's
  own tests (135) read the new text without change. The refusal codes and `loc` are as they were, so the
  front end's port (`frontend/src/ir/validate.ts`, same codes, its own words) is untouched. Phase 1 is
  complete; next is Phase 2 (the constructs library, from `idioms.py`).
- **13 Oct, 10:20 — Phase 2 opened: the package.** `app/agent/idioms.py` became `app/agent/constructs/`:
  one module per construct (`carried`, `only_if`, `largest_of`, `one_per_group` for exactly_one/at_most_one),
  each with `KEYS`, `FIELDS`, a neutral `DESCRIPTION` the Phase 3 instructions will include verbatim, and its
  `expand`; the registry and the one `expand(spec)` call in `__init__.py`; the helpers in `_common.py`. The
  wire format, the expansions, the notes and the refusal texts are as they were (the refusal class is
  `ConstructRefused`, `IdiomRefused` kept as its alias); `core.py` untouched, so the step-3b reverse patch
  still applies. `tests/test_constructs.py` (the three hand-worked optima, the refusal, the plan card) plus a
  registry test; the neutrality scan now reads every description and field text (43 tests pass with the
  canonical-form and summary tests). **Baseline for the exit criterion:** the 8 tuning golds hold 60 plain
  linear rules and 1 `place` rule, no construct rules -- so "every hard rule a construct or plain linear"
  already holds, and the mutation table cannot show a construct's refusal from the golds. **Decision:**
  `bench.phase1.mutate` gets a `construct` mutation class that takes each construct's wrong form from its own
  test fixture (the plan's last column: the starting amount in every period, a partial list with default 1,
  `level >= value x pick`, a missing `most`, the division written as is) and counts whether the construct
  refuses or the checks warn; it is written with the first new construct (2.2 allowed pairs). Then 2.5, 2.7,
  2.9, one per tick, each with its hand-worked optimum.
- **13 Oct, 11:00 — construct 2.2 `allowed_pairs`.** `app/agent/constructs/allowed_pairs.py`: the list's
  0/1 parameter, the pair's bindings, the amount, `most` (defaulting to the decision's bound), and the reading
  the data decides -- a list naming every record of the first index is complete (`amount <= most x allowed`),
  one naming some restricts those alone (`amount <= most x (1 - listed + allowed)`, `listed` made from the
  list); `"partial"` fixes the reading by hand; the list's default is set to 0 either way and the rule's note
  says which reading was taken. Hand-worked example in the module (`EXAMPLE`: three records, two options, the
  list naming one record: 8; complete 9; forced complete: infeasible) and the mistake written by hand
  (`WRONG`: the partial list on a default of 1, goal 4). The construct mutation class is in
  `bench.phase1.mutate` (`constructs_table`, with `bench/phase1/seed_data.py` turning a seed into the frozen
  dataset shape without the database): each construct's example through its expansion must reach its optimum,
  and its `WRONG` must be refused, warned or give the same goal; the canonical pass's notes on the seed count
  as warnings there. **Table: allowed_pairs example right (8); by hand caught (the pass's list-default
  note); golds unchanged -- 53 caught, 27 same goal, 19 missed.** 26 construct, neutrality and canonical-form
  tests pass. Next: 2.5 covering, 2.7 share_of_total, 2.9 used_only_where_given, and EXAMPLE/WRONG pairs for
  the four moved constructs so the table shows every construct.
- **13 Oct, 11:35 — construct 2.5 `covering`.** `app/agent/constructs/covering.py`: each requirement, the
  options, `covers` as a 0/1 parameter over (option, requirement) or as a relationship from the option to what
  it covers (a `via` binding), `chosen`, `at_least` (1). Example in the module (four requirements, three
  options: 7; as links 7; `at_least` 2 infeasible, since one requirement has one cover). The mistake written by
  hand -- the cover per pair, `chosen >= covers` for every option and requirement, which chooses every covering
  option (10) -- **is MISSED by every check**: the table reads 53 caught, 27 same goal, 20 missed (golds
  unchanged). A gap recorded for the next tick: a 0/1 decision with every cell at 1 decides nothing, as one
  with every cell at 0 does (the trial's "does nothing" card has the all-zero half only); whether a warning on
  the all-one half is safe on the golds is the test. 15 construct and neutrality tests pass. Next: 2.7
  share_of_total, 2.9 used_only_where_given, then EXAMPLE/WRONG pairs for the four moved constructs.
- **13 Oct, 12:10 — construct 2.7 `share_of_total`.** `app/agent/constructs/share_of_total.py`: the part,
  the whole (a sum over the parts), `<=` or `>=`, the share as a fraction (30 is refused: "30% is 0.3"); the
  platform writes part <= share x total. A record named by its key in the part is bound by the canonical pass
  after the expansion (the test checks the order). Example (three parts at 2, 5, 8 making 10; the third at
  least 30%, the first at most 50%: 44). The mistake written by hand -- the share compared to the part alone,
  `amount >= 0.3`, the whole left out (49.4) -- **is MISSED by every check**, like covering's: a hand-written
  rule that is linear and feasible has nothing for a shape check to see. The table: 53 caught, 27 same goal,
  21 missed (golds unchanged); 17 construct and neutrality tests pass. The reading: the two misses are the
  Phase 3.2 case exactly -- the sentence "at least 30% of the total" selects the construct, and a plain rule
  for such a sentence is what the staged protocol refuses. Next: 2.9 used_only_where_given, then
  EXAMPLE/WRONG pairs for the four moved constructs, then the all-one decision warning.
- **13 Oct, 12:45 — construct 2.9 `used_only_where_given`.** `app/agent/constructs/used_only_where_given.py`:
  the pair's indices, the amount, the parameter whose cells say where, `most`; the platform makes a 0/1
  parameter that is 1 exactly where the given parameter has a cell (one per distinct cell, after the files are
  loaded) and writes amount <= most x that; the note counts the cells. Example (two records needing 10 from
  three options of 8, a rate for four of six pairs: 44). The mistake written by hand -- no rule, the amount
  free at the default rate of 0 (goal 0) -- is **caught by the trial's no-data check**. Table: 54 caught, 27
  same goal, 21 missed (golds unchanged); 19 construct and neutrality tests pass. The nine constructs of the
  plan's table are in: 2.1, 2.3, 2.4, 2.6 moved; 2.2, 2.5, 2.7, 2.9 new; 2.8 is the seed's
  `relationships_in_order`. Next: EXAMPLE/WRONG pairs for the four moved constructs (the plan's last column),
  then the Phase 2 exit check and the all-one decision warning.
- **13 Oct, 13:20 — every construct in the table.** The four moved constructs carry their hand-worked
  example and the mistake written by hand (the plan's last column), and the three old tests read the modules'
  examples; `only_if` has a fixed-charge example of its own (two places, 15), and `carried` now *says* when a
  bare number is written among what comes in ("counted in EVERY period; if it is the amount on hand at the
  start, write it as initial") -- a note, not a refusal, since a fixed inflow is a real thing; a construct's
  `expand` may return (rules, notes) and the notes reach the model with the expansion's. The construct table,
  all eight modules: **6 caught** (carried: the construct's note and "does nothing"; only_if: refused for a
  missing `most`; allowed_pairs: the pass's list-default note; used_only_where_given: the trial's no-data
  check; largest_of: `level >= value x pick` caught by never-helps and "does nothing"), **1 harmless**
  (exactly one written as at least one: same goal), **2 missed** (covering per pair, the share against the
  part alone -- the Phase 3.2 case). Whole table: 58 caught, 27 same goal, 21 missed; golds unchanged. 33
  construct, neutrality and canonical-form tests pass. **Phase 2 exit:** every hard rule of every tuning gold
  is plain linear or `place` (none hand-writes a construct's algebra); all construct tests pass; the table
  shows each construct's refusal or warning, with the two misses named. Phase 2 is complete but for the
  all-one decision warning (a lever for covering's miss), which comes next; then Phase 3.
- **13 Oct, 14:00 — the always-yes warning; Phase 2 complete.** A probe of the eight golds' optima found no
  yes/no decision at 1 on every cell (the nearest: 45 of 48), so the warning is safe on the corpus. The trial
  now counts a yes/no decision's cells at 1 (`used[...].ones`, app/api/model_spec.py); the card says "CHECK
  THIS: open is yes on every one of its 3 cells -- a yes/no decision that is always yes decides nothing; a
  rule may force every one on, or nothing holds it down" (`core.always_yes_decisions`, two cells or more;
  the model's line names the per-pair cover as the usual cause); `bench.phase1.mutate` reads it as
  `trial:always yes`. Table: covering's hand-written form is now caught, and one gold's dropped rule that
  was missed before is caught by the same signal; no gold's own base changed. **60 caught, 27 same goal, 19
  missed**; the construct table reads 7 caught, 1 harmless, 1 missed (the share against the part alone, the
  Phase 3.2 case). 36 tests pass across the card, neutrality, construct and numbers tests. `core.py` was
  edited (the card lines, far from the instructions): the step-3b reverse patch still applies. Not deployed.
  **Phase 2 is complete.** Next: Phase 3, the staged build protocol.
- **13 Oct, 15:10 — Phase 3 opened: the stages as a pure layer.** `app/agent/stages.py` (new): `assemble`
  (the draft as the spec, with `sets` and `relationships` derived from what the model indexes over and walks),
  `check_decisions` (every index kind has records, bounds in order, the shape check, the read-back),
  `check_rule` (the one rule expanded and canonicalised, the shape check in the draft's model, its range as the
  product of the forall kinds' record counts -- "up to" with a filter or a via -- and the data it reads, the
  sentence kept as the rule's note), `check_goal` (the shape check, every parameter read declared, the
  read-back). The stage order refuses out of turn ("declare the decisions first with stage_decisions").
  **Deviation from the plan's text:** the draft is not a new platform message; the stage calls themselves
  are the state -- `draft.draft_from` folds `stage_data`, `stage_decisions`, `add_rule` (replace by id, `drop`)
  and `stage_goal` into the same draft the propose_plan patches use, so a summary carries it already and
  `to_wire` needs nothing; it now takes the id of the call being checked (`before`), since one assistant message
  may carry several stage calls. `tests/test_stages.py`: **every tuning gold replayed stage by stage is
  accepted at every stage and assembles to the gold model again** (decisions, parameters, rules, goal equal;
  the derived sets are the gold's but for a set nothing indexes over; every walked relationship present), plus
  the order, the read-back and the fold by id (44 tests with the draft, canonical-form and summary tests).
  Not wired to the Assistant yet (next tick: the four tools, dispatch, propose_plan with no spec; `stage_data`
  has its own path -- `misplaced`, `joined_keys`, the load, the seed-level findings -- since the full pass
  refuses a spec with no ir). The step-3b reverse patch is expected to break at 3.3 (the instructions
  rewrite lands on fe687b8's lines): measure 3b or drop it is the owner's call, to be put at that point.
- **13 Oct, 16:10 — the stages wired into the Assistant.** Four tools in the modelling mode
  (`STAGE_TOOL_SPECS` beside `PLAN_TOOL`, whose `spec` is no longer required): `stage_data` (the seed's parts
  through `misplaced`, `joined_keys` and the Assistant's own load; says what each entry stored, the records per
  kind, each parameter's cells and default, each relationship's links, and the seed-level findings as CHECK
  THIS lines -- a load that refuses refuses the whole stage, per-entry refusals are a later refinement),
  `stage_decisions`, `add_rule` (`drop` removes), `stage_goal`, each reading the draft the calls before it left
  (`_call_id`, set per call in the dispatch loop, through the canonical pass to the fold); a refusal begins
  "Not staged" and the fold skips a refused stage call, so a refused rule never joins the draft.
  `propose_plan` with no spec: the canonical pass completes the empty spec from the draft assembled from the
  stages and says so ("the plan was assembled from the stages: 7 rule(s), 4 decision(s), the goal"); the old
  path with a full spec is unchanged. `assemble` now unions what a draft already lists with what the stages
  since add (the fold assembles at every step). 50 tests pass: every gold replayed stage by stage, the
  Assistant's dispatch end to end (data, decisions, a rule accepted, a rule refused with the fix, the goal,
  the draft at propose without the refused rule), the draft, canonical-form, summary and neutrality tests;
  the Assistant's own suites (blend, field test: 177) passed before the last two fixes. The step-3b reverse
  patch still applies (the tools and dispatch sit far from the instructions). Not deployed: the model is not
  told the protocol yet (3.3), so nothing changes on the old path. Next: 3.2 (every sentence of the request
  mapped), then 3.3 (the instructions -- where the owner decides on step 3b).
- **13 Oct, 17:00 — 3.2, every sentence of the request mapped.** `app/agent/sentences.py` (new): the
  person's messages split into prose sentences (bullets stripped, a pasted table's rows and anything under four
  words left out); a sentence states a rule (must, never, cannot, at most, at least, no more than, only,
  exactly, within, before, after, capacity, deadline, ...; a sentence beginning "No ...") or a goal (minimise,
  cheapest, fewest, best, ...; "at most"/"at least" are not goals). A sentence is held when an `add_rule`
  claimed it, or a rule's note holds it, in the same words or most of them (one inside the other, or 60 % of
  the shorter one's words shared); a goal sentence is held once a goal is staged. The card line: **CHECK
  THIS: no rule holds "..." -- if it is a rule of the problem, it is missing** (at most eight named), and
  "no goal holds ..." when no goal was staged. Only on the protocol path (a plan built in stages); a plan
  written whole says nothing here -- its notes are the model's words, not the person's, and the line would be
  noise. `mapping()` gives the request-left, model-right table for the card (3.5). On the tuning requests the
  word lists find 3-9 rule sentences and 1-4 goal sentences each (the golds hold 5-14 rules), a proportionate
  first reading. 22 sentence, neutrality and stage tests pass; the neutrality scan reads the new modules'
  constants and card lines. Next: 3.3, the instructions (the step-3b decision), then 3.4-3.6.
- **13 Oct, 17:40 — 3.4 and 3.5.** The card (3.5): on the protocol path, after the CHECK THIS lines, the
  table "WHAT YOU WROTE -> THE RULE THAT HOLDS IT": each rule or goal sentence of the person's with the rule
  id whose note holds it, or "--" (`sentences.table_for_person`, at most 24 rows). The reply cap (3.4):
  `LLM_STAGE_REPLY_SECONDS` (120) applies when the model's last tool calls were stage calls and no
  propose_plan followed (`core.on_protocol`, `core.reply_cap`); the plan cap (`LLM_REPLY_SECONDS`, 240) stays
  for the old path, and the slow-reply message names the cap that applied. 103 tests pass (sentences,
  neutrality, stages, the Assistant's blend suite). The step-3b reverse patch still applies. **3.3 is next and
  is the owner's call**: the instructions rewrite lands on the lines fe687b8 (step 3b) changed, so from there
  the deploy recipe cannot exclude 3b. Either measure 3b first (three tuning runs on an image built from main
  as it is, which includes 3b) or drop it (`git revert fe687b8`, then 3.3 on top). Until then the model is not
  told the protocol and the live path is unchanged.
- **14 Oct, 06:50 — the plan adapted (the owner's "go ahead"), and 3.3 written.** Three changes: (1) step 8
  (main at 1ddf630, step 3b included) is the old path's baseline for 3.6, not a gate -- its three tuning runs
  finish, its hidden run is dropped (`runs/hidden/skip-step8`; `run_hidden.sh` honours the marker), the old
  path's hidden numbers being step 7's; (2) the parallel runner is tried on the protocol image's runs, to
  bring a run from two or three hours to about one; (3) reply time is attacked directly: thinking stays off
  after a stage that was accepted and on after one refused ("Not staged"), beside the 120-second stage cap.
  **3.3:** the sheet's PHASE 2 is the protocol -- stage_data, stage_decisions, add_rule one rule per call with
  the request's sentence, stage_goal, propose_plan with the summary only; a refused stage is fixed before
  moving on; a change redoes only the stage it touches; the whole-spec way still works but is named as slower.
  The SHORTCUTS block (step 3b's six lines) is replaced by the constructs' own descriptions
  (`constructs.describe()`, rendered into the sheet); PATTERNS stays until the protocol's three-run mean is
  at least the old path's. The sheet is 39,100 characters (from 34,000); 154 tests pass, the neutrality scan
  of the rendered sheet among them. Next: the protocol image (step 9) built from main once step 8's run 3 is
  in, its three tuning runs in parallel, read against step 8's.
- **14 Oct, 08:05 — diagnosis on step 9's first minutes, and the plan adapted again.** (Findings in the
  results document: the parallel runner's path bug, the propose path's stale call id, no tool-call log.) What
  the plan now adds, in order: **(a) protocol uptake is measured first** -- per case, how many stage calls
  against whole-spec proposals (`assistant.tool` lines, counted blind per run), because a protocol the model
  does not use measures nothing; **(b) if uptake is low** after the first parallel batch, a whole-spec
  `propose_plan` that is refused answers with the stage to redo instead of "fix and propose again" (the old
  path stays accepted when it passes, so nothing is lost); **(c) stage and propose calls in one reply** --
  today the turn loop keeps only the propose_plan and drops the rest; the stage calls beside it should run
  first. (b) and (c) are written only if (a) shows the need.
- **14 Oct, 08:45 — a stop rule, and one change per measured step (the owner: "we are going down").** The
  mean has gone 3.7, 4.3, 4.7, 4.3 over steps 5-8, and step 8's unwarned-wrong count tripled (2 -> 6 of 30)
  after four changes at once. From here: (1) step 9 is judged against **step 7** (4.7 right, 2 wrong unwarned
  of 30), the best so far; if its first run is below 4.7 right or has more than 2 wrong unwarned of 10, the
  step 7 image goes back on the stack and the protocol is worked on offline; (2) one change per measured step;
  (3) next change (built while step 9 runs, not deployed): the order checks that today fire only at the final
  proposal run at the stage they belong to -- undeclared or valueless parameters at stage_decisions, links of
  an undeclared type at stage_data, data no rule reads named at stage_goal -- since 7 of step 9's third start's
  refusals were of these kinds, found at the end.
- **14 Oct, 10:15 — what step 9's runs show next, and step 10's content (built, tested, not deployed).**
  Step 9 run 1 passed the stop rule (5 right, 1 wrong unwarned). Run 2's p04 showed a new failure: built and
  solved at 7.75 minutes with the goal wrong (-248703 against 963), the model saw it and tried to rebuild, and
  every rebuild was refused -- the workspace name already taken, then the problem name already taken in it,
  then the problem name left out -- until the 30-minute stop. Step 10 candidates, each with tests: (1) the
  stage checks of 08:45 (parameters, link types, unread data at their stage); (2) **revisions**: a plan
  proposed again after a build in the same conversation goes into the built workspace as "<problem>
  (version N)" (`stages.as_revision`; a workspace name not used before stays a new workspace). Both are
  defect fixes in the same component; if they go in together the step says so, and the causes table per
  case shows which one acted (stage refusals against revision notes).
- **14 Oct, 14:30 — the protocol behind a setting (the owner's choice: recommendation 3).** Steps 9-10 measured
  the protocol at 5 (one run) and 3.3 (three runs) against step 7's 4.7, with more cases out of time: more model
  calls, each slow. `LLM_BUILD_STAGES` (off by default) now decides it: off, the model sees the whole-spec
  PHASE 2 and no stage tools or constructs block, and a refused whole spec gets the patch hint as before; on,
  the full protocol. Tested both ways. The live stack runs the step 7 image regardless. Next, when the owner
  chooses: time the model server's replies, cut the context sent per call, and measure the protocol again on a
  faster model.
