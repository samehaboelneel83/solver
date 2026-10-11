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
| step2 | b9f3943 (step 2 alone) | tuning, 10 small | 5 / 10 | 7 | 2 (p03, p07) | exit met: the tuning score did not drop |
| step2 | b9f3943 (step 2 alone) | hidden, 16 small | running (from 04:19) | | | |
| step3 | image `solver-backend:step3`, built from 10dc21e (backend = fa738c9: step 3 + the step 4 card) | both | next | | | |
| step4 | the rest of step 4 (wide tables, units, the load report), committed after 10dc21e | both | after step3 | | | |

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
