# A neutral platform — the plan and its rules

**10 October 2026.** The owner asked for the platform to be fully neutral: no knowledge of any particular
domain in what the Assistant reads or in the platform's repairs, checks and messages; one pipeline for every
problem; and proof on problems it was never tuned on.

## Where it starts

- The Assistant's instructions in "describe a problem" mode are 32,000 characters. The rules are general, but
  the illustrations are not: one worked example spec (city projects, districts, a budget) and building blocks
  phrased in concrete terms ("project" 18 times, "map" 17, "district" 11, "stock" 9, "budget" 9, "truck" 8).
- Every repair and check added so far was found on one problem and tested only on that problem.
- Solvers are chosen by the model's shape, not its name (`docs/techniques.md`).
- On the 10 phase 1 small cases: 5 right after the fixes of 10 October, from 1.

## Steps

| Step | What | Exit |
|---|---|---|
| 1 | **Tuning and hidden sets.** Tuning: the 14 problems used so far. Hidden: 16 problems from new domains, written by independent agents, each with a generator, an independent reference and a checker of every hard rule. | The hidden set's score is the number that counts |
| 2 | **No domain content in what the Assistant reads.** Building blocks as modelling idioms; an abstract example (or several from different fields); messages in model terms; a build check that fails on domain words in the instructions | Tuning score does not drop |
| 3 | **Modelling idioms the Assistant fills in.** A balance carried between periods with its first period's starting amount; "only if chosen"; "the largest of"; at most / exactly one per group; within a threshold; next in order | Production and blending reach the other problems' rate |
| 4 | **Neutral data handling.** Any table shape (long or wide, composite keys, yes/no, dates, units); after loading, what was stored is shown against the file on the plan card | No data stored other than the file says |
| 5 | **Checks that do not depend on the problem.** Build twice and compare; every number and every rule sentence of the request mapped to the model; the existing structural checks | No wrong answer reaches a person without a warning |
| 6 | **Solver side.** Audit for anything keyed on names or templates; the special solvers reached only through general rule types | — |

**Done when** the hidden set scores within a few points of the tuning set, at ≥ 90% right first time with no
unwarned wrong answer, over three runs each.

## Rules for the hidden set

1. The hidden problems live in `backend/bench/hidden/`. Whoever changes the platform does **not** read the
   modules, the cases, or the run folders under `backend/bench/phase1/runs/hidden/` — only the aggregate from
   `python -m bench.phase1.blind runs/hidden <tag>`, which prints yes/no and numbers per case.
2. A fix is made and tested on the tuning set, then judged on the hidden set.
3. A defect seen only through a hidden case is described by its class (from the aggregate and the platform's own
   logs of refusal kinds), never by reading the case.
4. The hidden set is run before any step's changes (baseline) and after each step.
