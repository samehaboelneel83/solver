# Benchmark: solver-params-cp-sat-symmetry-level

12 runs; technique `cp-sat.symmetry_level`, baseline `2`. Time is the shifted geometric mean (shift 10 s), charging an unproven answer the full time limit.

The primal integral is the seconds spent without a good answer (`bench.primal`); smaller is better.

| family | size | backend | value | runs | proven | SGM time (s) | mean gap | primal integral (s) | wrong |
|---|---|---|---|---|---|---|---|---|---|
| rota | L | cp-sat | 0 | 2 | 2 | 0.134 | 0.00% | 0.056 | 0 |
| rota | L | cp-sat | 2 | 2 | 2 | 0.294 | 0.00% | 0.079 | 0 |
| rota | L | cp-sat | 4 | 2 | 2 | 0.238 | 0.00% | 0.092 | 0 |
| rota | M | cp-sat | 0 | 2 | 2 | 0.026 | 0.00% | 0.011 | 0 |
| rota | M | cp-sat | 2 | 2 | 2 | 0.212 | 0.00% | 0.015 | 0 |
| rota | M | cp-sat | 4 | 2 | 2 | 0.034 | 0.00% | 0.018 | 0 |

## `cp-sat.symmetry_level=0` against `2`

- wins / losses / ties: 4 / 0 / 0
- families at least 10% faster: rota
- wrong answers: 0
- more than 2x slower: 0
- **enable by default: no** (needs >= 2 families 10% better, nothing 2x slower, zero wrong)

## `cp-sat.symmetry_level=4` against `2`

- wins / losses / ties: 2 / 0 / 2
- families at least 10% faster: rota
- wrong answers: 0
- more than 2x slower: 0
- **enable by default: no** (needs >= 2 families 10% better, nothing 2x slower, zero wrong)
