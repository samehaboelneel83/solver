# Handover — the optimization-as-a-service platform

**As of 2026-09-26.** For whoever runs, builds on or evaluates this platform next. It lists
**everything that has been planned**: what is delivered (built, tested, deployed and checked live,
with the commit that did it), what is in progress, and what is not delivered and why.

**State in one paragraph:**
- Repository: `D:\solver`, branch `master`, 520 commits since 2026-09-16. Nothing is pushed: there
  is no remote.
- Deployed: app code including R39 backups; database at migration **0076**. Postgres runs with
  `archive_mode=on` and mounts `SOLVER_BACKUP_DIR` (default `D:\solver-backups`).
- Committed but **not yet deployed**: none.
- Docs: the detailed day-by-day record is
  [`docs/plans/2026-09-24-session-handover.md`](docs/plans/2026-09-24-session-handover.md) (one row per
  delivered item). The ordered work list, with each item's evidence, is
  [`docs/plans/2026-09-22-execution-queue.md`](docs/plans/2026-09-22-execution-queue.md).

---

## 1. What the platform is

Organizations describe a planning problem in their own terms and get a proven-best (or honestly
labelled) plan back:
- **the data:** entity types, entities, relationships, parameters and maps;
- **the model:** rules and goals, as a document, forms, or blocks.

The platform:
- chooses a solver for the model's mathematical class and records why;
- solves in a sandbox;
- explains what it found: which rules bind, what blocks an infeasible model, what a plan would cost
  otherwise;
- keeps every run immutable, so any two can be compared.

**Stack:**
- **Backend:** FastAPI, PostgreSQL with row-level security per organization, Alembic migrations, a
  worker that claims runs from a fair queue in Postgres. There is no Redis.
- **Solvers, each solve in a sandboxed subprocess:** OR-Tools (CP-SAT, GLOP, routing, min-cost
  flow, PDLP), HiGHS, SCIP, IPOPT, and three search heuristics (CMA-ES, particle swarm, a genetic
  algorithm).
- **Frontend:** React, Vite and Tailwind, with Blockly and Cytoscape.
- **Analytics:** ClickHouse, for run facts.
- **Maps:** a local tile server (Egypt basemaps, terrain, OSM vectors).

**Standing decisions** (these shape what is and is not built):
- a tenant is an organization;
- one solve per subprocess;
- a local optimum is shown with a warning and never called optimal;
- no Redis;
- no GPU lane;
- no LLM / natural-language-to-model work;
- nothing is bought: commercial solvers come with the customer's own licence.

---

## 2. Scoreboard

| Area | Items | Delivered | In progress | Not delivered |
|---|---|---|---|---|
| Product foundation (roadmap phases 0–5) | 6 | 6 | — | — |
| Hardening (target roadmap phases 6–17, as scoped) | 48 | 48 | — | parts of 14 and 17 by decision (§5.3) |
| Spatial / GIS (GIS 1–10) | 10 | 10 | — | — |
| Blockly edit mode (Blocks 0–4) | 5 | 5 | — | — |
| Roadmap queue R1–R22 (incl. R8b/c, R15a–c, R16a–b, R17a–d, R20a–b) | 31 | 31 | — | — |
| Track A — planner re-optimization and "why not?" (R23–R28) | 6 | 6 | — | two follow-ups (§5.4) |
| Track D — any native solver, customer's licence (R41–R44) | 4 | 4 | — | vendor manifests untested (§5.4) |
| Track B — model CI and shadow runs (R29–R32) | 4 | 4 | — | — |
| Track C — scale and enterprise (R33–R40) | 8 | 0 | — | all 8, waiting on customer demand (§5.2) |

---

## 3. Delivered

Each line was built, tested (`scripts/check.sh`: lint, typecheck, ~2,100 frontend and ~4,000
backend tests), deployed from a clean worktree, and checked live in a browser or through the API.
The commit is the one that did it. Migrations were rehearsed up, down and up on a copy of the
live database.

### 3.1 Product foundation — roadmap phases 0–5 (2026-09-16 → 09-21)

| Phase | Delivered | Commit |
|---|---|---|
| 0 | **The model contract**: a JSON problem IR with a published contract (`docs/contracts/problem-ir.md`), one validator in Python and TypeScript with the same refusal codes, shared fixtures | `7c283a1` |
| — | **The traversal gap closed**: rules can walk relationships (`via`) | `cb7a684` |
| 1 | **Model authoring**: the Model editor (forms), with the IR document underneath | `90eef1e`, `349a863`, `c4b76a6` |
| 2 | **Solver selection** for every linear class: capabilities as data, one choosing policy, each run records why | `24c894e`, `aeb5a6e` |
| 3 | **Runs**: data frozen at submit, the queue and worker, immutable runs | `dac2f03` |
| 4 | **Results and why**: rules held or bent, slack, duals, reduced costs, the answer in people's names | `9dafbd1`, `f89c152`, `edff8ad` |
| 5 | **Roles and configuration**: capabilities per role, settings per platform / domain / problem | `671fac8`, `237049c` |
| 7 | **Multi-tenancy, auth, quotas, fair queueing**: row-level security per organization, API keys, per-organization quotas, the fair claim | see `2026-09-22-handover.md` |

Also on 09-22:
- quadratic goals and rules;
- SCIP as the global solver;
- the showcase templates (feed blend, load balance, workshop);
- the golden suite (hand-solved models that every solver must agree on);
- the benchmark harness.

### 3.2 Hardening — target roadmap phases 6–17

| Item | What it gives | Commit |
|---|---|---|
| P0: flaky frontend test | an editor race found and fixed; 16 runs green | `fb8843c` |
| P0: weekly rota infeasible on a new domain | the template's coverage is a target; solves to 3669 | `e4cd513` |
| P0: non-superuser DB login | the app connects as `solver_runtime`; migrations as the owner | `9c2f2be` |
| 6: CI + nightly bench | `scripts/nightly.sh`, a Windows task at 03:00 | `49de003` |
| 6: primal integral | measured in the bench from streamed incumbents | `8d4904a` |
| 6: array loading | 10x faster model build for GLOP and the MILP wrapper | `d803b6b` |
| 6: CP-SAT fractional scaling | behind a setting; the bench keeps it off | `f823737` |
| 6: MIPLIB | ten instances, 0 wrong against published optima | — |
| 8: structured logs | JSON logs with run, organization, solver | `7d64ba5` |
| 8: metrics | `/metrics` on the API and worker | `6470b48` |
| 8: tracing | OpenTelemetry, one trace from request to solve | `c2cc8c9` |
| 8: ClickHouse run facts | every settled run, via an outbox | `efcd359` |
| 8: event retention | pruned after a setting (30 days) | `9b4d2b4` |
| 9: sandboxed solves | memory and CPU limits per solve; children cannot dump core | `6342afb` |
| 10: IR v2 contract | with Pydantic parity | `d8a4473` |
| 10: conditional rules | indicators and implications | `51a0079` |
| 10: big-M | from declared bounds | `ec0c7e4` |
| 10: curves | piecewise-linear | `6ebc2a1` |
| 10a–d: scheduling | intervals, no-overlap, cumulative, precedence; the template and the editor | `3b629fa`, `cf75153`, `2ff854d`, `5343dc6` |
| 11: explanations | native IIS (HiGHS), CP-SAT assumption cores, minimal conflicts, a business-language panel | `79d8b1a`, `3ec5a42`, `4cd7b4b` |
| 12: result cache | an unchanged question is answered without a solve | `0a5dd98` |
| 12: warm starts | hints from the nearest earlier answer | `21bff11` |
| 13: symmetry breaking | — | `bae4704` |
| 13: solver-parameter techniques | behind the bench gate | `e69e824` |
| 15: Pareto | a trade-off front with its chart | `1e78f90` |
| 15: uncertainty | in the IR, with robust counterparts | `df34fc4`, `5827038` |
| 16: nonlinear | function catalogue with convexity labels, DCP detection, McCormick, SOCP detection | `0c89b46`, `9a1195d`, `3f71f80`, `e550d2f` |
| 14a/b: separable blocks | found and solved in parallel; on by default (3–17x faster) | `d4abc92`, `28a59d0` |
| 17: fingerprints | a fingerprint for every run, stored | `c6cb42b` |
| 17a: per-problem memory | the problem's own history picks the solver | `ae3605e` |
| 17b: probe race | admissible solvers raced briefly; off by default | `dfeb0a4` |
| GenUI workspace, phase 1 | — | `3a94ff6` |

### 3.3 Spatial and GIS (GIS 1–10)

| Item | Delivered | Commit |
|---|---|---|
| GIS 1 | a geometry attribute type | `465989e` |
| GIS 2 | projection and the pure grid | `a21a054` |
| GIS 3 | the grid generator, API and form | `b2c8122` |
| GIS 4–6 | the `connected` rule: contract, exact flow compile, editor | `3b51256`, `99f0f6b`, `6bf376e` |
| GIS 7 | the map: GeoJSON of a run, the map component, export | `f990a6c` |
| GIS 8 | the region-partitioning template and the districting bench | `6f5a934` |
| GIS 9 | basemaps from the Egypt tile server under every map | `0a9cc91` |
| GIS 10 | elevation and slope per grid cell from terrain-RGB | `c27889c` |

### 3.4 Blockly edit mode (Blocks 0–4)

| Item | Delivered | Commit |
|---|---|---|
| Blocks 0 | the implementation plan | — |
| Blocks 1 | one shared draft store behind every editor | `fb1e285` |
| Blocks 2 | editable blocks for declarations, rules and goals, with an exact round trip | `c2d5579` |
| Blocks 3 | every advanced construct as a block, round-tripped over every fixture and template | `3feccaa` |
| Blocks 4 | refusals shown on the block, a dry-run validate route, Edit mode in the optimization view | `2a06560` |

### 3.5 The roadmap queue R1–R22

| Item | What it gives | Commit |
|---|---|---|
| R1 | PDLP for very large LPs (answers labelled `approximate`) | — |
| R2 | portfolio racing | `36428ae` |
| R3 | large-neighbourhood search | `50e00f3` |
| R4 | near-separable detection | `e3938ec` |
| R5 | a Lagrangian bound | `86df3c0` |
| R6 | IPOPT, a local nonlinear lane (answers labelled `local`) | `94b5829` |
| R7 | two-stage stochastic programming (sampled futures) | `f69a7b8` |
| R8, R8b, R8c | chance constraints: solver, editor, held below the asked share in sample | `ffee3c5`, `11beacd`, `6c38021` |
| R9 | rolling horizon | `093a03e` |
| R10 | tuning search per template family | `f18b8ea` |
| R11 | a learned solver selector, in shadow mode only | `2753b0b` |
| R12 | decomposition per template, exact where it applies | `ccad0ae` |
| R13 | connectivity at scale (a connected, balanced districting start) | `6265edf` |
| R14 | a metaheuristic lane (genetic algorithm, particle swarm, CMA-ES) | `c8f3995` |
| R15a | a network lane (min-cost flow) | `6ae302b` |
| R15b | vehicle routing | `5b994a0` |
| R15c | time windows on routes | `c7041ed` |
| R16a | straight-line distances from the map | `5526a8d` |
| R16b | road distances and travel times | `cf0c0cd` |
| R17a–d | views: every decision drawn by its shape; Gantt, timeline, maps, spreads, input views, calendars, uncertain values as ranges | `25f022a`, `607e3f5`, `5965e9f`, `9b25080` |
| R18 | entity-type inheritance | `50e2eba` |
| R19 | rules reading relationship (edge) attributes | `854bb8f` |
| R20a/b | reference attributes; entity-valued parameters | `b772a52`, `93f9cd1` |
| R21 | download templates and bulk uploads (CSV and Excel), with per-row faults | `e10b336` |
| R22 | the app's look: icon sidebar, Ctrl K palette, dark mode, right-to-left | `bc6159b` |

### 3.6 Track A — planner re-optimization and "why not?" (R23–R28) — **complete**

The planner can hold what is committed, re-plan the rest with the fewest changes, and ask why a
plan is not otherwise.

| Item | What it gives | Migration | Commit | Live evidence |
|---|---|---|---|---|
| R23 | every run keeps its amounts; warm starts hint them | — | `eb2d670` | a second run started from the first, 105 cells hinted |
| R24 | **locks**: one cell, a slice of an earlier run ("Monday as run 812 had it"), or everything before a date. Locks are named rules, so a clash names the lock | — | `91c191b` | Monday kept cell for cell, cost unchanged at 3669 |
| R25 | **stay close to a base plan**: weighted, or cheapest-first-then-fewest-changes | — | `9a99254` | one lost shift: a cold re-plan moved 24 cells, stay-close moved **4**, same cost |
| R26 | **"why not?"**: already so / blocked (the rules that forbid it) / possible (the cost and what moves) / unanswered | 0069 | `75e2db2` | two shifts in a day blocked by the one-shift rule; an empty cell possible at +0, moving 4 |
| R27 | **how far each number may move** (LP ranging) and **what-if** values on a copy of the data | 0070 | `4f1b722` | protein worth 2.06/unit between 11.6 and 35.25 kg; soy 10% cheaper saves exactly 0.484127 |
| R28 | **the planner's tools on a run**: keep part and solve the rest, why not?, ranges | — | `cdb17a5` | in a browser: why-not answered (+4, 2 cells); keep Monday, solve the rest, Monday unchanged |

### 3.7 Track D — any native solver, with the customer's licence (R41–R44) — **complete**

Asked for 2026-09-26: "facilities to add any native commercial solver", with nothing bought.
Everything is proved with free solvers standing in for commercial ones.

| Item | What it gives | Migration | Commit | Live evidence |
|---|---|---|---|---|
| R41 | **adapters from a manifest**, three kinds: an OR-Tools engine (Gurobi / Xpress / CPLEX arrive this way), any command-line program (MPS in, solution out), or a Python function. Claims are bounded by kind; a broken manifest is skipped with its reason | — | `6e495a8` | cbc, highs-cli and python-cpsat each solved the rota to 3669 by name |
| R42 | **per-organization licences**: encrypted, write-only, handed only to that organization's sandboxed solve and scrubbed from every error; allowed and denied solver lists | 0071 | `119e170` | no licence: refused; wrong key: error shows `[licence]`; right key: solved |
| R43 | **the conformance kit**: an added solver is chosen automatically only once its current version passes the checks every built-in meets | 0072 | `593b470` | cbc passed 10 of 10 checks (not honouring a stop is a note), then became eligible |
| R44 | **the Solvers page**: every solver, its status, conformance, write-only licence form | — | `bdb2299` | in a browser: 13 solvers listed; a licence set shows only its fingerprint |

The guide is [`docs/solver-adapters.md`](docs/solver-adapters.md). Reference adapters are in
`backend/adapters/reference/`.

### 3.8 Track B — model CI and shadow runs (R29–R32) — **complete**

| Item | What it gives | Migration | Commit | Live evidence |
|---|---|---|---|---|
| R29 | **acceptance cases**: any answered run becomes a case (its frozen data, patch and answer), asked again of any version, judged with reasons | 0073 | `5894e4d` | the blend case passed on its version; a 25 kg-protein version failed: "the objective is 53.849206, expected 43.531746" |
| R30 | **the gate**: a new version is put into use only once it passes every case. Checks run after plan runs. A checks panel on the Model versions page | 0074 | `73c4916` | a reworded version refused, checked, passed, accepted; a dearer one failed and stays refused |
| R31 | **shadow runs**: a candidate version (`shadow.version`) answers a share (`shadow.rate`) of real runs beside the live one; twins are hidden; `GET /problems/{id}/shadow` compares | 0075 | `23c02b9` | feed blend: twin 348 of run 347, both optimal at 43.531746, delta 0, twin off the runs list; report share_at_least_as_good 1 |
| R32 | **nightly model CI**: every case re-asked with the cache off; failures and day-over-day regressions; fast subset in `check.sh` | 0076 | `a7db47d` | weekly_rota case re-asked optimal; Checks `nightly_regressed: false` |

### 3.9 Track C — scale and enterprise (R33–R40) — **R39 done; rest gated**

| Item | What it gives | Migration | Commit | Live evidence |
|---|---|---|---|---|
| R39 | **backups and DR**: nightly `pg_dump` + WAL under `SOLVER_BACKUP_DIR` (default sibling `solver-backups/`); restore rehearsal into `solver_restore` runs the suites; RPO 24 h / RTO 4 h | — | *(this commit)* | dump ~322 KB; restore + suite self-check case pass; `solver_restore` dropped; `archive_mode=on` |

---

## 4. In progress

None. R39 is live-checked. Remaining Track C items (R33–R38, R40) wait on a named customer need (§5.2).

---

## 5. Not delivered

### 5.1 Planned next (Track B)

Track B is complete (R29–R32). R39 (backups) of Track C is done.

### 5.2 Planned, waiting on a named customer need (Track C, R33–R40)

By the plan's rule, none of these starts without a customer (or signed pilot) that needs it.
**R39 is done** (local host folder as the object store; sync elsewhere if you want off-box copies).

| Item | What it is | Unlocked by | Decision needed from you |
|---|---|---|---|
| R33 | worker scale-out and queue metrics; a load test showing fair shares | queue waits over 1 min at peak, or more than ~10 concurrent solves | none (no Redis) |
| R34 | an append-only audit log, exportable | a regulated customer or a security questionnaire | retention default |
| R35 | single sign-on, OIDC first | a customer on Okta, Entra ID or Google | which identity provider; adding `authlib` |
| R36 | SCIM user provisioning | more than ~200 users, or automatic deprovisioning | needs R35 |
| R37 | data retention, organization deletion and full export | a GDPR request or a contract clause | retention defaults; deletion report wording |
| R38 | Kubernetes / Helm deployment | a customer hosting it themselves, or moving off one machine | target cluster; managed Postgres or not |
| ~~R39~~ | ~~backups and disaster recovery~~ | **done** — see §3.9 | — |
| R40 | per-organization solve limits and priority tiers | tiered pricing | tier definitions |

### 5.3 Deliberately not built (standing decisions)

| Not built | Why | What would change it |
|---|---|---|
| GPU lane (cuOpt, cuPDLP) | no instance needs it; it costs infrastructure | a tenant with such instances |
| Natural language to model (LLM) | a standing default: tenant data would leave the platform | a decision on provider and data policy |
| Redis | Postgres holds the queue well past the load seen | a measured load that needs it |
| Automatic Dantzig–Wolfe; full branch-and-price | research-grade; decomposition is per template (R12) | a template whose gaps demand it |
| Learned variable fixing; GNN branching | research-stage | a solver shipping it, or months of run data |
| The learned selector *acting* | R11 runs in shadow mode only; the rules still choose | its predictions proving better on stored runs |
| Buying commercial solver licences | the user decides no spending; Track D lets customers bring theirs | — |
| A hosted CI workflow | there is no git remote to run it on; CI is `scripts/check.sh` plus the nightly task | a remote |
| A Prometheus server | metrics are exported, but nothing scrapes them permanently | an operations need |

### 5.4 Known gaps and follow-ups in delivered work

| Where | Gap |
|---|---|
| R28 | **Locking by clicking grid cells** is not built; pickers do it. **A what-if form** is not built; the API takes `override`. |
| R41 | The **Gurobi, Xpress and CPLEX manifests are untested** here, for want of a licence. They are documented, and a customer runs the conformance kit with theirs. |
| R43 | CBC (the reference) does not honour a stop request: recorded as a note; the sandbox stops it at its limit. |
| R29–R30 | Each checked version gets a scenario named "checks: version N", which appears in the Scenarios list. |
| R30 | An admin cannot override a failed gate with a reason; the setting `suite.required` turns the gate off per problem or domain. The audit trail for an override waits on R34. |
| R31 | Shadow runs do not yet have their own quota bucket; the rate (default 0) is the control. There is no shadow card in the UI yet; the report is API-only. |
| R24/R25 | Locks and stay-close are refused on a stochastic solve (each sampled future is compiled afresh). |
| R27 | Ranges exist only for linear models (none for whole-number models, by design); a GLOP answer is ranged by HiGHS only when HiGHS reaches the same plan. |
| R42 | Licences are encrypted under `SOLVER_SECRETS_KEY`, else a key derived from `JWT_SECRET`. Replacing that secret without setting the key first makes stored licences unreadable (runs say so). |
| Views (R17) | The GenUI assistant's floating chat and languages beyond English are not built (the no-LLM default; the language switch is a label). |

### 5.5 Waiting on an answer from you

| Question | Blocks |
|---|---|
| The chatbot icon design (`AI Button Redesign.html`): save the file into the repo, or run `/design-login`, and say which app it is for | the icon work |
| Where per-scenario data values should be stored (a data-model choice) | per-scenario data editing |
| The destination path for the `data_analytics` `.git` | that repository move |
| Which identity provider (R35) | Track C SSO, when a customer needs it |

---

## 6. Running it

| Task | How |
|---|---|
| **Backups (R39)** | `bash scripts/backup.sh dump`; restore rehearsal: `bash scripts/backup.sh rehearse`. Files under `SOLVER_BACKUP_DIR` (default `D:\solver-backups`). Runbook: `docs/runbooks/backups.md` |
| **Full check** | `SOLVER_BACKEND_IMAGE=solver-backend-test bash scripts/check.sh`: lint, typecheck, frontend tests, build, backend tests against a `_test` database, about 18 minutes. It mounts the working tree, so it tests uncommitted changes. |
| **One backend test file** | `docker run --rm --network solver_solver_net -v "D:/solver/backend:/app" -w /app --env-file D:/solver/.env solver-backend-test sh -c 'TEST_DATABASE_URL=${DATABASE_URL}_test pytest -q tests/<file>'` (`.env` is never read by hand) |
| **Migration rehearsal** | `pg_dump` the live database into `solver_migtest`, then `alembic upgrade head`, `downgrade -1`, `upgrade head`, then drop the copy |
| **Deploy** | from a clean worktree (`git worktree add -f ../solver-deploy HEAD --detach`): build `solver-backend:latest` / `solver-frontend:latest`, run `docker compose run --rm --no-deps -T backend alembic upgrade head`, then `docker compose up -d --no-build backend worker frontend` |
| **After every deploy** | check the image age (`docker images`), `alembic current`, and a route the change added. On 2026-09-26 a quiet build finished without building. Then `docker image prune -f`. |
| **Live checks** | `frontend/_browser_check_*.mjs` (gitignored): API and Playwright scripts, one per item |
| **Nightly** | the Windows task `solver-nightly` at 03:00 (`scripts/nightly.sh`); do not run `check.sh` then (it shares the test database) |
| **Adding a solver** | [`docs/solver-adapters.md`](docs/solver-adapters.md) |

**Secrets:** none are in this file or the repository. Credentials live in the gitignored `.env`
and `.env.runtime`, and the solver-licence key in `SOLVER_SECRETS_KEY` (see R42).

## 7. Where things are

| Document | What it holds |
|---|---|
| [`docs/plans/2026-09-22-execution-queue.md`](docs/plans/2026-09-22-execution-queue.md) | every item, ticked, with its evidence |
| [`docs/plans/2026-09-24-session-handover.md`](docs/plans/2026-09-24-session-handover.md) | one row per delivered item since 09-24; operational notes |
| [`docs/plans/2026-09-22-handover.md`](docs/plans/2026-09-22-handover.md) | standing procedures; the **State** line names the deployed commit |
| [`docs/plans/2026-09-26-planner-ops-scale-plan.md`](docs/plans/2026-09-26-planner-ops-scale-plan.md) | the plan for Tracks A–D (R23–R44) |
| [`docs/plans/2026-09-22-optimization-target-roadmap.md`](docs/plans/2026-09-22-optimization-target-roadmap.md) | phases 6–17 and their decisions |
| [`docs/plans/2026-09-20-platform-roadmap.md`](docs/plans/2026-09-20-platform-roadmap.md) | phases 0–5, the product |
| [`docs/contracts/problem-ir.md`](docs/contracts/problem-ir.md) | the model contract |
| [`docs/solver-adapters.md`](docs/solver-adapters.md) | adding a solver |
| `backend/bench/results/` | every benchmark behind a default setting |
