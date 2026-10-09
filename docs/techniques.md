# Optimization techniques in the platform

What the platform uses, where it lives, and when a run uses it. Everything works from the compiled model, not
from a problem type: a model is recognised by its shape (its rows), never by its name.

## Exact solvers (they prove what they return)

| Technique | Where | When |
|---|---|---|
| Constraint programming with clause learning (CP-SAT, OR-Tools) | `cpsat.py` | whole-number models, schedules, placement; chosen by the rules |
| Branch and cut for MILP (HiGHS; OR-Tools MILP) | `highs.py`, `milp.py` | mixed-integer linear models |
| Spatial branch and bound for nonconvex quadratic / nonlinear (SCIP) | `scip.py` | quadratic and nonlinear models, global optimum |
| Simplex and interior point for LP (HiGHS, GLOP) | `highs.py`, `lp.py` | linear programs, with duals and ranging |
| First-order LP (PDLP) | `pdlp.py` | very large LPs, optimal to a tolerance |
| Interior-point NLP, local (IPOPT) | `ipopt.py` | continuous nonlinear; polishes SCIP's answer |
| Network simplex, min-cost flow | `network.py` | any model whose rows are a network: proven, with shadow prices |
| Edmonds' blossom (matching) | `matching.py` | pairing models |
| Kruskal (minimum spanning tree / forest) | `join.py` | network design that is a spanning tree |

## Decomposition and bounds

| Technique | Where | When |
|---|---|---|
| Benders decomposition (with Pareto-optimal cuts) | `benders.py` | by name; facility-like models |
| Column generation | `colgen.py` | models with a generated candidate set |
| Lagrangian relaxation (a proven bound) | `lagrange.py` | setting `solve.lagrangian` |
| Separable blocks solved at once | `blocks.py` | models with independent parts |
| Exact decomposition for separable allocation | `allocation.py` | setting `solve.decompose` |
| Relax-and-fix over a time horizon | `horizon.py` | setting `solve.rolling_horizon` |

## Reformulation and strengthening

| Technique | Where | When |
|---|---|---|
| Convexity detection (quadratic, disciplined convex programming), SOCP recognition | `convexity.py`, `dcp.py`, `socp.py` | every quadratic or nonlinear model |
| McCormick linearisation of products with a yes/no factor | `mccormick.py` | backends without products |
| Tight big-M from bounds for conditional rules | `reformulate.py` | backends without indicators |
| Exact rows for trained tree ensembles (optimisation over ML predictions) | `predict.py` | models with `predict` |
| Symmetry breaking | `symmetry.py` | setting `solve.symmetry` |
| Disaggregated on/off limits and covers, added where the relaxation breaks them | `strengthen.py` | before HiGHS/SCIP solves of models with on/off limits |
| Flow-balance detection and cut-sets ((l,S), network cut-sets, covers) | `flowcuts.py` | the same pass |
| Network-design cuts separated by minimum cut | `join.py` | models with a `join` rule |
| The model as written raced against the strengthened one | `service.py`, `race.py` | when rows were added; the winner remembered per problem |

## Starts and matheuristics (answers handed to the exact solver)

| Technique | Where | When |
|---|---|---|
| Slope scaling + local search for fixed charges | `fixed_charge.py` | any model with costed on/off limits |
| Greedy for packing-shaped models | `greedy.py` | always, when the shape fits |
| Large-neighbourhood search (adaptive operators) | `lns.py` | setting `solve.lns` |
| Routing search (OR-Tools) as a start | `routing.py` | `route` rules |
| Repair heuristics for connectivity | `reach.py`, `partition.py` | `connected` rules |
| Steiner tree, capacity-aware design (min-cost flows, slope scaling, swaps) | `join.py` | `join` rules |
| Warm start from the nearest earlier answer | `warm.py` | setting `solve.warm_start` |

## Metaheuristics (an answer, never claimed best)

| Technique | Where | Decisions |
|---|---|---|
| Genetic algorithm | `evolve.py` (`ga`) | mixed |
| Particle swarm optimisation | `evolve.py` (`pso`) | continuous |
| CMA-ES (covariance matrix adaptation, IPOP restarts) | `evolve.py` (`cma-es`) | continuous |
| Simulated annealing (adaptive penalty, reheats) | `evolve.py` (`sa`) | mixed |
| Tabu search (aspiration, restarts) | `evolve.py` (`tabu`) | mixed, at home on yes/no |
| Differential evolution (JADE, current-to-pbest/1, archive) | `evolve.py` (`de`) | mixed |
| Ant colony optimisation (ACO_R / ACO_MV) | `evolve.py` (`aco`) | mixed |

Each runs when asked for by name. With setting `solve.metaheuristic`, after an exact solver ends with nothing,
the searches that take the model race at once (one thread each) and the best answer keeping every rule stands.
Rules are held by Deb's feasibility order; every answer is checked on every compiled row.

## Several goals, uncertainty

| Technique | Where | When |
|---|---|---|
| Epsilon-constraint Pareto front (exact) | `pareto.py` | two linear goals |
| Augmented epsilon-constraint front (AUGMECON: payoff table, grid of bounds, lexicographic sum, early exit) | `pareto.py` (`many_front`) | three to six linear goals |
| NSGA-II (non-dominated sorting, crowding, SBX) | `evolve.py` (`nsga2`), `pareto.py` | two to six goals where one multiplies decisions |
| Lexicographic goals | `compile.py` | goals ranked in order |
| Two-stage stochastic programming (sample average approximation), chance rules | `stochastic.py` | uncertain data |
| Robust optimisation (Bertsimas–Sim budget, Soyster), exact linear rewrite | `robust.py` | robust runs |

## Choosing and learning

| Technique | Where | When |
|---|---|---|
| Model classification and rule-based solver choice | `classify.py`, `backends.py` | every run |
| Probe race and portfolio of solvers | `race.py` | settings `solve.probe`, `solve.portfolio` |
| Per-problem memory of the fastest solver | `memory.py` | setting `solve.memory` |
| Learned solver selector (nearest neighbours on model fingerprints) | `selector.py` | shadow, or acting with `solve.selector_acts` |
| On/off choices learnt per problem (starts, cuts) | `choices.py` | every run with history |
| Escalation: the solver alone first, the steps before a solve only when it settles nothing | `service.py` | setting `solve.probe_first` (on) |
| Bayesian optimisation of each solver's options per problem (Gaussian process, expected improvement) | `tuning.py` | every run with history; `solve.solver_params` overrides |
| Infeasibility explanation (IIS, QuickXplain) | `diagnose.py` | infeasible runs |

## Not yet in the platform

- A wider space for the tuning: it searches only the options the benchmark whitelisted (two or three per
  solver), since an option must never change what a solver may answer.
- QUBO export for annealing hardware, and quantum-inspired solvers.
- Constraint learning from data (rules inferred from past plans).
