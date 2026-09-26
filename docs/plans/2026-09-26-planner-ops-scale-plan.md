# Plan of work: planner re-optimization, model CI, scale and enterprise

Written 2026-09-26, after every item in `2026-09-22-execution-queue.md` was done. Three tracks, in the
order they should run. Items are numbered R23 onward, so they continue the queue's numbering and can be
moved into it as they are approved. Each item gets the queue's usual routine:

- tests, then `bash scripts/check.sh`;
- a migration rehearsal (up, down, up) on a live copy;
- a deploy from a clean worktree and a live browser/API check;
- updates to the queue, the handovers and memory;
- a commit by path.

Standing defaults still hold:
- a tenant is an organization;
- one solve per subprocess;
- a local optimum is shown with a warning and never called optimal;
- no Redis, no GPU lane, no LLM work.

## What already exists (the plan builds on it, not beside it)

| Piece | Where | What it gives this plan |
|---|---|---|
| Scenario patch (`disable`, `harden`, `soften`) | `app/solve/service.py` `patched()` | The place a lock or a forced decision goes: a new verb, not a new pipeline |
| Warm starts | `app/solve/warm.py` (`prior_run`, `hint_from`) | Hints from a base run's roster for CP-SAT, HiGHS and SCIP |
| Run comparison | `app/solve/compare.py`, `GET /runs/{l}/compare/{r}` | What moved between two runs, and rule by rule |
| Conflicts | `app/solve/diagnose.py` (HiGHS IIS, CP-SAT cores, minimal shrink) | "Blocked by these rules" for any infeasible probe |
| Slack, duals, reduced costs | `constraint_result`, `solution.reduced_costs` | LP sensitivity with no extra solve |
| Result cache | `run.cache_key`, `reused_from` | Re-running an unchanged suite case costs nothing |
| Immutable versions | `model_version`, `dataset` (in `IMMUTABLE_TABLES`) | A frozen dataset to replay against, and a version to gate |
| Fair queue | `service.py` claim: per-organization fair, `FOR UPDATE SKIP LOCKED` | Several workers are already safe; scaling out means adding replicas |
| Quotas, API keys, roles | `api/quota.py`, `api/api_keys.py`, `iam.role` | The IAM that SSO and audit hang off |
| Bench | `bench/nightly.py`, `families.py` | The nightly job model CI runs inside |

**One limit shapes Track A.** `solution.assignments` stores, per variable, only the index tuples that
were not zero: a roster, not a table of values. Binaries can be locked exactly from it. Whole or
fractional amounts can be locked only where `solution.amounts` recorded them. Item R23 adds amounts to
every run whose model has non-binary decisions, before anything locks them.

---

## Track A — re-optimization of a locked plan, and "why not?" answers

**Goal.** A planner can:
- publish a plan;
- mark the parts that are already committed (yesterday's shifts, dispatched trucks, anything before a date);
- change the data;
- solve again, getting a new plan that keeps what was locked and moves as little of the rest as the
  rules allow.

On any answer the planner can ask:
- "why not X?", and get back the rules that forbid X, or what X would cost;
- "what if this number changed?", and get back how far it can move before the plan changes.

### R23 — every run records its values

- **What.**
  - Store the value of every non-zero integer or continuous decision in `solution.amounts`, keyed like
    `assignments`.
  - Cap the size: past 200k non-zero cells, store none and set `amounts_truncated`.
  - `warm.hint_from` reads amounts when they are present, so a warm start hints amounts too.
- **Files.**
  - `app/solve/service.py` (`_record`), `app/solve/warm.py`.
  - Migration 0069, only if `amounts_truncated` needs a column (otherwise it goes in `run.params`).
- **Tests** (`tests/test_run_amounts.py`).
  - The feed-blend LP stores its kilograms.
  - The warm hint of a blend run covers every used amount.
  - A truncated run hints only its binaries.
- **Done when.** A live blend run shows its amounts through `GET /runs/{id}` and a second run records
  `warm_start_from` with amounts hinted.

### R24 — the `lock` patch verb

- **What.** `patch.lock` is a list of locks. Each lock is one of:
  - `{"var": "assign", "index": ["ann","mon","early"], "value": 1}`: fix one cell;
  - `{"var": "assign", "where": {"day": ["mon","tue"]}, "from_run": 812}`: fix every cell of `assign`
    whose `day` position is in the list to its value in run 812. Cells run 812 left at zero are fixed
    to zero, so locking a day locks both who works and who does not;
  - `{"before": "2026-10-01", "attr": "date", "set": "day", "from_run": 812}`: a horizon freeze. Every
    decision indexed by a `day` whose `date` attribute is before the cut-off is fixed from run 812.
- **Where it applies.** `patched()` stays a pure IR→IR function. Locks do not change the IR: they are
  resolved against the compiled model in a new `app/solve/locks.py`. That module turns them into
  bound changes (lower = upper = value) on `Compiled.variables` after compilation and before the
  backend. Changing bounds keeps them exact for every backend, and the diagnoser can blame them (see R26).
- **Validation**, done at scenario create/update in `api/problems.py` with the IR checks' refusal style:
  - unknown variable or set → `lock_unknown`;
  - an index of the wrong arity → `lock_index_arity`;
  - `from_run` not a run of the same problem, or one with no answer → `lock_run_invalid`;
  - a locked value outside the variable's bounds → `lock_out_of_bounds`;
  - a continuous amount locked from a run whose amounts were truncated → `lock_amounts_missing`.
- **Files.**
  - New `app/solve/locks.py`.
  - `service.py`: call `locks.apply(compiled, patch, db)` beside the warm start.
  - The scenario patch schema in `models/v1_problem.py` / `api/problems.py`.
  - The cache key: it already covers `patch`, so a lock changes the key.
- **Tests** (`tests/test_locks.py`).
  - Weekly rota S: lock Monday from run A, raise Tuesday's demand, re-solve. Monday is identical cell
    for cell, and the result is optimal under the locks.
  - A lock that makes the model infeasible is reported as infeasible (R26 names the lock).
  - A horizon freeze on the facility model with a `date` attribute.
  - Each of the five refusals.
  - Locks on a separable model: the fixed cells land in the right block (`blocks.split` is unchanged,
    because bounds travel with the variables).

### R25 — change as little as possible

- **What.** `patch.stay_close` is `{"from_run": 812, "weight": 10, "vars": ["assign"]}`. It adds a
  penalty term: the weight times the number of cells that differ from the base run.
  - Binaries: `x` when the base cell is 0 and `1 − x` when it is 1. This is linear and needs no new
    variables.
  - Integers and continuous amounts: `|x − base|`, through one continuous deviation variable per used
    cell and two rows.
  - As a lexicographic option (`"mode": "lex"`): first optimize the original objective, then minimize
    change with the original objective held within `tolerance` (default 0). This reuses the lex-goal
    machinery from Phase 15.
- **Why both modes.** A weighted penalty trades cost against churn at a stated exchange rate. Lex
  means "the cheapest plan, and among those the one closest to yesterday's". Planners ask for both.
- **Recorded on the run**: `params.stay_close` holds the base run, the weight or mode, and the number
  of cells that moved. The compare endpoint already reports the moves.
- **Files.** `app/solve/locks.py` (the same module: this is "soft locks"), and the compile hook in
  `service.py`.
- **Tests.**
  - Rota: with a weight large enough, a one-cell demand change moves at most the cells a brute force
    over the small model says are needed.
  - Lex mode reaches the same cost as a cold solve, with at most as many moves as that cold solve made.
  - A weight of 0 is the plain model, with the same objective.
- **Blocks.** A model with `stay_close` in lex mode is refused a separable split by name, as other lex
  goals already are.

### R26 — "why not?" as a question on a run

- **What.** `POST /runs/{id}/why-not` takes `{"force": [{"var": "assign", "index": ["ann","mon","early"], "value": 1}]}`
  (one or more forced cells, the same shape as a lock). The server:
  1. creates a probe scenario: the run's scenario patch, plus the forced cells as locks, plus
     `stay_close` in lex mode from this run, so the answer is "the least that changes to make X true";
  2. queues it as an ordinary run with `purpose = 'why_not'` and `parent_run_id`;
  3. when it settles, fills a **verdict**:
     - **infeasible**: the diagnoser's minimal conflict, with the forced cells treated as rules. The
       answer reads "Ann can't work Monday early because: at most 5 shifts a week (c_max_shifts); she
       already works Tue–Sat, which is locked (lock 1)". Locks go into the conflict set as named
       members, so the diagnoser can point at a lock;
     - **feasible**: the cost of X (objective delta against the parent), and what else had to move
       (`compare` of the child against the parent: its moved cells and the rules whose slack changed);
     - **no answer in time**: say so. Never guess a verdict.
- **Storage.** Migration 0070 adds:
  - `run.purpose` (text, default `'plan'`, check `plan|why_not|shadow|suite`);
  - `run.parent_run_id` (a nullable FK to `run`);
  - `run.verdict` (JSONB).

  Probe runs do not appear in the main runs list unless asked for (`?purpose=`). They count against
  quota like any run.
- **Files.**
  - `api/runs.py`: the endpoint, and the listing filter.
  - New `app/solve/whynot.py`: builds the probe and the verdict.
  - `diagnose.py`: accept extra named members (the locks).
  - Migration 0070.
- **Tests** (`tests/test_why_not.py`).
  - Rota: forcing a sixth shift gives infeasible, with the conflict naming the weekly cap and the lock.
  - Forcing a cheap-but-unused cell gives feasible, with a delta ≥ 0 and the same delta as a
    hand-computed re-solve.
  - Forcing a cell already in the plan gives "already so", with no solve (answered at once, no run
    queued).
  - The probe does not show in the default runs list.
  - A probe of a probe is refused (`parent_run_id` depth 1).

### R27 — sensitivity: "how far can this number move?"

- **What.** For LP runs (HiGHS, GLOP), ask the solver for its ranging information: objective
  coefficient ranges, and right-hand-side ranges per row. HiGHS `getRanging()` gives both. Store them
  per rule instance in `constraint_result.range_low` / `range_high` (the row's right-hand side) and per
  variable in `solution.cost_ranges`. From duals and ranges the UI states:
  - "each extra kg of protein allowed saves 3.20, until the limit reaches 64 kg";
  - "maize stays in the blend while its price is between 0.18 and 0.31".
- **MIPs.** The honest answer is that ranging is not defined for a MIP. The page says "sensitivity is
  exact for linear models; for this model, ask 'what if' instead", and offers a what-if: a
  one-parameter change solved as a probe (the R26 machinery with a parameter override in place of a
  lock). The standing rule applies: never present LP-relaxation duals of a MIP as the MIP's sensitivity.
- **Migration 0071**: the range columns, nullable.
- **Files.**
  - `app/solve/backends/highs.py`: read ranging after an optimal LP.
  - `service.py` `_record`.
  - The what-if patch verb `override: {"param": "demand", "index": [...], "value": ...}`. It is
    applied to the dataset copy, never to the stored dataset.
- **Tests.**
  - Feed blend: every reported range is checked by moving the number just inside the range (the basis
    and plan stay, and the objective moves by dual × step) and just outside it (the plan changes).
  - A MIP run stores no ranges.
  - An override never writes to `dataset`, which is immutable (pinned by the existing immutability test).

### R28 — the planner's page: lock, re-solve, ask

- **UI**, in the run views that already exist:
  - **Grid and Gantt**: select cells or bars, then "Lock". Locked cells show a padlock and a hatched
    fill. "Lock everything before…" is a date picker, shown only when the model has a date attribute
    on an index set.
  - **Re-solve panel**: shows the locks (removable), a "stay close to this plan" switch
    (weighted/lex), and a "Solve the rest" button. The result opens in compare mode against the base
    run, with moved cells highlighted.
  - **"Why not?"**: right-click an empty cell, then "Why isn't this assigned?". A side sheet shows the
    verdict in the rule notes' business language (the Phase 11 panel style): the blocking rules or
    locks, or the cost and what moved, with "Apply this change" (it adopts the probe run as the new
    plan).
  - **Sensitivity sheet** on LP runs: per rule, "worth X per unit, valid from A to B"; per decision,
    "stays while its cost is in [A, B]". On a MIP, the what-if form instead.
- **Files.**
  - `frontend/src/components/RunViews.tsx` (selection and padlock overlay on ShapedView).
  - New `LockPanel.tsx`, `WhyNotSheet.tsx`, `SensitivitySheet.tsx`.
  - `lib/runViews.ts` (lock ↔ cell mapping).
  - `api/v1.ts` hooks.
- **Tests.**
  - Vitest for lock ↔ cell mapping and for verdict rendering (every verdict kind, including "no answer
    in time").
  - Live check (a gitignored browser script):
    1. lock Monday on a rota run;
    2. change Tuesday's demand;
    3. solve the rest;
    4. Monday is unchanged and moved cells are highlighted;
    5. why-not on an empty cell shows a named rule;
    6. the blend sensitivity sheet shows a range.

**Track A acceptance.** On the seeded weekly rota and feed blend, in a browser:
- a locked re-plan keeps every locked cell and is optimal under its locks;
- lex stay-close moves no more cells than a cold solve does;
- every why-not verdict is either a minimal conflict that names rules or locks, or a cost delta with
  what moved;
- every LP range has been checked by a probe in the tests.

---

## Track B — model CI and shadow runs

**Goal.** Changing a model is safe:
- every new model version is checked against the problem's own acceptance cases before it can be made
  the version planners run;
- a candidate version can run beside the live one on real traffic, so its answers are compared before
  anyone relies on them.

### R29 — acceptance suites

- **What.** Each problem has a suite of cases. A case is:
  - a frozen dataset (an existing immutable `dataset` row);
  - an optional scenario patch;
  - expectations:
    - `status`: e.g. `optimal`, or `infeasible` for a "must refuse" case;
    - `objective`: a value, with `tolerance_abs`/`tolerance_rel`;
    - `must_hold`: e.g. "ann never works nights", written as locks that must already hold in the
      answer, so they reuse R24's shape;
    - `max_seconds`.
  - A case can be made from any past run with one click, "Keep this as a test case". Its answer becomes
    the expectation, which the user may loosen.
- **Storage.** Migration 0072 adds `suite_case`:
  - `id`, `problem_id`, `name`, `dataset_id`, `patch`, `expect` (JSONB), `created_from_run_id`,
    `created_by`, `created_at`;
  - organization-scoped with RLS, following the existing per-table pattern.
- **Files.**
  - New `app/api/suites.py`: CRUD, and `POST /problems/{id}/suite-cases/from-run/{run_id}`.
  - New `app/solve/suite.py`: evaluate one case's run against its expectations, and return pass/fail
    with the reason.
- **Tests** (`tests/test_suites.py`).
  - A case made from an optimal run passes on the same version (answered by the result cache, so no
    solve).
  - A version whose rule change raises the cost beyond the tolerance fails, with a reason that names
    the objective and both values.
  - A `must_hold` violation names the lock.
  - RLS: another organization cannot read or run the cases.

### R30 — the gate: a version runs its suite before it is published

- **What.**
  - `model_version` gains `state` (`draft` → `checking` → `passed` | `failed` → `published`).
    Migration 0073 backfills every existing version as `published`.
  - `POST /model-versions/{id}/check` queues one `purpose='suite'` run per case, all at a lower
    priority than planner runs. They go through the fair claim, and planners' runs go first within the
    organization.
  - When the runs settle, the version becomes `passed` or `failed`, with a report: case by case, then
    the version's objective against the currently published version's, and the time.
  - `publish` is refused for a version that is not `passed`. An organization setting
    (`suite.required`, default on once a problem has at least one case) turns the gate off. The refusal
    names the failed cases.
- **Where "the version planners run" lives.** Today a scenario pins a model version. Publishing
  therefore means: the problem's `current_version_id` moves, and new scenarios default to it. Existing
  scenarios keep their version until moved explicitly. (If a problem-level pointer does not exist yet,
  migration 0073 adds it.)
- **Files.**
  - `api/problems.py` (publish, check).
  - `app/solve/suite.py` (roll-up).
  - `service.py` (priority: the claim orders by `purpose='plan'` first, then age).
  - Frontend: a "Checks" tab on the model page with a case list, run status and a diff table, and a
    publish button that shows the refusal inline.
- **Tests.**
  - Publish is refused while `checking` or `failed`, and allowed after `passed`.
  - Suite runs never delay a planner run in the same organization (two queued, one worker: the plan
    run is claimed first).
  - A version with no cases publishes when the gate is off, or when the problem has no cases.
  - A suite run of a case already answered for this `ir_hash` + `data_hash` is taken from the cache.

### R31 — shadow runs

- **What.** A problem can have a **shadow version**: a passed but unpublished candidate. With shadowing
  on (`shadow.rate`, 0–1, default 0), each planner run is also queued once against the shadow version:
  - `purpose='shadow'`, `parent_run_id` = the planner's run;
  - the same dataset and patch;
  - lowest priority;
  - the planner never sees it.

  When both have settled, the comparison is stored on the shadow run's `verdict`:
  - status of each;
  - objective delta;
  - time ratio;
  - how many cells moved (from `compare.py`);
  - rules whose slack changed sign.
- **Shadow report.** A rolling summary per shadow version:
  - how many runs;
  - share where the shadow was at least as good;
  - worst regression, with a link to the pair;
  - median time ratio.
- **Quota and cost.** Shadow runs count against a separate `shadow` quota bucket, capped by the rate.
  The rate is an organization decision, because it doubles solve cost at 1.0.
- **Files.**
  - `service.py`: queue the twin at submit time, and compare at settle.
  - `api/problems.py`: set the shadow version and rate.
  - `app/solve/compare.py`: reuse `compare()` unchanged.
  - Frontend: a "Shadow" card on the model page with the summary and the worst pairs, and a "Promote"
    button that goes through R30's publish.
- **Tests.**
  - Rate 1: every plan run gets exactly one twin, rate 0 gets none, and rate 0.5 over 200 submits falls
    in a binomial band.
  - The twin never appears in the planner's list or events.
  - A shadow that fails to compile is recorded as a failed shadow, not an error on the planner's run.
  - Cancelling the planner's run cancels its twin.

### R32 — nightly model CI

- **What.** `bench/nightly.py` gains a `--suites` pass. It re-runs every problem's suite against its
  published version with the result cache off, so solver or library upgrades that change answers or
  times are caught. The report goes to `bench/results/<date>-suites.md` and to a `suite_nightly` table
  (migration 0074): problem, version, case, status, objective, seconds, and verdict against expect. A
  case that passed yesterday and fails today shows as a red row on the model's Checks tab.
- **Also.** The same pass runs in `scripts/check.sh` for the seeded problems (a fast subset,
  `max_seconds` ≤ 5), so a code change that breaks a seeded model's answer fails the check before deploy.
- **Tests.** A fake upgrade (a monkeypatched backend that returns a worse objective) makes the nightly
  mark the case failed, and it does not publish or unpublish anything.

**Track B acceptance.**
- In a browser: make a case from a rota run, edit the rule, run the check, and see the failure named
  with both objectives; publish is refused.
- Loosen the tolerance and publish.
- Set the version as shadow at rate 1, submit three plan runs, and the shadow card shows three pairs
  with deltas.
- The nightly report lists every seeded case.

---

## Track C — scale and enterprise, each item gated on a named customer need

Nothing in this track starts without a customer (or a signed pilot) whose need it meets. Each item
below says the need that unlocks it and what "done" is. They are independent and can be taken in any
order.

| Item | Unlocked by | What | Decision needed |
|---|---|---|---|
| **R33 — worker scale-out and queue metrics** | A customer whose queue wait is > 1 min at peak, or more than ~10 concurrent solves | Workers already claim with `SKIP LOCKED` and fairness. Add queue depth, wait time and running count per organization as Prometheus metrics (`/metrics`, admin only). Document `docker compose up --scale worker=N` and memory per worker. A load test (`bench/load.py`: 200 submits across 5 organizations) shows fair shares ±10% and no organization starved. | None: no Redis. Postgres stays the queue until measured otherwise (it holds well past 100 claims/s). |
| **R34 — audit log** | Any regulated customer, or a procurement security questionnaire | Migration: an append-only `audit_event` (org, actor, api_key_id, action, object type/id, before/after hash, ip, at), with inserts only (a trigger refuses UPDATE/DELETE). Written for: model publish, scenario and lock changes, dataset upload, bulk upload, role/key changes, settings, login. `GET /audit` (admin, filters, CSV export). Retention per organization (`audit.retention_days`, default 400), with pruning done by a nightly job that also records itself. | Retention default. |
| **R35 — SSO (OIDC first)** | A customer on Okta, Entra ID or Google Workspace | OIDC authorization-code flow with PKCE via `authlib`. Per-organization IdP config (issuer, client id, the client secret stored encrypted with the existing secret mechanism, never logged). Just-in-time user creation. Group claim → role mapping. "SSO required" per organization disables password login for its members. SAML later, only if a customer's IdP cannot do OIDC. | Which IdP the first customer uses. Whether to add `authlib` (a dependency). |
| **R36 — SCIM provisioning** | A customer with more than ~200 users, or one who requires automatic deprovisioning | SCIM 2.0 `/scim/v2/Users` and `/Groups` with a per-organization bearer token. Deprovisioning revokes sessions and API keys at once. | Needs R35. |
| **R37 — data retention and deletion** | A GDPR/DPA request, or a contract clause | Per-organization retention for runs, solutions and uploads (`retention.runs_days`). Hard deletion of an organization with a signed deletion report. Export of all of an organization's data (JSON + the existing Excel templates). The immutable tables are deleted only by the organization-delete path, which the immutability triggers allow for that role alone. | Retention defaults. The legal wording of the report. |
| **R38 — Kubernetes / Helm deployment** | A customer who hosts it themselves, or a move off one host | A Helm chart: backend, worker (HPA on the R33 queue-depth metric), frontend, migrations as a pre-upgrade Job (`alembic upgrade head`, as today), Postgres external. Worker pods keep the sandbox's rlimits and non-dumpable children, so the pod security context must allow `prctl`. | Target cluster. Whether Postgres is managed. |
| **R39 — backups and disaster recovery** | Any paying customer (do before the first) | Nightly `pg_dump` plus WAL archiving to object storage. A restore rehearsal script that restores to `solver_restore`, runs the suite (R32) against it, and drops it. Documented RPO 24 h and RTO 4 h to start with. ClickHouse `run_fact` is rebuildable from Postgres, so it is not backed up. | Where backups live (this costs money: ask). |
| **R40 — per-organization solve limits and priorities** | Tiered pricing, or one customer's large solves hurting others | Per-organization caps on concurrent solves, per-run seconds and memory. A tier setting that weights the fair claim. Built on `quota.py`. | Tier definitions (commercial). |

**R39 should run first of Track C**, whatever the demand, because it protects data that already exists.
The others wait for their trigger.

---

## Track D — a facility to add any native solver, commercial or not (asked 2026-09-26)

**Goal.** Anyone can plug a solver into the platform without changing platform code. Examples:
Gurobi, Xpress, CPLEX, COPT, a university's research code, or a customer's in-house heuristic.

- The customer brings the licence. The platform buys nothing.
- An adapter is refused until it passes the same checks our built-in solvers pass.
- The existing solver-choice policy picks it up without change.

It is proved with free solvers standing in for commercial ones, so no licence is needed to build or
test any of it.

**What exists.** `app/solve/backends.py` already treats solvers as data:
- a `Backend` row declares `classes`, `provides`, `rank` and `proves`;
- `choose()` is one policy over the `REGISTRY` tuple;
- every solve already runs in a sandboxed child (`sandbox.run`).

The facility makes that registry open and gives it a contract. Our OR-Tools 9.15 build already
carries the hooks for Gurobi, Xpress and CPLEX: `pywraplp` loads their shared libraries at run time
when they are present. `cryptography` is already installed.

### R41 — the adapter contract and discovery

Three kinds of adapter, from the least to the most code:

1. **`ortools-engine`**: a manifest only. It names an OR-Tools engine (`GUROBI`, `XPRESS`, `CPLEX`,
   `SCIP`, `CBC`, …) and where the vendor's library is. The model goes through the same `pywraplp`
   translation our `milp` backend uses, so every rule we can express reaches the engine. This is the
   whole Gurobi, Xpress and CPLEX story for linear and whole-number models.
2. **`command-line`**: a manifest naming an executable. The platform writes the model as MPS (the
   `bench/mps.py` writer, promoted into `app/solve/mps.py`), runs the executable with the
   manifest's argument template (`{model}`, `{solution}`, `{time_limit}`, `{threads}`, `{gap}`), and
   reads back a solution file in the manifest's format. Any solver with a command line fits, with
   no Python.
3. **`python`**: a module exposing `solve(compiled, *, time_limit, workers, should_stop, seed,
   gap_rel, on_progress, hint, options) -> Solution`, the same signature as the built-ins. This is
   for full control: callbacks, native conflicts, a vendor's Python API.

**Manifest** (`adapter.toml`, one folder per adapter under `SOLVER_ADAPTERS_DIR`, default
`/opt/solver/adapters`, mounted read-only into backend and worker; or a Python package exposing the
entry point group `solver.adapters`):
- `name`, `version`, `kind`;
- `classes`, `provides` and `proves`, checked against the classifier's vocabulary, so an unknown
  word is refused;
- `rank` (default 50, below every built-in unless an organization raises it);
- `licence`: what the adapter needs (environment variable names, a licence file, a licence server
  address);
- `options`: the tuning options it accepts, each with a type.

**Loading** (`app/solve/adapters.py`), at process start in the API, the worker and each sandbox
child alike, so all three agree:
- each manifest is validated;
- a bad one is skipped with a logged reason and shown on the admin page (R44). One broken adapter
  never stops the platform;
- a name that clashes with a built-in is refused;
- adapters join `REGISTRY` as ordinary `Backend` rows.

`is_available()` means: the library or executable is found and the licence check passes.

**Tests:**
- a manifest for each kind, pointing at **CBC** (`ortools-engine`), a solver executable
  (`command-line`; CBC's or HiGHS's binary added to the test image) and a small Python adapter;
- each is discovered, validated, chosen by name, solves the golden models, and runs in the sandbox;
- a bad manifest (unknown capability, missing `proves`, name clash) is skipped with its reason;
- an adapter whose library is missing is listed as unavailable, never chosen, and a run that asks
  for it is refused by name.

### R42 — bring-your-own licences, per organization

- **Migration:** `solver_licence` (organization, adapter, kind `env` | `file` | `server`, `payload`
  encrypted with Fernet under `SOLVER_SECRETS_KEY` from the environment, `fingerprint`, `set_by`,
  `set_at`), with RLS by organization.
- **API:** `PUT /solver-licences/{adapter}` is write-only. `GET` shows only whether a licence is
  set, its fingerprint and when. There is no read-back of the secret, ever. Deletion is allowed.
- **At solve time:** the worker decrypts the licence into the sandbox child only, as environment
  variables or a temporary file under the child's own directory, deleted on exit. The licence never
  appears in logs, in `run.params`, in errors (vendor messages are scrubbed of the payload before
  they are stored), or in traces.
- **Availability** becomes per organization: an adapter that needs a licence is available only to
  organizations that have set one. `choose()` asks `available_for(org)`.
- **Settings:** `solve.allowed_solvers` / `solve.denied_solvers` at organization or problem level,
  so a customer can pin, for example, "Gurobi only, never the free fallback", or the reverse.
- **Tests:**
  - a fake licence reaches the child's environment and nothing else: grep logs, params and the
    error text;
  - another organization cannot see or use it (RLS);
  - a wrong licence gives an error naming the adapter, not the secret;
  - `allowed_solvers` is obeyed and a refusal names it.

### R43 — the conformance kit

`python -m bench.conformance <adapter>` runs the suite every built-in already meets:
- LP, MIP, an infeasible model, an unbounded one, a trivial one;
- a time limit that stops early and keeps the best found;
- a stop request honoured, or reported as not honoured;
- a hint that is bad and must not change the proven optimum;
- `gap_rel` obeyed;
- the answer re-checked against every rule (`evolve.holds`);
- the objective checked against the known optimum.

It writes a report and records the result (the date, the passed and failed checks, the adapter
version) in a `solver_conformance` table. **An adapter that has not passed is never chosen
automatically**. It can still be named explicitly, and each such run says "unverified solver".
Organization admins can re-run the kit from the page (R44).

- **Tests:** the three reference adapters pass. A deliberately wrong adapter fails, and is never
  auto-chosen. It is one that reports `optimal` on a feasible plan, or ignores the time limit.

### R44 — the Solvers admin page

Settings → Solvers lists every solver, built-in and added. For each it shows:
- its kind, version and what it solves;
- whether it is available, and why not (a missing library, no licence);
- its conformance result;
- its rank for this organization.

Actions:
- set or replace the organization's licence (write-only);
- run the conformance kit;
- allow or deny the solver for the organization;
- read the manifest's options.

The live check is in a browser: the CBC reference adapter is shown, passes conformance, is allowed,
and solves a model by name.

**Out of scope, on purpose.** No licence is bought, and no vendor's software is shipped in our
image. A customer's own image (or a volume mount) supplies Gurobi, Xpress or CPLEX. The docs give
the few-line manifest for each, marked "untested here, for want of a licence" until a customer runs
the conformance kit with theirs.

## Order and size

| Order | Items | Rough size | Migrations |
|---|---|---|---|
| 1 | R23 amounts, R24 locks | 2–3 days | 0069 (maybe) |
| 2 | R25 stay-close | 2 days | — |
| 3 | R26 why-not, R27 sensitivity | 4–5 days | 0070, 0071 |
| 4 | R28 planner UI | 4 days | — |
| 5 | R29 suites, R30 gate | 4 days | 0072, 0073 |
| 6 | R31 shadow, R32 nightly | 3–4 days | 0074 |
| 7 | R41–R44 solver adapters (Track D; asked 2026-09-26, taken right after R27) | 5–6 days | 2 (licences, conformance) |
| 8 | R39 backups, then R33–R40 on demand | per item | per item |

Migration numbers are provisional. Other sessions commit on master, so each is renumbered at merge, as
usual.

## Risks and how each is handled

- **Locks make a model infeasible, and the planner doesn't know why.** R26's diagnoser treats locks as
  named conflict members, so the answer names the lock.
- **Stay-close adds a variable per cell for integer models (size).** It is only for used cells and
  their neighbours. The row and variable count is recorded, and a warning is shown past 1M added
  variables.
- **Why-not probes flood the queue.** A probe is one run with a quota. At most 3 probes are queued per
  user at a time. Probes of an unchanged question hit the result cache.
- **LP ranges are misread as MIP sensitivity.** The API never returns ranges for a MIP. The UI says why
  and offers what-if.
- **Shadow doubles the cost.** The rate defaults to 0, it has its own quota bucket, and it runs at the
  lowest priority.
- **The suite gate blocks an urgent fix.** An organization admin can publish past a failed check. This
  is recorded in the audit log (R34), with the reason required.

## Decisions for you before starting

1. **Track A first?** It is the planner-facing differentiator and builds only on code that exists.
   (Recommended.)
2. **R26 probes count against quota?** Recommended yes, with a separate small allowance so asking
   questions never blocks planning.
3. **Track C spending.** R39's backup storage and R38's cluster cost money. Name the storage target
   before R39 starts.
4. **SSO dependency.** `authlib` for R35, when a customer asks.
