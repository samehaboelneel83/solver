# The Lagrangian bound against the solver's own — 2026-09-24

`python -m bench.lagrange --time-limit 20 [--backend cp-sat]` (queue R5).
Near-separable instances (`blocks.structure`, R4), large sizes: the solver
alone for 20 s on 8 threads; when it ends with an answer but no proof, a
further 5 s relaxing the linking rules into the goal and searching their
prices (`app.solve.lagrange`), the bound kept when tighter than the solver's.

**Verdict: leave off** (`solve.lagrangian` defaults off, migration 0054).
On this platform's families at their largest the solvers either prove the
optimum (rota, rota_rates, rota_teams at XL -- both HiGHS and CP-SAT;
facility L) or end with a bound already tighter than the Lagrangian one
(facility XL, gap 0.35%: 2 rounds, not kept). On districting the relaxed
model still carries the connectivity flow and one round finds no bound. No
bound was ever invalid. Earlier, on smaller instances, the bound came within
1.4-4.4% of the optimum in 10 s -- valid, but looser than a MIP solver's own
bound there.

It stays available per problem or domain: its value is a model far larger
than the bench builds, where the solver's own bound stalls. Next to try:
solve the relaxed blocks in parallel (`blocks.solve`) rather than as one
model, and repair the relaxed answer into a feasible one (the roadmap's
"repaired heuristic").

## HiGHS

| family | size | solver | status | answer | solver gap | with Lagrangian | rounds | kept | note |
|---|---|---|---|---|---|---|---|---|---|
| rota | XL | highs | optimal | 13119 | 0% | - | 0 | no | solver ended optimal |
| rota_rates | XL | highs | optimal | 18467.07 | 0% | - | 0 | no | solver ended optimal |
| rota_teams | XL | highs | optimal | 24226 | 0% | - | 0 | no | solver ended optimal |
| facility | XL | highs | feasible | 41190.0674 | 0.346% | 0.346% | 2 | no |  |
| facility | L | highs | optimal | 18590.620424 | 0% | - | 0 | no | solver ended optimal |
| districting | M | highs | feasible | 1846 | 2.65% | 2.65% | 1 | no |  |

- families whose gap it narrowed: none
- invalid bounds: none
- verdict: leave off

## CP-SAT

| family | size | solver | status | answer | solver gap | with Lagrangian | rounds | kept | note |
|---|---|---|---|---|---|---|---|---|---|
| rota | XL | cp-sat | optimal | 13119 | 0% | - | 0 | no | solver ended optimal |
| rota_rates | XL | cp-sat | optimal | 18467.07 | 0% | - | 0 | no | solver ended optimal |
| rota_teams | XL | cp-sat | optimal | 24226 | 0% | - | 0 | no | solver ended optimal |
| facility | XL | cp-sat | - | None | - | - | 0 | no | cp-sat cannot take it: 'ship' is continuous |
| facility | L | cp-sat | - | None | - | - | 0 | no | cp-sat cannot take it: 'ship' is continuous |
| districting | M | cp-sat | unknown | None | - | - | 0 | no | solver ended unknown |

- families whose gap it narrowed: none
- invalid bounds: none
- verdict: leave off
