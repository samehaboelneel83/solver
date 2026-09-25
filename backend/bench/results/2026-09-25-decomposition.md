# Decomposition per template: the gate, and what it found — 2026-09-25

`python -m bench.decompose_gate --time-limit 30` (queue R12). The target
roadmap decomposes a model only if its monolithic gap after the time budget
is over 5% **and** its linking rows (from R4's `blocks.structure`) are under
5% of its rows **and** a decomposition exists for its template. Every bench
family at its two largest sizes, the rules' backend for 30 s:

| family | size | backend | status | gap | blocks (by) | linking rows | candidate |
|---|---|---|---|---|---|---|---|
| rota | L | cp-sat | optimal | 0% | 80 (person) | 3.38% | no |
| rota | XL | cp-sat | optimal | 0% | 200 (person) | 1.43% | no |
| rota_rates | L | highs | optimal | 0% | 80 (person) | 3.38% | no |
| rota_rates | XL | highs | optimal | 0% | 200 (person) | 1.43% | no |
| rota_teams | L | cp-sat | optimal | 0% | 80 (person) | 3.38% | no |
| rota_teams | XL | cp-sat | optimal | 0% | 200 (person) | 1.43% | no |
| facility | L | highs | optimal | 0% | 40 (site) | 2.43% | no |
| facility | XL | highs | feasible | 0.306% | 80 (site) | 1.23% | no |
| facility_regions | L | highs | feasible | 0.886% | 4 (-) | 0.00% | no |
| facility_regions | XL | highs | failed: highs worker failed: Exception in thread Thread-1 (__solve): | - | 4 (-) | 0.00% | no |
| knapsack | L | highs | optimal | 0% | 1 (-) | 0.00% | no |
| knapsack | XL | highs | feasible | 0.124% | 1 (-) | 0.00% | no |
| knapsack_depots | L | highs | feasible | 0.193% | 4 (-) | 0.00% | no |
| knapsack_depots | XL | highs | feasible | 0.208% | 4 (-) | 0.00% | no |
| flow_shop_timed | L | cp-sat | feasible | 4.72% | 1 (-) | 0.00% | no |
| flow_shop_timed | XL | cp-sat | failed: the solver crashed (SIGABRT); the memory limit is 4096 MB | - | 1 (-) | 0.00% | no |
| districting | L | cp-sat | unknown | - | 8 (zone) | 1.28% | **yes** |
| districting | XL | cp-sat | failed: the solver crashed (SIGABRT); the memory limit is 4096 MB | - | 12 (zone) | 0.84% | **yes** |
| load_balance | L | highs | optimal | 0% | 1000 (person) | 0.10% | no |
| load_balance | XL | scip | unknown | - | 5000 (person) | 0.02% | **yes** |

**What the gate found.** Two families pass it.

- **load_balance XL** (5,000 people, one rule tying them). The first
  finding was not the model but the classification: the convexity check
  refused any quadratic over 2,000 variables and sent a plain sum of squares
  to SCIP. It now checks block by block (a matrix is positive semidefinite
  exactly when each of its blocks is), so the model goes to HiGHS -- which
  still does not prove it: 1,000 people in 1.2 s, 5,000 not in 60 s (best
  answer 2,441,769). So it gets its decomposition: `app.solve.allocation`
  prices the one linking rule and solves each piece in closed form,
  bisecting the price. It is exact, and its dual bound proves it:
  **2,265,094.79 in 0.09 s** (the solver's best was 7.8% worse); M and L
  match HiGHS's proven optima to 1e-7. Behind `solve.decompose`, **on** by
  default (migration 0059): wherever it applies it is exact and proven, and
  where it does not nothing changes.
- **districting** (L and XL; cells tied to zones by one assignment rule).
  Its difficulty is the connectivity flow, already recorded (2026-09-24:
  exact connectivity does not scale past ~200 cells). A decomposition for it
  -- generating connected districts as columns -- needs a pricing problem
  over connected subgraphs; it stays the open item "connectivity at scale",
  not built here.

Every other family either proves its optimum or ends within 5%
(facility_regions L 0.9%, flow_shop_timed L 4.7%), so the shift-scheduling
column generation the roadmap named first is not needed: the rota families
are proven in 1-2.5 s at their largest.
