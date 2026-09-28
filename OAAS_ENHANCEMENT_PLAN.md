# OaaS enhancement and database integration plan

**Date:** 27 September 2026  
**Status:** Proposed implementation plan; no capabilities in this document should be treated as delivered unless explicitly identified as existing.  
**Environment:** Isolated installation, with access only to authorized internal systems.  
**Companion:** [Original platform proposal](OAAS_PLATFORM_PROPOSAL.md).

### Implementation progress — 27 September 2026

The first implementation slice is complete:

- ENH-02, partial: global, domain and problem routes now have distinct sidebar groups. Legacy pages retain compatibility navigation and the command palette keeps the destination catalog. Inputs, Checks and other proposed destinations are not represented as implemented pages.
- ENH-03, partial: explicit domain routes resolve by ID instead of searching the first 500 domains. Header, overview and selector can display the selected domain beyond the first list page. Searchable selection across all domains and browser Back/Forward draft protection remain outstanding.
- ENH-04, partial: added the Python snapshot-extraction contract and bounded streaming batches, plus a [contract and certification boundary](docs/contracts/database-integration.md). No live connector, credentials API, scheduler or write-back is delivered by this foundation.

Validation: **2,200 frontend tests pass**, TypeScript and full ESLint pass, and **10 isolated Python integration-contract tests pass** without database access or migrations. The production build passes with the existing large-bundle and mixed-import warnings. No public-network dependencies were added. Live browser acceptance and live-database certification remain outstanding.

### Second implementation increment — PostgreSQL extraction pilot

- Added an experimental read-only PostgreSQL adapter with scope/source checks, quoted identifiers, permitted-network validation, verified TLS, server-side cursor, timeouts and cancellation monitoring.
- Corrected the integration organization identifier to UUID to match existing IAM. Added lossless decimal/large-integer conversion and source-column OIDs.
- Added atomic local extraction artifacts with counts, checksum, source metadata and timestamps. Partial failures clean up their own staging output and preserve prior artifacts. Artifacts explicitly require mapping validation before optimization use.
- Added an operator-only offline command and [runbook](docs/runbooks/database-extraction.md). Passwords resolve from a worker environment reference; this is not the planned encrypted application credential store.
- Validation: **17 isolated integration tests pass**, including mocked driver behavior, scope refusal before credential resolution, network rejection, SQL identifier construction, precision preservation, artifact integrity and failure cleanup. Command help runs locally. No live source database was contacted, and no engine/version combination is certified yet.

### Third implementation increment — authenticated ingestion service

- Migration 0085 adds domain-owned connections and persisted ingestion jobs with tenant-inheritance triggers, row-level security and one active job per connection.
- Dedicated `integration.manage` and `integration.run` capabilities protect the API. AES-GCM credential envelopes are bound to organization/connection identity; create, rotate, disable, submit, status and cancel endpoints do not expose credentials.
- A separate worker claims jobs with row locking, supervises extraction children, enforces time/memory bounds, handles cancellation and fences completion with attempt UUIDs. Expired supervisor attempts become failed without automatic replay.
- Added an opt-in Compose overlay and [service runbook](docs/runbooks/ingestion-service.md). Capabilities remain organization-wide; finer per-user/domain grants and a mapping interface are outstanding.
- Validation: **37 PostgreSQL-backed tests pass** across ingestion, tenancy and API keys in a disposable isolated container; **19 pure integration tests pass**. Python compilation, Compose configuration validation and diff checks pass. Tests found and fixed a nullable-UUID settlement query and test API-key cleanup.

Latest live verification: ingestion is now configured and operational against a separate local PostgreSQL 16 sample source. Authenticated job 1 extracted three rows over verified TLS 1.3; checksum, decimal precision and read-only source permissions pass. The private keyring and certificates are outside the repository, and the dedicated worker is running. Frontend/API health remains good. Run 589's failed PSO selection already has a successful replacement: run 590 used CP-SAT on the same scenario/dataset and reached optimal objective 2564. See the [operational evidence and restart procedure](docs/runbooks/ingestion-operational-check.md).

Next milestone: onboard the installation's actual business database, broaden connector certification beyond the verified local PostgreSQL path, and build connection/mapping/validation screens and validated dataset publication. The full delivery roadmap below remains active; these increments do not mark it complete.

## 1. Outcome and priorities

Build a platform that lets a planner connect operational data, define a decision, compare feasible alternatives, and deliver an approved plan with reproducible evidence. Prioritize the time from usable data to an accepted decision, alongside solver speed and solution quality.

The intended differentiators are:

1. A readable, contextual navigation tree and guided planning workflow.
2. Reusable integration with internal databases and business applications.
3. Verified optimization results with useful explanations and stable re-planning.
4. Measured performance on chosen workload families.
5. Complete installation, operation, recovery, and upgrades without public internet.

“Outperform” is an acceptance target, not an existing market claim. No platform can solve every mathematical problem or beat every competing solver on every instance. Select reference workloads and publish reproducible comparisons. Likewise, support for “any database” means an extensible adapter contract plus a tested compatibility catalog, not automatic compatibility with every product, version, data type, or authentication mode.

This plan uses local repository evidence. It does not provide a current external competitor ranking or externally verified database-driver compatibility assessment.

## 2. Starting point

| Area | Observed foundation | Next investment |
|---|---|---|
| Navigation | Shared registry, scoped domain/problem routes, overview pages, ownership checks | Distinct contextual sidebars, remaining canonical links, draft-safe browser navigation |
| Frontend verification | Previous implementation increment recorded 2,194 passing tests, type/lint/build checks | Browser accessibility and offline end-to-end acceptance; bundle reduction |
| Bulk data | `backend/app/api/bulk.py` supports CSV/XLSX templates, validation, dry run, and row errors | Reuse validation semantics in asynchronous database ingestion |
| Bulk limits | Current importer defines 100,000 rows and 20 MiB per file | Separate streaming ingestion path with measured limits |
| Database infrastructure | SQLAlchemy/PostgreSQL application storage; ClickHouse client dependency | External source abstraction, separate credentials, extraction jobs and source contracts |
| Optimization | Shared IR, multiple solver paths, scenario/run infrastructure and verification foundations | Coverage certification, explanations, workload-specific tuning and benchmark gates |
| Release | Existing offline proposal and operational scripts | Clean-host evidence, signed bundles, driver/license inventory and restore drills |

An application database dependency is not evidence of a supported external connector. The inspected paths did not reveal a general connector framework; confirm this inventory before creating new modules. Audit the current implementation before reimplementing any roadmap feature.

## 3. Navigation: first product milestone

Show one context at a time. Keep the organization, domain, and problem in the header; use descriptive names, with technical IDs in secondary details. Hide destinations that the user cannot access, and enforce the same permissions on the server.

```text
Global
├── Home
├── Domains
├── Template library
├── Operations                 [operator]
├── Administration             [administrator]
└── Help

Domain: Workforce
├── Overview
├── Problems
├── Data
│   ├── Datasets
│   ├── Records
│   ├── Relationships
│   ├── Parameters
│   └── Map & graph
├── Integrations               [data steward]
│   ├── Connections
│   ├── Import pipelines
│   ├── Sync history
│   └── Publication targets
└── Structure                  [modeler/data steward]
    ├── Record types
    └── Relationship types

Problem: Weekly staffing
├── Overview
├── Inputs
├── Model
├── Scenarios
├── Runs & results
├── Compare
├── Quality checks
└── Approved plans
```

### Interaction requirements

- Problem overview answers: what decision is being made, who owns it, whether inputs are current, what prevents a solve, and what to do next.
- Inputs shows the exact dataset snapshot, mapping version, units, validation errors, freshness and source lineage. It does not expose credentials.
- Use a single run detail with Summary, Decisions, Explanations, Comparison, and Technical details. Preserve filters and selected tabs in shareable URLs.
- Keep ordinary planning actions visible; place solver parameters, raw IR and SQL in advanced views.
- Provide actionable empty/error states: identify the missing requirement and link to the page that resolves it.
- Complete browser Back/Forward draft protection and direct object lookup beyond the first page of lists.
- Support keyboard navigation, visible focus, meaningful labels, narrow screens, and status indicators that do not depend only on color.
- Persist a saved draft separately from a published model. A failed save must never appear successful.

### Navigation acceptance

At least 90% task completion in a pilot with planners, modelers and operators. At least 8 of 10 first-time pilot users complete a bundled planning example within ten minutes. Test unauthorized URLs, missing objects, cross-domain links, more than 500 domains, refresh, new tabs, Back/Forward, and failed API requests. These are proposed release targets, not measured results.

## 4. Database integration product

### 4.1 Supported connection strategies

| Strategy | Intended use | Delivery order | Boundary |
|---|---|---|---|
| Native relational adapters | PostgreSQL first; then SQL Server and MySQL/MariaDB according to installation demand | Initial releases | Certify each engine/version/authentication combination independently |
| Enterprise adapters | Oracle and other named enterprise databases | Demand-led | Drivers, redistribution rights and a representative customer test system are prerequisites |
| ODBC adapter | Internal relational systems with available ODBC drivers | After native contract stabilizes | A common interface does not guarantee equivalent semantics or performance |
| JDBC bridge | Systems requiring a Java driver | Optional later release | Separate local process/service; package the JVM and drivers offline |
| File ingestion | Existing CSV/XLSX; proposed Parquet, JSON and SQLite import | Early | Validate size, schema, encoding and supported type conversions |
| Internal APIs | Approved REST endpoints or business-system export APIs | After relational ingestion | Pagination, rate limits, authentication and snapshots need source-specific contracts |
| Document/graph/time-series adapters | Named customer use cases | Later | Explicit projection into optimization entities, relationships and parameters |
| Customer adapter SDK | Systems not in the certified catalog | After two native connectors | Must pass the same conformance and isolation checks |

Do not install arbitrary drivers at runtime. Maintain statuses of **certified**, **experimental**, and **unsupported**. A missing driver or unsupported type should be visible before an import starts.

### 4.2 Connection workflow

1. Select a connector from the locally installed catalog.
2. Enter internal address, database, authentication and trust settings. Store a secret reference, never a password inside pipeline JSON.
3. Test connectivity using a limited read-only identity; report DNS, TLS, authentication and permission failures distinctly.
4. Browse only permitted schemas, tables and views. Preview a bounded sample with sensitive columns masked where required.
5. Choose source objects or an approved parameterized query.
6. Map source fields into domain records, relationships and parameters.
7. Preview converted values, joins, rejected rows and estimated volume.
8. Validate the complete staged import, then publish an immutable dataset snapshot.
9. Set manual or scheduled refresh and an explicit freshness policy.
10. Link the snapshot to problem inputs; run optimization against that frozen input.

Provide reusable mapping templates for workforce, routing, production and allocation, selected according to real installation priorities. Include example data and explanations offline.

### 4.3 Proposed architecture

```text
Internal source database / file / API
                |
      Isolated connector worker
                |
   Bounded extraction and staging
                |
  Versioned mappings and validation
                |
     Immutable dataset snapshot
                |
   Scenario + model version + policy
                |
        Optimization workers
                |
     Independently checked result
                |
       Business plan approval
                |
   Optional publication worker ---> approved internal target
```

Keep the platform's PostgreSQL storage architecture initially. Connecting to Oracle or SQL Server must not require moving the platform's own persistence layer. Keep connector pools and workers separate from API and solver workers, with per-source concurrency, memory, time and row/byte budgets.

Optimization must not execute arbitrary live queries during solving. Materialize its inputs first. For multiple sources, record each source's extraction time and consistency level; do not imply a globally atomic snapshot across unrelated systems.

### 4.4 Connector contract

Define versioned capabilities: `test_connection`, `discover`, `preview`, `extract_snapshot`, `extract_incremental`, `cancel`, and optional `publish`. Each adapter reports supported modes and limits.

The contract must describe:

- Connector/driver versions, supported database versions, operating systems and authentication modes.
- Source identifiers, safe identifier quoting, query parameter types and schema fingerprints.
- Stable ordering/pagination, resume tokens, transaction behavior and consistency guarantees.
- Decimal precision, nulls, booleans, strings/collation, binary values, timestamps/time zones, large integers and spatial reference systems.
- Cancellation, bounded retries, retryable error classes, timeout and credential-redaction behavior.
- Incremental update and deletion semantics; unsupported capabilities must return explicit errors.

Expose a common UI without hiding database-specific limitations. SQLAlchemy can help relational access; it does not replace adapter certification or normalize every database behavior.

### 4.5 Proposed data model and API

Reuse existing dataset, audit and job objects where their contracts fit; introduce only missing concepts.

| Concept | Required metadata |
|---|---|
| Connection | Organization, owner, connector/version, endpoint, secret reference, TLS policy, permitted scope |
| Connection grant | Which domains and roles may use the connection; discovery and import rights |
| Mapping version | Source schema fingerprint, target schema, transformations, units, keys, validation rules |
| Import pipeline | Connection, mapping version, extraction mode, refresh/freshness policy, resource limits |
| Sync job | Attempt, state, checkpoint, counts, bytes, timings, redacted errors, staged artifacts |
| Dataset snapshot | Immutable manifest/hash, schema, mapping version, source positions, validation report, retention |
| Publication target | Connection, approved tables/operations, field mapping, conflict and approval policy |
| Publication job | Approved result reference, idempotency key, target transaction/receipt, reconciliation state |

Proposed API families: `/api/v1/connections`, `/import-pipelines`, `/sync-jobs`, `/dataset-snapshots`, `/publication-targets`, and `/publication-jobs`. Long operations return a job ID. Creation must validate organization/domain ownership. Endpoint names remain subject to existing API conventions.

### 4.6 Correctness and data quality

Validate in stages: schema → type conversion → keys → relationships → units → business rules → model coverage. Show errors by source object, row/key, field and reason. Never silently round high-precision decimals, interpret local time as UTC, or replace missing values with zero.

Required policies:

- Composite keys and source namespaces prevent unrelated records from colliding.
- Duplicate and null-key handling is explicit; joins report multiplication and unmatched rows.
- Normalization rules cover units, currency effective dates, time zones and coordinate systems.
- Invalid records remain quarantined with a downloadable report. By default, an optimization snapshot is published only after required checks pass.
- If partial acceptance is allowed, record excluded rows and require model coverage checks; current file importer `clean_only` behavior alone is insufficient for trustworthy optimization inputs.
- Adding optional columns may be compatible; dropped fields, changed types or keys pause the pipeline pending mapping review.
- Every run records its snapshot and mapping version. Replaying a run never depends on current source contents.

### 4.7 Refresh, consistency and recovery

Start with full refresh and manual scheduling. Add incremental polling using a stable cursor such as `(updated_at, primary_key)` only when the source supports reliable semantics. Use a bounded overlap and deduplication for late changes; checkpoint after durable staging/publication, not before.

Updates and deletes need explicit handling. A timestamp column alone may miss hard deletes; require tombstones, a change log, CDC, or periodic full reconciliation. Implement CDC only for certified adapters with tested initial-snapshot/change-log handoff, retention-gap detection and restart behavior.

For failures, preserve resumable work where valid and keep the previous published snapshot active. A retry must not duplicate records. Avoid promising distributed exactly-once delivery; use durable checkpoints, idempotent application and reconciliation.

### 4.8 Result publication

Deliver read-only ingestion first. Add write-back as a separate capability after approval and reconciliation work is complete.

- Publish only a specific approved result with its effective period and provenance.
- Default to a dedicated staging table or target API; let the business system own its final operational validation.
- Show a dry-run diff with inserts, updates, rejected rows and conflicts.
- Require a target policy, bounded batch size, idempotency key and separate least-privilege credentials.
- Detect changes since input extraction; reject or explicitly resolve stale-source conflicts.
- Track `pending`, `sending`, `acknowledged`, `failed`, and `unknown outcome`. Reconcile unknown outcomes before retrying.
- Provide rollback where transactional behavior supports it; otherwise use an explicit compensating workflow. Never label a non-atomic multi-system operation as atomic.

### 4.9 Isolation and deployment

Encrypt stored credentials with locally managed keys, support rotation, verify server certificates against a local trust store, and redact secrets from logs/exports. Restrict outbound connections to approved internal endpoints and ports; revalidate resolved addresses and redirects. Connector identities need minimum source permissions. Do not rely on checking that a SQL string starts with `SELECT` to make arbitrary SQL safe.

Package drivers, native libraries, certificates, licenses, notices, checksums, SBOM, migration instructions and conformance reports into the offline release. Customer-supplied licensed drivers must follow a documented offline installation path. Keep plugins versioned and installed by administrators; the planner cannot upload executable connector code.

## 5. Optimization capabilities that earn a performance advantage

### 5.1 Certified coverage

Publish a matrix by problem family and execution path: formulation support, accepted constraints/objectives, solver, guarantee, verifier, tested size, limitations and examples. Distinguish optimal, feasible, infeasible with valid evidence, unbounded, time-limited and numerical failure. A heuristic result must not inherit an exact solver's proof claim.

Choose two flagship families first using installation demand and available reference datasets. Workforce scheduling and resource/distribution allocation are starting candidates, not fixed commitments.

### 5.2 Engineering sequence

1. Measure extraction, transformation, model construction, presolve, queueing, solve, verification and result rendering separately.
2. Improve formulations, scaling, bounds and sparse construction before expanding solver portfolios.
3. Add validated warm starts and reusable structure for repeated planning. Cache keys include model, data, scenario, execution policy and relevant engine versions.
4. Use bounded portfolios only when equal-budget benchmarks demonstrate a gain; account for total CPU/memory across all workers.
5. Add decomposition or rolling-horizon approaches for named large workloads; compare feasibility, quality and boundary effects against reference cases.
6. Keep learned selection in shadow mode until holdout results justify promotion; retain deterministic fallback and rollback.

### 5.3 Planner experience

- Explain binding rules, unmet demand, resource bottlenecks and why a requested decision is impossible, with links to model rules and inputs.
- Offer targeted what-if changes, locked decisions, change penalties and side-by-side business metrics.
- Show trade-offs explicitly for multiobjective problems; do not imply one Pareto point is universally best.
- Separate business approval from model publication and mathematical proof.
- Export a locally readable evidence package containing model/input versions, policy, result, verification and approval history.

## 6. Fair comparison and measurable targets

Use two baselines: the current stable platform release and an appropriately configured reference solver/workflow available under the installation's licenses. Compare frozen datasets, equivalent formulations, solver versions, hardware, threads, wall-clock limits and total resource budgets. Tuning data must be separate from the final holdout set.

| Dimension | Proposed release gate |
|---|---|
| Correctness | Zero known invalid accepted results; every supported path passes its verification suite |
| Solver improvement | For selected flagship families, target at least 20% lower median time to the same verified quality; report p95, timeout rate and regressions |
| Solution quality | Under a fixed budget, report objective/gap distributions and feasibility rates; compare only equivalent objectives |
| Planner efficiency | Target 30% lower median time from ready data to an approved plan versus the recorded current workflow |
| Navigation | At least 90% core task completion in the representative pilot |
| Integration | Resume/retry tests yield no missing or duplicated logical records; lineage links every published snapshot to its source/mapping |
| UI | On agreed reference hardware/data, target p95 ordinary page interaction below 2 seconds; measure large-result behavior separately |
| Offline operation | Clean installation, ingestion, solve, approval, export and restore pass with public egress blocked |

Targets require baseline measurement before commitment. Publish per-instance results, failed cases, seeds and execution manifests. Use repeated runs for noisy/heuristic paths and enough instances to avoid treating one favorable example as a general advantage. Obtain required rights before distributing competitor software or datasets in offline bundles.

## 7. Reliability, scale and maintainability

- Give ingestion, solving and publication independent queues and capacity limits. One slow source must not exhaust API connections or solver capacity.
- Stream extraction and large result artifacts; use chunked local storage and paginated retrieval with completeness checks.
- Preserve job attempt identity and fencing so stale workers cannot publish over current attempts.
- Add freshness, queue age, failure rate, extraction throughput, solve quality, memory and publication reconciliation metrics to Operations.
- Reduce the current frontend main bundle through measured route-level loading and dependency isolation; keep all assets local.
- Verify organization boundaries across connection discovery, jobs, snapshots, caches and artifacts.
- Test backup restoration of metadata, snapshots, results, secrets and encryption keys. Define installation-specific RPO/RTO before setting numerical guarantees.
- Keep releases reversible with migration compatibility checks, a tested rollback procedure and previous offline bundles.

## 8. Delivery roadmap

Indicative sequencing for a team with frontend/product, backend/integration, optimization and QA/operations capacity. A smaller team should serialize the tracks. Re-estimate after discovery; weeks are planning ranges, not promises.

| Phase | Window | Main deliverables | Exit gate |
|---|---|---|---|
| A. Baseline and design | Weeks 1–2 | Capability audit, pilot tasks, source inventory, connector ADR, benchmark datasets and reference hardware | Owners agree workflows, source contracts and measurable baselines |
| B. Navigation completion | Weeks 3–5 | Contextual shells, Inputs/Checks, canonical links, draft protection, accessible error states | Navigation and browser regression gates pass |
| C. First integration | Weeks 3–7, parallel to B if staffed | PostgreSQL read-only adapter, worker isolation, mappings, validation, snapshots, lineage | Interrupted/retried ingestion and repeatable solve pass on internal test DB |
| D. Reusable integration | Weeks 8–11 | Second demanded relational adapter, SDK conformance, incremental polling, scheduling, schema drift | Same contract passes on both databases; deletion/reconciliation documented |
| E. Planning and performance | Weeks 8–13, separate capacity required | What-if/locks, explanations, benchmark instrumentation, targeted tuning, large-result inspection | Correctness and measured family targets pass; regressions published |
| F. Controlled publication | Weeks 12–15 | Approval object/workflow, staged write-back, conflict detection, reconciliation | Duplicate retry, stale data and unknown-outcome tests pass |
| G. Offline release pilot | Weeks 16–18 | Complete bundle, restore/upgrade drills, accessibility and user pilot | Clean isolated host passes end-to-end release matrix |
| H. Demand-led expansion | After pilot | Oracle/ODBC/JDBC, CDC, specialized stores, larger deployment topology | Named use case, license, owner and conformance evidence for each addition |

Do not make the first release depend on supporting every database, real-time CDC, autonomous solver selection or a new distributed architecture.

## 9. First implementation backlog

| ID | Priority | Concrete task | Owner | Dependency / acceptance |
|---|---|---|---|---|
| ENH-01 | P0 | Reconcile current code with proposal and define reference workflows | Tech lead + product | Baseline statuses and test evidence recorded |
| ENH-02 | P0 | Finish context-specific navigation and page destinations | Frontend | ENH-01; route/permission/browser checks |
| ENH-03 | P0 | Replace paginated scope lookup and finish draft-safe routing | Frontend + API | ENH-01; >500 domains and Back/Forward tests |
| ENH-04 | P0 | Define connector, snapshot and consistency contracts | Backend + data steward | ENH-01; reviewed examples and error model |
| ENH-05 | P0 | Create secret references, connection grants and audit actions | Backend + operations | ENH-04; tenant isolation/redaction tests |
| ENH-06 | P0 | Implement bounded PostgreSQL extraction worker | Backend | ENH-05; timeout/cancel/retry and source-load tests |
| ENH-07 | P0 | Implement mapping preview, validation and snapshot publication | Backend + frontend | ENH-06; exact counts, types and lineage |
| ENH-08 | P1 | Bind Inputs and runs to immutable snapshot manifests | Backend + frontend | ENH-07; source changes cannot alter replay |
| ENH-09 | P1 | Add scheduling, checkpoints and schema-drift handling | Backend | ENH-07; crash/restart/delete reconciliation |
| ENH-10 | P1 | Certify second connector and publish SDK conformance harness | Integration | ENH-09; no database-specific assumptions in core |
| ENH-11 | P1 | Record end-to-end timings and create benchmark holdout suite | Optimization + QA | ENH-01; repeatable equal-budget reports |
| ENH-12 | P1 | Improve flagship formulations and repeated-run performance | Optimization | ENH-11; verification and regression gates |
| ENH-13 | P1 | Complete explanations, comparison and large-result workflow | Frontend + optimization | ENH-08; representative planner acceptance |
| ENH-14 | P1 | Implement approval-bound publication and reconciliation | Backend + product | ENH-08/10; dry run, conflicts, retries |
| ENH-15 | P0 release gate | Assemble/test offline bundle, recovery and upgrades | Operations + QA | All selected release scope; egress-blocked acceptance |

Candidate implementation areas: `frontend/src/nav/registry.ts`, `components/AppShell.tsx`, `pages/PlanningOverview.tsx`, a proposed integration page group, existing `backend/app/api/bulk.py` validation logic, and proposed `backend/app/integrations/` adapter/orchestration modules. Separate pure row validation from HTTP handlers before reusing it; do not import private endpoint helpers as the integration architecture.

## 10. Acceptance scenarios

1. A new planner navigates from Home to a domain, prepares inputs, runs a bundled example and understands its result without accessing technical tables.
2. A steward connects an internal PostgreSQL database, maps keys/units, catches a bad relationship, fixes the mapping and publishes a traceable snapshot.
3. A sync fails halfway through; restart yields the same logical dataset without duplicate keys or an advanced-but-uncommitted checkpoint.
4. Source data changes during extraction; the dataset reports its actual consistency guarantees. A multi-source dataset exposes each extraction position.
5. A source column disappears or precision changes; the import pauses and leaves the previous published snapshot usable.
6. A run is replayed after source changes using its preserved inputs; verification remains equivalent within documented numerical tolerances.
7. A viewer cannot discover unauthorized schema names, read secrets, create a connection or publish results through either UI or API.
8. An approved result is published twice with the same key; only one logical operation takes effect. An ambiguous timeout is reconciled before retry.
9. A large import or result remains bounded in memory, cancellable and inspectable while other users continue working.
10. A clean offline host installs, imports, solves, approves, exports, backs up and restores using only the release bundle and authorized internal endpoints.

## 11. Decisions for discovery

Collect the first two database engines and versions, authentication requirements, expected rows/bytes, refresh cadence, deletion semantics, planning time horizon, desired publication target and reference hardware. Also identify a planner, data steward and operations owner for the pilot.

Until those details are available, use these planning defaults: PostgreSQL first, a second adapter chosen by demand, read-only batch ingestion, manual refresh before scheduling, immutable snapshots, and staged write-back in a later milestone. Preserve the existing offline/no-cloud architecture and avoid adding external AI dependencies.

The first demonstrable release should complete one trustworthy loop: **connect internal data → validate and freeze inputs → optimize → explain and compare → approve → publish with reconciliation**. Expand database coverage and optimization families only after that loop is repeatable and measured.
