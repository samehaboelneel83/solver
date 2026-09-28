# Operational ingestion verification — 27 September 2026

## Installed state

The API and dedicated ingestion worker are configured and running. Private
material lives outside the Git repository at `D:/solver-private/ingestion`, with
Windows access restricted to the current operator and SYSTEM. No keys or
passwords are stored in this document or committed source.

- `integration.env`: local encryption keyring and source network/TLS policy.
- `trust/source-ca.pem`: public CA certificate, mounted read-only by the API/worker.
- `authority/ca.key`: private CA key; never mounted into application containers.
- `server/`: reference database certificate and key, mounted only by that source.
- `source.env`, `reader.json`: reference database credentials.
- `compose.env`: private-file paths used by Compose; contains no credentials.

The reference source is a separate PostgreSQL 16 container with synthetic capacity
data. It has no published host port and uses an internal Docker network. The
ingestion allowlist permits only its fixed address, `172.29.89.2/32`. Business
sources require their own trusted CA, endpoint policy and least-privilege login;
this verification does not claim an arbitrary business database is connected.

## Evidence

| Check | Result |
|---|---|
| Verification domain | 203, `Ingestion verification` |
| Connection | 1, `Local TLS reference` |
| Authenticated API submission | Job 1 accepted and processed by the dedicated worker |
| Final job state | `extracted`, no error code |
| Source TLS | TLS 1.3 with hostname and CA verification |
| Source permissions | Transaction read-only; INSERT privilege absent |
| Artifact | 3 rows; SHA-256 and byte count verified against manifest |
| Decimal values | `12.2500`, `9.5000`, `14.1250` preserved exactly |
| Platform after rollout | Frontend-proxied API health returns PostgreSQL/ClickHouse `ok` |

Artifacts remain `extracted_requires_mapping_validation`; no business mapping or
optimization-ready dataset was fabricated. The sample connection is intentionally
visible as a reference configuration, separate from existing planning domains.

## Restart or update consistently

From `D:/solver`, retain both integration overlays when updating the backend:

```powershell
docker compose --env-file .env --env-file D:/solver-private/ingestion/compose.env -f docker-compose.yml -f deploy/compose/integrations.yml -f deploy/compose/ingestion-reference.yml up -d --no-build --pull never backend ingestion-worker ingestion-reference
```

Using only the base Compose file to recreate the backend removes its integration
configuration. Do not print resolved Compose configuration: it contains runtime
secrets. Keep the private keyring and reference certificates in the installation's
protected backup procedure alongside application data and artifact volumes.

`scripts/prepare-ingestion-reference.py` creates new private material only in an
empty directory. Never re-run it over the installed keyring or replace keys as a
troubleshooting step. Credential rotation is documented in `ingestion-service.md`.
The leaf certificate has a one-year validity; renew it using the protected local
CA before expiry, preserving hostname verification.

## Solver finding

Run 589 failed because its explicit `pso` choice lacks required connectivity and
integrality capabilities. A subsequent existing run, **590**, already solved the
same scenario **246** and frozen dataset **154** using **CP-SAT**, reaching
**optimal** with objective **2564**. This was verified before creating any new run;
no duplicate solve was needed. The failed run was preserved rather than rewritten.
Use automatic selection or a compatible exact solver for this model. PSO is not
silently substituted when explicitly requested.
