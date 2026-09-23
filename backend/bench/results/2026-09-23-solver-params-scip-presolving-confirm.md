# Benchmark: solver-params-scip-presolving-confirm

96 runs; technique `scip.presolving`, baseline `default`. Time is the shifted geometric mean (shift 10 s), charging an unproven answer the full time limit.

The primal integral is the seconds spent without a good answer (`bench.primal`); smaller is better.

| family | size | backend | value | runs | proven | SGM time (s) | mean gap | primal integral (s) | wrong |
|---|---|---|---|---|---|---|---|---|---|
| facility | L | scip | default | 6 | 6 | 12.971 | 0.00% | 1.758 | 0 |
| facility | L | scip | fast | 6 | 6 | 11.019 | 0.00% | 1.669 | 0 |
| facility | M | scip | default | 6 | 6 | 0.800 | 0.00% | 0.040 | 0 |
| facility | M | scip | fast | 6 | 6 | 0.262 | 0.00% | 0.034 | 0 |
| knapsack | L | scip | default | 6 | 6 | 0.592 | 0.00% | 0.003 | 0 |
| knapsack | L | scip | fast | 6 | 6 | 0.567 | 0.00% | 0.002 | 0 |
| knapsack | M | scip | default | 6 | 6 | 0.107 | 0.00% | 0.001 | 0 |
| knapsack | M | scip | fast | 6 | 6 | 0.056 | 0.00% | 0.001 | 0 |
| rota | L | scip | default | 6 | 6 | 0.147 | 0.00% | 0.112 | 0 |
| rota | L | scip | fast | 6 | 6 | 0.139 | 0.00% | 0.105 | 0 |
| rota | M | scip | default | 6 | 6 | 0.046 | 0.00% | 0.014 | 0 |
| rota | M | scip | fast | 6 | 6 | 0.020 | 0.00% | 0.012 | 0 |
| rota_rates | L | scip | default | 6 | 6 | 0.126 | 0.00% | 0.095 | 0 |
| rota_rates | L | scip | fast | 6 | 6 | 0.108 | 0.00% | 0.082 | 0 |
| rota_rates | M | scip | default | 6 | 6 | 0.018 | 0.00% | 0.011 | 0 |
| rota_rates | M | scip | fast | 6 | 6 | 0.017 | 0.00% | 0.009 | 0 |

## `scip.presolving=fast` against `default`

- wins / losses / ties: 29 / 2 / 17
- families at least 10% faster: facility, knapsack, rota, rota_rates
- wrong answers: 0
- more than 2x slower: 0
- **enable by default: yes** (needs >= 2 families 10% better, nothing 2x slower, zero wrong)
