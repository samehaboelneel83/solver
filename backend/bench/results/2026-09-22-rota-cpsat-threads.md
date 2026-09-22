# Benchmark: rota-cpsat-threads

24 runs; technique `workers`, baseline `1`. Time is the shifted geometric mean (shift 10 s), charging an unproven answer the full time limit.

| family | size | backend | value | runs | proven | SGM time (s) | mean gap | wrong |
|---|---|---|---|---|---|---|---|---|
| rota | M | cp-sat | 1 | 2 | 1 | 18.633 | 7.82% | 0 |
| rota | M | cp-sat | 8 | 2 | 2 | 0.029 | 0.00% | 0 |
| rota | M | highs | 1 | 2 | 2 | 0.351 | 0.00% | 0 |
| rota | M | highs | 8 | 2 | 2 | 0.363 | 0.00% | 0 |
| rota | M | milp | 1 | 2 | 2 | 0.025 | 0.00% | 0 |
| rota | M | milp | 8 | 2 | 2 | 0.064 | 0.00% | 0 |
| rota | S | cp-sat | 1 | 2 | 0 | 20.181 | 100.00% | 0 |
| rota | S | cp-sat | 8 | 2 | 2 | 0.014 | 0.00% | 0 |
| rota | S | highs | 1 | 2 | 2 | 0.342 | 0.00% | 0 |
| rota | S | highs | 8 | 2 | 2 | 0.355 | 0.00% | 0 |
| rota | S | milp | 1 | 2 | 2 | 0.012 | 0.00% | 0 |
| rota | S | milp | 8 | 2 | 2 | 0.033 | 0.00% | 0 |

## `workers=8` against `1`

- wins / losses / ties: 4 / 5 / 3
- families at least 10% faster: rota
- wrong answers: 0
- more than 2x slower: 0
- **enable by default: no** (needs >= 2 families 10% better, nothing 2x slower, zero wrong)

## Reading

CP-SAT on one thread cannot prove the rota optimum inside 20 s even at the
smallest size (100% gap at S), and on eight it takes 15-30 ms, faster than
HiGHS and the MILP wrapper. The difference is CP-SAT's portfolio: its
single-thread search has no LP-relaxation worker, which is what closes the
bound on a covering model like this one. Runs default to `solve.workers = 8`,
so the platform as deployed is on the fast side of this. `solve.workers = 1`
would not be, for any all-integer model; it is a setting to leave alone
until the benchmark says otherwise.

Not an enable-by-default decision -- `workers` is already 8 -- so the rule's
"two families" verdict does not apply.
