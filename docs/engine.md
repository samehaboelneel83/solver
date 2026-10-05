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
| A network model solved as a network, by NetworkX | `"solver": "networkx"` on a run (or nothing: the network lane uses it) | Network simplex (min-cost flow); a proven optimum |

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

## NetworkX as a solver

NetworkX (BSD licence, `networkx==3.6.1`) is in the image and used two ways.

**As a solver of its own, asked for by name:** `POST /api/v1/scenarios/{id}/runs {"solver": "networkx"}`.
It takes a *network* model — transport, assignment, shortest path, maximum flow and any mix of them:
every rule is flow in less flow out (each coefficient +1 or −1, each decision in at most two rules, a
rule on one decision read as its bound), and every number is whole. It builds the network
(`networkx.MultiDiGraph`, a node per rule plus one outside node, an arc per decision) and solves it with
`networkx.network_simplex`: the optimum is **proven** (`optimality: global`), infeasible is a proof too, and
an answer resting on a guard ceiling is reported unbounded with the reason, as for every solver.
Continuous and whole-number networks both work (a network's LP optimum is whole). Anything else — a
knapsack row, a product, a curve, a fractional cost — is refused before solving, with the reason, e.g.
*"networkx solves a network … This model is not one: the rule 'cap' weighs a decision by more than one"*.
The rules never choose it unasked (`automatic=False`): the model class alone cannot tell a network from
any other linear model.

**As the network lane's engine (the default):** with setting `solve.network` on, a whole-number network
model is solved by min-cost flow without being asked. Setting `solve.network_engine` (migration 0108)
picks the algorithm: `networkx` (the default) or `ortools` (OR-Tools `SimpleMinCostFlow`, about ten
times quicker on large networks: a 400 × 400 assignment in 0.1 s against 1.1 s). Both prove the same
optimum. The run records the engine in `params.network_engine` and `params.network_run.engine`, and the
solver string says which: `network (min-cost flow, NetworkX network simplex)`.

The Assistant's `run_python` has NetworkX too (paths, connectivity, components), e.g. to work out which
cells of a layout reach a door before the model is written.

Code: `backend/app/solve/network.py` (`_walk_networkx`, `_walk_ortools`), the `NETWORKX` entry in
`backend/app/solve/backends.py`. Tests: `backend/tests/test_network.py`, the `transport_network` case in
`test_golden.py`.


## A run's answer as a CAD drawing (DXF)

`GET /api/v1/runs/{id}/export?format=dxf` (the **DXF (CAD)** button under *Take the answer out*) writes the
answer as a DXF (R2018) drawing for AutoCAD:

- **Coordinates:** when the domain holds a drawing placed in local engineering coordinates (what a CAD file
  with no projection gets), the answer is written in that drawing's own units and numbers, so it lies
  exactly on the original. A drawing placed in a projected CRS (UTM, an Egyptian belt) gives that CRS. With
  neither, the drawing uses local metres around the answer's centre, and the note in the drawing says so.
- **The original drawing** is drawn underneath on grey `MAP-<layer>` layers, from the coordinates it was
  read with.
- **Each decision** goes on its own layers, by what happened:
  - `<DECISION>-CHOSEN` (green), with a solid fill on `<DECISION>-CHOSEN-FILL`;
  - `<DECISION>-NOT-CHOSEN` (grey, turned off);
  - `<DECISION>-LINKS` for pairs;
  - `UNMET-SHORT` (red) where a rule fell short;
  - `<DECISION>-LABELS` for the names of what was chosen.
- **Records placed by numbers rather than a shape** are drawn too (a layout's generated candidates, for
  example). Their position comes from the first of these that the record has:
  - `shape_m` (WKT);
  - `min_x_m`/`min_y_m` with a width and height;
  - `x_m`/`y_m` as the centre, with `width_m`/`w_m`/`w` and `height_m`/`h_m`/`h`.

  These are metres from the drawing's lower-left corner, the frame the Assistant's file reader uses.
- **A note at the top left** gives the run, its status and goal value, the coordinates used, and a count
  per layer.
- **A run with nothing placed** is refused with the reason (409).

Code: `backend/app/api/run_dxf.py`. Tests: `backend/tests/test_run_dxf.py`, and
`test_an_answer_exports_as_a_cad_drawing` in `test_results_out.py`.
