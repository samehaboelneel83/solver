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
| Postgres | `postgis/postgis:16-3.4` | Same; pin via generated `docker-compose.digests.yml` (O04) |
| ClickHouse | `clickhouse/clickhouse-server:24.8` | Same |
| Digest Compose override | `scripts/render-digest-compose.sh` | Shipped in the bundle as `docker-compose.digests.yml` |
| Wheelhouse / npm cache | `backend/wheelhouse/`, `frontend/npm-cache/` | Required only if rebuilding app images on the isolated host; the bundle script ships prebuilt images and does not fill these caches |
| Migrations | Alembic in backend image | `alembic upgrade head` against the customer DB |
| Local maps / tiles | Host or volume mounts | Must resolve without CDN egress |
| Docs / runbooks | This tree | Copied into the bundle by `offline-bundle.sh` |
| Solver adapters + licences | `docs/solver-adapters.md` | Customer-provided; never downloaded by the platform |
| Checksums / signed manifest | `SHA256SUMS` from the bundle script | Verify before `docker load` |

Build on a networked host:

```bash
bash scripts/offline-bundle.sh          # → dist/offline-bundle/
# Includes digests.txt, image *.tar, docs, and docker-compose.digests.yml
# (OAAS O04 — filled pins, not REPLACE_ placeholders).
# Optional offline rebuild: first transfer/cache each Docker base image and
# populate the Python wheelhouse and npm cache. OFFLINE=1 skips apt; without a
# Pango-enabled PYTHON_BASE, PDF export uses the printable-report fallback.
docker build --build-arg OFFLINE=1 --build-arg PYTHON_BASE=python:3.12-slim -t solver-backend ./backend
docker build --build-arg OFFLINE=1 -t solver-frontend ./frontend
```

On the isolated host after transfer:

```bash
# verify SHA256SUMS, then:
docker load -i solver-backend__latest.tar
# …load the other archives…
docker compose -f docker-compose.yml -f docker-compose.digests.yml up -d --no-build
```

Acceptance on the isolated host:

```bash
EGRESS_BLOCKED=1 bash scripts/egress-check.sh
# or from a checkout with the stack up:
bash scripts/check.sh --isolated   # OAAS O05 — fails if stack down or egress open
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
- [ ] Basemap / terrain / vector / font requests stay on the internal tile server; `spatial.internet_basemaps`
      is false (the default since migration 0122), so no built-in internet map is offered.
- [ ] `LLM_BASE_URL` points inside the network and the egress check prints `OK: model reachable`.
- [ ] UI webfonts are bundled via `@fontsource/archivo` and
      `@fontsource/source-serif-4` (no Google Fonts link in `index.html`).
- [ ] Telemetry exporters are off or pointed at an internal endpoint.
- [ ] Commercial licence activation works under the isolation policy (customer-owned).

## ClickHouse dependency

ClickHouse is optional for planning (OAAS S01): compose waits only for the container to be started, the
backend serves without it, and `/api/health` reports it separately. Analytics degrade; planning does not block.

## The language model (the Assistant)

The Assistant talks to an OpenAI-compatible chat server named by `LLM_BASE_URL` and `LLM_MODEL` in `.env`
(today vLLM serving `qwen3.5` on the LAN). It is **not in the bundle**: run it on the same host or inside the
network, never on the public internet. Everything else — the editor, the solvers, maps, exports, the API — works
without it; the Assistant alone then answers "cannot reach the model at …" and the person uses the editor.
`bash scripts/egress-check.sh` probes the model from inside the backend container and prints OK or WARN.
One slow reply is cut at `LLM_REPLY_SECONDS` (420 s) and asked again shorter; a model that never answers ends
the turn with that message, never the platform.

## What is not yet done

- Offline rebuilds need locally available base images plus populated
  `backend/wheelhouse/` and `frontend/npm-cache/`. Backend `OFFLINE=1` skips
  apt; PDF export needs a Pango-enabled `PYTHON_BASE` or uses its printable
  fallback. Release bundles use prebuilt app images and do not need build caches.
- Main `docker-compose.yml` stays tag-based for development; customer releases
  use the generated `docker-compose.digests.yml` from the offline bundle (O04).
- `scripts/check.sh --isolated` (O05) is the hard egress gate when validating an
  isolated host; plain `check.sh` still skips egress when the stack is down.

Track progress under backlog **O01**–**O05**.
