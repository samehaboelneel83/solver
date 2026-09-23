# Benchmark: solver-params-highs-mip-heuristic-effort

32 runs; technique `highs.mip_heuristic_effort`, baseline `0.05`. Time is the shifted geometric mean (shift 10 s), charging an unproven answer the full time limit.

The primal integral is the seconds spent without a good answer (`bench.primal`); smaller is better.

| family | size | backend | value | runs | proven | SGM time (s) | mean gap | primal integral (s) | wrong |
|---|---|---|---|---|---|---|---|---|---|
| facility | L | highs | 0.05 | 2 | 2 | 4.962 | 0.00% | 0.269 | 0 |
| facility | L | highs | 0.3 | 2 | 2 | 5.557 | 0.00% | 0.271 | 0 |
| facility | M | highs | 0.05 | 2 | 2 | 0.681 | 0.00% | 0.029 | 0 |
| facility | M | highs | 0.3 | 2 | 2 | 0.861 | 0.00% | 0.032 | 0 |
| knapsack | L | highs | 0.05 | 2 | 2 | 1.240 | 0.00% | 0.018 | 0 |
| knapsack | L | highs | 0.3 | 2 | 2 | 1.311 | 0.00% | 0.020 | 0 |
| knapsack | M | highs | 0.05 | 2 | 2 | 0.571 | 0.00% | 0.007 | 0 |
| knapsack | M | highs | 0.3 | 2 | 2 | 0.518 | 0.00% | 0.005 | 0 |
| rota | L | highs | 0.05 | 2 | 2 | 0.543 | 0.00% | 0.064 | 0 |
| rota | L | highs | 0.3 | 2 | 2 | 0.509 | 0.00% | 0.062 | 0 |
| rota | M | highs | 0.05 | 2 | 2 | 0.422 | 0.00% | 0.020 | 0 |
| rota | M | highs | 0.3 | 2 | 2 | 0.423 | 0.00% | 0.010 | 0 |
| rota_rates | L | highs | 0.05 | 2 | 2 | 0.515 | 0.00% | 0.060 | 0 |
| rota_rates | L | highs | 0.3 | 2 | 2 | 0.516 | 0.00% | 0.063 | 0 |
| rota_rates | M | highs | 0.05 | 2 | 2 | 0.424 | 0.00% | 0.017 | 0 |
| rota_rates | M | highs | 0.3 | 2 | 2 | 0.423 | 0.00% | 0.011 | 0 |

## `highs.mip_heuristic_effort=0.3` against `0.05`

- wins / losses / ties: 1 / 3 / 12
- families at least 10% faster: none
- wrong answers: 0
- more than 2x slower: 0
- **enable by default: no** (needs >= 2 families 10% better, nothing 2x slower, zero wrong)
