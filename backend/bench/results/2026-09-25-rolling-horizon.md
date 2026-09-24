# Relax-and-fix over the days against the whole model — 2026-09-25

`python -m bench.horizon --time-limit 30` (queue R9). The families laid out
over a `day` set, at their two largest sizes: HiGHS on the whole model (8
threads) against relax-and-fix (`app.solve.horizon`: four windows of days,
the window whole, later days relaxed, earlier ones held), the same time.
Both in sandboxed children.

**Verdict: leave off** (`solve.rolling_horizon` defaults off, migration 0057).
HiGHS proves every instance's optimum on the whole model in 1-2.5 s; relax-
and-fix reaches the same answer on rota and rota_teams, within 0.02% on
rota_rates, and takes two to four times as long. On models this platform
builds, the whole solve is not the bottleneck relax-and-fix exists for. It
stays available per problem or domain for a horizon long enough that the
whole model does not fit the time; its answers are `feasible`, never proven
best. Next to try: overlapping windows, and fixing only a window's first
half before sliding.

| family | size | whole: status / answer / s | relax-and-fix: status / answer / s | windows |
| rota | L | optimal / 2717 / 2.5 | feasible / 2717 / 2.4 | 4 |
| rota | XL | optimal / 13119 / 1.5 | feasible / 13119 / 4.1 | 4 |
| rota_rates | L | optimal / 3969.44 / 0.9 | feasible / 3970.2 / 2.7 | 4 |
| rota_rates | XL | optimal / 18467.07 / 1.6 | feasible / 18467.7 / 6.4 | 4 |
| rota_teams | L | optimal / 4822 / 0.8 | feasible / 4822 / 2.3 | 4 |
| rota_teams | XL | optimal / 24226 / 1.6 | feasible / 24226 / 4.0 | 4 |
- families where it found better: none
- more than 1% worse than a proven optimum: none
- verdict: leave off
