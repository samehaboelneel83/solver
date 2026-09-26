# Offline installation contract (OAAS O01)

**Audience:** operators installing on an isolated host (no public internet after the
bundle is transferred).  
**Related:** [`offline-dependency-manifest.md`](../offline-dependency-manifest.md),
[`backups.md`](backups.md), [`workers.md`](workers.md),
[`OAAS_PLATFORM_PROPOSAL.md`](../../OAAS_PLATFORM_PROPOSAL.md) §6.

## Product claim

A single-host reference install can be transferred as a versioned bundle, started
with Compose, and used for login → template → solve → map → export with **public
egress blocked**. Rebuilds that call `pip install` / `npm install` against the
public network are **not** the offline path; they are the development path.

## Bundle contents (minimum)

| Item | Source today | Offline requirement |
|---|---|---|
| App images | `solver-backend:latest`, `solver-frontend:latest` (Compose build) | Save/load as digest-pinned archives (`bash scripts/offline-bundle.sh`) |
| Postgres | `postgres:16` | Same; pin digest in `deploy/compose/docker-compose.digests.example.yml` |
| ClickHouse | `clickhouse/clickhouse-server:24.8` | Same |
| Wheelhouse / npm cache | `backend/wheelhouse/`, `frontend/npm-cache/` | Build with `docker build --build-arg OFFLINE=1` after `offline-bundle.sh` fills the caches |
| Migrations | Alembic in backend image | `alembic upgrade head` against the customer DB |
| Local maps / tiles | Host or volume mounts | Must resolve without CDN egress |
| Docs / runbooks | This tree | Copied into the bundle by `offline-bundle.sh` |
| Solver adapters + licences | `docs/solver-adapters.md` | Customer-provided; never downloaded by the platform |
| Checksums / signed manifest | `SHA256SUMS` from the bundle script | Verify before `docker load` |

Build on a networked host:

```bash
bash scripts/offline-bundle.sh          # → dist/offline-bundle/
# Optional: rebuild images from a local wheelhouse / npm cache
docker build --build-arg OFFLINE=1 -t solver-backend ./backend
docker build --build-arg OFFLINE=1 -t solver-frontend ./frontend
```

On the isolated host after transfer:

```bash
docker load -i solver-backend__latest.tar   # etc.
# fill digests in deploy/compose/docker-compose.digests.example.yml
docker compose -f docker-compose.yml -f deploy/compose/docker-compose.digests.example.yml up -d --no-build
bash scripts/egress-check.sh                # local smoke
EGRESS_BLOCKED=1 bash scripts/egress-check.sh   # also prove no public egress from backend
```

## Install sequence (isolated host)

1. Transfer the bundle (removable media or internal file share).
2. Verify checksums against the signed release metadata.
3. `docker load` each image; confirm digests match the manifest.
4. Copy `.env` from the sample; set secrets (`JWT_SECRET`, DB passwords,
   `SOLVER_SECRETS_KEY` if licences are stored).
5. `docker compose up -d` (or the customer override that uses digests).
6. `docker compose run --rm --no-deps -T backend alembic upgrade head`.
7. Smoke: login, open Home, apply a template, submit a run, open the guided view,
   view a map tile if maps are packaged, export a result.
8. Record the installed manifest (image digests, migration head, date).

## Update sequence

Verify bundle → disk space → backup (`scripts/backup.sh dump`) → rehearse
migrations on a copy → deploy coordinated API/worker/frontend versions → smoke →
record manifest. Rollback must respect schema compatibility (not only an older
image).

## Acceptance with egress blocked

Block outbound public networking on the host (or firewall the Compose network)
and confirm:

- [ ] No container attempts successful public HTTPS during smoke.
- [ ] Frontend loads (nginx static assets are local).
- [ ] API `/api/health` returns postgres (and clickhouse if required).
- [ ] FastAPI docs, if enabled, use only local assets or are disabled.
- [ ] Basemap / terrain / vector / font requests stay on the internal tile server.
- [ ] UI webfonts are bundled via `@fontsource/archivo` and
      `@fontsource/source-serif-4` (no Google Fonts link in `index.html`).
- [ ] Telemetry exporters are off or pointed at an internal endpoint.
- [ ] Commercial licence activation works under the isolation policy (customer-owned).

## ClickHouse dependency

Compose currently waits for ClickHouse health before starting the backend.
For an install that only needs planning (not analytics), operators may use a
documented override that makes ClickHouse optional — prefer degrading reporting
over blocking planning. Until that override is published as supported, treat
ClickHouse as required for the reference compose file.

## What is not yet done

- Dockerfile `pip install` / `npm install` are not replaced by offline wheelhouse
  COPY steps in the default Dockerfiles (development still builds online).
- Image digests are not pinned in `docker-compose.yml` tags (use a release
  override file when shipping a customer bundle).
- Automated egress-blocked CI on a clean VM is not yet a gate in `scripts/check.sh`.

Track progress under backlog **O01** / **O02**.
