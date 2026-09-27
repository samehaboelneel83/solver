# Database integration contract, revision 1

Status: experimental PostgreSQL adapter and local operator runner, 27 September
2026. No native database connector is certified or exposed through an API.

## Implemented boundary

`backend/app/integrations/contracts.py` defines connector capabilities, a snapshot
request, positive extraction budgets and a streaming batch boundary. Batches are
immutable UTF-8 JSON lines. Schema mismatch, nonfinite values and integers beyond
the JavaScript exact-integer range fail extraction; adapters must encode sensitive
numeric values losslessly under a declared schema. Cancellation and consumer
abort close the iterator. Driver errors are replaced with safe public messages.

These batches are uncommitted staging artifacts. The caller must consume the
entire extraction successfully and validate its complete dataset before publishing
anything. A yielded batch is not a checkpoint, successful job, or dataset snapshot.

## Required next layer

1. Authorize organization, connection and domain grants before opening a driver.
2. Resolve locally encrypted credential references inside an isolated worker.
   Credentials never belong in extraction requests, logs or manifests.
3. Validate source endpoints against the installation's internal network policy;
   configure TLS trust and read-only source permissions.
4. Certify the implemented PostgreSQL adapter with quoted identifiers, explicit
   columns, bounded server cursor, TLS verification, read-only repeatable-read
   transaction, source statement timeout and connection timeout. No arbitrary SQL.
5. Extend the implemented atomic extraction artifacts with mapping/business
   validation and application metadata before publishing usable dataset snapshots.
6. Publish model bindings and lineage that reference the exact manifest version.

The Python batch helper cannot interrupt blocking driver I/O, bound a driver's
prefetch buffer, or prevent allocation of one oversized row. Driver limits and
worker process memory/deadline enforcement remain mandatory before API exposure.
The adapter adds query timeouts, cancellation monitoring and a total extraction
deadline; a supervised process is still required for hard resource bounds.
It does not implement scheduling, retries, incremental checkpoints, CDC, write-back,
or tenant authorization. Those are separate job-service responsibilities.

The local runner accepts operator-owned configuration and a secret environment
reference. See [pilot runbook](../runbooks/database-extraction.md). The contract's
organization ID is a UUID, matching the existing IAM model.

## Certification gates

Certify engine version, driver, operating system and authentication combination
against a local test database. Include decimals, large IDs, Unicode, nulls, time
zones, schema changes, cancellation, connection loss, source load and isolation.
Incremental and publication capabilities stay false until their own restart,
deletion and reconciliation cases pass. Generic ODBC/JDBC support must pass the
same gates and must not be labeled universal compatibility.

Pure foundation tests run without a database or migrations:

```powershell
cd D:\solver\backend
python -m unittest discover -s integration_tests -v
```
