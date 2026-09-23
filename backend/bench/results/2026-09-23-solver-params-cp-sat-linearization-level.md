# Benchmark: solver-params-cp-sat-linearization-level

12 runs; technique `cp-sat.linearization_level`, baseline `1`. Time is the shifted geometric mean (shift 10 s), charging an unproven answer the full time limit.

The primal integral is the seconds spent without a good answer (`bench.primal`); smaller is better.

| family | size | backend | value | runs | proven | SGM time (s) | mean gap | primal integral (s) | wrong |
|---|---|---|---|---|---|---|---|---|---|
| rota | L | cp-sat | 0 | 2 | 2 | 0.280 | 0.00% | 0.072 | 0 |
| rota | L | cp-sat | 1 | 2 | 2 | 0.286 | 0.00% | 0.080 | 0 |
| rota | L | cp-sat | 2 | 2 | 2 | 0.277 | 0.00% | 0.075 | 0 |
| rota | M | cp-sat | 0 | 2 | 2 | 0.035 | 0.00% | 0.014 | 0 |
| rota | M | cp-sat | 1 | 2 | 2 | 0.267 | 0.00% | 0.015 | 0 |
| rota | M | cp-sat | 2 | 2 | 2 | 0.034 | 0.00% | 0.014 | 0 |

## `cp-sat.linearization_level=0` against `1`

- wins / losses / ties: 1 / 0 / 3
- families at least 10% faster: rota
- wrong answers: 0
- more than 2x slower: 0
- **enable by default: no** (needs >= 2 families 10% better, nothing 2x slower, zero wrong)

## `cp-sat.linearization_level=2` against `1`

- wins / losses / ties: 2 / 1 / 1
- families at least 10% faster: rota
- wrong answers: 0
- more than 2x slower: 0
- **enable by default: no** (needs >= 2 families 10% better, nothing 2x slower, zero wrong)
