# Authenticated ingestion service

This increment adds migration 0085, authenticated connection/job endpoints and a
separate ingestion worker. Epic UX (U-4, migration 0089) adds the connection UI,
job history, preview, column mapping, row-level validation and a one-time load
with lineage (see "From extraction to domain data" below). CDC and result
write-back remain out of scope.

## Scope and credentials

Connections belong to one domain. The API checks organization ownership and the
database applies row-level security inherited through the domain. Capabilities
are organization-wide, consistent with existing IAM: `integration.manage` creates,
rotates or disables connections; `integration.run` reads connections and submits,
reads or cancels jobs. Existing Admin roles receive both in migration 0085.
Per-user/per-domain connection grants are not implemented. A capability-limited
API key must itself have the required capability.

Credentials are AES-256-GCM envelopes. Associated data binds ciphertext to the
organization and connection ID. APIs never return credential envelopes, passwords
or encryption keys. Audit records identify actions without credential contents.
Source metadata such as hostname and username is visible to integration readers.

## Operator configuration

Use a private environment file outside the repository, readable only by the
deployment operator. Supply these values to both API and ingestion worker:

| Setting | Meaning |
|---|---|
| `OAAS_INTEGRATION_KEYS` | JSON object mapping key IDs to base64-encoded random 32-byte AES keys |
| `OAAS_INTEGRATION_ACTIVE_KEY` | Key ID used for new encryption and credential rotation |
| `OAAS_INTEGRATION_NETWORKS` | Comma-separated approved internal CIDRs; no default permission |
| `OAAS_INTEGRATION_CA` | CA certificate path inside the container, e.g. `/integration-certs/source-ca.pem` |

Generate keys locally with a cryptographic random generator. Do not reuse the
JWT signing key. Protect the environment file and backups; loss of old keys makes
their existing credential envelopes unreadable. Rotation: add a new key, switch
the active ID on API and worker, re-save credentials through the rotation endpoint,
then retire an old key only after no retained/live envelopes require it. Rotation
does not retroactively change credentials already loaded into a running child.

The Docker overlay `deploy/compose/integrations.yml` mounts a private artifact
volume and local trust certificates, and starts a separate worker with a 2 GiB
container ceiling. Each Linux extraction child additionally has a 1 GiB address
space ceiling; the supervisor terminates extraction after 330 seconds. Set
`OAAS_INTEGRATION_ENV_FILE` and `OAAS_INTEGRATION_CERT_DIR` to existing private
host paths when using that overlay. Never print resolved Compose configuration
with secrets into logs. Runtime keys are not included in offline image bundles.

Build the updated backend from the approved offline dependency bundle, migrate to
0085 as the database owner, then start the API and dedicated worker with the
overlay. This implementation did not migrate or restart the running installation.
The new direct cryptography dependency is pinned to 50.0.1, verified present in
the local backend image used for container tests; offline bundle generation must
carry that pinned wheel and its dependencies.

## API workflow

1. `POST /api/v1/connections`: provide `domain_id`, `name`, `password`, and `source`
   containing `host`, `port`, `database`, `username`, `schema`, `table`, `columns`.
   The server supplies network, TLS and timeout policy. No raw SQL is accepted.
2. `GET /api/v1/connections?domain_id=...&limit=50&offset=0`: metadata only.
3. `POST /api/v1/connections/{id}/jobs`: returns a persisted queued job and HTTP
   202. At most one queued/running job per connection; duplicates return 409.
4. `GET /api/v1/ingestion-jobs/{id}`: state, times, safe error code and artifact ID.
5. `POST /api/v1/ingestion-jobs/{id}/cancel`: requests cancellation; the worker
   acknowledges it. `POST /api/v1/connections/{id}/disable` blocks new submissions
   and requests cancellation of existing jobs.
6. `PUT /api/v1/connections/{id}/credential`: rotates the encrypted credential.

Jobs have `queued`, `running`, `extracted`, `failed` or `cancelled` states.
`extracted` means a raw artifact needs mapping and quality validation, not that it
is safe to solve against. No artifact-download API is exposed in this milestone.

## Failure and recovery

Claims use PostgreSQL `FOR UPDATE SKIP LOCKED`; completion requires the same
attempt UUID. A cancellation/disable visible at completion overrides success.
A supervisor-lost job older than ten minutes becomes `failed` when another worker
polls. There is no automatic replay; inspect its state before submitting again.

Abrupt termination or a cancellation race can leave an unreferenced completed
artifact or `.pending-*` staging folder. Application consumers must use the
artifact ID of a successfully extracted job, not enumerate files as approved
datasets. Artifact garbage collection, retention and crash reconciliation remain
follow-up work. Back up the artifact volume, application database and keyring as
one recovery procedure; the existing database-only backup is insufficient.

The worker authorizes source scope, checks whether the connection remains enabled,
and applies operator network policy. Jobs are authorized on submission; revoking
the submitter's role/key alone does not cancel already submitted work. Disable the
connection or cancel its jobs to revoke pending execution.

Connection lists are paginated and each connection's job history is listed
(`GET /api/v1/connections/{id}/jobs`). Editing/re-enabling a connection, finer
connection grants and live source certification remain follow-up work. Domain deletion is blocked while it owns connections.


## From extraction to domain data (Epic UX, U-4)

The API reads artifacts through `OAAS_INTEGRATION_OUTPUT`, mounted **read-only**
into the backend by `deploy/compose/integrations.yml`. Without it, preview,
validation and load answer 409 with the reason.

1. `GET /api/v1/ingestion-jobs/{id}/preview?limit=20` (`integration.run`): the
   manifest's columns and source schema, the row count and the first rows.
2. `POST /api/v1/ingestion-jobs/{id}/validate` (`integration.run`):
   `{"entity_type_id": 9, "columns": {"staff_id": "key", "full_name": "label", "hours": "hours"}}`.
   Every row goes through the bulk-upload code (types, then the database's rules
   in a savepoint), all rolled back. Faults are `{row, column, message}`: the n-th
   extracted row, `source → target`; a mapping fault is row 0. The report is
   stored in `import_validation` with the artifact's SHA-256 and the mapping hash.
3. `POST /api/v1/ingestion-jobs/{id}/load` (`integration.run` and `domain.edit`):
   `{"validation_id": 5}`. Only a clean validation; the rows are re-read and their
   SHA-256 checked against the manifest and the validation; written in one
   transaction with an `import_load` row (artifact SHA-256, mapping hash, rows
   written) and an audit entry. A second load of the same job and mapping is 409.
   If the domain changed since validation and a row no longer loads, nothing is
   written and the faults are returned.

The next run's `snapshot_dataset()` freezes the loaded records like any other;
`import_load` says which extraction and mapping they came from. In the UI:
Domain → Data → Sources & imports → Extractions → Import….
