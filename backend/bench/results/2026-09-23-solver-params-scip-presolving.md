# Benchmark: solver-params-scip-presolving

48 runs; technique `scip.presolving`, baseline `default`. Time is the shifted geometric mean (shift 10 s), charging an unproven answer the full time limit.

The primal integral is the seconds spent without a good answer (`bench.primal`); smaller is better.

| family | size | backend | value | runs | proven | SGM time (s) | mean gap | primal integral (s) | wrong |
|---|---|---|---|---|---|---|---|---|---|
| facility | L | scip | aggressive | 2 | 2 | 10.104 | 0.00% | 1.681 | 0 |
| facility | L | scip | default | 2 | 2 | 10.152 | 0.00% | 1.650 | 0 |
| facility | L | scip | fast | 2 | 2 | 7.649 | 0.00% | 1.564 | 0 |
| facility | M | scip | aggressive | 2 | 2 | 0.640 | 0.00% | 0.040 | 0 |
| facility | M | scip | default | 2 | 2 | 0.616 | 0.00% | 0.038 | 0 |
| facility | M | scip | fast | 2 | 2 | 0.251 | 0.00% | 0.032 | 0 |
| knapsack | L | scip | aggressive | 2 | 2 | 0.642 | 0.00% | 0.003 | 0 |
| knapsack | L | scip | default | 2 | 2 | 0.641 | 0.00% | 0.002 | 0 |
| knapsack | L | scip | fast | 2 | 2 | 0.808 | 0.00% | 0.002 | 0 |
| knapsack | M | scip | aggressive | 2 | 2 | 0.071 | 0.00% | 0.001 | 0 |
| knapsack | M | scip | default | 2 | 2 | 0.072 | 0.00% | 0.001 | 0 |
| knapsack | M | scip | fast | 2 | 2 | 0.055 | 0.00% | 0.000 | 0 |
| rota | L | scip | aggressive | 2 | 2 | 0.165 | 0.00% | 0.136 | 0 |
| rota | L | scip | default | 2 | 2 | 0.140 | 0.00% | 0.112 | 0 |
| rota | L | scip | fast | 2 | 2 | 0.135 | 0.00% | 0.106 | 0 |
| rota | M | scip | aggressive | 2 | 2 | 0.026 | 0.00% | 0.015 | 0 |
| rota | M | scip | default | 2 | 2 | 0.069 | 0.00% | 0.016 | 0 |
| rota | M | scip | fast | 2 | 2 | 0.020 | 0.00% | 0.010 | 0 |
| rota_rates | L | scip | aggressive | 2 | 2 | 0.166 | 0.00% | 0.136 | 0 |
| rota_rates | L | scip | default | 2 | 2 | 0.123 | 0.00% | 0.096 | 0 |
| rota_rates | L | scip | fast | 2 | 2 | 0.107 | 0.00% | 0.081 | 0 |
| rota_rates | M | scip | aggressive | 2 | 2 | 0.019 | 0.00% | 0.013 | 0 |
| rota_rates | M | scip | default | 2 | 2 | 0.018 | 0.00% | 0.011 | 0 |
| rota_rates | M | scip | fast | 2 | 2 | 0.019 | 0.00% | 0.009 | 0 |

## `scip.presolving=aggressive` against `default`

- wins / losses / ties: 1 / 5 / 10
- families at least 10% faster: none
- wrong answers: 0
- more than 2x slower: 0
- **enable by default: no** (needs >= 2 families 10% better, nothing 2x slower, zero wrong)

## `scip.presolving=fast` against `default`

- wins / losses / ties: 8 / 1 / 7
- families at least 10% faster: facility, rota
- wrong answers: 0
- more than 2x slower: 0
- **enable by default: yes** (needs >= 2 families 10% better, nothing 2x slower, zero wrong)
