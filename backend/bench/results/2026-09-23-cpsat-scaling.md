# Benchmark: cpsat-scaling

44 runs; technique `cpsat_scaling`, baseline `0`. Time is the shifted geometric mean (shift 10 s), charging an unproven answer the full time limit.

The primal integral is the seconds spent without a good answer (`bench.primal`); smaller is better.

| family | size | backend | value | runs | proven | SGM time (s) | mean gap | primal integral (s) | wrong |
|---|---|---|---|---|---|---|---|---|---|
| knapsack | L | routed | 0 | 3 | 3 | 1.150 | 0.00% | 0.013 | 0 |
| knapsack | L | routed | 1 | 3 | 3 | 0.135 | 0.00% | 0.010 | 0 |
| knapsack | M | routed | 0 | 3 | 3 | 0.535 | 0.00% | 0.007 | 0 |
| knapsack | M | routed | 1 | 3 | 3 | 0.017 | 0.00% | 0.004 | 0 |
| knapsack | S | routed | 0 | 3 | 3 | 0.367 | 0.00% | 0.004 | 0 |
| knapsack | S | routed | 1 | 3 | 3 | 0.006 | 0.00% | 0.002 | 0 |
| knapsack | XL | routed | 0 | 2 | 0 | 30.460 | 0.13% | 0.044 | 0 |
| knapsack | XL | routed | 1 | 2 | 0 | 30.039 | 0.13% | 0.065 | 0 |
| rota_rates | L | routed | 0 | 3 | 3 | 0.533 | 0.00% | 0.062 | 0 |
| rota_rates | L | routed | 1 | 3 | 3 | 0.318 | 0.00% | 0.084 | 0 |
| rota_rates | M | routed | 0 | 3 | 3 | 0.414 | 0.00% | 0.012 | 0 |
| rota_rates | M | routed | 1 | 3 | 3 | 0.033 | 0.00% | 0.014 | 0 |
| rota_rates | S | routed | 0 | 3 | 3 | 0.407 | 0.00% | 0.008 | 0 |
| rota_rates | S | routed | 1 | 3 | 3 | 0.107 | 0.00% | 0.007 | 0 |
| rota_rates | XL | routed | 0 | 2 | 2 | 1.032 | 0.00% | 0.233 | 0 |
| rota_rates | XL | routed | 1 | 2 | 2 | 5.846 | 0.00% | 0.510 | 0 |

## `cpsat_scaling=1` against `0`

- wins / losses / ties: 17 / 2 / 3
- families at least 10% faster: knapsack
- wrong answers: 0
- more than 2x slower: 2
  - rota_rates-XL-0 on routed, seed 1: 1.014s -> 2.626s
  - rota_rates-XL-1 on routed, seed 1: 1.049s -> 9.887s
- **enable by default: no** (needs >= 2 families 10% better, nothing 2x slower, zero wrong)

## Reading

`python -m bench.run --family rota_rates,knapsack --technique cpsat_scaling=0,1`,
S/M/L three instances each at 20 s, XL two instances at 30 s, 2026-09-23.
Each row is the backend a run would get: HiGHS with the setting off,
CP-SAT with it on.

Every proven optimum agreed to the cent between the two, 0 wrong: the
scaling is exact. Up to L, CP-SAT is faster on every instance (it proves
knapsack-M in 0.02 s where HiGHS, started in its own process, takes 0.5 s).
At XL the picture turns: on the large rota CP-SAT is 2.6x and 9.4x slower
(and its time varies between runs), and on the large knapsack neither
proves the optimum in 30 s, with CP-SAT's primal integral higher.

**Verdict: stays off by default.** The rule wants nothing 2x slower, and
two XL instances are. The setting `solve.cpsat_scaling` is there for a
problem or domain whose models are small enough to gain from it; the
answers are the same either way.
