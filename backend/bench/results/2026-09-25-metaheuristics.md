# A metaheuristic lane: CMA-ES, particle swarm, a genetic algorithm -- 2026-09-25 (queue R14)

`python -m bench.evolve --time-limit 60`. Each case solved sandboxed, as a
run, by the backend the rules choose and by each search (CMA-ES and particle
swarm on continuous models only), 60 s each, seed 1. Cases: the nonconvex
`sines` and `bilinear` of the IPOPT bench, and the integer families with the
widest gaps or no answer on the decomposition gate: knapsack XL,
flow_shop_timed L and XL, districting L (here without R13's start, to ask
whether a search finds a partition by itself).

**Verdict: `solve.metaheuristic` stays off (migration 0061); the three
searches ship by name.** The fallback's case -- an answer where the exact
solver had none -- never happened: on the two cases with no exact answer
(flow_shop_timed XL, where CP-SAT runs out of 4 GB, and districting L) the
genetic algorithm found no answer that keeps every rule either. Where the
exact solver answered, a search did better only on `sines` (a sum of sines
and cosines of neighbours, nonconvex, SCIP's bound far from its answer):
the genetic algorithm found 215.30 at 200 decisions against SCIP's 211.83,
and 53.89 at 50 against 53.53. At 1,000 decisions SCIP's answer is better
again, and on bilinear SCIP proves the optimum. So a planner with a
nonconvex model and an unproven answer may ask for `ga` by name; nothing
is switched on for everyone.

- **The genetic algorithm is the strongest of the three here**, continuous
  models included; the fallback would use it for both kinds.
- **CMA-ES** (the modern derivative-free standard) comes second on the
  continuous cases; particle swarm last.
- **Found while benching: numpy's bundled OpenBLAS ran a spinning thread per
  core** (20), and the first run's CMA-ES and GA were killed for passing the
  sandbox's CPU allowance. A search now tells the library to use one thread
  (`evolve._blas_threads`), pinned by a test; the CMA-ES decomposition is
  also recomputed every few generations, not every one (Hansen's lazy
  update), which at 200 decisions was most of each generation's time.
- **What the answers claim.** Nothing: `feasible`, no bound, optimality
  `none`. The queue line said `approximate`; on this platform that word
  means optimal to a stated tolerance (PDLP), which a search cannot say.

| case | exact: backend / status / answer / bound | cma-es | pso | ga | answer where none | better answer |
|---|---|---|---|---|---|---|
| sines 50 | scip / feasible / 53.5326 / 95.488 | 38.3697 | 50.0521 | 53.8931 | no | ga |
| sines 200 | scip / feasible / 211.83 / 379.298 | 164.488 | 150.747 | 215.304 | no | ga |
| sines 1000 | scip / feasible / 995.501 / 1813.64 | 397.747 | 42.3443 | 846.408 | no | no |
| bilinear 200 | scip / optimal / 6828.99 / 6828.99 | 5416.34 | 2200.65 | 6242.97 | no | no |
| knapsack XL | highs / feasible / 7434.19 / 7441.84 | -- | -- | 7338.37 | no | no |
| flow_shop_timed L | cp-sat / optimal / 102 / 102 | -- | -- | unknown | no | no |
| flow_shop_timed XL | cp-sat / crashed (out of memory, 4096 MB) | -- | -- | unknown | no | no |
| districting L | cp-sat / unknown | -- | -- | unknown | no | no |
