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
| base | 531fb9e (before step 2) | hidden, 16 small | 5 / 16 | 12 | 7 | 2 of the 7 are "checker could not read the plan" |
| step2 | b9f3943 (step 2 alone) | tuning, 10 small | running | | | |
| step2 | b9f3943 (step 2 alone) | hidden, 16 small | queued after tuning | | | |

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
- **No wrong answer carried a warning.** The checks of step 5 have nothing to say on these problems yet.
