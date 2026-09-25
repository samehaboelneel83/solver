# A connected, balanced start for districting -- 2026-09-25 (queue R13)

`python -m bench.connected_start --time-limit 120 --sizes M,L,XL` (S: proven
optimal from the start too, 610 and 575, in the tests). Districting as on
2026-09-24: M 14 x 14 cells in 6 zones, L 20 x 20 in 8, XL 40 x 40 in 12;
people dense round a centre, each zone within 10% of an even share, each zone
connected (the exact flow). Each backend solved twice per instance, sandboxed
as a run: from nothing, and from `app.solve.partition`'s start (built in
0.01-0.9 s, taken from the solver's time).

**Verdict: on by default (`solve.connected_start`, migration 0060).**

- **An answer where there was none.** At 400 cells CP-SAT from nothing found
  no partition in two minutes; from the start it found one and improved it
  by about a third (16,955 to 11,360; 16,915 to 12,725). At M-0 it found
  nothing from nothing, and came within 2.85% of its bound from the start.
- **Never worse.** Where both runs found answers (M-0 HiGHS, M-1 both), the
  answers and gaps are the same.
- **The start is itself an answer.** It keeps every rule (pinned by
  `tests/test_partition.py` on every compiled row at S-XL), so a solver that
  ends with nothing -- HiGHS at L and XL here, or CP-SAT crashing -- leaves
  the start as the run's answer: feasible, no bound, never called optimal.
  Every size up to 1,600 cells now gets an answer.
- **Found, not fixed: CP-SAT runs out of memory at XL** (4096 MB, with or
  without the start): 1,600 cells x 12 zones of flow is 75,000 integer
  variables. The run keeps the start; a smaller encoding (cuts on the
  incumbent's disconnected pieces instead of the flow) is what would let a
  solver improve it there.

| size | instance | backend | start | start objective | status | objective | gap |
|---|---|---|---|---|---|---|---|
| M | M-0 | cp-sat | no | -- | unknown | -- | -- |
| M | M-0 | cp-sat | yes | 3622 | feasible | 1858 | 2.85% |
| M | M-0 | highs | no | -- | feasible | 1839 | 2.28% |
| M | M-0 | highs | yes | 3622 | feasible | 1839 | 2.28% |
| M | M-1 | cp-sat | no | -- | optimal | 1297 | 0% |
| M | M-1 | cp-sat | yes | 1815 | optimal | 1297 | 0% |
| M | M-1 | highs | no | -- | optimal | 1297 | 0% |
| M | M-1 | highs | yes | 1815 | optimal | 1297 | 0% |
| L | L-0 | cp-sat | no | -- | unknown | -- | -- |
| L | L-0 | cp-sat | yes | 16955 | feasible | 11360 | 42% |
| L | L-0 | highs | no | -- | unknown | -- | -- |
| L | L-0 | highs | yes | 16955 | unknown | -- | -- |
| L | L-1 | cp-sat | no | -- | unknown | -- | -- |
| L | L-1 | cp-sat | yes | 16915 | feasible | 12725 | 41.9% |
| L | L-1 | highs | no | -- | unknown | -- | -- |
| L | L-1 | highs | yes | 16915 | unknown | -- | -- |
| XL | XL-0 | cp-sat | no | -- | crashed (out of memory, 4096 MB) | -- | -- |
| XL | XL-0 | cp-sat | yes | 201035 | crashed (out of memory, 4096 MB) | -- | -- |
| XL | XL-0 | highs | no | -- | unknown | -- | -- |
| XL | XL-0 | highs | yes | 201035 | unknown | -- | -- |
| XL | XL-1 | cp-sat | no | -- | crashed (out of memory, 4096 MB) | -- | -- |
| XL | XL-1 | cp-sat | yes | 171093 | crashed (out of memory, 4096 MB) | -- | -- |
| XL | XL-1 | highs | no | -- | unknown | -- | -- |
| XL | XL-1 | highs | yes | 171093 | unknown | -- | -- |

**HiGHS rerun (same day), after two fixes.** The HiGHS rows above ended
`unknown` even with the start: HiGHS was handed it before its objective,
and setting the objective drops a start given earlier -- so no HiGHS warm
start had ever been tried (the same bug cost `solve.warm_start`). Given
after the objective, HiGHS takes it at every size; it then proves a bound
but does not improve the start in 120 s. The start was also not the same
from run to run (ties broken by set order, and string hashing differs per
process): ties are now broken by name, pinned by a test.

| size | instance | backend | start | start objective | status | objective | gap |
|---|---|---|---|---|---|---|---|
| L | L-0 | highs | no | -- | unknown | -- | -- |
| L | L-0 | highs | yes | 18710 | feasible | 18710 | 64.9% |
| L | L-1 | highs | no | -- | unknown | -- | -- |
| L | L-1 | highs | yes | 16915 | feasible | 16915 | 56.2% |
| XL | XL-0 | highs | no | -- | unknown | -- | -- |
| XL | XL-0 | highs | yes | 217334 | feasible | 217334 | 58.9% |
| XL | XL-1 | highs | no | -- | unknown | -- | -- |
| XL | XL-1 | highs | yes | 171093 | feasible | 171093 | 42.8% |

The bench runs call the sandbox directly, so the rows show the solver's own
status; in a run, the `unknown` and crashed rows with a start end `feasible`
at the start's objective.
