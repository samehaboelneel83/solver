# Solver engine additions (Epic engine)

Five additions to how the platform solves, all built on the solvers it already ships (HiGHS,
IPOPT, CP-SAT, SCIP) — no commercial solver is needed for any of them.

| You want | You ask for | What happens |
| --- | --- | --- |
| Several good plans to pick from, not one | `"alternatives": 5` on a run | The next-best distinct plans within a gap of the best, each a run of its own |
| A better answer to a nonlinear model | setting `solve.solver_params` = `ipopt.starts=8` | IPOPT from several starting points; the best answer is kept |
| A large mixed model with an easy continuous part | `"solver": "benders"` on a run | Benders decomposition over HiGHS; a proven optimum |
| The learned selector to choose the solver | setting `solve.selector_acts` = `true` | A confident pick solves the run; the reason is recorded |
| A faster “why is this infeasible?” on large models | nothing — always on | QuickXplain in the conflict search above 12 candidate rules |

## 1. Alternative plans (E-1)

```http
POST /api/v1/scenarios/{id}/runs
{ "alternatives": 5, "alternatives_within": 0.02 }
```

After the best answer, the worker finds the best plan that differs from it in at least one
yes-or-no decision, then the best that differs from both, and so on — each held within
`alternatives_within` of the best goal value (a share of it, default 0.02; absolute below a value of
1). In the order found they are the k best distinct plans.

- Each alternative is a finished **run of its own** (`params.alternative_of` names the best run) with
  its own rules report, so it can be opened, compared and exported like any run. The runs list shows
  only the run that was asked for.
- `GET /api/v1/runs/{id}` returns `alternatives`: `seq`, `objective`, `changed` (how many yes-or-no
  decisions differ from the best), `status`, `run_id`. `params.alternatives_result` says how many were
  asked for and found, or why none were looked for (`skipped`).
- Fewer than asked means no more plans come within the gap.
- Refused with a reason: models with no yes-or-no decisions (distinctness is judged on those only), a
  lexicographic goal, a goal that multiplies decisions. `alternatives` together with `pareto_steps` or
  `robust` is a 422.
- Alternatives are never reused from, or stored in, the answer cache.
- On the Runs page: **Solve, with 5 alternative plans** (shown when the model has a yes-or-no decision).

How: one row holds the goal within the gap; each plan found adds a *no-good cut* that forbids exactly
that combination of the yes-or-no decisions. Code: `backend/app/solve/alternatives.py`; table
`run_alternative` (migration 0088).

## 2. IPOPT multistart (E-2)

IPOPT follows the slope from where it starts, so on a goal with several peaks one start finds the
nearest. With `ipopt.starts` (1, 4, 8, 16 or 32; setting `solve.solver_params`, or `solver_params` on
the bench) it solves from that many points — the first the model's hint or the middle of each range,
the rest spread one per slice of every decision's range (Latin hypercube; an unbounded side becomes
a box of 1,000 around the other) — and keeps the best. Each start gets an equal share of the time
limit, and the whole is reproducible from the run's seed.

The answer is still a **local** optimum: several nearby optima are still nearby optima. The solver
string says how it was found: it ends `, best of 8 answers from 8 starts`.
Code: `backend/app/solve/ipopt.py`.

## 3. Benders decomposition (E-3)

For a mixed model whose whole-number decisions are few (which sites to open) and whose continuous
part is large and easy once they are fixed (how much to ship). Asked for by name:
`"solver": "benders"`; the rules never choose it, since on most models HiGHS's own branch and cut is
faster.

- **Master**: the whole-number decisions, the rules on them alone, and `θ` for the continuous part's
  cost. **Subproblem**: the continuous part with those decisions fixed, a linear program.
- Each round the subproblem's row duals give an **optimality cut** (it prices the proposal) or, when
  the proposal leaves the continuous part with no answer, a phase-one program's duals give a
  **feasibility cut**. The loop stops when the master's bound meets the best answer: a proven,
  **global** optimum, reported with its bound. Out of time, the best answer found is `feasible`.
- Takes: linear goal and rules, both whole-number and continuous decisions, the continuous part
  bounded in the direction the goal pushes it. Soft rules, piecewise curves and conditional rules
  over declared bounds arrive as linear rows and are fine. Anything else is refused with the reason.
- The solver string records the work, e.g. `benders (highs 1.15.1): 14 rounds, 9 optimality and 4
  feasibility cuts`.

Code: `backend/app/solve/benders.py` (runs in HiGHS's child process, `highs_worker`).

## 4. The learned selector acting (E-4)

The selector (`app.solve.selector`) votes, from the stored benchmark, for the backend that solved the
most similar known models fastest. By default it only records its pick (shadow mode). With setting
`solve.selector_acts` = `true` (organization, domain or problem scope; migration 0088):

- a **confident** pick (80% of its 5 nearest models) solves the run;
- order of precedence: an explicit `solver` → the problem's own history (`solve.memory`) → the
  selector → the rules;
- it only ever picks among the backends the rules admit for the model;
- `why_solver` records the evidence (“the learned selector picked scip: 100% of the 5 nearest known
  models (…) were solved fastest by it; the rules would have chosen cp-sat”), and
  `params.selector` has `acted: true` and `rules_chose`. The run page shows “Learned selector (chose
  the solver)”.

## 5. QuickXplain in the conflict search (E-5)

An infeasible run's conflict is shrunk to an irreducible set of rules. Above 12 candidate rules the
search now splits the set in halves (QuickXplain) instead of testing one rule at a time: on 300
candidates with a 3-rule conflict it asks under a fifth of the probes. A probe that cannot decide in
its time stops the search, and the conflict is reported as not shown minimal. Code:
`backend/app/solve/diagnose.py`.

## Tests

`test_alternatives.py`, `test_multistart.py`, `test_benders.py`, `test_selector_acts.py`,
`test_quickxplain.py` (backend); `Runs.test.tsx` (alternatives and selector wording).
