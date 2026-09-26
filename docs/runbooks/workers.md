# Scaling workers (R33)

Workers claim with `FOR UPDATE SKIP LOCKED`, fairly across organizations
(fewest runs in progress first). Postgres is the queue; there is no Redis.

## Scale out

```bash
# N workers, same image as the API. Memory ceiling is per container.
docker compose up -d --scale worker=4 --no-recreate backend frontend postgres clickhouse
```

Each worker container is capped at **12 GB** (`mem_limit` in
`docker-compose.yml`) and **8 CPUs**. Each solve inside a worker is also
sandboxed (`SOLVE_MEMORY_MB`, default 4096). Budget roughly:

| Workers | Host RAM to keep free for them |
|---|---|
| 1 | ≥ 12 GB |
| 2 | ≥ 24 GB |
| 4 | ≥ 48 GB |

Do not publish the metrics ports. Scrapes stay on the compose network
(`worker:9100`, `backend:9101`), or an operator reads
`GET /api/v1/metrics` (Bearer token of an operator organization).

## What the gauges mean

| Metric | Where | Meaning |
|---|---|---|
| `queue_depth{org}` | API | Queued runs per organization |
| `runs_running{org}` | API | Runs a worker currently holds, per organization |
| `queue_oldest_wait_seconds{org}` | API | Age of that organization's oldest queued run |
| `queue_wait_seconds` | worker | Histogram of wait from queue to claim |
| `worker_busy` | worker | 1 while this process holds a run |

## Fair-share load check

```bash
docker run --rm --network solver_solver_net \
  -v "D:/solver/backend:/app" -w /app --env-file D:/solver/.env \
  solver-backend-test \
  sh -c 'TEST_DATABASE_URL=${DATABASE_URL}_test python -m bench.load --check'
```

Uses only a database whose name ends in `_test` (refuses the live `solver`
database). 200 submits across 5 organizations must land within ±10% of an
equal share, with nobody starved.
