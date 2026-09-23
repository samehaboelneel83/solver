# Benchmark: solver-params-highs-presolve

48 runs; technique `highs.presolve`, baseline `choose`. Time is the shifted geometric mean (shift 10 s), charging an unproven answer the full time limit.

The primal integral is the seconds spent without a good answer (`bench.primal`); smaller is better.

| family | size | backend | value | runs | proven | SGM time (s) | mean gap | primal integral (s) | wrong |
|---|---|---|---|---|---|---|---|---|---|
| facility | L | highs | choose | 2 | 2 | 4.988 | 0.00% | 0.263 | 0 |
| facility | L | highs | off | 2 | 2 | 4.490 | 0.00% | 0.230 | 0 |
| facility | L | highs | on | 2 | 2 | 5.086 | 0.00% | 0.272 | 0 |
| facility | M | highs | choose | 2 | 2 | 0.680 | 0.00% | 0.037 | 0 |
| facility | M | highs | off | 2 | 2 | 0.629 | 0.00% | 0.033 | 0 |
| facility | M | highs | on | 2 | 2 | 0.658 | 0.00% | 0.033 | 0 |
| knapsack | L | highs | choose | 2 | 2 | 1.214 | 0.00% | 0.012 | 0 |
| knapsack | L | highs | off | 2 | 2 | 1.257 | 0.00% | 0.009 | 0 |
| knapsack | L | highs | on | 2 | 2 | 1.213 | 0.00% | 0.022 | 0 |
| knapsack | M | highs | choose | 2 | 2 | 0.570 | 0.00% | 0.010 | 0 |
| knapsack | M | highs | off | 2 | 2 | 0.521 | 0.00% | 0.005 | 0 |
| knapsack | M | highs | on | 2 | 2 | 0.544 | 0.00% | 0.008 | 0 |
| rota | L | highs | choose | 2 | 2 | 0.543 | 0.00% | 0.057 | 0 |
| rota | L | highs | off | 2 | 2 | 0.493 | 0.00% | 0.034 | 0 |
| rota | L | highs | on | 2 | 2 | 0.526 | 0.00% | 0.063 | 0 |
| rota | M | highs | choose | 2 | 2 | 0.422 | 0.00% | 0.012 | 0 |
| rota | M | highs | off | 2 | 2 | 0.450 | 0.00% | 0.013 | 0 |
| rota | M | highs | on | 2 | 2 | 0.472 | 0.00% | 0.009 | 0 |
| rota_rates | L | highs | choose | 2 | 2 | 0.542 | 0.00% | 0.055 | 0 |
| rota_rates | L | highs | off | 2 | 2 | 0.541 | 0.00% | 0.033 | 0 |
| rota_rates | L | highs | on | 2 | 2 | 0.542 | 0.00% | 0.064 | 0 |
| rota_rates | M | highs | choose | 2 | 2 | 0.425 | 0.00% | 0.013 | 0 |
| rota_rates | M | highs | off | 2 | 2 | 0.448 | 0.00% | 0.009 | 0 |
| rota_rates | M | highs | on | 2 | 2 | 0.450 | 0.00% | 0.012 | 0 |

## `highs.presolve=on` against `choose`

- wins / losses / ties: 0 / 3 / 13
- families at least 10% faster: none
- wrong answers: 0
- more than 2x slower: 0
- **enable by default: no** (needs >= 2 families 10% better, nothing 2x slower, zero wrong)

## `highs.presolve=off` against `choose`

- wins / losses / ties: 3 / 3 / 10
- families at least 10% faster: none
- wrong answers: 0
- more than 2x slower: 0
- **enable by default: no** (needs >= 2 families 10% better, nothing 2x slower, zero wrong)
