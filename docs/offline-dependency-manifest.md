# Offline dependency manifest (OAAS O01)

Inventory of runtime and build dependencies for an isolated install.
Status values: **bundled** (ships in our image), **pull-at-build** (needs network
during image build), **external** (operator-supplied), **optional**.

## Compose services (reference)

| Service | Image / build | Status | Notes |
|---|---|---|---|
| postgres | `postgis/postgis:16-3.4` | pull-at-build / bundle | Pin digest in customer release |
| clickhouse | `clickhouse/clickhouse-server:24.8` | pull-at-build / bundle | Health-gated backend start today |
| backend / worker | `solver-backend:latest` from `backend/Dockerfile` | pull-at-build | `pip install -r requirements.txt` in Dockerfile |
| frontend | `solver-frontend:latest` from `frontend/Dockerfile` | pull-at-build | `npm install` then nginx alpine |

## Backend Python (`backend/requirements.txt`)

Installed into the backend image at build time. Offline rebuilds need a
wheelhouse or a pre-built image. Solvers (OR-Tools, HiGHS, SCIP, IPOPT, …)
come from that install; commercial engines are **external** (customer licence +
adapter under `/opt/solver/adapters`).

`scikit-learn` (with its `joblib` and `threadpoolctl`) is part of that install since
Epic ML (2026-09-28): it trains predictors (`app.ml.train`) and the run-time estimate
(`app.ml.eta`). An offline wheelhouse must carry it; nothing is fetched at run time.

## Frontend Node (`frontend/package.json`)

Installed at frontend image build (`npm install`). Runtime is static files in
nginx — no Node at serve time. UI fonts (`@fontsource/archivo`,
`@fontsource/source-serif-4`) are npm dependencies bundled into the Vite build
(OAAS **O03**); there is no Google Fonts (or other CDN) link in `index.html`.

## Maps / tiles

Local tile configuration and Egypt basemap assets (see `frontend/src/lib/tiles.ts`,
`useBasemaps`). Must not fall back to a public CDN when offline.

## Identity

Default: local username/password. OIDC/SCIM (R35/R36) require an IdP reachable
**inside** the isolated network — cloud-only IdPs are unsuitable as the default.

## Backups / recovery

| Asset | Location | Offline note |
|---|---|---|
| Postgres dumps + WAL | `SOLVER_BACKUP_DIR` (default host `../solver-backups`) | Keep a copy outside the primary host failure domain |
| Encrypted solver licences | DB + `SOLVER_SECRETS_KEY` / JWT-derived key | Back up the secrets key separately (`docs/runbooks/backups.md`) |

## Operator procedures (already local)

- `docs/runbooks/workers.md`
- `docs/runbooks/backups.md`
- `docs/runbooks/offline-install.md`
- `scripts/backup.sh`, `scripts/check.sh`

## Release checklist for a customer bundle

1. Build backend + frontend images from a clean tag.
2. `docker images --digests` and record digests for app + postgres + clickhouse.
3. `docker save` those digests to archives; checksum the archives.
4. Include this manifest, offline-install runbook, problem-IR contract, and
   coverage matrix (`docs/coverage-acceptance-matrix.md`).
5. Include sample `.env` without secrets; document required secrets.
6. Confirm the smoke list in `offline-install.md` on a host with egress denied.
