# Benchmark: flow-shop-formulations

30 runs; technique `none`, baseline `None`. Time is the shifted geometric mean (shift 10 s), charging an unproven answer the full time limit.

The primal integral is the seconds spent without a good answer (`bench.primal`); smaller is better.

| family | size | backend | value | runs | proven | SGM time (s) | mean gap | primal integral (s) | wrong |
|---|---|---|---|---|---|---|---|---|---|
| flow_shop | L | cp-sat | None | 2 | 2 | 0.031 | 0.00% | 0.005 | 0 |
| flow_shop | M | cp-sat | None | 2 | 2 | 0.011 | 0.00% | 0.003 | 0 |
| flow_shop | S | cp-sat | None | 2 | 2 | 0.237 | 0.00% | 0.003 | 0 |
| flow_shop_timed | L | cp-sat | None | 2 | 2 | 31.021 | 0.00% | 5.990 | 0 |
| flow_shop_timed | L | highs | None | 2 | 0 | 60.982 | — | 60.982 | 0 |
| flow_shop_timed | L | milp | None | 2 | 0 | 75.266 | — | 75.271 | 0 |
| flow_shop_timed | L | scip | None | 2 | 0 | 60.280 | — | 60.280 | 0 |
| flow_shop_timed | M | cp-sat | None | 2 | 2 | 0.714 | 0.00% | 0.213 | 0 |
| flow_shop_timed | M | highs | None | 2 | 0 | 60.468 | 15.29% | 34.930 | 0 |
| flow_shop_timed | M | milp | None | 2 | 0 | 60.825 | 15.69% | 60.825 | 0 |
| flow_shop_timed | M | scip | None | 2 | 0 | 60.041 | 19.93% | 29.224 | 0 |
| flow_shop_timed | S | cp-sat | None | 2 | 2 | 0.023 | 0.00% | 0.009 | 0 |
| flow_shop_timed | S | highs | None | 2 | 2 | 0.558 | 0.00% | 0.026 | 0 |
| flow_shop_timed | S | milp | None | 2 | 2 | 0.219 | 0.00% | 0.220 | 0 |
| flow_shop_timed | S | scip | None | 2 | 2 | 0.192 | 0.00% | 0.159 | 0 |

## What this compares

One flow shop, two formulations, identical data (`bench.families`,
`flow_shop` and `flow_shop_timed`, seeded by `flow_shop-{size}-{instance}`
for both): jobs pass through a chain of machines, one job per machine at a
time, minimise the makespan. Two instances per size, one seed, 60 s limit,
`python -m bench.run --family flow_shop,flow_shop_timed --sizes S,M,L
--instances 2 --time-limit 60`.

| size | jobs x machines | horizon (slots) | interval: variables / rules | time-indexed: variables / rows |
|---|---|---|---|---|
| S | 4 x 2 | 16, 17 | 17 / 14 | 257-273 / 308-326 |
| M | 8 x 3 | 55, 52 | 49 / 43 | 2,497-2,641 / 2,716-2,869 |
| L | 15 x 4 | 123, 128 | 121 / 109 | 14,761-15,361 / 15,417-16,037 |

The horizon is the makespan of the jobs in generated order -- a schedule
that exists, so no optimum lies past it. The interval model's size depends
only on jobs x machines; the time-indexed model's on that times the horizon.

## What it shows

- **The interval formulation wins by three orders of magnitude at L:**
  CP-SAT proves the optimum in 0.03 s (SGM) against 31 s for the same
  solver on the time-indexed model -- about 1,000x, and growing with the
  horizon (S 0.2 s vs 0.02 s is noise at that size; M 0.011 s vs 0.71 s,
  ~65x).
- **The MIP backends cannot use the time-indexed model past S:** at M
  HiGHS, the MILP wrapper and SCIP stop at 60 s with 15-20% gaps; at L none
  finds an answer at all. Only CP-SAT holds intervals, so for them the
  time-indexed model is the only formulation -- and it does not scale.
- **No wrong answers:** every proven optimum agrees across backends and
  across the two formulations (16, 16, 46, 48, 102, 108); the S instances
  also match Johnson's rule in `tests/test_bench.py`.

Consequence: `flow_shop_timed` is comparison-only (`COMPARISON_ONLY`) and
is left out of the nightly -- at L, 26-36 s against the nightly's 30 s
limit would prove it some nights and not others. `flow_shop` runs nightly.
