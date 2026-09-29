# Epic UX — the P1 product items (design)

Source: `OAAS_CUMULATIVE_WORK_REPORT.md` §12, the five open P1 packages, in the report's recommended
order. Each package below lists the gaps found in the code (survey of 2026-09-29) and what this epic
builds to meet the acceptance criteria.

## U-1 Navigation completion

| Gap | Build |
| --- | --- |
| Scenarios, runs, versions, parameters, entity types, relationship types have no search; lists capped at 500 | `q` on those list endpoints (name / id match), search boxes on the pages, the domain picker searches server-side |
| Only ModelEditor and Scenarios use `LoadFailure`; a 403 reads as a generic failure | `LoadFailure` everywhere a page loads by id, with a distinct "no access" state for 403 and "not found" for 404; Retry on the Ops, API keys, Solvers and Settings pages |
| `?parameter=` resolved only within the first 500 | fetched by id when not in the loaded page |
| Capability rules only hide menu items; routes are not guarded | `RequireCapability` on capability-gated routes, saying which capability is missing |
| No role × route test | a table-driven test: four roles × every registry destination and deep link |
| Legacy unscoped routes are live pages; `/data`, `/inputs`… take two hops to a table | legacy destinations resolve `?problem=` / `?domain=` to the canonical scoped path in one step; hubs land on the domain chooser |

## U-2 Complete graph authoring

The Visual Graph is read-only today. This makes it an editor, writing through the same draft as the forms.

- **Inspectors** for a selected variable, parameter or set (domain, bounds, index; index and uncertainty; members) and the existing rule/objective editors — beside the graph.
- **Typed connection commands** (`guidedCommands.ts`): `index` (a set indexes a variable or parameter), `use` (a variable or parameter enters a rule's left side, or an objective term, with a coefficient). Dragging from one card to another maps the two kinds to the one command that fits, or explains why none does. The same commands are offered from a Connect dialog listing only compatible targets.
- **Deletion** of any part: the dependents are listed first; confirming removes the part and exactly those uses — every unrelated reference is left byte-for-byte as it was.
- **Keyboard**: the parts list is the keyboard surface — Enter inspects, C connects, Delete deletes, arrows move (existing).

## U-3 Guided pattern expansion

- A **pattern catalogue** replacing the three hard-coded kinds, adding scheduling and routing: *task with a duration* (interval with start/end), *one at a time* (no-overlap), *shared capacity* (cumulative), *vehicle routes*, *connected regions*. Each pattern produces IR the validator accepts, tested per pattern.
- **Units**: a parameter's unit from the domain reaches the guided fields and the summary; a rule comparing a coefficient and a limit with different units warns.
- **Stable identities**: rules keyed and focused by id, not position; renaming a rule, variable or parameter rewrites every reference.
- **Model review**: one readable page — sets, decisions with bounds and units, every rule in words, the goal, the classification — before Publish.

## U-4 Import / mapping workflow

The backend extracts a table into an artifact (`rows.jsonl` + manifest) and stops there. This epic finishes the path to a dataset a run can reproduce.

- **Source setup UI**: create a connection, rotate its credential, disable it; run an extraction; follow the job (state, cancel) and see the connection's job history (`GET /connections/{id}/jobs`).
- **Preview**: `GET /ingestion-jobs/{id}/preview` — the artifact's columns and first rows.
- **Mapping and validation**: `POST /ingestion-jobs/{id}/validate` with a target entity type and a column → attribute map; the rows are checked by the same code as a bulk upload (types, then the database's own rules in a savepoint, rolled back), faults `{row, column, message}`, the report stored.
- **Publication**: `POST /ingestion-jobs/{id}/load` only with a validated mapping of the same artifact and mapping hash; writes the rows and an `import_load` lineage row (artifact SHA-256, mapping hash, report, rows written). A load is never repeated for the same artifact and mapping. The next run's dataset snapshot is the reproducible publication, and its lineage says which import it came from.
- **Wizard**: `domains/:d/data/sources/:id/import/:job` — preview, map, validate (fault table), load.

## U-5 Pre-run and result experience

- **Solver fit**: `backends.fit()` — every backend with whether it fits this model and why not (class, missing capability, local-only, by name only, kept out by settings, not in this build). `choose()` is built on it.
- **Worker availability**: workers write a heartbeat row (`worker_heartbeat`, migration); `GET /workers` — online workers and the queue ahead.
- **Preflight**: `GET /scenarios/{id}/preflight` — compiles the scenario's model on the live data and returns `ready`, missing inputs and empty ranges as findings, rules with no arithmetic, the model class, the solver fit list and the workers.
- **Runs page**: a *Before you solve* panel from the preflight; the Solve button says why it cannot run when it cannot; the Solver list shows only solvers that fit, each with its reason when disabled.
- **Comparison**: optimality claim, gap, solver, time and class side by side, with a warning when the two claims differ.

## Verification

Backend tests per endpoint and command; frontend tests per component and the role × route matrix; the full backend and frontend suites, lint and build; the OAAS report §12 and the handover updated.
