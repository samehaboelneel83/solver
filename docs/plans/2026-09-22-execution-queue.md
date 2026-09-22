# Execution queue — 2026-09-22

The ordered list of what remains, one work item per line. Take the first
unchecked item, finish it (built, tested, `scripts/check.sh` green, deployed,
verified live, committed), tick it, and only then start the next. An item
that proves bigger than one sitting is split here: tick what is done, add the
rest as new unchecked lines in its place. An item that proves wrong or
unnecessary is struck through (`~~…~~`) with a one-line reason.

Plan of record: [the target roadmap](2026-09-22-optimization-target-roadmap.md)
(phases 6–17). State and procedures: [the handover](2026-09-22-handover.md).

Standing defaults: a tenant is an organization; one solve per subprocess; a
local optimum is shown with a warning, never called optimal; no Redis; no GPU
lane; no LLM / NL→IR work.

## P0 — known problems

- [x] (P0) Intermittent frontend test failure — done when the race in the editor is found and fixed, and `vitest` passes 10 runs in a row. *(`fb8843c`: react-querybuilder's mount report wrote a stale rule over fresh edits; 10 plain + 6 shuffled runs green.)*
- [x] (P0) `weekly_rota` on an empty domain is infeasible — done when applying the template to a new domain and solving gives an optimal answer, pinned by a test. *(`e4cd513`, `ca6580e`: the template's coverage is a target (soft, 100); start-up now refreshes the template; live run optimal at 3669, the hand-worked value.)*
- [x] (P0) Non-superuser Postgres login role for the app — done when API and worker connect as a role that is not a superuser and owns nothing, migrations still run as the owner, and tenant isolation holds live. *(`9c2f2be`, migration 0037: `solver_runtime`. Amended: the line first said "without BYPASSRLS", which 0032's design rules out -- system code sees every tenant -- so the role keeps it.)*
- ~~(P0) API requests log in without BYPASSRLS~~ — struck: `set_config('app.org_id', …)` needs no privilege either (shown live: a `solver_app` session went from 0 runs to another organization's 37 with one call), so no login role can stop SQL in the same session from changing tenant; RLS on a session setting guards against app bugs, and the defence against injection is parameterised SQL (checked: every interpolated SQL fragment in `backend/app` is a module constant or an integer route id). An unforgeable tenant is recorded as a Phase 7 idea in the roadmap.

## Phase 6 leftovers

- [x] (6) CI + nightly benchmark — done when a CI job runs `scripts/check.sh` and a scheduled job runs the L-size bench with `--store`, both runnable locally. *(`49de003`, `08ed49e`: `scripts/nightly.sh`, scheduled as the Windows task `solver-nightly` at 03:00. A hosted workflow was not written: there is no git remote for it to run on.)*
- [x] (6) Primal integral — done when the bench computes it from streamed incumbents, it appears in `bench.run` rows and the report, checked against a hand-computed curve. *(`8d4904a`, migration 0038: `bench.primal`; stored in `bench_result.primal_integral`.)*
- [ ] (6) Array-building for GLOP and the MILP wrapper (measure first) — done when a proto/array load is measured against today's per-row build on the 200,000-entry model and adopted only if it wins, with the numbers committed.
- [ ] (6) CP-SAT fractional scaling — done when fractional models with ≤4 decimals can be admitted to CP-SAT behind a setting (default off), with golden cases and a bench report deciding the default.
- [ ] (6) Download MIPLIB — done when `bench.download_miplib` has fetched the easy subset and the MPS lane has run on it with a committed result.

## Phase 8 — observability

- [ ] (8) Structured logs — done when API and worker emit JSON logs via `structlog` with `run_id`, `org_id`, `solver` bound.
- [ ] (8) Metrics and `/metrics` — done when `solve_seconds`, `run_gap`, `queue_depth`, `queue_wait_seconds`, `worker_busy` are exported on the API and a worker port and scraped live.
- [ ] (8) OpenTelemetry tracing — done when a run's API span and its worker spans (`compile`, `choose`, `solve`, `diagnose`, `persist`) share one trace through `run.params.trace`, exporter configurable.
- [ ] (8) ClickHouse `run_fact` writer — done when every settled run inserts one `run_fact` row, verified live.
- [ ] (8) `run_event` retention — done when events older than the setting (default 30 days after settle) are pruned by the worker, pinned by a test.

## Phase 9 — isolation

- [ ] (9) Sandboxed solves with memory/CPU limits — done when each solve runs in its own subprocess with `RLIMIT_AS`/`RLIMIT_CPU` and a hard wall deadline, an OOM model ends `failed` with a reason and the worker survives, and compose sets `mem_limit`/`cpus`.

## Phase 10 — IR v2, in slices

- [ ] (10) Contract v2 + Pydantic parity — done when `ir/contract.json` is version 2 (v1 documents valid), Pydantic models exist and a parity test binds them to the contract.
- [ ] (10) Indicators and implications — done when `when/then` rules solve natively on CP-SAT and SCIP, with equivalence tests and golden cases.
- [ ] (10) Big-M from declared bounds — done when HiGHS/MILP take indicators through a tight M from declared bounds and refuse, naming the variable, when a bound is a default.
- [ ] (10) Piecewise-linear — done when `pwl` terms solve on every backend that accepts them (epigraph / incremental / element / SOS2), equivalence-tested.
- [ ] (10) Scheduling constructs — done when interval variables, `no_overlap` and `cumulative` solve on CP-SAT, other backends refuse with a reason, and a scheduling template + bench family exist.
- [ ] (10) Editor, validators and all four graph styles — done when every v2 construct can be built in the editor, the TS validator matches the Python one, and all four Optimization View styles draw them.

## Phase 11 — explanations

- [ ] (11) Native IIS — done when HiGHS LP conflicts come from its own IIS (or a measured fallback), with probes and time compared.
- [ ] (11) CP-SAT assumption cores — done when CP-SAT diagnoses via enforcement literals and `SufficientAssumptionsForInfeasibility`.
- [ ] (11) Minimal conflicts — done when cores are shrunk to minimal by deletion filtering on the core only, and `conflict_minimal` is honest.
- [ ] (11) Explanations UI — done when the run page shows the new conflicts in business language, verified in a browser.

## Phase 12 — reuse

- [ ] (12) Result cache — done when a submit matching a proven-optimal run returns a new run with `reused_from` and no solve.
- [ ] (12) Warm starts — done when the nearest prior run hints CP-SAT, HiGHS and SCIP behind `solve.warm_start` (default off), with a bench report on the default.

## Phase 13 — search power

- [ ] (13) Symmetry breaking — done when identical entities get ordering rules on HiGHS/MILP only, equivalence-tested, default decided by the bench.
- [ ] (13) Solver-parameter techniques behind the benchmark gate — done when the whitelisted parameter settings are measured by the harness and only winners are enabled, with reports committed.

## Phase 15 — multiple objectives and uncertainty

- [ ] (15) Pareto with trade-off chart — done when two objectives yield an epsilon-constraint front stored as points and drawn on the run page, each point linked to its run.
- [ ] (15) IR uncertainty — done when parameters may declare `uncertainty {interval|scenarios, deviation, gamma}` in the contract and editor.
- [ ] (15) Robust solving — done when Bertsimas–Sim Γ rows are reformulated exactly, equivalence-tested, and the price of robustness is reported.

## Phase 16 — nonlinear

- [ ] (16) Function catalogue with convexity labels — done when a closed catalogue of functions, each labelled convex/concave/neither, is in the contract and editor.
- [ ] (16) DCP detection — done when term trees are classified convex/concave/unknown by composition rules, pinned by tests.
- [ ] (16) McCormick — done when bilinear terms with declared finite bounds get McCormick envelopes where used, equivalence-tested on tiny models.
- [ ] (16) SOCP detection — done when second-order-cone rules are recognised and routed to SCIP.

## Phase 14 — scale (only this part)

- [ ] (14) Separable blocks — done when a model whose incidence graph has >1 component is solved block by block in parallel, objective summed, status the worst, checked against the monolithic answer.

## Phase 17 — learning (only this part)

- [ ] (17) Run fingerprint + stored facts — done when every run computes and stores its fingerprint and it reaches `run_fact`.
