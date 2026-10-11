# Neutrality plan — measurements

Each row is one measurement of one platform state (`docs/plans/2026-10-10-neutrality-plan.md`, rule 4: one step
per measurement). Hidden-set numbers come only from `python -m bench.phase1.blind runs/hidden <tag>`; nobody who
changes the platform has read the cases. Small (S) size, one run each, 20 minutes a case, local LLM (qwen3.5).

**Columns.** *built*: a model was built. *first*: built with no send-back. *right*: the checker passes every hard
rule and the goal is within tolerance of the independent reference. *wrong, unwarned*: solved, not right, and no
warning on the plan card — the number that must reach 0.

## Summary

| Tag | Platform | Set | Right | Built | Wrong, unwarned | Notes |
|---|---|---|---|---|---|---|
| after | 70004a0 (fixes of 10 Oct) | tuning, 10 small | 5 / 10 | 7 | 1 (p03) | from `2026-10-10-phase1-results.md` |
| base | 531fb9e (before step 2) | hidden, 16 small | 6 / 16 | 12 | 6 | re-scored after two checkers were fixed (rule 5); first read 5 / 16 |
| step2 | b9f3943 (step 2 alone) | tuning, 10 small | 6 / 10 | 7 | 1 (p03) | exit met; re-scored: p07 was scored on a what-if run (first read 5 / 10) |
| step2 | b9f3943 (step 2 alone) | hidden, 16 small | 4 / 16 | 9 | 3 | down from 6 / 16: more cases hit the 20-minute limit |
| step3 | image `solver-backend:step3`, built from 10dc21e (backend = fa738c9: step 3 + the step 4 card) | tuning, 10 small | 3 / 10 | 9 | 6 | exit not met: down from 6; re-scored: p08 was scored on a what-if run (first read 2 / 10) |
| step3 | same | hidden, 16 small | stopped after 2 (0 / 2) | | | stopped: step 3 withdrawn on the tuning result |
| step4 | image `solver-backend:step4`: a37829d without step 3's instructions (step 2 + step 4; the idiom expansion is in, inert) | tuning, 10 small | 3 / 10 | 6 | 2 (+1 warned) | below step 2's 6; three not built in 20 minutes |
| step4 | same | hidden, 16 small | queued after tuning | | | |

## base — hidden set, before step 2 (finished 02:29, 11 Oct)

```
case           built  first  solved right  viol  warned  min
h01-S          yes    yes    yes    no    1     0       5.4
h02-S          yes    no     yes    yes   0     1       17.7
h03-S          yes    yes    yes    yes   0     0       3.9
h04-S          yes    yes    yes    no    0     0       8.1
h05-S          no     no     no     no    0     1       20
h06-S          yes    yes    yes    yes   0     0       4.3
h07-S          yes    no     yes    yes   0     0       17.9
h08-S          yes    yes    yes    no    0     0       2.6
h09-S          no     no     no     no    0     0       20
h10-S          no     no     no     no    0     0       20
h11-S          yes    yes    yes    no    0     0       12.3  (checker could not read the plan)
h12-S          yes    yes    yes    no    23    0       8.6
h13-S          yes    yes    yes    no    7     0       4.8
h14-S          yes    yes    yes    no    0     0       16.8  (checker could not read the plan)
h15-S          yes    yes    yes    yes   0     0       4.4
h16-S          no     no     no     no    0     0       20

5 right of 16; built 12; wrong but solved 7 (of them warned on the card 0)
```

What the aggregate says, by class only (rule 3):

- **Right 5 of 16 (31%)** against 5 of 10 (50%) on the tuning set: the gap the plan exists to close.
- **Not built 4 of 16**, each at the 20-minute limit: the Assistant never reached a model the platform accepted.
- **Solved but wrong, with no warning: 7.** Three break hard rules (1, 7 and 23 violations); two keep every rule
  but miss the reference goal (a weaker optimum or a misread goal); two cannot be judged yet — their checkers
  could not read the platform's real export. Rule 5: a separate agent fixes those two checkers with only the
  module and the export, and reports pass or fail; the base rows are then re-scored.
- **Re-scored (rule 5).** A separate agent, given only each module and its export, fixed the two checkers and
  reported pass for both: each expected a record pair's keys in separate columns, where the export joins them
  into one key (and leaves out decisions that are all zero). Re-read through the blind runner:
  h11-S right no, 12 violations; h14-S right yes. **Base: 6 right of 16; wrong but solved 6, warned 0** — four
  break hard rules (1, 7, 12, 23 violations), two miss the reference goal. The step 2 run and later ones are
  scored by the fixed checkers.
- **No wrong answer carried a warning.** The checks of step 5 have nothing to say on these problems yet.

## step2 — tuning set, step 2 alone (finished 04:19, 11 Oct)

Through the same blind runner, next to the run of 10 October (`after`):

```
case    after: built first right viol min    step2: built first right viol min
p01-S          yes   yes   yes   0    3.4           yes   yes   yes   0    2.5
p02-S          yes   yes   yes   0    2.5           yes   yes   yes   0    5.6
p03-S          yes   yes   no    0    5.7 *         yes   yes   no    0    6.6 *
p04-S          yes   no    yes   0    5.5           yes   yes   yes   0    5.4
p05-S          no    no    no    0    20            no    no    no    0    20
p06-S          no    no    no    0    20            no    no    no    0    20
p07-S          no    no    no    0    20            yes   yes   no    11   13.4
p08-S          yes   yes   no    2    19.9          no    no    no    0    20   (warned 1)
p09-S          yes   yes   yes   0    11.6          yes   yes   yes   0    4.8
p10-S          yes   yes   yes   0    6.2           yes   yes   yes   0    7.8
* checker could not read the plan (the layout problem: the export has no placed items, a known gap)

after: 5 right of 10; built 7; wrong but solved 2 (warned 0)
step2: 5 right of 10; built 7; wrong but solved 2 (warned 0)
```

- **The exit of step 2 holds:** removing every domain illustration from the instructions cost nothing on the
  problems they were written for — the same five right, two of them faster, one (p04) now first time.
- **The two that moved are the two hardest:** the power-grid problem is now built (but breaks 11 rules, no
  warning), and the security problem is no longer built in 20 minutes. One run each, so a single case moving
  either way is within run-to-run noise; the counts are what the step is judged on.
- The blind runner counts p08 `after` as warned 0, where `2026-10-10-phase1-results.md` scored it warned by hand
  from the card; the hand reading stands for that run.

## step 6 — solver-side audit (11 Oct, read only; no measurement)

Looked for anything on the solve path keyed on a domain's or problem's name rather than the model's shape:

- **Solver choice and the special methods are by structure.** `app/solve/fingerprint.py` and `classify.py`
  name model classes (knapsack, partition, cover, packing) from the compiled rows, not from names; each special
  method (`allocation`, `fixed_charge`, `greedy`, `horizon`, `join`, `lagrange`, `lns`, `matching`, network)
  has an `applies(compiled)` that tests the rows. Comparisons with `.name ==` in `app/solve` are solver
  (backend) names only.
- **The routing solver is reached through a general rule type** (`route`, with its own `depot` / `depot_by`
  keys, validated in `app/ir/validate.py`), not through a problem name.
- **No branch on `domain_name` or `problem_name`** anywhere in `app/`: they are only checked for being new or
  unused.
- **Three domain-named modules exist** (`app/facilities.py`, `app/emergency_coverage.py`, `app/heatwave.py`):
  ready-made example templates a person applies from the showcase (`app/showcase.py`). The Assistant does not
  read or reach them (no reference in `app/agent/`), so they do not bias what it builds. They stay as examples.

Result: step 6's audit finds nothing to change on the solver side.

## step2 — hidden set, step 2 alone (finished 08:02, 11 Oct)

```
case           built  first  solved right  viol  warned  min
h01-S          yes    yes    no     no    0     0       20
h02-S          yes    yes    yes    yes   0     0       7.4
h03-S          yes    yes    yes    yes   0     0       4.9
h04-S          no     no     no     no    0     0       20
h05-S          no     no     no     no    0     0       20
h06-S          yes    yes    yes    yes   0     0       3
h07-S          yes    yes    yes    no    0     0       6.4
h08-S          yes    yes    yes    no    2     0       2.2
h09-S          yes    no     no     no    0     0       20
h10-S          no     no     no     no    0     0       20
h11-S          yes    yes    yes    yes   0     0       6.6
h12-S          no     no     no     no    0     0       20
h13-S          yes    yes    yes    no    2     0       9.8
h14-S          no     no     no     no    0     2       20
h15-S          no     no     no     no    0     0       20
h16-S          no     no     no     no    0     0       20

4 right of 16; built 9; wrong but solved 3 (of them warned on the card 0)
```

Against the baseline (6 right, 12 built, 6 wrong unwarned), by class only:

- **Fewer built: 9, from 12.** Nine cases ended at the 20-minute limit, from four. Three of the baseline's
  right cases went the other way (h14 and h15 now not built, h07 now wrong) and one wrong one became right (h11).
  With one run a case, a net move of 2 right is within run-to-run noise on this LLM, but the drop in "built" is
  the larger move and is in the direction the plan warned of: without concrete illustrations the Assistant takes longer to reach a model the platform accepts.
- **Fewer wrong answers: 3 unwarned, from 6**, and fewer rules broken (2 + 2 violations, from 1 + 7 + 12 + 23).
  What it builds is more often right; it builds less often in time.
- **Reading.** Step 2's exit (tuning score holds) is met: 5 / 10. On the hidden set it is not a gain. Step 3's
  idioms are the planned answer to the time lost: compact rules for the constructs that took several tries.
  Measured next, alone.

## step3 — tuning set, step 3 + the step 4 card (finished 09:58, 11 Oct)

```
case           built  first  solved right  viol  warned  min
p01-S          yes    yes    yes    yes   0     0       3.4
p02-S          yes    yes    yes    no    2     0       2.7
p03-S          yes    yes    yes    no    0     0       6.7  (checker could not read the plan)
p04-S          yes    yes    yes    no    2     0       12
p05-S          no     no     no     no    0     0       20
p06-S          yes    yes    yes    no    0     0       13.4
p07-S          yes    yes    yes    no    69    0       12.2
p08-S          yes    yes    yes    no    1     0       7.4
p09-S          yes    yes    yes    yes   0     0       13.7
p10-S          yes    no     yes    no    0     0       19.7  (checker could not read the plan)

2 right of 10; built 9; wrong but solved 7 (of them warned on the card 0)
```

- **Built more (9, from 7), right less (2, from 5).** Step 3's exit (production and blending reach the other
  problems' rate) is not met; the tuning score dropped.
- **The idioms were written in 3 of 10 cases** (p07, p08, p09 -- p09 right). The other seven never used them,
  so most of the change is the instructions' new text and run-to-run variation, not the idioms' expansion.
- **What went wrong, on the tuning set (readable):**
  - p02 and p04: a list of ALLOWED pairs was loaded as a 0/1 parameter whose default is 1 -- every pair the list
    does not name stays allowed, so the list restricts nothing. The step 4 card showed it ("allowed: 1 cells
    given (value 1), every other cell 1") but raised no warning. A data check that does not depend on the
    problem catches it: a parameter whose given cells all equal its default changes nothing.
  - p06: solved, all rules kept, goal 189 against the reference 909 -- a goal or a rule misread.
  - p07: 69 violations (the grid problem: rules left out). p08: over budget by 2,000 (a rule weakened).
  - p10: the export has no shipment decision over (warehouse, location, day, good) -- the model's decision has
    another shape; the checker cannot judge it.
- The step 3 hidden run follows now on the same image; step 4 (rest) and step 5 wait for it.

## Harness fix: the plan as asked, not a what-if run (11 Oct, 10:50)

The browser driver scored the newest run made during a case. When the Assistant also solved what-if scenarios
after the plan ("Budget 400k", "Solar +10%"), the newest run was one of those. Found on p08 under step 3: the
scored run broke the budget, but it was the "Budget 400k" scenario; the base plan reached the reference goal
exactly (620,380). `drive_case.mjs` now takes the newest run of a scenario that changes nothing (patch `{}`), and
`rebase_runs.py` re-scores finished runs the same way, printing only which folders moved. Over every run so far
(tuning after / step2 / step3, hidden base / step2) two moved, both tuning: p07 under step 2 (now right, goal
26,803.94 = reference) and p08 under step 3 (now right). No hidden run moved. Corrected totals:

| Tag | Tuning right | Wrong, unwarned |
|---|---|---|
| after | 5 / 10 | 2 |
| step2 | 6 / 10 | 1 |
| step3 | 3 / 10 | 6 |

The step 3 drop stands (6 to 3 right on the tuning set).

## Step 3 withdrawn (11 Oct, 10:45, on the owner's "fix and go on")

Step 3's instructions (the IDIOMS block and the building blocks pointing to it) took the tuning set from 6 to 3
right, and the Assistant wrote an idiom in 3 of 10 cases. They are withdrawn (e5c361c); the expansion in
`app/agent/idioms.py` stays, since it acts only on a rule written as an idiom. The step 3 hidden run was stopped
after two cases (both at the 20-minute limit) -- the tuning result decided it, and the rest would have measured
instructions that are no longer in. Step 4 is now measured on step 2 alone: the live image is a37829d without
step 3's instructions, and holds neither of the step 5 checks committed since.

## Harness: the last two tuning checkers read every plan (11 Oct, 11:10)

- **p03 (layout):** the answer map carries no placed items yet, so the checker could not read any plan. It now
  rebuilds the beds from the run's decisions (placed, x, y, turned; the placement solver's 0.1 m cells from the
  lower-left, length along x when not turned). Checked on the generator's own layout (23 beds, no violation).
  Read this way, p03 is wrong in every run (after, step 2, step 3): 50 beds placed, 34 with no 1.2 m way to an
  entrance -- the corridor-width gap already known.
- **p10 (relief):** a plan that ships nothing exports no shipment (zeros are not exported) and was read as
  "no shipment decision". It is now judged as shipping nothing (step 3: wrong, all demand unmet).
- No total changes: after 5 / 10, step 2 6 / 10, step 3 3 / 10. "Checker could not read the plan" no longer
  appears on the tuning set.

## Step 3b prepared (11 Oct, 13:00; not deployed)

Why step 3 failed, from the tuning runs: the idioms were written in 3 of 10 cases (2 of them right), while the
new text replaced written-out formulas ("exactly one": the sum over the group's members = 1) with pointers to the
idioms, so the 7 cases written by hand had less to go on, in 2,000 more characters. The failures were ordinary
modelling mistakes, none in an idiom.

Step 3b keeps every formula as it was (step 2's text) and adds one optional paragraph, SHORTCUTS (~600
characters), offering only the two idioms whose hand-written form went wrong before: `carried` (a balance between
periods with the starting amount in the first period) and `largest_of` (effects that overlap). It is queued after
step 5 and measured over **three tuning runs** (tags step3b-1..3) before any hidden run, since one run moves
by about two cases on this LLM.

## step4 — tuning set, step 4 on step 2 (finished 13:00, 11 Oct)

```
case           built  first  solved right  viol  warned  min
p01-S          yes    yes    yes    yes   0     0       2.3
p02-S          yes    yes    yes    yes   0     0       4.3
p03-S          yes    yes    yes    no    34    0       5.6
p04-S          yes    no     yes    no    2     0       14.8
p05-S          no     no     no     no    0     0       20
p06-S          yes    no     yes    no    0     1       16.7
p07-S          no     no     no     no    0     0       20
p08-S          no     no     no     no    0     1       20
p09-S          yes    yes    yes    yes   0     0       7.1
p10-S          no     no     no     no    0     0       20.1

3 right of 10; built 6; wrong but solved 3 (of them warned on the card 1)
```

- p07 and p08, right under step 2 (p07) and step 3 (p08), were not built in 20 minutes; p10, right under step 2,
  was not built either. Step 4 changed the loader and two lines of instructions, none of it on these cases' path
  in a way that explains a timeout. This is the run-to-run noise the issues report puts first
  (`2026-10-11-issues-and-plan.md`, A): one run cannot judge this step. p04 repeats the allowed-list mistake
  (caught by the step 5 check `as_default`).
- The step 4 hidden run follows (from 13:00).

## Harness: a timed-out turn is now stopped (11 Oct, 13:20)

Cause of time found in the step 4 tuning run: p08 reached the 20-minute limit at 11:46 and the driver moved on
without stopping the Assistant's turn, which kept the model busy. p07 started at once and its FIRST model call
(about 1 token of context) waited the whole 20 minutes. So one timeout can make the next case time out too: part
of every "not built" count so far (tuning and hidden) may be this cascade, not the platform. `drive_case.mjs`
now presses Stop at the limit and waits for the turn to end before the next case. In effect from the step 4
hidden run's next case on; earlier measurements carry this fault and are read with it in mind.

## Where the time goes (plan A.2; `python -m bench.phase1.causes runs <tag>`, counts only)

Over the three tuning sets (step 2, 3, 4: 30 case runs, 9 not built in 20 minutes):

| What ended the case | Cases | Which |
|---|---|---|
| A model reply ran past 7 minutes (cut, asked again shorter) | 4 | p05 in every run it timed out; p08 |
| No plan card at all, no refusal, no slow reply: the turn never came back | 3 | p05 and p06 (step 2), p07 (step 4: behind p08's unstopped turn) |
| A warned card declined, the second card not in time | 2 | p08 (step 2, step 4) |
| Refusals of the spec, one after another | 1 | p10 (step 4: 7 refusals, now repaired) |

- **Refusals are rare** (8 in 30 runs; 7 of them in one case). The time is lost in the model's own replies:
  thinking replies longer than 7 minutes, and turns that do not come back at all.
- p05 is the clearest case: every run, a reply over 7 minutes. Next for plan C: what p05's first reply is doing
  (thinking length, tokens), and whether a shorter first reply (a cap on thinking for the first plan) helps.
- The cascade (a timed-out turn left running) is fixed in the driver (13:20); "no plan card, nothing logged"
  should fall once the measurements carry that fix.

## Step 5 image (queued after the step 4 hidden run; measured over three tuning runs, `rerun_three.sh step5`)

Built from `main` without step 3b's paragraph. On top of step 4 it holds:

- warnings on the card (CHECK THIS): numbers in the request the model does not use; a parameter whose given
  values all equal its default; a pair parameter given one way round; a trial plan that does nothing (every
  decision 0, or every decision but one);
- repairs: a list loaded or typed as 1 on a default of 1 gets default 0 (said on the card); one number read with
  an index, or with none, reads as one number;
- tables pasted into a message are attached as files, and the Assistant is told to load them.

More than one change in one measurement (rule 4 relaxed): each measurement now costs three tuning runs, and
every item above was found on the tuning set and tested there. The hidden run that follows judges them together.
