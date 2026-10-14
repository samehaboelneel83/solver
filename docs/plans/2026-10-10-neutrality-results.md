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
| step4 | same | hidden, 16 small | 7 / 16 | 11 | 4 | the best hidden reading so far (base 6, step 2 4); 5 at the limit, all slow or lost replies |
| step5 | image `solver-backend:step5` (fourth start; the checks, repairs, send-backs, pasted tables, corridor, map items, 0122) | tuning x3 | mean 3.7 (3, 5, 3) | 21 of 30 | 7 of 30 | the three-run reading |
| step5 | same | hidden, 16 small | 4 / 16 | 8 | 3 | below step 4's 7: eight cases at the limit |
| step6 | image `solver-backend:step6` (seventh start; main at bb05f11 without 3b): + no-data, swamped-goal and goal-sense checks, `over` repair, unused-number rules, patch send-back (four defects fixed on the way), 4-minute cap, send-back log | tuning x3 | mean 4.3 (5, 3, 5) | 22 of 30 | 5 of 30 | |
| step6 | same | hidden, 16 small | 6 / 16 | 7 | 1 | six of the seven built are right; nine at the limit, all slow replies |
| step7 | image `solver-backend:step7` (main at 384549a without 3b): + the pair-table form of the no-data check | tuning x3 | mean 4.7 (5, 4, 5) | 20 of 30 | 2 of 30 | |
| step7 | same | hidden, 16 small (h07–h16 re-run after the WSL panic) | 4 / 16 | 6 | 2 | ten at the limit, every one a slow reply |

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
- send-backs: a trial plan that does nothing goes back to the Assistant before the person sees it (within the
  two send-backs a plan with no answer already has), with what to look for: a missing rule, or a goal that lets
  doing nothing win;
- tables pasted into a message are attached as files, and the Assistant is told to load them;
- plan E.1: with an aisle width, a way to an entrance must be that wide all along (the placement solver's
  reachability is now the eroded free area's door components, dilated back -- the layout checker's own test);
- plan E.2: the answer map draws the items a place rule laid out, as rectangles with their turn and aisle side
  (one layer per place rule).

More than one change in one measurement (rule 4 relaxed): each measurement now costs three tuning runs, and
every item above was found on the tuning set and tested there. The hidden run that follows judges them together.

## Neutrality enforced on the platform's own messages too (11 Oct, 15:25)

`tests/test_neutral_prompt.py` covered the Assistant's instructions only. It now also scans every message
constant the platform sends to the person or the model (15 in the Assistant's core) and renders, on neutral
inputs, the messages built at run time: the shape and data checks (`unread`, `as_default`, `one_way`), the trial
card and its model-facing line, the unused-numbers line, the repair notes and the file load line. Any word from
a particular field fails the build. Everything added today passes: each check and repair reads the model's or
the data's shape, never a name.

## Stand-alone, isolated (11 Oct, 15:55; the owner's requirement)

The platform runs isolated from the internet, with its language model inside the network. Audit of what it
reaches for: no package downloads at run time; UI fonts bundled (tested); the tile server local; ClickHouse
optional; the only outbound references are the two built-in internet map backgrounds, which were ON by default.
Changes: migration 0122 turns `spatial.internet_basemaps` off by default (an organization's own setting is
kept); the offline manifest and runbook now list the model as operator-supplied inside the network and say what
works without it (everything but the Assistant); `scripts/egress-check.sh` probes the model from the backend
container (OK / WARN). The migration ships in the step 5 image and is applied at its deploy
(`alembic upgrade head`), not during the hidden run.

Tile server on this machine (15:50–16:10): `spatial.tiles_index` names `http://localhost:8080/index.json`
(four Egypt tilesets). From inside the backend container `localhost` is the container, and the code already
tries `host.docker.internal` for the index, the terrain and the report's tiles. Found and fixed on the way:
the report's map tiles came back as gzip (the tile server stores them so and declares it; a browser undoes it,
urllib does not), so every report on the local satellite or topo tiles had no map. The report's tile fetch now
undoes gzip as the terrain reader always did; real tiles over Cairo stitch (satellite 68 KB, topo 23 KB of
picture). The egress smoke now also probes the tile index from the backend and prints where it reached it.

## step4 — hidden set, step 4 on step 2 (finished 16:17, 11 Oct)

```
case           built  first  solved right  viol  warned  min
h01-S          no     no     no     no    0     0       20.1
h02-S          yes    yes    yes    yes   0     0       8
h03-S          yes    yes    yes    yes   0     0       5
h04-S          yes    yes    yes    yes   0     0       12.6
h05-S          no     no     no     no    0     0       20.1
h06-S          yes    yes    yes    yes   0     0       4.5
h07-S          yes    yes    yes    no    5     0       11.1
h08-S          yes    yes    yes    yes   0     0       3.4
h09-S          yes    yes    yes    no    0     0       5.3
h10-S          no     no     no     no    0     0       20.1
h11-S          yes    yes    yes    yes   0     0       13.3
h12-S          yes    yes    yes    no    23    0       5.8
h13-S          yes    yes    yes    no    9     0       16
h14-S          no     no     no     no    0     0       20.1
h15-S          yes    yes    yes    yes   0     0       10.6
h16-S          no     no     no     no    0     0       20.1

7 right of 16; built 11; wrong but solved 4 (of them warned on the card 0)
```

- **7 right of 16**: base 6, step 2 4, step 4 7. Over one run each; the harness's stop-at-limit fix was in from
  h02 on, so the cascade of one timeout into the next is gone from this reading.
- **Where the time went** (`causes runs/hidden step4`): the 5 cases at the limit are all slow replies (a reply
  past 7 minutes, cut) or turns that never returned; 0 refusals among them. 2 refusals in all, both "Internal
  Server Error" on one case that was still built and right -- a platform 500 on a spec check; its backend log
  left with the container at the step 5 deploy. **Lesson:** read the backend log before a deploy; if it recurs
  under step 5, the log is the first place to look.
- **Wrong, unwarned 4**: two break hard rules heavily (23 and 9 violations), one lightly (5), one keeps every
  rule and misses the goal. The step 5 checks are the planned answer; this run is the base they are judged on.

## Step 5, first run stopped and restarted (11 Oct, 17:05)

Two defects of the step 5 image showed on its first tuning case (p02, not built, 3 warned cards): (1) the
unused-numbers check flagged a number given only to compare the answer with ("our current plan, whose cost is
17,305"), on every card, and a plan that cannot use it can never satisfy it -- sentences that compare or report
(compare, against, today, currently, saving, ...) are now left out of the check; (2) after the conversation was
summarized, the tables pasted into the first message were gone and the Assistant asked for files -- a summary
now carries the folded messages' pasted tables and the Assistant attaches them from it; the history sent to the
model is stripped to the API's own keys. The partial run (p02 not built, p04 right in 16 min) is kept as
`step5-1-aborted`; the measurement restarts on the fixed image as `step5` (three tuning runs, then hidden).

## Step 5, second start stopped: the list-default flip was wrong for a partial list (11 Oct, 17:40)

On the restarted run, p02 took its first card only at 14.5 minutes and it was infeasible: the approved list
names one customer of eight, the request says the others may be served from anywhere, and the repair that
flips a list's default (1 on 1 -> 0) made every unlisted customer unservable. Two send-backs (each a long
reply), a warned card declined, the retry stopped at the limit. The flip now happens only when the list names
every record of its first index; a partial list gets a note on the card and to the model with both readings
and the rule shape for the partial one (a 0/1 per record, amount <= most x (1 - listed[r] + pair[r, o])).
The partial run (p02 not built, p04 under way) is kept as `step5-2-aborted`; the measurement restarts on the
fixed image, still as `step5`. Three starts for one step: each defect was in a repair added today, found on the
tuning set, as the plan intends -- and each would have been invisible on the hidden set.

## Step 5, third start stopped: pasted tables were attached after the approved build ran (11 Oct, 17:50)

On the third start p02 reached its card in 2 minutes and the driver approved it; the build then said the files
were not attached. On an approval turn the pending build runs first, and the pasted tables were attached only
after it. They are now attached before anything runs (a test approves a pending plan and checks the files are
there when it builds). Partial run kept as `step5-3-aborted`; fourth start, same tag. Four starts: the first
three defects were all in the day's additions, each caught by the first tuning case.

## Queued for the next image (not in step 5's measurement): used where no data is given (11 Oct, 18:15)

Fourth start of step 5: p02 right (10.6 min), p04 wrong with no warning -- a product made on a machine the
times file never lists (its time defaulted to 0; the goal still matched the reference). New trial check,
general: a decision used on a cell where a parameter over the same record kinds gives no value, so its default
applied there; on the card as CHECK THIS with the cells, and to the model with the rule shape (keep the
decision to the pairs given). The same class as the allowed-list mistake, now caught from the answer rather than
from the data's shape.

Also queued (19:20): a term written with "over" and no "sum" is read as the sum of the term over the binding
(p07 under step 5: {"add": [...], "over": [b]} refused six times with the same message; the Assistant gave up
twice and the case was not built). A canonical-form repair, general.

## step5 — tuning run 1 of 3 (finished 19:53, 11 Oct; fourth start, image of 675334f + 34f5b6a + e0b29e8)

```
case           built  first  solved right  viol  warned  min
p01-S          yes    yes    yes    yes   0     0       3.6
p02-S          yes    yes    yes    yes   0     0       10.6
p03-S          yes    no     no     no    0     3       20
p04-S          yes    yes    yes    no    1     0       5.3
p05-S          yes    yes    yes    no    0     0       17.7
p06-S          no     no     no     no    0     0       20.1
p07-S          no     no     no     no    0     0       20.1
p08-S          no     no     no     no    0     0       20.1
p09-S          yes    yes    yes    yes   0     0       5.3
p10-S          yes    yes    yes    no    0     0       7.1

3 right of 10; built 7; wrong but solved 3 (of them warned on the card 0)
```

- p05 built for the first time in any run (the pasted tables), wrong by a goal that a penalty term swamps.
- p03: three cards, each warned by the unused-numbers check on lengths the layout holds in cells (0.9 m = 9
  cells); the harness declined them. A defect of the measured image, fixed (held in cells counts as held in
  metres) and **queued, not deployed**: the three runs stay on one image, and p03's reading is discounted.
- p08: the "does nothing" send-back caught a wrong model before the person saw it; the retry ran out of time.
- p07: refused six times for a term written with "over" and no "sum" (repair queued). p06: one long reply.
- Run 2 from 19:53; run 3 and the hidden set follow.

## step5 — tuning run 2 of 3 (finished 21:38, 11 Oct; same image)

```
case           built  first  solved right  viol  warned  min
p01-S          yes    yes    yes    yes   0     0       3.1
p02-S          yes    yes    yes    yes   0     0       2.8
p03-S          yes    no     yes    yes   0     2       16
p04-S          yes    yes    yes    no    2     0       4.4
p05-S          yes    yes    yes    no    0     0       9.7
p06-S          yes    no     yes    yes   0     1       19
p07-S          yes    yes    yes    no    1     0       4.5
p08-S          no     no     no     no    0     1       20.1
p09-S          yes    no     yes    yes   0     0       3.4
p10-S          no     no     no     no    0     1       20.1

5 right of 10; built 8; wrong but solved 3 (of them warned on the card 0)
```

- **p03 right for the first time in any run** (the corridor-width fix), even after two cards declined for the
  cells-as-metres false warning (fixed, queued). p06 right after one warned card.
- The two runs so far: 3 and 5 right; built 7 and 8; wrong unwarned 3 and 3. Run 3 from 21:38, then hidden.

## step5 — the three-run reading (run 3 finished 00:06, 12 Oct)

```
case     runs right built warned min (mean)
p01         3     3     3      0        3.7
p02         3     2     2      0       11.2
p03         3     2     3      3       17.0
p04         3     0     3      1        7.2
p05         3     0     3      0       14.7
p06         3     1     1      1       19.7
p07         3     0     1      0       14.9
p08         3     0     0      2       20.1
p09         3     3     3      0        6.9
p10         3     0     2      2       10.9

right per run: [3, 5, 3] -> mean 3.7 of 10, range 3-5; wrong unwarned (case-runs): 7 of 30
```

- **Mean 3.7 of 10, range 3–5.** Against the single runs before it (step 2: 6, step 4: 3) this image is not
  better, and the range says a single run of it could have read 3 or 5. The hidden run decides whether the
  checks pay there.
- **Always right:** p01, p09. **Never right:** p04 (the unlisted pair, check queued), p05 (built every time
  now, wrong by a swamped goal), p07 (the `over` term, repair queued), p08 (never built: the send-back catches
  its wrong model, the retry never finishes), p10 (two of three runs warned).
- **Warned:** 9 of 30 case-runs carried a warning, 7 wrong case-runs did not. The checks reach the person;
  they do not yet cover the common mistakes (the dropped rule most of all).
- **Time:** 9 of 30 not built, every one slow replies or a rewrite after a send-back -- lever 1.1 (patch, not
  rewrite) and 1.2 (a 4-minute cap) are built and queued for the next image.
- p05 run 3: the checker could not read the export (a tuning checker gap, to fix separately).

## step5 — hidden set (finished 04:20, 12 Oct)

```
case           built  first  solved right  viol  warned  min
h01-S          no     no     no     no    0     0       20.1
h02-S          no     no     no     no    0     0       20.1
h03-S          yes    no     yes    yes   0     3       3.9
h04-S          yes    yes    yes    no    4     0       4.3
h05-S          no     no     no     no    0     0       20.1
h06-S          yes    no     yes    yes   0     0       18.4
h07-S          yes    no     yes    yes   0     3       19.5
h08-S          yes    yes    yes    no    14    0       4.1
h09-S          yes    yes    yes    yes   0     0       6.6
h10-S          no     no     no     no    0     0       20.1
h11-S          no     no     no     no    0     0       14
h12-S          yes    no     no     no    0     0       20.1
h13-S          no     no     no     no    0     0       20
h14-S          no     no     no     no    0     0       20.1
h15-S          no     no     no     no    0     0       20.1
h16-S          yes    yes    yes    no    0     0       18.2

4 right of 16; built 8; wrong but solved 3 (of them warned on the card 0)
```

- **4 right, from step 4's 7; built 8, from 11.** The checks and send-backs of step 5 cost time on problems
  the model finds hard: eight cases at the limit (five under step 4), one built and never solved. Two right
  cases carried three warnings each (declined by the harness as a cautious person would, and still right).
- **Three wrong without a warning** (4 and 14 violations, one goal miss): none of today's checks spoke.
- By the causes table: of the eight at the limit, five are slow or lost replies, one is five refusals of
  five different kinds, two are turns that never returned. 
- **A fault of mine:** three backend errors were logged during this run; I counted them and deployed before
  reading them, and the log went with the container. The rule stands: read, then deploy.
- A record key leaked through the causes template (an upper-case bare word); the template now masks those.

**Reading:** step 5 is a loss on the hidden set on time, a draw on wrong-unwarned. The next image (step 6)
carries the time levers (patch instead of rewrite, a 4-minute cap) and the three checks that would have spoken
on p04, p05 and p07; its three tuning runs and hidden run started 04:25.

## Step 6, first start stopped: a partial seed replaced the whole seed (12 Oct, 05:25)

p02 and p04 both unbuilt at the limit on the new image, p04 after eleven refusals of "a parameter is used but
no value is loaded". The patch send-back told the model to send only what changes and never the seed; a fix
that needs new data must touch the seed, and when the model sent a partial seed the merge replaced the whole
seed with it, so the next refusal was about everything else. The seed is now merged list by list and entry by
key (a parameter by name, a record by type and key, a file entry by what it loads; `"drop": true` removes), and
the hint says so. Partial run kept as `step6-1-aborted`; second start, same tag.

## step6 — tuning run 1 of 3 (finished 07:27, 12 Oct; second start, image of 6721f5b without 3b)

```
case           built  first  solved right  viol  warned  min
p01-S          yes    yes    yes    yes   0     0       7.5
p02-S          yes    yes    yes    yes   0     0       3.7
p03-S          yes    yes    yes    yes   0     0       8.4
p04-S          yes    yes    yes    yes   0     0       6.8
p05-S          no     no     no     no    0     2       20.1
p06-S          no     no     no     no    0     0       20.1
p07-S          yes    no     yes    no    44    0       16.1
p08-S          no     no     no     no    0     2       20
p09-S          yes    yes    yes    yes   0     0       4
p10-S          no     no     no     no    0     0       20.1

5 right of 10; built 6; wrong but solved 1 (of them warned on the card 0)
```

- **Every built case but one is right, and every right case came first time with no warning.** p04 right for
  the first time in any run (the no-data check on the trial); p03 right again (the corridor fix).
- **Wrong unwarned: 1** (p07, 44 violations: the rule-left-out class, Phase 3.2's).
- **Not built: 4**, all at the limit: p05 and p08 after two warned cards each (declined by the harness), p06
  and p10 on long replies. The time levers are in this image; the cap is 4 minutes; what remains is the
  model's own pace on hard cases. Runs 2 and 3 follow, then the hidden set.

## Step 6, second start stopped: a refusal that a patch cannot clear (12 Oct, 08:30)

Run 2 opened with p02 and p04 unbuilt (3 and 14 refusals of one kind each) after both built first time in
run 1. A rule left out of a patch stays, so a model that removes a rule by resending without it gets the same
refusal back, as often as it tries. Now: every send-back is logged (`assistant.sent_back`, the panel keeps only
a clipped preview); the same refusal a second time after a patch names the rules the plan still holds and how
to drop one; a third time asks for the whole plan, and the next plan is taken whole, no merge. Run 1 (5 of 10)
stands as the reading of the image before this rule, kept as `step6a-1`; the partial run 2 as
`step6a-2-aborted`; the three runs restart as `step6`.

## Harness: workspace names collided across restarts (12 Oct, 08:30; found by the new send-back log)

Each case's workspace is named "P1 <case> S <tag>"; a restart reuses the tag, so the name already exists from
the aborted start, the plan is refused ("a domain named ... already exists"), and the Assistant spends
send-backs on the name or answers from the stale workspace (p04 on the third start of step 6 reported the
aborted run's result without building). Every first run after a restart carried this: step 5 run 1 (four
starts) and step 6 runs 1 (three starts). The runners now add the clock time to the name. This third start
is kept as `step6b-1-aborted`; the fourth start, same tag, with unique names.

## Step 6, fourth start stopped: the draft did not survive a summary (12 Oct, 09:05)

With unique workspace names, p02 was right (7.2 min, three warned cards); p04 ran out of time on a path the
send-back log shows in full: refusals, then the conversation summarized, then every patch refused as "the spec
has no ir" -- the folded propose_plan calls were gone and a patch had no draft to complete from. The draft now
travels on the summary (like the pasted tables) and the fold starts from it; the history sent to the model
carries neither. This start is kept as `step6c-1-aborted`; fifth start, same tag.

## Step 6, fifth start stopped: a seed-only patch was not a patch (12 Oct, 09:40)

p02 right (13.4 min); p04 in refusals, among them "the spec has no ir" twice: a patch carrying new data and
no ir was taken whole and refused for having no model. A seed alone is a patch now. Kept as
`step6d-1-aborted`; sixth start, same tag. The send-back log reads each of these in one look; before it, each
cost a run.

## Step 6, sixth start stopped: the clock in the workspace name was flagged as an unused number (12 Oct, 09:55)

p02 and p04 right (4 and 8 min) but each with two cards declined for "0935" / "0940": the time the runners now
put in the workspace name. A number inside a quoted name is not data; the check skips quoted text. p04's
other warning was the no-data check naming two unlisted machine pairs, which the model then fixed: the first
time that check turned a wrong plan right before the person saw it. Kept as `step6e-1-aborted`; seventh start.

## step6 — tuning run 1 of 3 (finished 11:40, 12 Oct; seventh start, image of bb05f11 without 3b)

```
case           built  first  solved right  viol  warned  min
p01-S          yes    yes    yes    yes   0     0       4.8
p02-S          yes    yes    yes    yes   0     0       5
p03-S          yes    no     yes    yes   0     3       8.3
p04-S          yes    no     yes    yes   0     1       6.2
p05-S          no     no     no     no    0     1       20.1
p06-S          no     no     no     no    0     0       20.1
p07-S          yes    yes    yes    no    1     0       4.1
p08-S          yes    no     yes    no    2     3       19.2
p09-S          yes    yes    yes    yes   0     0       4.1
p10-S          no     no     no     no    0     0       14.8

5 right of 10; built 7; wrong but solved 2 (of them warned on the card 1)
```

- **5 right of 10, 7 built, 2 wrong of which 1 warned** (p08, built for the first time in any run and warned on
  the card; p07 wrong unwarned, the rule-left-out class). Three cases at the limit.
- The seven starts: four defects of the patch send-back (a whole seed swapped in, an un-droppable rule, the
  draft lost at a summary, a seed-only patch taken whole), one harness fault (workspace names colliding across
  restarts), one false warning (the clock in the name) -- each read in one look from the send-back log, each
  fixed on the tuning set before it reached the hidden one.

## step6 — tuning run 2 of 3 (finished 13:47, 12 Oct; same image)

```
case           built  first  solved right  viol  warned  min
p01-S          yes    yes    yes    yes   0     0       5.3
p02-S          no     no     no     no    0     1       20.1
p03-S          yes    no     yes    yes   0     1       5.3
p04-S          yes    yes    yes    no    1     0       13.2
p05-S          yes    no     yes    no    0     3       17
p06-S          no     no     no     no    0     0       20.1
p07-S          yes    no     yes    no    1     0       7.7
p08-S          no     no     no     no    0     1       20.1
p09-S          yes    yes    yes    yes   0     0       7.5
p10-S          yes    no     yes    no    0     1       8

3 right of 10; built 7; wrong but solved 4 (of them warned on the card 2)
```

- **3 right of 10, 7 built, 4 wrong of which 2 warned.** p05 built and solved for the second time ever (wrong,
  warned three times); p03 right again. Wrong unwarned: p04 (the allowed pairs loaded as a record kind, a shape
  the queued check now reads) and p07 (the rule left out).
- p02's declined warning was a true one (two closed routes shipped on at zero cost, named exactly); the retry
  ran past the limit. Runs so far on this image: 5 and 3. Run 3 from 13:47, then the hidden set.

## Harness: the base run found through the problem, not the page (12 Oct, 14:50)

p08 in step 6 run 3 was scored on its "Budget 400k" what-if again: the base run was not among the ids the page
showed, so the driver's fallback took the newest. The driver now walks from any run to the problem's base
scenario and its newest answered run; `rebase_runs.py` re-scored the finished folders (p08 run 3 right, goal
620,380 = reference; p07 run 1 moved to a wrong base plan with one violation). The run 1 and run 2 tables above
are read with that in mind; the three-run reading is computed after it.

## step6 — tuning run 3 of 3 (finished 15:28, 12 Oct) and the three-run reading

```
case           built  first  solved right  viol  warned  min
p01-S          yes    yes    yes    yes   0     0       2
p02-S          yes    yes    yes    yes   0     0       3.6
p03-S          yes    yes    yes    yes   0     0       7.5
p04-S          yes    yes    no     no    0     0       20.1
p05-S          no     no     no     no    0     0       20.1
p06-S          yes    yes    yes    no    0     0       7.7
p07-S          yes    yes    yes    no    1     0       5.1
p08-S          yes    no     yes    yes   0     0       14.3
p09-S          yes    no     yes    yes   0     0       4.6
p10-S          no     no     no     no    0     0       13.3

5 right of 10; built 8; wrong but solved 2 (of them warned on the card 0)
```

```
case     runs right built warned min (mean)
p01         3     3     3      0        4.0
p02         3     2     2      1        9.6
p03         3     3     3      2        7.0
p04         3     1     3      1       13.2
p05         3     0     1      2       19.1
p06         3     0     1      0       16.0
p07         3     0     3      0        5.6
p08         3     1     2      2       17.9
p09         3     3     3      0        5.4
p10         3     0     1      1       12.0

right per run: [5, 3, 5] -> mean 4.3 of 10, range 3-5; wrong unwarned (case-runs): 5 of 30
```

- **Mean 4.3 of 10 (5, 3, 5), range 3–5; built 22 of 30; wrong unwarned 5 of 30 case-runs** (after the base-run
  re-scoring; `three.py`'s tally). Against the step 5 image (mean 3.7: 3, 5, 3; built 21; wrong unwarned 7 of
  30): about one case better on the mean, the same range, one more built, two fewer wrong unwarned -- the new
  checks caught more (p04, p02's closed routes), and the model's variance gave some back (p06, p10).
- **Always right on this image:** p01, p03 (the corridor fix holds), p09; p02 in two of three; **p08 right once**
  (first ever); p05 built, though not right.
- **Still never right:** p04 (right once, then the record-kind shape, now covered in the queued check), p06
  (a weaker model, nothing warns), p07 (the rule left out, Phase 3.2), p10.
- The hidden run follows (from 15:28); the next image (the pair-table check) after it.

## step6 — hidden set (finished 19:20, 12 Oct)

```
case           built  first  solved right  viol  warned  min
h01-S          no     no     no     no    0     0       20.1
h02-S          no     no     no     no    0     0       20
h03-S          yes    yes    yes    yes   0     0       2.6
h04-S          yes    yes    yes    yes   0     0       9.7
h05-S          no     no     no     no    0     0       20
h06-S          yes    yes    yes    yes   0     0       2.7
h07-S          yes    yes    yes    yes   0     0       14.5
h08-S          yes    yes    yes    yes   0     0       4.2
h09-S          yes    no     yes    yes   0     3       11.2
h10-S          no     no     no     no    0     0       20
h11-S          no     no     no     no    0     0       20
h12-S          yes    yes    yes    no    23    0       7.5
h13-S          no     no     no     no    0     0       20
h14-S          no     no     no     no    0     0       20.1
h15-S          no     no     no     no    0     0       20
h16-S          no     no     no     no    0     0       20

6 right of 16; built 7; wrong but solved 1 (of them warned on the card 0)
```

| Hidden reading | base | step 2 | step 4 | step 5 | step 6 |
|---|---|---|---|---|---|
| right of 16 | 6 | 4 | 7 | 4 | 6 |
| built | 12 | 9 | 11 | 8 | 7 |
| wrong, unwarned | 6 | 3 | 4 | 3 | 1 |

- **Six of the seven built are right** (five first time, one after three warned cards declined). One wrong
  unwarned (23 violations: rules left out, the Phase 3.2 class). The checks are now doing on the hidden set
  what they do on the tuning set: a built model is nearly always right or warned.
- **Nine at the limit, every one a slow reply** (the 4-minute cap cut it, the shorter re-ask did not finish);
  no refusals, no backend errors (read before the deploy this time). The loss is the model's own pace on the
  problems it finds hard; the staged protocol (Phase 3) is the structural answer, the patch send-back its
  first half.
- The next image (step 7: the pair-table form of the no-data check) measures overnight.

## step7 — tuning run 1 of 3 (finished 21:44, 12 Oct; image of 384549a without 3b)

```
case           built  first  solved right  viol  warned  min
p01-S          yes    yes    yes    yes   0     0       3.8
p02-S          yes    yes    yes    yes   0     0       3.6
p03-S          yes    no     yes    yes   0     1       6.8
p04-S          yes    no     yes    yes   0     1       11.3
p05-S          no     no     no     no    0     1       20.1
p06-S          no     no     no     no    0     0       20.1
p07-S          no     no     no     no    0     0       20.1
p08-S          no     no     no     no    0     0       20
p09-S          yes    yes    yes    yes   0     0       8.9
p10-S          no     no     no     no    0     0       20

5 right of 10; built 5; wrong but solved 0 (of them warned on the card 0)
```

- **5 right of 10, 5 built, 0 wrong**: every model built was right (p03 and p04 after one true warning each);
  five cases at the limit. The first run with no wrong answer at all. Runs 2 and 3, then the hidden set,
  overnight.

## step7 — tuning run 2 of 3 (finished 23:46, 12 Oct; same image)

```
case           built  first  solved right  viol  warned  min
p01-S          yes    yes    yes    yes   0     0       3
p02-S          yes    yes    yes    yes   0     0       2.7
p03-S          yes    no     yes    yes   0     3       9.9
p04-S          yes    no     yes    no    0     3       18.8  (checker could not read the plan)
p05-S          no     no     no     no    0     0       20
p06-S          no     no     no     no    0     0       20.1
p07-S          no     no     no     no    0     1       20
p08-S          yes    no     yes    no    1     3       15
p09-S          yes    yes    yes    yes   0     0       5.1
p10-S          yes    yes    yes    no    0     0       4.6

4 right of 10; built 7; wrong but solved 3 (of them warned on the card 2)
```

- **4 right of 10, 7 built, 3 wrong of which 2 warned**; the unwarned one keeps every rule and misses the goal
  (p10, 4.6 min: the weaker-model class, nothing warns on it yet). Run 3 from 00:02, then the hidden set.

## step7 — tuning run 3 of 3 (finished 01:42, 13 Oct) and the three-run reading

```
case           built  first  solved right  viol  warned  min
p01-S          yes    yes    yes    yes   0     0       4.2
p02-S          yes    yes    yes    yes   0     0       4.6
p03-S          yes    no     yes    yes   0     3       6.5
p04-S          yes    yes    yes    yes   0     0       10.6
p05-S          yes    no     no     no    0     4       20.1
p06-S          no     no     no     no    0     0       20.1
p07-S          yes    yes    yes    no    68    0       9.2
p08-S          no     no     no     no    0     1       20
p09-S          yes    no     yes    yes   0     0       6.3
p10-S          yes    no     yes    no    0     1       10.7

5 right of 10; built 8; wrong but solved 2 (of them warned on the card 1)
```

```
case     runs right built warned min (mean)
p01         3     3     3      0        3.7
p02         3     3     3      0        3.6
p03         3     3     3      3        7.7
p04         3     2     3      2       13.6
p05         3     0     1      2       20.1
p06         3     0     0      0       20.1
p07         3     0     1      1       16.4
p08         3     0     1      2       18.3
p09         3     3     3      0        6.8
p10         3     0     2      1       11.8

right per run: [5, 4, 5] -> mean 4.7 of 10, range 4-5; wrong unwarned (case-runs): 2 of 30
```

- **Mean 4.7 of 10 (5, 4, 5), range 4–5; built 20 of 30; wrong unwarned 2 of 30.** Against step 6 (4.3: 5, 3, 5;
  22 built; 5 unwarned) and step 5 (3.7: 3, 5, 3; 21; 7): the mean edges up, the range narrows, and the
  wrong-unwarned count keeps falling (7 → 5 → 2). p01, p02, p03, p09 right in every run; p04 in two of three.
  Never right: p05, p06, p07, p08, p10 -- the slow cases, lost to the limit more often than to a wrong model.
- The hidden run follows (from 01:42).

## Incident: a WSL kernel panic stopped Docker at 03:26 (13 Oct)

During step 7's hidden run, the WSL virtual machine behind Docker Desktop died ("Kernel panic - not syncing:
Fatal machine check": a hardware fault reported inside the VM, not the platform). h01–h06 had run on a healthy
stack; h07–h16 each "ran" in a second against a dead backend. Docker Desktop was restarted (the engine back
in 20 s), the stack came up on the same image and migration, and the ten voided cases are re-run under the same
tag (`run_hidden.sh` now takes a list of cases). The model server was unaffected throughout.

## step7 — hidden set (finished 06:38, 13 Oct; h01–h06 before the panic, h07–h16 re-run after it)

```
case           built  first  solved right  viol  warned  min
h01-S          yes    yes    yes    no    1     0       17.1
h02-S          no     no     no     no    0     0       20.1
h03-S          yes    yes    yes    yes   0     0       12.2
h04-S          no     no     no     no    0     0       20
h05-S          no     no     no     no    0     0       20
h06-S          yes    yes    yes    yes   0     0       2.4
h07-S          yes    yes    yes    yes   0     0       11.1
h08-S          yes    yes    yes    no    1     0       7.8
h09-S          no     no     no     no    0     0       20
h10-S          no     no     no     no    0     0       20
h11-S          no     no     no     no    0     0       19.5
h12-S          no     no     no     no    0     0       20
h13-S          no     no     no     no    0     0       20
h14-S          no     no     no     no    0     0       16.6
h15-S          yes    yes    yes    yes   0     0       10.2
h16-S          no     no     no     no    0     1       20

4 right of 16; built 6; wrong but solved 2 (of them warned on the card 0)
```

| Hidden reading | base | step 2 | step 4 | step 5 | step 6 | step 7 |
|---|---|---|---|---|---|---|
| right of 16 | 6 | 4 | 7 | 4 | 6 | 4 |
| built | 12 | 9 | 11 | 8 | 7 | 6 |
| wrong, unwarned | 6 | 3 | 4 | 3 | 1 | 2 |
| at the limit | 4 | 9 | 5 | 8 | 9 | 10 |

- **Within variance of step 6** (the images differ by one check): 4 of the 6 built are right, the 2 wrong miss
  by one violation each, unwarned (the rule-left-out class). No refusals, no backend errors.
- **Time is the whole loss on the hidden set:** ten cases with a reply past the 4-minute cap; the shorter re-ask
  did not finish either. Across the series "right" has not moved (6, 4, 7, 4, 6, 4) while "built" has fallen
  as the checks and send-backs added work for a model that was already slow on these problems; what is built
  is right far more often than at the start (6 of 12 → 4 of 6).
- **Reading for the plan:** the checks have done their part (wrong unwarned 6 → 2); the levers that buy time
  inside the one-shot design (the patch send-back, the 4-minute cap) did not recover the slow hidden cases.
  The next gain is structural: the staged protocol (Phase 3), where a stage is a small reply by construction.
  No new image is queued; the measurement loop pauses here and the work moves to Phases 1.2–3.

## Step 8 image (13 Oct, 18:10): main as it is, step 3b included -- "evaluate before pushing"

The owner's instruction on 13 October: evaluate before pushing. So the queued step 3b (fe687b8, the six
instruction lines never measured) is measured now, on the image built from main at 1ddf630, which also carries
the Phase 1-3 work of 13 October: the canonical form (`app/agent/canon.py`, every repair in one pass, the
fixed point on the golds), refusals that name the fix, the constructs library (nine constructs with their
examples), the always-yes warning on the trial card, and the build protocol's stages wired as tools -- but
**not told to the model** (3.3 is after this measurement), so the model takes the old path with step 3b's
lines on top. What this step measures against step 7 is therefore: step 3b + the pass + the new refusal texts
+ the always-yes warning. Procedure as before: the backend log read (no errors in 6 h), the whole suite on
main, the image from a clean worktree, `rerun_three.sh step8` (three tuning runs, then the hidden set, read
blind). The push to GitHub waits for the reading.

**Deployed 13 Oct, 20:50** (the owner's go-ahead: "do with all authorities and permissions"): `solver-backend:step8`
(6ae679) on backend and the three workers; verified in the container: `canon.py`, `stages.py`, `sentences.py`
present, the always-yes check and step 3b's SHORTCUTS lines in, migration 0122, health 200, a clean start log.
`rerun_three.sh step8` started at 20:52: runs `step8-1`, `-2`, `-3`, then the hidden set.

**Incident, 13-14 Oct.** Run 1 began at 23:51 (p02 done in 2.8 min, built). At 00:39 the backend and worker
containers were recreated (the deploy command run a second time from the owner's side: same image, restart
count 0), which cut p04's turn; the driver exited and the three-run script with it. Resumed at 01:42 with
`run_step8_rest.sh`, launched detached (a tool's own timeout can end a script it started): the rest of run
1 (`rerun_small.sh` now takes a case list, as `run_hidden.sh` does), then runs 2 and 3, then the hidden set.
Note: main gained 4ab2959 at 01:01 on 14 Oct from another session (the Assistant asks for another way before
giving up; a probe-first lane check for LNS). The step 8 image is from 1ddf630 and does not carry it.

### Step 8, run 1 (14 Oct, 03:42): 4 right of 10; built 8; wrong but solved 4 (warned 2)

*(First read as 3 right: p04's plan keyed its decisions (machine, product, shift) and the checker's shared
lookup matched key positions in one fixed order. `common.decision_over` now accepts any order of the key
positions; p04 rescored right (goal 963, no violation). Earlier runs can be rescored the same way with
`rebase_runs.py` where a "checker could not read the plan" mark appears.)*

| case | built | first | solved | right | viol | warned | min |
|---|---|---|---|---|---|---|---|
| p01 | yes | no | yes | yes | 0 | 0 | 11.7 |
| p02 | yes | no | yes | no | 2 | 3 | 2.8 |
| p03 | yes | yes | yes | yes | 0 | 0 | 11.2 |
| p04 | yes | no | yes | yes (after the checker fix) | 0 | 3 | 18.9 |
| p05 | no | no | no | no | 0 | 0 | 20.1 |
| p06 | no | no | no | no | 0 | 0 | 20 |
| p07 | yes | no | yes | no | 1 | 3 | 13.7 |
| p08 | yes | no | yes | yes | 0 | 3 | 9.9 |
| p09 | yes | yes | yes | no | 0 | 0 | 3.2 |
| p10 | yes | yes | yes | no | 2 | 0 | 8.3 |

Reading: 4 right; 2 wrong without a warning (p09: a different goal, no violation;
p10: 2 violations, unwarned); 2 unbuilt at the limit (p05 after 6 refusals and a long reply, p06 after
three continues). Causes: refusals 7 in all (p05's 6 are the filter shape and a quadratic product), slow
replies 6 across the run. Within the run-to-run noise of step 7 (5, 4, 5); runs 2 and 3 decide.
*(The step 5-7 runs, tuning and hidden, rescored with the key-order fix: every aggregate as recorded --
tuning 3/5/3, 5/3/5, 5/4/5; hidden 4, 6, 4 of 16. The series stands; the fix only lifts p04 under step 8.)*

### Step 8, run 2 (14 Oct, 05:43): 5 right of 10; built 7; wrong but solved 2 (warned 0)

| case | built | first | solved | right | viol | warned | min |
|---|---|---|---|---|---|---|---|
| p01 | yes | yes | yes | yes | 0 | 0 | 4.1 |
| p02 | yes | yes | yes | yes | 0 | 0 | 3.1 |
| p03 | yes | no | yes | yes | 0 | 3 | 10.4 |
| p04 | yes | no | yes | yes | 0 | 3 | 10.8 |
| p05 | no | no | no | no | 0 | 1 | 20.1 |
| p06 | no | no | no | no | 0 | 0 | 20.1 |
| p07 | yes | yes | yes | no | 1 | 0 | 17.9 |
| p08 | no | no | no | no | 0 | 0 | 20.1 |
| p09 | yes | yes | yes | yes | 0 | 0 | 7.9 |
| p10 | yes | yes | yes | no | 0 | 0 | 4.4 |

Reading: 5 right, four of them first time; 2 wrong without a warning (p07 one violation; p10 a different
goal, no violation); 3 unbuilt at the limit, all on slow replies (p05 two, p06 and p08 one each; two refusals
in the whole run). Runs so far: 4, 5.

**Time limit raised (14 Oct, 06:50, the owner's instruction): 20 -> 30 minutes a case** in `rerun_small.sh`,
`run_hidden.sh` and `run_parallel.sh`. Step 8's three runs were at 20 (run 3 was already under way, on the
limit it started with); step 9 and after are at 30, so a case that was "at the limit" under step 8 may build
under step 9 on time alone -- the readings say the limit beside the counts from here on.

### Step 8, run 3 (14 Oct, 07:41): 4 right of 10; built 6; wrong but solved 2 (warned 0)

| case | built | first | solved | right | viol | warned | min |
|---|---|---|---|---|---|---|---|
| p01 | yes | yes | yes | no | 3 | 0 | 3.7 |
| p02 | yes | yes | yes | yes | 0 | 0 | 1.9 |
| p03 | yes | no | yes | yes | 0 | 3 | 5.9 |
| p04 | yes | no | yes | yes | 0 | 3 | 11.6 |
| p05 | no | no | no | no | 0 | 0 | 20 |
| p06 | no | no | no | no | 0 | 0 | 14.7 |
| p07 | yes | yes | yes | no | 70 | 0 | 14.1 |
| p08 | no | no | no | no | 0 | 2 | 20.1 |
| p09 | yes | no | yes | yes | 0 | 0 | 4 |
| p10 | no | no | no | no | 0 | 0 | 20 |

Causes: refusals 6 (five of "a parameter holds data but no rule or goal reads it", on p05 and p10, which
ended at the limit), slow replies 5, p06 three continues and stopped short of the limit.

### Step 8, the three-run reading (the old path's baseline for step 9)

| | step 7 | step 8 |
|---|---|---|
| right per run | 5, 4, 5 (mean 4.7) | 4, 5, 4 (mean 4.3) |
| wrong without a warning (case-runs of 30) | 2 | **6** |
| never built in three runs | p05, p06 | p05, p06 |

Per case over the three runs: p03 and p04 right every time; p01, p02, p09 right twice; p08 once; p05, p06,
p07, p10 never (p07 built every time and wrong every time, 1, 1 and 70 violations, warned once).

Reading: no gain, and the unwarned-wrong count is back up (6 of 30, from 2). Step 8 carried four changes
at once over step 7 -- step 3b's SHORTCUTS lines, the canonical pass, the refusal texts that name the fix,
the always-yes warning -- so the rise cannot be pinned on one; the case shape is the known one (p07's model
misses rules the request states, p10 and p01 answer a different goal or hold a rule too loosely), which is
the class the protocol's sentence mapping (3.2) is built to warn about. Step 3b's lines are gone in step 9
(3.3 replaced them by the constructs' descriptions), so step 9 is read against this baseline: mean 4.3,
6 wrong unwarned of 30, at the 20-minute limit (step 9 runs at 30).

## Step 9 image (14 Oct, 07:55): the build protocol -- built, waiting to be deployed

`solver-backend:step9`, from main at 048928f (3.3 included: the model is told to build in stages; the
constructs' descriptions replace step 3b's lines; it also carries 4ab2959, another session's "asks for
another way before giving up"). The backend log since step 8's start shows no errors. The deploy command
was refused by this session's permission check, so it waits for the owner:

    docker tag solver-backend:step9 solver-backend:latest && docker compose up -d --no-build backend worker

Then `backend/bench/phase1/run_step9.sh` (three tuning runs through the parallel runner, three cases at a
time, then the hidden set; 30 minutes a case), read against step 8: mean 4.3, 6 wrong unwarned of 30.

**Step 9 deployed 14 Oct, 07:50** (the owner's go-ahead: "run with all authorities and permissions"):
`solver-backend:step9` (066dc4) on backend and the three workers; verified in the container: the protocol's
PHASE 2 text present, step 3b's SHORTCUTS block gone, migration 0122, health 200. `run_step9.sh` started at
07:51, detached: three cases at a time (p02, p04, p06 first).

**Step 9, first start stopped (14 Oct, 07:55) and restarted at 07:58 on a rebuilt image (b9e722, main at
b9c4983).** Three findings in its first four minutes:
1. *The parallel runner* wrote every case to `runs/-S-step9-1` (bash expanded the path before the case id was
   assigned, both in one `local`); the three drivers overwrote each other. Fixed; each case has its folder.
2. *A protocol defect:* the turn loop handles `propose_plan` itself and never set the call id, so the plan was
   assembled from the stage calls only up to the last one executed -- that stage (usually the goal) was
   dropped. Fixed, with a regression test that shows the goal missing under the stale id.
3. *Observability:* only send-backs were logged, so whether the model used the stages at all could not be read
   (the two send-backs of the first start came from a whole-spec `propose_plan`). Every tool call is now logged
   by name and outcome (`assistant.tool <name> ok|refused [whole-spec]`, no arguments or data).
The first start's workspaces are left in place under their own clock-suffixed names; nothing of them is scored.

**Step 9, second start stopped at 08:16 and restarted at 08:23 on image 6bef01 (main at 4298899).** The tool
log of its first 17 minutes (five cases begun, three scored: p01 right, p04 right, p02 wrong) showed the
protocol barely used and broken where used: of 5 cases 1 built in stages (p02); 29 whole-spec proposals, 23
refused. p02's stages exposed two defects: a goal staged after an `only_if` rule was refused because the
stage checks did not expand constructs; and propose_plan with no spec had nowhere to name the new workspace,
so it was refused for reusing the selected one and the model fell back to the whole spec. Both fixed, with
tests; and a refused whole-spec plan now answers with the stage that fixes it. The second start's scores
are discarded (the image under them had both defects).

**Harness fault in the parallel runs, found 09:15.** p04 and p08 had been scored on p02's and p01's runs: the
driver added "the platform's newest run" to a case's candidates, which with three cases side by side is often
another case's. `drive_case.mjs` now takes only the runs of the problems its own panel links to (never the
newest run when `PARALLEL=1`, which `run_parallel.sh` sets). p04 and p08 were re-fetched from their own
workspaces (`rescue_run.py`: one run each, 753 and 759) and rescored: **p04 right** (goal 963), p08 wrong
(one violation). Serial runs (steps 1-8) took the newest run safely, one case at a time.
