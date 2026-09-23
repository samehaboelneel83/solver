# Solver options behind the benchmark gate: the verdicts

Every whitelisted option (`app.solve.params.WHITELIST`) measured against its solver's default with
`python -m bench.run --family rota,facility,knapsack,rota_rates --sizes M,L --instances 2 --time-limit 30
--technique <backend.option>=<default>,<values>` and `bench.report`'s enable rule: at least 10% better SGM time
(or final gap) on at least two families, nothing more than 2x slower, zero wrong answers.

| option | value | wins / losses / ties | families >= 10% faster | 2x slower | wrong | verdict | report |
|---|---|---|---|---|---|---|---|
| `cp-sat.linearization_level` | 0 | 1 / 0 / 3 | rota | 0 | 0 | no | `2026-09-23-solver-params-cp-sat-linearization-level.md` |
| `cp-sat.linearization_level` | 2 | 2 / 1 / 1 | rota | 0 | 0 | no | same |
| `cp-sat.symmetry_level` | 0 | 4 / 0 / 0 | rota | 0 | 0 | no | `2026-09-23-solver-params-cp-sat-symmetry-level.md` |
| `cp-sat.symmetry_level` | 4 | 2 / 0 / 2 | rota | 0 | 0 | no | same |
| `highs.mip_heuristic_effort` | 0.3 | 1 / 3 / 12 | none | 0 | 0 | no | `2026-09-23-solver-params-highs-mip-heuristic-effort.md` |
| `highs.presolve` | on | 0 / 3 / 13 | none | 0 | 0 | no | `2026-09-23-solver-params-highs-presolve.md` |
| `highs.presolve` | off | 3 / 3 / 10 | none | 0 | 0 | no | same |
| `scip.presolving` | aggressive | 1 / 5 / 10 | none | 0 | 0 | no | `2026-09-23-solver-params-scip-presolving.md` |
| `scip.presolving` | **fast** | 8 / 1 / 7 | facility, rota | 0 | 0 | **yes** | same |
| `scip.heuristics` | aggressive | 2 / 14 / 0 | none | 0 | 0 | no | `2026-09-23-solver-params-scip-heuristics.md` |
| `scip.heuristics` | fast | 9 / 1 / 6 | rota, rota_rates | 1 (facility M 0: 0.9 s to 2.2 s) | 0 | no | same |

**Confirmed before enabling.** The one winner was measured again with three instances (one never seen by the
sweep) and two seeds: 29 wins, 2 losses, 17 ties over 96 runs, all four families at least 10% faster (facility L
10.2 s to 7.6 s by SGM), nothing 2x slower, nothing wrong
(`2026-09-23-solver-params-scip-presolving-confirm.md`). It is enabled for every SCIP solve
(`app.solve.params.ENABLED`); nothing else is.

**What the gate cannot see here.** CP-SAT takes only `rota` among these families (the others are fractional or
mixed), so no CP-SAT option can reach the rule's two families; its `symmetry_level=0` won all four comparisons on
rota and stays off for that reason, not on the evidence against it. A family CP-SAT takes with a different
structure would let it be judged.
