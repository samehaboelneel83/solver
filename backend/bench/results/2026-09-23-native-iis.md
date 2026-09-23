# Benchmark: native IIS

`python -m bench.iis --sizes S,M,L` (probe clock 5 s, budget 200 probes; one instance per size).

| family | size | backend | instances | deletion: probes / s / size / minimal | IIS core: probes / s / size / minimal | same rules |
|---|---|---|---|---|---|---|
| feed_blend | S | glop | 4 | 6 / 0.001 / 2 / True | 3 / 0.67 / 2 / True (iis) | True |
| feed_blend | M | glop | 11 | 13 / 0.004 / 2 / True | 3 / 0.822 / 2 / True (iis) | True |
| feed_blend | L | glop | 31 | 33 / 0.092 / 2 / True | 3 / 0.582 / 2 / True (iis) | True |
| rota | S | cp-sat | 101 | 24 / 0.039 / 1 / True | 2 / 0.422 / 1 / True (iis) | True |
| rota | M | cp-sat | 261 | 24 / 0.079 / 1 / True | 2 / 0.43 / 1 / True (iis) | True |
| rota | L | cp-sat | 1242 | 45 / 0.651 / 1 / True | 2 / 0.472 / 1 / True (iis) | True |
| facility | S | highs | 125 | 28 / 11.146 / 20 / True | 26 / 11.571 / 20 / True (iis) | True |
| facility | M | highs | 1295 | 98 / 41.115 / 79 / True | 96 / 42.986 / 79 / True (iis) | True |
| facility | L | highs | 12340 | 200 / 118.601 / 263 / False | 200 / 121.014 / 263 / False (iis) | True |

[exited with code 0]

"deletion" is the search as it was: deletion filtering over every rule,
then every instance of the rules kept. "IIS core" asks HiGHS for an
infeasible subset of the linear relaxation (`highs.iis`, strategy
`FromLp`), confirms it with the run's own backend (one probe) and shrinks
it by deletion filtering on the core alone. Both name the same rules on
every instance, and every conflict proven minimal by one is by the other.

## What it shows

- **Probes: never more, and far fewer when the conflict is small in a big
  model.** rota L: 2 probes against 45; feed_blend L: 3 against 33. The
  core goes straight to the instance that matters instead of filtering
  1,242 instances' rules one by one.
- **When the conflict is most of the model the core saves little.**
  facility: every site's capacity and nearly every customer's service are
  in it, so the core *is* the conflict (20, 79, 263 instances) and only
  the rule pass is saved (2 probes). The instance shrink -- one probe per
  core member -- dominates; at L both exhaust the 200-probe budget and say
  so (`minimal` False). Shrinking a large core faster is the next queue
  item (minimal conflicts), not this one.
- **Seconds: a fixed ~0.4-0.8 s for the HiGHS child** (a fresh interpreter,
  as every HiGHS call is). On models whose probes take a millisecond that
  is slower in wall time (feed_blend S: 0.67 s against 0.001 s); it pays
  back where probes are expensive, and breaks even at rota L.
- **The strategy was measured, not assumed.** HiGHS's `Irreducible` flag
  on the facility L relaxation (12,340 rows) took 49 s for a core of 334
  rows; `FromLp` alone took 1.05 s for 340. HiGHS does not stop its IIS
  search at `time_limit` (a first run was killed at the child's deadline),
  so the flag is off, and a core HiGHS cannot finish is no core
  (`highs.iis` returns None and the full search runs).
- **Where it applies:** any linear model, whatever backend solved it --
  the core only proposes; the run's backend decides. A model whose
  relaxation is feasible (only whole numbers conflict), or that holds a
  switch, a curve or a scheduling rule, has no core and is searched as
  before.

## CP-SAT assumption cores (added the same day)

`python -m bench.iis --families rota --sizes S,M,L` -- a third mode for
the instances CP-SAT solves: every rule instance enforced by a literal of
its own, all assumed, and `SufficientAssumptionsForInfeasibility` read
back as the core (`cpsat.core`), then confirmed and shrunk as the others.

| family | size | backend | instances | deletion | IIS core | CP-SAT core | same rules |
|---|---|---|---|---|---|---|---|
| rota | S | cp-sat | 101 | 24 / 0.041 s / 1 / True | 2 / 0.478 s / 1 / True | 2 / 0.012 s / 1 / True | True |
| rota | M | cp-sat | 261 | 24 / 0.105 s / 1 / True | 2 / 0.434 s / 1 / True | 2 / 0.027 s / 1 / True | True |
| rota | L | cp-sat | 1242 | 45 / 0.708 s / 1 / True | 2 / 0.471 s / 1 / True | 2 / 0.122 s / 1 / True | True |

(probes / seconds / conflict size / minimal.) The CP-SAT core is as short
as HiGHS's and has no child process to start, so it is the fastest of the
three on every size -- and it is exact for the whole-number model: where
only whole numbers conflict (`2x = 1`), HiGHS's relaxation offers nothing
and CP-SAT names the rule (`tests/test_diagnose.py`). A CP-SAT run tries
its own core first, then HiGHS's. A model with a scheduling rule has no
CP-SAT core: `NoOverlap` and `Cumulative` take no enforcement literal.
