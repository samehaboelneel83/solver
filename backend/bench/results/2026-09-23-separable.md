# Separable blocks solved at once -- 2026-09-23

`python -m bench.separable --sizes M,L --instances 3 --time-limit 30`: four
independent `facility` or `knapsack` instances in one model
(`facility_regions`, `knapsack_depots`), each solve in the sandbox as a run
does, 8 threads; blocks in up to four children at once with the threads
shared out. A time-out or a sandbox failure is charged the 30 s limit.

**Verdict: on.** Faster on every family and backend that could finish
(SGM 3.3-17x), never slower, 16 proofs gained, no different optimum. The
MILP wrapper times out on the knapsacks either way. Six whole-model MILP
solves at L failed the 4096 MB sandbox; the same models split did not.

Default `solve.separable` = true (migration 0046). A split is made only
when two or more blocks hold rules (`blocks.worth_splitting`), and never
for a lex goal, soft rules, symmetry rows, a front or a robust run.

| facility_regions | M | 0 | highs | 4 | optimal / 33337.008084 / 6.188 | optimal / 33337.008084 / 1.722 | True |
| facility_regions | M | 0 | milp | 4 | feasible / 33338.354865 / 30.928 | optimal / 33337.008084 / 1.461 | True |
| facility_regions | M | 0 | scip | 4 | feasible / 33338.354865 / 30.558 | optimal / 33337.008084 / 0.945 | True |
| facility_regions | M | 1 | highs | 4 | optimal / 32000.183964 / 5.92 | optimal / 32000.183964 / 1.373 | True |
| facility_regions | M | 1 | milp | 4 | optimal / 32000.183964 / 21.929 | optimal / 32000.183964 / 1.119 | True |
| facility_regions | M | 1 | scip | 4 | optimal / 32000.183964 / 8.389 | optimal / 32000.183964 / 0.791 | True |
| facility_regions | M | 2 | highs | 4 | optimal / 31145.125168 / 7.811 | optimal / 31145.125168 / 1.689 | True |
| facility_regions | M | 2 | milp | 4 | optimal / 31145.125168 / 28.9 | optimal / 31145.125168 / 1.421 | True |
| facility_regions | M | 2 | scip | 4 | optimal / 31145.125168 / 6.3 | optimal / 31145.125168 / 0.88 | True |
| facility_regions | L | 0 | highs | 4 | feasible / 77428.996635 / 33.728 | optimal / 77335.778295 / 9.25 | True |
| facility_regions | L | 0 | milp | 4 | error / None / 13.311 | optimal / 77335.778295 / 31.443 | True |
| facility_regions | L | 0 | scip | 4 | feasible / 78135.151705 / 32.83 | optimal / 77335.778295 / 21.596 | True |
| facility_regions | L | 1 | highs | 4 | feasible / 75482.402264 / 33.725 | optimal / 75156.299942 / 9.59 | True |
| facility_regions | L | 1 | milp | 4 | error / None / 13.942 | feasible / 75160.555851 / 31.537 | True |
| facility_regions | L | 1 | scip | 4 | feasible / 76091.325979 / 32.6 | optimal / 75156.299942 / 23.718 | True |
| facility_regions | L | 2 | highs | 4 | feasible / 76910.694002 / 33.728 | optimal / 76870.404156 / 10.458 | True |
| facility_regions | L | 2 | milp | 4 | error / None / 21.8 | feasible / 76899.869734 / 31.58 | True |
| facility_regions | L | 2 | scip | 4 | feasible / 79688.598531 / 32.653 | feasible / 76870.404156 / 31.336 | True |
| knapsack_depots | M | 0 | highs | 4 | feasible / 4775.59 / 30.813 | optimal / 4775.59 / 1.052 | True |
| knapsack_depots | M | 0 | milp | 4 | feasible / 4772.48 / 0.47 | feasible / 4772.48 / 0.264 | True |
| knapsack_depots | M | 0 | scip | 4 | feasible / 4775.59 / 30.25 | optimal / 4775.59 / 0.505 | True |
| knapsack_depots | M | 1 | highs | 4 | optimal / 4577.59 / 2.329 | optimal / 4577.59 / 1.021 | True |
| knapsack_depots | M | 1 | milp | 4 | feasible / 4573.42 / 0.387 | feasible / 4573.42 / 0.252 | True |
| knapsack_depots | M | 1 | scip | 4 | optimal / 4577.59 / 1.615 | optimal / 4577.59 / 0.338 | True |
| knapsack_depots | M | 2 | highs | 4 | optimal / 4259.51 / 21.029 | optimal / 4259.51 / 1.033 | True |
| knapsack_depots | M | 2 | milp | 4 | feasible / 4259.51 / 0.448 | feasible / 4259.51 / 0.258 | True |
| knapsack_depots | M | 2 | scip | 4 | optimal / 4259.51 / 23.342 | optimal / 4259.51 / 0.373 | True |
| knapsack_depots | L | 0 | highs | 4 | feasible / 11525.19 / 30.781 | optimal / 11528.99 / 2.126 | True |
| knapsack_depots | L | 0 | milp | 4 | feasible / 11528.99 / 2.222 | feasible / 11522.01 / 0.308 | True |
| knapsack_depots | L | 0 | scip | 4 | feasible / 11528.99 / 30.264 | optimal / 11528.99 / 1.948 | True |
| knapsack_depots | L | 1 | highs | 4 | feasible / 11050.25 / 30.878 | optimal / 11053.1 / 2.778 | True |
| knapsack_depots | L | 1 | milp | 4 | feasible / 11052.12 / 1.092 | feasible / 11050.3 / 0.322 | True |
| knapsack_depots | L | 1 | scip | 4 | feasible / 11051.54 / 30.246 | optimal / 11053.1 / 2.721 | True |
| knapsack_depots | L | 2 | highs | 4 | feasible / 10969.21 / 30.807 | optimal / 10976.970000000001 / 2.316 | True |
| knapsack_depots | L | 2 | milp | 4 | feasible / 10971.84 / 2.777 | feasible / 10971.68 / 0.336 | True |
| knapsack_depots | L | 2 | scip | 4 | feasible / 10976.07 / 30.246 | optimal / 10976.970000000001 / 2.064 | True |
| family | size | inst | backend | blocks | whole: status / objective / s | blocks: status / objective / s | same optimum |
|---|---|---|---|---|---|---|---|
| facility_regions | M | 0 | highs | 4 | optimal / 33337.008084 / 6.188 | optimal / 33337.008084 / 1.722 | True |
| facility_regions | M | 0 | milp | 4 | feasible / 33338.354865 / 30.928 | optimal / 33337.008084 / 1.461 | True |
| facility_regions | M | 0 | scip | 4 | feasible / 33338.354865 / 30.558 | optimal / 33337.008084 / 0.945 | True |
| facility_regions | M | 1 | highs | 4 | optimal / 32000.183964 / 5.92 | optimal / 32000.183964 / 1.373 | True |
| facility_regions | M | 1 | milp | 4 | optimal / 32000.183964 / 21.929 | optimal / 32000.183964 / 1.119 | True |
| facility_regions | M | 1 | scip | 4 | optimal / 32000.183964 / 8.389 | optimal / 32000.183964 / 0.791 | True |
| facility_regions | M | 2 | highs | 4 | optimal / 31145.125168 / 7.811 | optimal / 31145.125168 / 1.689 | True |
| facility_regions | M | 2 | milp | 4 | optimal / 31145.125168 / 28.9 | optimal / 31145.125168 / 1.421 | True |
| facility_regions | M | 2 | scip | 4 | optimal / 31145.125168 / 6.3 | optimal / 31145.125168 / 0.88 | True |
| facility_regions | L | 0 | highs | 4 | feasible / 77428.996635 / 33.728 | optimal / 77335.778295 / 9.25 | True |
| facility_regions | L | 0 | milp | 4 | error / None / 13.311 | optimal / 77335.778295 / 31.443 | True |
| facility_regions | L | 0 | scip | 4 | feasible / 78135.151705 / 32.83 | optimal / 77335.778295 / 21.596 | True |
| facility_regions | L | 1 | highs | 4 | feasible / 75482.402264 / 33.725 | optimal / 75156.299942 / 9.59 | True |
| facility_regions | L | 1 | milp | 4 | error / None / 13.942 | feasible / 75160.555851 / 31.537 | True |
| facility_regions | L | 1 | scip | 4 | feasible / 76091.325979 / 32.6 | optimal / 75156.299942 / 23.718 | True |
| facility_regions | L | 2 | highs | 4 | feasible / 76910.694002 / 33.728 | optimal / 76870.404156 / 10.458 | True |
| facility_regions | L | 2 | milp | 4 | error / None / 21.8 | feasible / 76899.869734 / 31.58 | True |
| facility_regions | L | 2 | scip | 4 | feasible / 79688.598531 / 32.653 | feasible / 76870.404156 / 31.336 | True |
| knapsack_depots | M | 0 | highs | 4 | feasible / 4775.59 / 30.813 | optimal / 4775.59 / 1.052 | True |
| knapsack_depots | M | 0 | milp | 4 | feasible / 4772.48 / 0.47 | feasible / 4772.48 / 0.264 | True |
| knapsack_depots | M | 0 | scip | 4 | feasible / 4775.59 / 30.25 | optimal / 4775.59 / 0.505 | True |
| knapsack_depots | M | 1 | highs | 4 | optimal / 4577.59 / 2.329 | optimal / 4577.59 / 1.021 | True |
| knapsack_depots | M | 1 | milp | 4 | feasible / 4573.42 / 0.387 | feasible / 4573.42 / 0.252 | True |
| knapsack_depots | M | 1 | scip | 4 | optimal / 4577.59 / 1.615 | optimal / 4577.59 / 0.338 | True |
| knapsack_depots | M | 2 | highs | 4 | optimal / 4259.51 / 21.029 | optimal / 4259.51 / 1.033 | True |
| knapsack_depots | M | 2 | milp | 4 | feasible / 4259.51 / 0.448 | feasible / 4259.51 / 0.258 | True |
| knapsack_depots | M | 2 | scip | 4 | optimal / 4259.51 / 23.342 | optimal / 4259.51 / 0.373 | True |
| knapsack_depots | L | 0 | highs | 4 | feasible / 11525.19 / 30.781 | optimal / 11528.99 / 2.126 | True |
| knapsack_depots | L | 0 | milp | 4 | feasible / 11528.99 / 2.222 | feasible / 11522.01 / 0.308 | True |
| knapsack_depots | L | 0 | scip | 4 | feasible / 11528.99 / 30.264 | optimal / 11528.99 / 1.948 | True |
| knapsack_depots | L | 1 | highs | 4 | feasible / 11050.25 / 30.878 | optimal / 11053.1 / 2.778 | True |
| knapsack_depots | L | 1 | milp | 4 | feasible / 11052.12 / 1.092 | feasible / 11050.3 / 0.322 | True |
| knapsack_depots | L | 1 | scip | 4 | feasible / 11051.54 / 30.246 | optimal / 11053.1 / 2.721 | True |
| knapsack_depots | L | 2 | highs | 4 | feasible / 10969.21 / 30.807 | optimal / 10976.970000000001 / 2.316 | True |
| knapsack_depots | L | 2 | milp | 4 | feasible / 10971.84 / 2.777 | feasible / 10971.68 / 0.336 | True |
| knapsack_depots | L | 2 | scip | 4 | feasible / 10976.07 / 30.246 | optimal / 10976.970000000001 / 2.064 | True |
| family | backend | runs | whole SGM s | blocks SGM s | blocks faster | blocks slower | proofs gained | wrong |
|---|---|---|---|---|---|---|---|---|
| facility_regions | highs | 6 | 14.345 | 4.277 | 6 | 0 | +3 | 0 |
| facility_regions | milp | 6 | 28.303 | 7.561 | 3 | 0 | +2 | 0 |
| facility_regions | scip | 6 | 18.963 | 5.957 | 5 | 0 | +3 | 0 |
| knapsack_depots | highs | 6 | 19.190 | 1.629 | 6 | 0 | +4 | 0 |
| knapsack_depots | milp | 6 | 30.000 | 30.000 | 0 | 0 | +0 | 0 |
| knapsack_depots | scip | 6 | 18.719 | 1.128 | 6 | 0 | +4 | 0 |
