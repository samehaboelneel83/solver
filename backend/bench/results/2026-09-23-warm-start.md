# Benchmark: warm starts

`python -m bench.warm --families rota,facility,knapsack --sizes M,L --instances 2 --time-limit 30` -- solve an instance, perturb 5% of its numeric data by up to 10%, then solve the perturbed model cold and warm (hinted with the first answer's roster, `app.solve.warm.hint_from`, as a run would be) on every backend that takes hints and the model.

| family | size | inst | backend | variables | hinted | cold: status / objective / s | warm: status / objective / s | same optimum |
|---|---|---|---|---|---|---|---|---|
| rota | M | 0 | cp-sat | 630 | 630 | optimal / 711 / 0.034 | optimal / 711 / 0.03 | True |
| rota | M | 0 | highs | 630 | 630 | optimal / 711 / 0.599 | optimal / 711 / 0.472 | True |
| rota | M | 0 | scip | 630 | 630 | optimal / 711 / 0.031 | optimal / 711 / 0.02 | True |
| rota | M | 1 | cp-sat | 630 | 630 | optimal / 614 / 0.029 | optimal / 614 / 0.027 | True |
| rota | M | 1 | highs | 630 | 630 | optimal / 614 / 0.423 | optimal / 614 / 0.429 | True |
| rota | M | 1 | scip | 630 | 630 | optimal / 614 / 0.02 | optimal / 614 / 0.02 | True |
| rota | L | 0 | cp-sat | 3360 | 3360 | optimal / 2717 / 0.265 | optimal / 2717 / 0.306 | True |
| rota | L | 0 | highs | 3360 | 3360 | optimal / 2717 / 0.489 | optimal / 2717 / 0.489 | True |
| rota | L | 0 | scip | 3360 | 3360 | optimal / 2717 / 0.146 | optimal / 2717 / 0.164 | True |
| rota | L | 1 | cp-sat | 3360 | 3360 | optimal / 3006 / 0.303 | optimal / 3006 / 0.405 | True |
| rota | L | 1 | highs | 3360 | 3360 | optimal / 3006 / 0.589 | optimal / 3006 / 0.543 | True |
| rota | L | 1 | scip | 3360 | 3360 | optimal / 3006 / 0.156 | optimal / 3006 / 0.154 | True |
| facility | M | 0 | highs | 1215 | 1132 | optimal / 7776.753161 / 0.632 | optimal / 7776.753161 / 0.598 | True |
| facility | M | 0 | scip | 1215 | 1132 | optimal / 7776.753161 / 2.295 | optimal / 7776.753161 / 1.497 | True |
| facility | M | 1 | highs | 1215 | 1130 | optimal / 8862.606813 / 0.882 | optimal / 8862.606813 / 0.884 | True |
| facility | M | 1 | scip | 1215 | 1130 | optimal / 8862.606813 / 0.398 | optimal / 8862.606813 / 0.84 | True |
| facility | L | 0 | highs | 12040 | 11727 | optimal / 18611.047004 / 4.873 | optimal / 18611.047004 / 4.764 | True |
| facility | L | 0 | scip | 12040 | 11727 | optimal / 18611.047004 / 5.794 | optimal / 18611.047004 / 5.013 | True |
| facility | L | 1 | highs | 12040 | 11727 | optimal / 18373.067758 / 8.012 | optimal / 18373.067758 / 7.98 | True |
| facility | L | 1 | scip | 12040 | 11727 | optimal / 18373.067758 / 9.938 | optimal / 18373.067758 / 11.691 | True |
| knapsack | M | 0 | highs | 60 | 60 | optimal / 1213.0749 / 0.517 | optimal / 1213.0749 / 0.519 | True |
| knapsack | M | 0 | scip | 60 | 60 | optimal / 1213.0749 / 0.114 | optimal / 1213.0749 / 0.11 | True |
| knapsack | M | 1 | highs | 60 | 60 | optimal / 1209.9088 / 0.567 | optimal / 1209.9088 / 0.469 | True |
| knapsack | M | 1 | scip | 60 | 60 | optimal / 1209.9088 / 0.037 | optimal / 1209.9088 / 0.034 | True |
| knapsack | L | 0 | highs | 150 | 150 | optimal / 2914.1087 / 1.473 | optimal / 2914.1087 / 1.472 | True |
| knapsack | L | 0 | scip | 150 | 150 | optimal / 2914.1087 / 1.871 | optimal / 2914.1087 / 1.329 | True |
| knapsack | L | 1 | highs | 150 | 150 | optimal / 2959.4075 / 1.273 | optimal / 2959.4075 / 1.223 | True |
| knapsack | L | 1 | scip | 150 | 150 | optimal / 2959.4075 / 0.914 | optimal / 2959.4075 / 0.897 | True |
| backend | runs | cold SGM s | warm SGM s | warm faster | warm slower | warm proved more |
|---|---|---|---|---|---|---|
| cp-sat | 4 | 0.151 | 0.180 | 1 | 2 | +0 |
| highs | 12 | 1.183 | 1.140 | 2 | 0 | +0 |
| scip | 12 | 0.950 | 0.918 | 4 | 3 | +0 |

(SGM: shifted geometric mean of seconds, shift 1 s; "faster"/"slower": by more than 10%.)

## Decision: `solve.warm_start` stays off by default

- **No wrong answers, no lost proofs.** Every one of the 28 solves proved
  its optimum warm and cold, and every pair agrees.
- **No win worth turning on.** HiGHS is 4% faster by SGM and SCIP 3% --
  inside the noise, with instances going either way (SCIP facility M 1:
  0.40 s cold, 0.84 s warm; facility L 0: 5.8 s cold, 5.0 s warm). CP-SAT
  is slower (0.151 s against 0.180 s): its own presolve and portfolio find
  these answers faster than it can use a hint.
- **Why so little.** These families are solved to optimality in seconds,
  where there is little search for an incumbent to shorten, and the hint
  is partial where it matters: a stored roster keeps which amounts were
  used, not how much (facility's shipments), so a MILP gets its yes-or-no
  decisions hinted and its quantities left to it.

The mechanism stays, off: a problem whose models run to their time limit
without a proof -- where an early incumbent is most of the value -- can turn
it on at its own level (problem, domain or platform, migration 0014), and
a later bench on such a family (Phase 13's LNS lane) can revisit the
default. Storing values rather than a roster would make the MILP hint whole;
that belongs with the run's stored facts (queue item 17).
