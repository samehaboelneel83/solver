# Chance rules: the in-sample share held below the asked one — 2026-09-25

Queue R8c. The live check of R8 found a chance rule asked to hold in 90% of
futures holding in 70% of fresh ones (20 sampled): the extensive form lets a
rule fail in `epsilon * N` of the *sampled* futures, and a plan fitted to
those is optimistic about the rest. `app.solve.stochastic.in_sample` now
holds the in-sample share below the asked one by 1.645 standard errors of a
share estimated from N draws (one-sided 95%).

Measured on the hand-worked cover model (demand 100 +- 50% uniform, order the
least that covers it in 90% of futures; the share a plan truly holds is
exact: (order - 50) / 100), twelve seeds each, HiGHS:

| futures | in-sample share | mean held (true) | lowest | seeds meeting 90% | mean order |
|---|---|---|---|---|---|
| 20 | 10% (as asked) | 85.9% | 76.2% | 4 / 12 | 135.9 |
| 20 | 0% (held below) | 93.4% | 82.2% | 9 / 12 | 143.4 |
| 50 | 10% (as asked) | 88.4% | 82.2% | 4 / 12 | 138.4 |
| 50 | 3.0% (held below) | 96.0% | 92.3% | 12 / 12 | 146.0 |

**Default: held below.** Solving at the asked share misses the promise two
seeds in three; held below, it keeps it every time at 50 futures for about
5% more order. At 20 futures it still misses in 3 of 12 -- too few futures
to promise 90% from; the run records the share held in sample
(`held_in_sample`) beside what was asked and what held.
