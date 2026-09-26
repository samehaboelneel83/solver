# Approved plans (OAAS Phase 5)

Business acceptance of a **specific immutable run**, with optional effective dates.
Not the same as:

- solver proof (`optimal` / `feasible` / local / approximate),
- publishing a model version,
- a gate override on version checks.

## API

| Method | Path | Capability | Effect |
|---|---|---|---|
| `POST` | `/api/v1/runs/{id}/approve` | `model.publish` | Create approval; supersede prior current approval on the same problem |
| `GET` | `/api/v1/problems/{id}/approvals` | signed-in | List approvals (`current_only=true` by default) |

Body for approve: `{ "reason": "…", "effective_from"?: "YYYY-MM-DD", "effective_to"?: "YYYY-MM-DD" }`.

Audit action: `plan.approve`.

## UI

Runs detail → **Plan approval** panel (`ApprovePlanPanel`): approve / supersede with
reason and optional effective dates. Requires `model.publish`.

## Schema

Table `approved_plan` (migration **0082**): one row per approved run; `superseded_by`
points at the newer acceptance when a later run is approved for the same problem.

## Chunked amounts (same migration)

Large continuous/integer amount tables go to `solution_amount_chunk` when they
exceed the inline cap (`AMOUNT_CELLS`). Read them with:

`GET /api/v1/runs/{id}/amounts?variable=&offset=&limit=`

`run.params.amounts_chunked` records `{ cells, chunk_size }` when chunked.
