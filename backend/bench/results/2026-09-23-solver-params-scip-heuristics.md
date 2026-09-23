# Benchmark: solver-params-scip-heuristics

48 runs; technique `scip.heuristics`, baseline `default`. Time is the shifted geometric mean (shift 10 s), charging an unproven answer the full time limit.

The primal integral is the seconds spent without a good answer (`bench.primal`); smaller is better.

| family | size | backend | value | runs | proven | SGM time (s) | mean gap | primal integral (s) | wrong |
|---|---|---|---|---|---|---|---|---|---|
| facility | L | scip | aggressive | 2 | 1 | 29.219 | 0.06% | 1.944 | 0 |
| facility | L | scip | default | 2 | 2 | 10.064 | 0.00% | 1.642 | 0 |
| facility | L | scip | fast | 2 | 2 | 8.940 | 0.00% | 1.655 | 0 |
| facility | M | scip | aggressive | 2 | 2 | 0.692 | 0.00% | 0.052 | 0 |
| facility | M | scip | default | 2 | 2 | 0.615 | 0.00% | 0.040 | 0 |
| facility | M | scip | fast | 2 | 2 | 1.228 | 0.00% | 0.054 | 0 |
| knapsack | L | scip | aggressive | 2 | 2 | 0.978 | 0.00% | 0.003 | 0 |
| knapsack | L | scip | default | 2 | 2 | 0.651 | 0.00% | 0.003 | 0 |
| knapsack | L | scip | fast | 2 | 2 | 0.621 | 0.00% | 0.002 | 0 |
| knapsack | M | scip | aggressive | 2 | 2 | 0.088 | 0.00% | 0.001 | 0 |
| knapsack | M | scip | default | 2 | 2 | 0.071 | 0.00% | 0.001 | 0 |
| knapsack | M | scip | fast | 2 | 2 | 0.056 | 0.00% | 0.001 | 0 |
| rota | L | scip | aggressive | 2 | 2 | 0.175 | 0.00% | 0.067 | 0 |
| rota | L | scip | default | 2 | 2 | 0.143 | 0.00% | 0.115 | 0 |
| rota | L | scip | fast | 2 | 2 | 0.115 | 0.00% | 0.085 | 0 |
| rota | M | scip | aggressive | 2 | 2 | 0.033 | 0.00% | 0.014 | 0 |
| rota | M | scip | default | 2 | 2 | 0.069 | 0.00% | 0.018 | 0 |
| rota | M | scip | fast | 2 | 2 | 0.021 | 0.00% | 0.011 | 0 |
| rota_rates | L | scip | aggressive | 2 | 2 | 0.151 | 0.00% | 0.051 | 0 |
| rota_rates | L | scip | default | 2 | 2 | 0.128 | 0.00% | 0.100 | 0 |
| rota_rates | L | scip | fast | 2 | 2 | 0.090 | 0.00% | 0.063 | 0 |
| rota_rates | M | scip | aggressive | 2 | 2 | 0.024 | 0.00% | 0.009 | 0 |
| rota_rates | M | scip | default | 2 | 2 | 0.019 | 0.00% | 0.011 | 0 |
| rota_rates | M | scip | fast | 2 | 2 | 0.018 | 0.00% | 0.007 | 0 |

## `scip.heuristics=aggressive` against `default`

- wins / losses / ties: 2 / 14 / 0
- families at least 10% faster: none
- wrong answers: 0
- more than 2x slower: 2
  - facility-M-1 on scip, seed 1: 0.341s -> 0.778s
  - facility-L-0 on scip, seed 1: 4.489s -> 30.174s
- **enable by default: no** (needs >= 2 families 10% better, nothing 2x slower, zero wrong)

## `scip.heuristics=fast` against `default`

- wins / losses / ties: 9 / 1 / 6
- families at least 10% faster: rota, rota_rates
- wrong answers: 0
- more than 2x slower: 1
  - facility-M-0 on scip, seed 1: 0.897s -> 2.230s
- **enable by default: no** (needs >= 2 families 10% better, nothing 2x slower, zero wrong)
