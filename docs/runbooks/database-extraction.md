# Offline PostgreSQL extraction pilot

Status: operator tool with a verified local PostgreSQL 16/TLS extraction path.
The authenticated service is now deployed separately; see
[operational evidence](ingestion-operational-check.md). Broader database/version
certification and optimization-ready dataset publication remain outstanding.

## Prepare

Use an operator-owned configuration file and output directory protected by OS
permissions. The tool runs with that operator's authority. Organization IDs in
the file are provenance/scope checks, not a login or grant of application access.
Do not accept these files or paths from untrusted users.

Configure a dedicated source login with SELECT on the required table/view only.
Supply a local trusted CA file and a certificate matching the configured host.
TLS verification is mandatory. Restrict networks to the narrow internal ranges
needed for this source; public egress should remain blocked by installation policy.

Example operator configuration (replace placeholders with actual installation values):

```json
{
  "organization_id": "00000000-0000-0000-0000-000000000001",
  "connection_id": 1,
  "host": "planning-db.internal",
  "port": 5432,
  "database": "operations",
  "username": "oaas_reader",
  "secret_ref": "OAAS_SOURCE_PASSWORD",
  "schema": "planning",
  "table": "staff",
  "columns": ["staff_id", "hourly_cost"],
  "allowed_networks": ["10.20.30.0/24"],
  "root_certificate": "D:/oaas-private/certs/source-ca.pem",
  "connect_timeout_seconds": 10,
  "statement_timeout_ms": 30000,
  "extraction_timeout_seconds": 300
}
```

Provision `OAAS_SOURCE_PASSWORD` in the process environment through the site's
secret-handling process. Do not put a password in the JSON, command arguments,
repository or shell history. Environment references are a pilot mechanism; an
encrypted, authorized application secret store remains to be implemented.

## Run

From the backend directory, with its existing offline Python dependencies:

```powershell
python -m app.integrations --config D:/oaas-private/source.json --output D:/oaas-private/extractions --max-rows 100000 --max-bytes 20971520 --batch-rows 1000
```

The command emits the completed artifact path. Ctrl+C requests cancellation.
Data remains local. No command has been run against a real source as part of
this implementation.

## Inspect and interpret

The artifact contains `rows.jsonl` and `manifest.json`, partitioned under the
organization and connection IDs. Check byte count, row count and SHA-256 before
downstream consumption. Its status is `extracted_requires_mapping_validation`.
Do not use it directly as an approved model input.

Decimals and integers outside JavaScript's exact range are encoded as strings;
date/time values use ISO 8601, and UUID values use strings. PostgreSQL column OIDs
are recorded. Mapping must still establish destination types, time-zone rules,
units, keys, relationships and model coverage. Unsupported values fail instead
of silently coercing. This is single-source repeatable-read extraction, not a
cross-database atomic snapshot. Physical row order is unspecified; hashes describe
the exact artifact, not a canonical ordering of the source table.

## Failures and limits

An ordinary failure deletes only that invocation's temporary directory. Earlier
artifacts remain intact; a retry creates a new artifact, never overwrites one.
There is no incremental resume or automatic retry. Readers must ignore
`.pending-*` directories left by abrupt process/host termination. Recovery and
retention cleanup need a separately authorized operational process.

Source query timeouts and cancellation bound normal database operations. DNS,
driver cancellation itself, large individual values and source prefetch still
require a supervised worker process with hard memory/time limits before production
API exposure. Local filesystem rename publishes complete artifacts atomically;
power-loss durability and network filesystem semantics need installation testing.

No schema discovery, mapping UI, scheduler, app grants/RLS, encrypted credential
store, CDC, write-back or real-engine certification is implied by this pilot.
