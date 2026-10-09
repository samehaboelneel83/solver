# Solver engine additions (Epic engine)

Five additions to how the platform solves, all built on the solvers it already ships (HiGHS,
IPOPT, CP-SAT, SCIP) — no commercial solver is needed for any of them.

| You want | You ask for | What happens |
| --- | --- | --- |
| Several good plans to pick from, not one | `"alternatives": 5` on a run | The next-best distinct plans within a gap of the best, each a run of its own |
| A better answer to a nonlinear model | setting `solve.solver_params` = `ipopt.starts=8` | IPOPT from several starting points; the best answer is kept |
| A large mixed model with an easy continuous part | `"solver": "benders"` on a run | Benders decomposition over HiGHS; a proven optimum |
| A linear model with many more decisions than rules | `"solver": "colgen"` on a run | Column generation over HiGHS; a bound over every column |
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

HiGHS counts a time limit against all the run time of one solver, not each solve's (`getRunTime`), so
each round's limit is that run time plus what is left (9 October 2026; before, later rounds stopped early
once the rounds before had used the time left).

## 3a. Column generation (plan of 8 October 2026, 1D)

For a linear model with far more decisions than rules -- every pairing of crews and duties, every
cutting pattern, a large candidate list -- most of whose decisions are zero in any good answer. Asked for
by name: `"solver": "colgen"`.

- A **restricted master** holds the rules over a few columns: every decision that cannot be left at zero,
  and the cheapest of the rest. Each round, the master's row prices give every column its reduced cost at
  once, from the rule matrix (no problem-specific pricing), and the most improving columns join the
  master, until none improves.
- **Bound**: at each round's prices, the Lagrangian of the rules over *every* column -- a proven bound on
  the whole model even if the loop is stopped early. **Answer**: the master once more with whole-number
  decisions whole, over the columns found (price and branch); proven best only when it meets the bound,
  otherwise `feasible` with the gap.
- Rows the starting point does not meet get two slack columns at a large price, so the first masters
  have an answer; a slack still used when no column improves, and no whole answer, is `infeasible`.
- Refused with the reason: a goal or rule that is not linear, curves, functions, schedules or
  placements.
- A model with fewer than twice as many decisions as rules gains nothing from a small master (the camp's
  candidate list at 0.5 m has 54,468 positions and 116,686 rules, and each master solve was slower than
  the last): the master is then the whole model from the start, solved as HiGHS would, its whole-number
  optimum proven, and the solver string says so.
- Measured (9 October 2026): a set cover of 300 items by 60,000 sets, as a linear program -- 2.4 s and
  3,143 columns, against 10.8 s for HiGHS on the whole model, the same optimum; whole-numbered, both
  are still searching at 60 s, with the same bound.
- The solver string records the work, e.g. `colgen (highs 1.15.1): 6 rounds, 1,243 of 40,000 columns`.

Code: `backend/app/solve/colgen.py` (runs in HiGHS's child process, `highs_worker`); tests
`backend/tests/test_colgen.py`.

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

## Fixed charges, in any model (9 October 2026)

A fixed charge is an on/off decision that costs something and lets other quantities be non-zero only while it is
on: a rule `a1*x1 + ... <= M * open` with every `a > 0`, every `x >= 0`, and `open` charged in the goal. Facility
location, lot sizing (produce only with a set-up), network design (the `join` rule compiles to such rows too),
unit commitment, renting a vehicle, opening a route -- `app/solve/fixed_charge.py` reads the shape off the compiled
model and knows none of these by name. Branch and bound is slow on them because the relaxation opens every charge
a little (`open = usage / M`) and pays almost nothing for it.

The start (`fixed_charge_start_run`), before any MIP solve with a hinted solver (HiGHS, SCIP, CP-SAT), for up to
30 s or 20% of the run:

1. **Slope scaling** (Kim and Pardalos): the charges are set aside and each one's cost spread over what it limits,
   per unit, at first over its M, then over what the last round used; the relaxation is solved; a charge is on
   exactly when what it limits is used. Each design is completed by solving the model itself with the charges
   fixed (its other rules and whole-number decisions included), so the start keeps every rule. Up to 20 rounds,
   while new designs come.
2. **Local search** over the best design: every charge switched off in turn (dearest first) while that solves for
   less; then one switched on; then one swapped for another; then two for one -- back to the first move after
   any gain, until none pays or the time is spent.

All of it runs in the HiGHS worker process on one model changed in place (bounds, costs, integrality), so a
design costs milliseconds. Another start already made (the join rule's, the greedy one) is kept when it is
better. Results: facility location (10 sites, 25 customers) and lot sizing within 5% of the optimum in under a
second; an 18×18 capacitated network design (612 links) 21,891 in 30 s where HiGHS alone has 23,175 after 60 s
(and the join rule's own start 22,648); a 60×300 facility model 1.5% above the optimum HiGHS proves in 18 s --
there the start only costs time.

### Rows the on/off limits imply (`app/solve/strengthen.py`)

Before a HiGHS or SCIP solve of any model with on/off limits (`sum(a*x) <= M*on`, `on` yes or no, whatever it
costs), two families of rows the model implies are added where the relaxation breaks them (`strengthen_run`, up
to 15 s or 10% of the run; setting `strengthen`, on):

- **each quantity within its own limit**: where another rule bounds a quantity below what its limit allows (a
  shipment by its customer's demand), `a*x <= min(M, a*u) * on` -- the classic facility-location strengthening,
  found in any model of that shape;
- **covers**: a rule needing at least `d` of quantities each behind a limit needs enough of them on:
  `sum(min(allowed, d) * on) >= d`.

- **cut-sets of flow balances** (`app/solve/flowcuts.py`): rules over quantities with +1 and -1 only (what
  comes in less what goes out equals, or is at least, what a place keeps) are read as nodes, each turned the way
  round that makes the quantities in two of them arcs (+1 at the head, -1 at the tail); a node that sends (a
  shared capacity: `sum(x) <= C` is a supply of C) is never inside a set. For a set U, the arcs into it must
  bring D(U), each at most `min(M, D_a)` while on (D_a: the demand it can reach inside U) or its flow:
  `sum(min(M_a, D_a) * on_a  or  x_a) >= D(U)`. Every node's own set is checked each round, and sets are grown
  from the 20 most broken (up to 40 nodes) by the node sending most into them. That is the (l, S) inequality of
  lot sizing, the cut-set of network design and the cover of facility location -- found in any model with those
  rows, none named.

Measured with HiGHS (60 s): uncapacitated lot sizing -- the relaxation reaches the optimum (the (l, S) cut-sets
are its hull); an 18×18 network design compiled by the join rule with the rule's own cuts off -- bound 15,524 to
17,277 and 22,612–23,857 found (the rule's own cuts still do better there: 20,280); multi-item capacitated lot
sizing (20 × 30) -- the relaxation rises from 5,952 to 34,796, but HiGHS's own flow covers already prove it in
4.5 s, and with the rows it takes 5.8 s: modern solvers find these cuts themselves on models this regular, so the
rows pay off where the solver's own do not (facility location, network design). Rows the last relaxation does not
hold tight are dropped before the solve (they made HiGHS take 22 s instead of 5 on the lot-sizing case).

**Both forms race.** Whether the rows help depends on the solver and the model, and no rule read off the model
says which in advance. So when rows were added (and the run has two threads or more), the model as written and the
strengthened one are solved at once by the same solver on half the threads each: the first proof (optimum,
infeasible, unbounded) ends both, otherwise the better answer at the deadline stands (`app.solve.race`, as the
portfolio does with solvers). `strengthen_run.forms` records both and which won; setting `hedge_forms` turns it
off. A run is then never slower than the faster form by more than what half the threads cost.

**Remembered per problem** (`app.solve.memory.recall_form`). Most runs re-solve a problem already solved, so
once the same form has proved the problem's last three races first (each by a proof), the next runs use that
form alone on all the threads -- and when it is the model as written, the rows are not made at all. After ten
runs on a remembered form the forms race again, since new data may change which is faster.

All candidates are checked against the relaxation as one sparse product per round; up to 2,000 are added a
round, in the HiGHS worker on one model. Uncapacitated facility location, 100 sites × 400 customers: the
relaxation's bound goes from 17,876 to 35,695 -- the optimum -- in 3.9 s, and HiGHS then proves it in 1.5 s
(5.2 s without). The fixed-charge start runs after it, from the model as written, and stops once its answer is
within 0.2% of that bound (`near_bound`): the solver needs no better start then.

### Choices learnt from the problem's own runs (`app/solve/choices.py`)

Whether to build a start before the solve (the rule's own start, or the fixed-charge one) and whether to add the
cuts a relaxation breaks are each one on/off choice, learnt per problem the same way: on by default; tried off
only once two runs with it on have *proved* their answers (so a problem that needs it to find any answer is never
left without one), until two runs each way; then the way with the lower median time to a proof (an unproven run
counts as the whole time allowed and more) is kept; every ten runs the other way is tried once again. A run that
tried it off and did not prove, where every run with it did, turns it back on at once. Each run records its
choices and why (`params.choices`, "Learnt from earlier runs" on the run page); setting `learn_choices` turns the
learning off. The greedy start stays always on: it takes a moment and is what keeps a run from ending empty.

## More searches, raced; NSGA-II fronts (9 October 2026)

The metaheuristic lane (`app/solve/evolve.py`) adds simulated annealing (`sa`), tabu search (`tabu`), differential
evolution (`de`, JADE) and ant colony optimisation (`aco`, ACO_R / ACO_MV) to the genetic algorithm, particle swarm
and CMA-ES. All take mixed decisions except PSO and CMA-ES (continuous), share Deb's feasibility order and the
compiled model's own evaluation, and never claim an optimum. After an exact solver ends with nothing
(`solve.metaheuristic`), the searches that take the model race at once, one thread each (tabu, sa, ga, de, aco for
whole-number models; cma-es, de, pso, sa, ga, aco, tabu for continuous ones, the first `workers` of them), and the
best answer keeping every rule is the run's (`metaheuristic_run.raced`). A two-goal front whose goal multiplies
decisions, which no exact epsilon-constraint solve takes, is drawn by NSGA-II (`evolve.nsga2`), each point
`feasible`. The full map of techniques is `docs/techniques.md`.

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
knapsack row, a product, a curve — is refused before solving, with the reason, e.g.
*"networkx solves a network … This model is not one: the rule 'cap' weighs a decision by more than one"*.
The rules never choose it unasked (`automatic=False`): the model class alone cannot tell a network from
any other linear model.

**As the network lane's engine (the default):** with setting `solve.network` on, a whole-number network
model is solved by min-cost flow without being asked. Setting `solve.network_engine` (migration 0108)
picks the algorithm: `networkx` (the default) or `ortools` (OR-Tools `SimpleMinCostFlow`, about ten
times quicker on large networks: a 400 × 400 assignment in 0.1 s against 1.1 s). Both prove the same
optimum. The run records the engine in `params.network_engine` and `params.network_run.engine`, and the
solver string says which: `network (min-cost flow, NetworkX network simplex)`.

**Numbers with decimals (9 October 2026).** Min-cost flow works in integers, so decimals are scaled exactly:
goal coefficients always (the cheapest flow is the same), limits and bounds when every decision may be
fractional (whole-number decisions on a scaled network would count tenths, so such a model is left to the
solvers). The run records `network_run.scaled`. A fractional cost no longer sends a network to a MIP solver.

**Shadow prices (9 October 2026).** Each rule's price is the goal's change per +1 on its limit, worked out from
the solved network: one more unit into a place travels the cheapest path from the outside through the arcs
that can still change (forward while an arc has room, backward while it carries flow), one more unit out of it
the cheapest path back. A turned rule takes the second. Where an answer is degenerate the two sides differ and
the price is the +1 side (an LP solver may report the other). Checked against re-solving with each limit moved
a little. They are stored like any solver's (`constraint_result.dual`), for whole-number networks too (a
network's linear optimum is whole, so its prices hold), up to 300,000 arcs. A rule whose limit cannot move alone -- an exact
balance (`=`) in an assignment, a shortest path or a flow where every unit in must go out -- has no price:
one more unit there has no answer (an LP solver reports a potential difference there instead). Timing: a
12,000-arc transport solves and prices in 0.3 s (NetworkX) or 0.13 s (OR-Tools).

**Pairings (9 October 2026): Edmonds' blossom.** When any record may pair with any other (room-mates,
two-person teams, back-up pairs) the model is not a network: three records pairwise joined make an odd cycle,
and its linear relaxation is fractional. `app/solve/matching.py` reads such a model -- every decision yes or
no, every rule `sum <= 1` (or every one `sum = 1`, a perfect pairing) with +1 coefficients, each decision in
two rules (or one: a record left on its own, when every rule is `<= 1`) -- and solves it with
`networkx.max_weight_matching`, weights scaled to whole numbers. The optimum is proven, and a perfect pairing
that cannot exist is a proven infeasibility. It runs when `networkx` is asked for by name and the model is not
a network, and in the network lane (`solve.network`) after the network check. The solver string says
`matching (Edmonds' blossom, NetworkX)`; `params.network_run.kind` is `matching`.

**Network design (9 October 2026): spanning trees.** The `join` rule (`docs/contracts/problem-ir.md` §4.4a)
says the links built join the places. `app/solve/join.py` compiles it as an exact flow, and reads the compiled
model: when the rule has no `use`, every other rule fixes one link in or out, and the goal only adds up the links
built, it is a minimum spanning tree (a forest, with sources: one more node joined to every source at no cost).
Links that pay for themselves and forced links are taken first, Kruskal completes the rest, and the answer is the
proven optimum with every flow variable set. On a 20×20 grid (400 places, 760 links) Kruskal answers in 4 ms
where HiGHS, after 60 s on the flow rows, has 7,410 against the optimum 5,747; 10,000 places take 0.15 s. It runs
in the network lane after the network and pairing checks, and when `networkx` is asked for by name; the solver
string says `minimum spanning tree (Kruskal)`, `params.network_run.kind` is `spanning`. Every other model with one
join rule gets the tree as a start (`params.join_start_run`); with `use`, a Steiner tree (NetworkX's
approximation) joining the places forced in and the sources. With `demand` (and `capacity`, `supply`, `carry`), the rule
also carries what each place takes from the sources; a demand alone keeps the spanning lane (the demand flow is set
from each subtree's total), while capacities, supplies or a priced carry make it a capacitated network design for
the MIP solver, started from the tree; The start for a capacitated design (no `use`) is
built for it: the demand is sent at least cost with every link open, each link priced per unit at its carrying
cost plus its building cost spread over what it carried last round (slope scaling, up to 12 rounds, the cheapest
design kept); places that take nothing are joined by Kruskal; then links are dropped, dearest first, while the
rest still joins and carries everything for less. Every flow is a NetworkX min-cost flow, so the start keeps
every row of the rule. On an 18×18 grid (324 places, 612 links, capacities and per-unit costs) it gives 22,648 in
2.4 s where HiGHS alone has 23,659 after 60 s; on small cases it is within a few per cent of the optimum. With
`use` and sources, the start also chooses the places: from the places that must be used (joined to the sources
by a Steiner tree; when that tree cannot carry their demand, by routing it at least cost through any places and
adding the places the flow passes until none is new), places worth something in the goal are added along their
cheapest path -- or routed, when that path cannot carry them -- while the design that feeds them costs less than
they bring in; then places are taken out while that pays, and one place out with another in together (`swaps`), the three
moves repeated until none pays or the time is spent (`join_start_run.used_places`, `moves`, `swaps`). Places are
tried in order of what they bring less what reaching them costs; routing round a full link (several flows) is
kept for the three likeliest each round. Each design is
the capacity-aware one above, so the start keeps every row. A 14×14 grid with prizes, capacities and four places
that must be served: HiGHS alone finds no answer in 60 s and CP-SAT -707; the start gives -1,033 in 19 s, and
CP-SAT from it reaches -1,148. On a
9×9 grid HiGHS with the start ends at -1,190 against -1,177 without. Without sources, the Steiner start (with
`overloaded`) is kept.

**Cuts the rule adds itself.** The flow rows are exact but their relaxation is loose, so the rule also writes
rows every answer keeps (the optimum is unchanged): each joined place but a source (or the root) has a built link
at it; joining k such places takes at least k links; with capacities, the links at a place cover its need
(`sum(min(capacity, need) * build) >= need`, a link counting no more than the need it could carry in), and the
links leaving the sources and their first, second and third rings of neighbours cover the demand beyond (the same
strengthening when every place is fed; the plain capacity sum against the used places' demand with `use`). The
compiled rule records how many (`cuts`). With HiGHS for 60 s: a 10×10 capacitated grid closes from a 28.5% gap to
3.2%, an 18×18 one from 34% to 11% (and finds 23,175 instead of 23,659), and the 14×14 grid with prizes has its
bound raised from -2,609 to -1,814. `app.solve.join.CUTS` turns them off only to measure this. Beyond these, cuts are found where the relaxation breaks them
(`join.separate`, run before a MIP solve when `solve.connected_start` is on, for up to 20 s or 15% of the time):
the relaxation is solved, and for each place it joins a minimum cut between the sources (or, without sources, the
place most used) and that place, with each link weighed by how much of it the relaxation builds, says whether that
building could join it; when not, the links across the cut must be built at least as much as the place is used
(and, with capacities and every place fed, cover the demand beyond it). Up to 60 per round, 12 rounds, until none
is broken. On the 14×14 grid with prizes, HiGHS alone now finds -1,190 (before: no answer in 60 s) and its bound
rises to -1,687 (from -1,814); on the 18×18 capacitated grid the bound barely moves (the weak part there is how
capacities round, not how places join), though HiGHS finds 22,624. The run records `join_cuts_run`. Before
any of this, a maximum flow with every link built checks that the demand can be carried at all: when it cannot,
the run is refused with the shortfall ("at most 285 of the 303 ... can reach them").

The Assistant's `run_python` has NetworkX too (paths, connectivity, components), e.g. to work out which
cells of a layout reach a door before the model is written.

Code: `backend/app/solve/network.py` (`_walk_networkx`, `_walk_ortools`, `_prices`),
`backend/app/solve/matching.py`, `backend/app/solve/join.py`, the `NETWORKX` entry in `backend/app/solve/backends.py`. Tests:
`backend/tests/test_network.py`, `backend/tests/test_matching.py`, `backend/tests/test_join.py`, the `transport_network` case in
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
