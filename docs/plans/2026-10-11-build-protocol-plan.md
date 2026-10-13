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
