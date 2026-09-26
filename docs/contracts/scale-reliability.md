# Scale and reliability notes (OAAS Phase 5 / S01–S04)

## S01 — Analytics may degrade without blocking planning

Compose: the API waits for Postgres **healthy** and ClickHouse only
**started** (`docker-compose.yml`). A ClickHouse outage must not prevent
login, model edit, or solve. `/api/health` still reports `clickhouse`
separately so operators can see degraded analytics.

Workers already depended only on Postgres.

## S02 — Submit idempotency

`POST /api/v1/scenarios/{id}/runs` accepts optional header
`Idempotency-Key` (1–128 printable ASCII). Within an organization the same
key returns the existing run with **200**; a new key still returns **201**.
Stored on `run.idempotency_key` (migration **0083**), unique per organization.

Use this for client retries after network loss; it is not a cache of solve
results (see `reuse` / `cache_key` for that).

## S03 — Execution-attempt fencing

Each `claim_next` bumps `run.execution_attempt` (migration **0084**). Settling
writes (`_record`, verification failure, adapter failure) require
`execution_attempt` to still match. A stale worker that finishes after reclaim
cannot overwrite the newer attempt's result.

## S04 — Resource reservations (CPU / memory / licence seats)

Before a run starts (and before a portfolio expands it), the worker reserves
host capacity via `app.solve.reserve`:

| Env | Default | Meaning |
|---|---|---|
| `SOLVE_HOST_WORKERS` | 32 | Total solver threads across concurrent runs |
| `SOLVE_HOST_MEMORY_MB` | `SOLVE_MEMORY_MB` × 8 | Total sandbox memory envelope |
| `SOLVE_LICENSE_SEATS` | 8 | Concurrent commercial-licence seats |
| `SOLVE_CHECK_SHARE` | 0.25 | Cap for shadow/suite (**check** pool) |

Planner runs keep the remaining share so quality checks cannot starve
planning. A portfolio multiplies memory by entrant count (each sandbox) and
counts licensed entrants as seats; if the host has no room, the portfolio is
skipped (`params.portfolio_skipped`) and the rules' single solver continues.
`claim_next` stamps `params.reservation` when a run becomes `running`.

## S05 — Measured capacity limits (reference host)

These are **documented maxima for the single-host reference install**, not
marketing claims. Operators should re-measure on their hardware and set the
env vars in S04 accordingly.

| Dimension | Reference limit | How enforced |
|---|---|---|
| Concurrent planner solves | `SOLVE_HOST_WORKERS` / typical `workers` (default 32/8 ≈ 4) | S04 reservation at claim |
| Shadow/suite share | `SOLVE_CHECK_SHARE` (default 25%) | S04 check pool |
| Sandbox memory per solve | `SOLVE_MEMORY_MB` (default 4096) | `sandbox.memory_cap` |
| Host memory envelope | `SOLVE_HOST_MEMORY_MB` (default 8× per-solve) | S04 reservation |
| Commercial licence seats | `SOLVE_LICENSE_SEATS` (default 8) | S04 reservation |
| Decisions per model | org `max_vars` quota | enqueue refusal |
| Time limit | org `max_time_limit_s` | enqueue refusal |
| Inline result amounts | 200 000 cells | chunked `amounts` API (0082) |
| Result verification | independent check before settle | Q02 `verify.py` |

**Re-measure when:** changing default workers, enabling portfolio by default,
or certifying a new solver. Record timings under `backend/bench/results/` and
update this table. Equal-budget gates (Q04) remain the performance claim
mechanism; this table is the capacity envelope those benches assume.
