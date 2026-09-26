# Kubernetes / Helm (queue R38)

Postgres is **external** (managed). The chart deploys API, worker (HPA), frontend,
and a pre-install/upgrade Job that runs `alembic upgrade head`.

## Install

```bash
kubectl create secret generic solver-db --from-literal=password='…'
kubectl create secret generic solver-jwt --from-literal=secret='…'

helm upgrade --install solver deploy/helm/solver \
  --set postgresql.host=my.postgres.example \
  --set postgresql.user=solver \
  --set postgresql.database=solver \
  --set image.api=solver-backend:latest \
  --set image.frontend=solver-frontend:latest
```

## Worker sandbox

Each solve runs in a child with `RLIMIT_AS` and `prctl(PR_SET_DUMPABLE)`. The
worker pod `securityContext` allows `SYS_RESOURCE` and privilege escalation so
those limits can be set. Do not drop them for worker pods.

## Metrics / HPA

R33 exposes per-org `queue_depth` on the API scrape. Wire a Prometheus adapter
to scale on that metric when ready; until then HPA uses CPU (see `values.yaml`).

## Backups

WAL and `pg_dump` remain the operator's responsibility on the managed Postgres
(or the R39 host scripts if you still run Postgres on a VM). ClickHouse
`run_fact` is rebuildable and is not required in the chart by default.
