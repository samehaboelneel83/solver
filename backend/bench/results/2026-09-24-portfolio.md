# The portfolio against the rule choice — 2026-09-24

`python -m bench.portfolio --sizes M,L --instances 3 --time-limit 30` (the
nightly families) and `--sizes S,M --instances 2 --families
facility_regions,knapsack_depots,rota_teams,flow_shop_timed,districting`
(queue R2). Each integer instance with two or more admissible solvers: the
rule's choice alone on all 8 threads for 30 s, against the portfolio -- every
admissible solver at once, the threads shared out, the first proof ending it,
else the best answer at the deadline. Both in sandboxed children, as a run
does. A solve without a proof is charged 30 s.

**Verdict: leave off** (`solve.portfolio` defaults off, migration 0052). On
the nightly families the portfolio is 20-40% faster (rota, rota_rates: SCIP
or the MILP wrapper proves first) and never 2x slower; facility breaks even.
But where CP-SAT is the rule's choice and the right one (flow_shop_timed,
districting) it loses its threads to the others: 2-4x slower. It changed no
optimum, and on one districting instance it found an answer (gap 2.65%)
where CP-SAT alone found none in 30 s. It stays available per problem or
domain -- worth turning on for a model whose best solver is not known.

**Found by the bench, fixed:** the first two runs had the portfolio take the
full 30 s even after a proof -- a beaten entrant asked to stop did not, and
ran to its time limit. `sandbox.run(..., abandon=)` now ends a beaten
entrant's process at once (`sandbox.Abandoned`); a person's Stop still asks
politely and keeps the best answer.

Next to try: keep the rule's choice on most of the threads rather than an
equal share -- the regressions are all the rule's own solver starved.

## Nightly families

| family | size | inst | rule | portfolio winner | rule: status / s / gap | portfolio: status / s / gap |
|---|---|---|---|---|---|---|
| facility | M | 0 | highs | scip | optimal / 1.72 / 0% | optimal / 0.69 / 0% |
| facility | M | 1 | highs | scip | optimal / 1.23 / 0% | optimal / 0.68 / 0% |
| facility | M | 2 | highs | scip | optimal / 1.33 / 0% | optimal / 0.68 / 0% |
| facility | L | 0 | highs | highs | optimal / 3.72 / 0% | optimal / 4.70 / 0% |
| facility | L | 1 | highs | highs | optimal / 8.42 / 0% | optimal / 11.49 / 0% |
| facility | L | 2 | highs | highs | optimal / 7.67 / 0% | optimal / 10.28 / 0% |
| rota | M | 0 | cp-sat | milp | optimal / 0.76 / 0% | optimal / 0.47 / 0% |
| rota | M | 1 | cp-sat | scip | optimal / 0.63 / 0% | optimal / 0.46 / 0% |
| rota | M | 2 | cp-sat | scip | optimal / 0.58 / 0% | optimal / 0.45 / 0% |
| rota | L | 0 | cp-sat | scip | optimal / 0.83 / 0% | optimal / 0.77 / 0% |
| rota | L | 1 | cp-sat | scip | optimal / 0.87 / 0% | optimal / 0.77 / 0% |
| rota | L | 2 | cp-sat | scip | optimal / 0.93 / 0% | optimal / 0.77 / 0% |
| rota_rates | M | 0 | highs | scip | optimal / 0.92 / 0% | optimal / 0.46 / 0% |
| rota_rates | M | 1 | highs | scip | optimal / 0.91 / 0% | optimal / 0.46 / 0% |
| rota_rates | M | 2 | highs | scip | optimal / 0.91 / 0% | optimal / 0.45 / 0% |
| rota_rates | L | 0 | highs | scip | optimal / 1.04 / 0% | optimal / 0.72 / 0% |
| rota_rates | L | 1 | highs | scip | optimal / 1.06 / 0% | optimal / 0.72 / 0% |
| rota_rates | L | 2 | highs | scip | optimal / 1.10 / 0% | optimal / 0.73 / 0% |

| family | runs | rule SGM s | portfolio SGM s |
|---|---|---|---|
| facility | 6 | 3.195 | 2.956 |
| rota | 6 | 0.759 | 0.606 |
| rota_rates | 6 | 0.990 | 0.586 |

- families at least 10% faster: rota, rota_rates
- instances at least 2x slower: none
- disagreeing optima: 0
- verdict: enable

## Harder families

| family | size | inst | rule | portfolio winner | rule: status / s / gap | portfolio: status / s / gap |
|---|---|---|---|---|---|---|
| facility_regions | S | 0 | highs | scip | optimal / 1.56 / 0% | optimal / 0.85 / 0% |
| facility_regions | S | 1 | highs | scip | optimal / 0.94 / 0% | optimal / 0.87 / 0% |
| facility_regions | M | 0 | highs | highs | optimal / 5.76 / 0% | optimal / 7.48 / 0% |
| facility_regions | M | 1 | highs | highs | optimal / 6.33 / 0% | optimal / 7.64 / 0% |
| knapsack_depots | M | 0 | highs | scip | feasible / 30.00 / 0.295% | feasible / 30.00 / 0.138% |
| knapsack_depots | M | 1 | highs | scip | optimal / 2.42 / 0% | optimal / 1.77 / 0% |
| rota_teams | S | 0 | cp-sat | milp | optimal / 0.46 / 0% | optimal / 0.42 / 0% |
| rota_teams | S | 1 | cp-sat | scip | optimal / 0.50 / 0% | optimal / 0.42 / 0% |
| rota_teams | M | 0 | cp-sat | milp | optimal / 0.57 / 0% | optimal / 0.45 / 0% |
| rota_teams | M | 1 | cp-sat | scip | optimal / 0.54 / 0% | optimal / 0.45 / 0% |
| flow_shop_timed | S | 0 | cp-sat | milp | optimal / 0.56 / 0% | optimal / 0.44 / 0% |
| flow_shop_timed | S | 1 | cp-sat | cp-sat | optimal / 0.53 / 0% | optimal / 0.85 / 0% |
| flow_shop_timed | M | 0 | cp-sat | cp-sat | optimal / 1.57 / 0% | optimal / 5.40 / 0% |
| flow_shop_timed | M | 1 | cp-sat | cp-sat | optimal / 1.74 / 0% | optimal / 4.88 / 0% |
| districting | S | 0 | cp-sat | cp-sat | optimal / 3.38 / 0% | optimal / 7.94 / 0% |
| districting | S | 1 | cp-sat | highs | optimal / 1.60 / 0% | optimal / 6.26 / 0% |
| districting | M | 0 | cp-sat | highs | unknown / 30.00 / - | feasible / 30.00 / 2.65% |
| districting | M | 1 | cp-sat | highs | optimal / 3.42 / 0% | optimal / 6.61 / 0% |

| family | runs | rule SGM s | portfolio SGM s |
|---|---|---|---|
| facility_regions | 4 | 2.960 | 2.989 |
| knapsack_depots | 2 | 9.302 | 8.271 |
| rota_teams | 4 | 0.518 | 0.435 |
| flow_shop_timed | 4 | 1.025 | 2.166 |
| districting | 4 | 5.291 | 10.125 |

- families at least 10% faster: knapsack_depots, rota_teams
- instances at least 2x slower: flow_shop_timed-M-0: 1.57s -> 5.40s; flow_shop_timed-M-1: 1.74s -> 4.88s; districting-S-0: 3.38s -> 7.94s; districting-S-1: 1.60s -> 6.26s
- disagreeing optima: 0
- verdict: leave off

