# Scale and reliability notes (OAAS Phase 5 / S01–S02)

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
