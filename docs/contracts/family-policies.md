# Family-specific solve policies (OAAS Q04 / Phase 4)

**Purpose:** pin how each template family chooses defaults, budgets, and
promotion evidence. Complements `docs/coverage-acceptance-matrix.md`.

## Equal-budget rule

A technique may change a default only when, on a named family and size set:

1. **Correctness:** zero `wrong` rows (backends that both claim proven optima agree; known optima respected).
2. **Budget:** same `time_limit` and `workers` for baseline and challenger (no N×threads portfolios unless the portfolio’s *total* CPU is capped to the baseline).
3. **Gain:** challenger wins (≥10% faster) more often than it loses on the held instances; regressions are published even when the default stays unchanged.

Harness:

```bash
python -m bench.equal_budget --family rota --sizes S,M --seeds 2 \
  --technique workers=8,4 --time-limit 30 --workers 8 \
  --out bench/results/equal-budget-rota.md
```

Ordinary `python -m bench.run --technique name=baseline,challenger …` remains
the measurement engine; `equal_budget` only enforces the gate narrative.

## Family defaults (standing decisions from committed benches)

| Family | Default posture | Evidence |
|---|---|---|
| `rota` / workforce IP | CP-SAT; symmetry off; rolling horizon off | symmetry / rolling-horizon reports |
| `facility` / MILP | HiGHS / rules’ pick; separable on when blocks admit | separable report |
| `feed_blend` LP | GLOP / HiGHS | golden + params reports |
| `load_balance` QP | HiGHS; decompose on for XL linking form | decomposition report |
| `flow_shop` | Interval formulation (CP-SAT); time-indexed comparison-only | flow-shop formulations |
| Routing / network | Dedicated modules; road distances local | routing / roads / network reports |
| Heuristics (CMA-ES / PSO / GA) | Never labelled proven best | metaheuristics report |
| Learned selector | **Shadow only** | selector report |
| Portfolio race | Off by default (unfair unless total budget capped) | portfolio report |

## Phase timings (Q03)

Successful runs record `params.phases` with wall seconds for:

`compile_s`, `choose_s`, `solve_s`, `verify_s`, `persist_s`

Use these to see which phase dominates a family before changing solvers.

## Offline representative suites

For an isolated install, re-ask acceptance with:

```bash
python -m bench.suites --check          # ≤5 s smoke (also in scripts/check.sh)
python -m bench.suites --night YYYY-MM-DD
```

Family generators (`bench.families`) need no network. MIPLIB downloads are
**not** part of the offline acceptance path.
