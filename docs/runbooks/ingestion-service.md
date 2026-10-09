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

## Failure classes (October 2026)

A failed job records one safe class in `error_code`, never driver text: `authentication_failed`, `tls_failed`,
`source_unreachable`, `network_not_allowed`, `source_missing`, `not_permitted`, `trust_unavailable`,
`credential_unreadable`, `deadline_exceeded`, `limit_exceeded`, `format_invalid` (web sources), `worker_lost`, or
`extraction_failed` when nothing more specific is known. The Sources page explains each.

## Web sources (HTTPS)

`source` may instead be `{"kind": "http", "url": "https://…", "format": "json" | "csv" | "xlsx", "columns": [...],
"auth": "none" | "bearer" | "basic" | "oauth_client", "username"?, "sheet"?, "records_at"?}`: a REST endpoint's JSON list (at the
dotted path `records_at`, e.g. `data.items`), or a CSV or Excel file served over HTTPS. The same policy applies as
for a database: the host must resolve inside `OAAS_INTEGRATION_NETWORKS`, TLS is verified (against
`OAAS_INTEGRATION_CA` when set), redirects are not followed, the answer is capped at 20 MB. A token or password is
encrypted like a database password; `auth: "none"` needs no `password`. A database view is read like a table; raw
SQL is still not accepted -- define a view for a query.

A JSON answer in pages is read whole with `paging` (8 October 2026): `"next_link"` follows the next page's address in
the answer at `next_at` (`next`, `links.next`, `@odata.nextLink`; a relative address is taken from the page it is
on), `"link_header"` follows `Link: <…>; rel="next"`, and `"page_number"` sets `page_param` (from `first_page`,
default 1) until a page is empty. Every page is read under the policy above; the next address must stay on the
source's host over https (else `network_not_allowed`), the 20 MB cap is for all pages together, at most 1,000 pages
are read (`limit_exceeded`), and an address seen twice ends the reading.

Only what changed (migration 0118): a database source may name `changed_column`, one of its columns that grows when
a row changes (an update time or a version number). Every read of such a source keeps the column's highest value in
its manifest (`high_water`); `POST /api/v1/connections/{id}/jobs {"incremental": true}` then reads only the rows
whose value is at least that (`>=`, so rows stamped in the same instant are read again rather than lost; the mark is
bound as a parameter, a time as a datetime and a number as a number, for every engine). A refresh from such a read
adds and updates records and values but takes nothing away: a row it did not read is unchanged, not gone. Read the
source whole now and then to find what was deleted. With no earlier mark, an incremental read is a whole one.

Notices (migration 0119): a scheduled refresh that found changes to review, applied changes (and queued runs), or
could not finish leaves a notice for the person who set it, shown under the bell in the app's header
(`GET /api/v1/notices`, `POST /api/v1/notices/{id}/read`, `POST /api/v1/notices/read-all`).

Sign-in by OAuth 2 client credentials (9 October 2026): `"auth": "oauth_client"` with `token_url` (https), `client_id`,
optional `scope` and `audience`, and `client_auth` (`"basic"`, the default, or `"post"`: the secret in the form); the
client secret is the source's credential (`password`), encrypted like any. Each extraction exchanges it at the token
address for an access token (grant `client_credentials`) and reads with it as a bearer token. The token address is
read under the same policy as the data -- https, inside `OAAS_INTEGRATION_NETWORKS` (it may be another host there),
verified TLS, no redirects, an answer of 64 KB at most. A token refused mid-read (401) is renewed once, then the
refusal stands (`authentication_failed`); a token address that refuses the client, gives no bearer token or cannot be
reached fails with the usual classes. The token is never stored.

Several tables as one source (9 October 2026): a database source may name `more_tables` (up to 20), each
`{"table", "columns", "changed_column"?}` in the same database and schema. One extraction reads them all into one
artifact, a sheet per table (`rows.jsonl`, then `rows-2.jsonl`, ...; the manifest's `tables` lists them, each with its
own rows, digest and `high_water`). The import preview takes `?table=` and names `tables`; a mapping names its `table`
(the first when left out), so each table is imported, bound and refreshed on its own, and an incremental read takes
each table from its own mark.

## Database engines (plan of 8 October 2026, phase 4A)

A database source names its `engine`: `postgres` (default), `mysql` (MySQL and MariaDB), `sqlserver` or `oracle`;
`port` defaults to the engine's usual one (5432, 3306, 1433, 1521). For Oracle, `database` is the service name and
`schema` the owner; for MySQL, `schema` is the database the table is in. The drivers need no system libraries:
PyMySQL, pymssql (FreeTDS inside its wheel) and python-oracledb in thin mode (no Oracle client).

Every engine keeps the PostgreSQL contract: the host must resolve inside `OAAS_INTEGRATION_NETWORKS` before any
credential is used; TLS is required and verified against `OAAS_INTEGRATION_CA` by host name; only
`SELECT <columns> FROM <schema>.<table>` is sent, with quoted identifiers; a statement timeout and the worker's
deadline bound it; failures become the same classes. MySQL is reached on the checked address. SQL Server and Oracle
drivers open their own connection by host name; TLS ties the answer to the certificate for that name. A read-only
transaction is used where the engine has one (MySQL, Oracle); on SQL Server, give the login read permission only
(`db_datareader`, or SELECT on the tables).

## The Assistant, bindings and refresh (migrations 0114, 0115)

- `describe_workspace` lists `data_sources` (to `integration.run`) and `files` kept in the workspace.
- `use_source` attaches a source's latest (or a fresh) extraction, or a kept file, as a sheet; a plan loads it with
  `*_from_file`.
- A build records a `source_binding` for every `*_from_file` entry that read a source or an attached file: the
  connection or the workspace file (kept by version in `workspace_file`), the mapping, and the extraction or version
  used.
- `GET /api/v1/domains/{id}/source-bindings`, `GET|POST /api/v1/domains/{id}/files`,
  `GET /api/v1/domains/{id}/files/{name}?version=`.
- `POST /api/v1/domains/{id}/sources/refresh` `{"jobs"?, "files"?, "connections"?, "apply": false,
  "remove_missing": true}` compares the newest (or named) extraction / file version with what the domain holds:
  records added, fields changed (before -> after), records gone, links and values added / changed / gone. With
  `"apply": true` (needs `domain.edit`) it writes all of it in one transaction; records a source no longer has are
  set inactive, not deleted. The Assistant's `refresh_sources` reports first, asks, and applies exactly what it
  reported; the Sources page has the same ("Check for changes", "Apply these changes", "Add a new version").
- Only data loaded from a source is refreshed: a number typed into a plan is not. The Assistant is told to take
  every number a source holds from the source.
