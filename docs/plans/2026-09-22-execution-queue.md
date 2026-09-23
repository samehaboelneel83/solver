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
- [x] (6) Array-building for GLOP and the MILP wrapper (measure first) — done when a proto/array load is measured against today's per-row build on the 200,000-entry model and adopted only if it wins, with the numbers committed. *(`d803b6b`: proto load 0.435 s → 0.043 s on 200,000 entries, 1.56 s → 0.37 s on facility-XL; `bench/results/2026-09-23-pywraplp-build.md`.)*
- [x] (6) CP-SAT fractional scaling — done when fractional models with ≤4 decimals can be admitted to CP-SAT behind a setting (default off), with golden cases and a bench report deciding the default. *(`f823737`, migration 0039: `solve.cpsat_scaling`; the bench says it stays off -- CP-SAT wins up to L but is 2.6x/9.4x slower on the XL rota.)*
- [x] (6) Download MIPLIB — done when `bench.download_miplib` has fetched the easy subset and the MPS lane has run on it with a committed result. *(ten instances plus MIPLIB's solution file; 0 wrong against the published optima; `bench/results/2026-09-23-miplib.md`.)*

## Phase 8 — observability

- [x] (8) Structured logs — done when API and worker emit JSON logs via `structlog` with `run_id`, `org_id`, `solver` bound. *(`7d64ba5`: `app.core.logs`; checked live on both containers.)*
- [x] (8) Metrics and `/metrics` — done when `solve_seconds`, `run_gap`, `queue_depth`, `queue_wait_seconds`, `worker_busy` are exported on the API and a worker port and scraped live. *(`6470b48`: internal ports 9101 (API) and 9100 (worker), unpublished; scraped from the compose network. No Prometheus server is deployed.)*
- [x] (8) OpenTelemetry tracing — done when a run's API span and its worker spans (`compile`, `choose`, `solve`, `diagnose`, `persist`) share one trace through `run.params.trace`, exporter configurable. *(`c2cc8c9`: `OTEL_TRACES_EXPORTER` log/otlp/none; checked live across both containers.)*
- [x] (8) ClickHouse `run_fact` writer — done when every settled run inserts one `run_fact` row, verified live. *(`efcd359`, migration 0040: an outbox swept by the worker; live backfill 37/37, and a new run's fact within seconds.)*
- [x] (8) `run_event` retention — done when events older than the setting (default 30 days after settle) are pruned by the worker, pinned by a test. *(`9b4d2b4`, migration 0041: `run.event_retention_days`, per problem/domain/platform; pruned live at worker start.)*

## Phase 9 — isolation

- [x] (9) Sandboxed solves with memory/CPU limits — done when each solve runs in its own subprocess with `RLIMIT_AS`/`RLIMIT_CPU` and a hard wall deadline, an OOM model ends `failed` with a reason and the worker survives, and compose sets `mem_limit`/`cpus`. *(`6342afb`, `4a63e05`: `app.solve.sandbox`. The run status is `error` -- the enum has no `failed` -- with the reason; live, a 64 MB worker ended run 61 "ran out of memory (limit 64 MB)" and solved run 62 at 4096 MB, 0 restarts.)*

## Phase 10 — IR v2, in slices

- [x] (10) Contract v2 + Pydantic parity — done when `ir/contract.json` is version 2 (v1 documents valid), Pydantic models exist and a parity test binds them to the contract. *(`d8a4473`: `acceptedVersions` [1, 2]; `app/ir/models.py`; `tests/test_ir_models.py` places every rule as structural or semantic.)*
- [x] (10) Indicators and implications — done when `when/then` rules solve natively on CP-SAT and SCIP, with equivalence tests and golden cases. *(`51a0079`: a constraint's `when: {var, index, is}`; OnlyEnforceIf / addConsIndicator; 80 brute-force equivalence cases; live 44 on CP-SAT and SCIP.)*
- [x] (10) Big-M from declared bounds — done when HiGHS/MILP take indicators through a tight M from declared bounds and refuse, naming the variable, when a bound is a default. *(`ec0c7e4`: `app/solve/reformulate.py`; 160 brute-force equivalence cases on four backends; live: HiGHS 44 via big-M, unbounded to SCIP, forced HiGHS refused naming `ship_a`.)*
- [x] (10) Piecewise-linear — done when `pwl` terms solve on every backend that accepts them (epigraph / incremental / element / SOS2), equivalence-tested. *(`6ebc2a1`: CP-SAT AddElement, SCIP SOS2, HiGHS/MILP epigraph or incremental, GLOP epigraph only; 7 hand-worked models with takers asserted, 200 random cases against exact fractions; live: CP-SAT 13, HiGHS 13 incremental, GLOP 5 epigraph, a version 1 curve a 422. Fix-forward `d65b6d5`: the editor and graph views threw on a curve (`describeTerm` read it as a product) -- found by review, reproduced live in a browser, fixed; a browser now opens a curve model in the editor and all four styles with no page error.)*
- [x] (10a) Scheduling constructs — done when interval variables, `no_overlap` and `cumulative` solve on CP-SAT (hand-worked and brute-force-equivalence tested, named in conflicts), other backends refuse with a reason, and the editor and graph views show them read-only without error. *(`3b629fa`: domain `interval` {start, end, size, presence}; rules `no_overlap` / `cumulative` {interval, over[, demand, capacity]}; ten rule codes in both validators; 40 random models against every placement; live: one mill 9, two at a time 6, too short infeasible with conflict `c_machine` (minimal), HiGHS refused with the reason, a fractional size refused by name, version 1 a 422; a browser opened the model in the editor and all four styles with no page error.)*
- [x] (10b) Scheduling template + bench family — done when a scheduling template applies and solves, and a bench family compares the interval formulation against a time-indexed one at growing horizons. *(Split from 10a, 2026-09-23: each is a full iteration. `cf75153`: template `workshop` (cut then weld, route as a relationship) -- live: applied, CP-SAT, 9 = Johnson's rule; families `flow_shop` / `flow_shop_timed` on identical data, both matching Johnson on 2 machines; at L (horizon ~125) intervals 0.03 s vs time-indexed 31 s on CP-SAT and no answer in 60 s on HiGHS/MILP/SCIP -- `bench/results/2026-09-23-flow-shop-formulations.md`. The time-indexed family is comparison-only, out of the nightly.)*
- [x] (10c) Editor: conditional rules and curves — done when a `when` and a `pwl` can be built in the editor and every Optimization View style shows them. *(Split 2026-09-23 from "Editor, validators and all four graph styles"; the TS validator already matched the Python one code for code through the shared fixtures, 10 rules for pwl/when/scheduling. `2ff854d`: "Only while a yes-or-no decision is set" on a rule, a curve's variable and decimal points in TermBuilder, a switch line and "Applies" row in the graph, the condition in the block view. Found and fixed: the editor kept a version 1 base's number, so a condition or curve could never be published from it. Live: a browser built both on a version 1 model, published version 2, and it solved on CP-SAT at 13.)*
- [x] (10d) Editor: intervals and scheduling rules — done when an interval variable and a `no_overlap` / `cumulative` rule can be built in the editor (today they are kept and shown read-only), and the Remove guard knows what they name. *(`5343dc6`: "a span of time" adds an interval with its start and end; its parts are chosen from declarations over its own sets; "Add a scheduling rule" and its editor (never overlap / share a capacity, For every, Over, interval, demand, capacity); `strandedBy` counts switches, scheduling rules and interval parts. Live: a browser built an interval and a no_overlap on three feeds, published; with a sum-of-ends goal it solved on CP-SAT at 18 = 3 + 6 + 9.)*

## Phase 11 — explanations

- [x] (11) Native IIS — done when HiGHS LP conflicts come from its own IIS (or a measured fallback), with probes and time compared. *(`79d8b1a`: `highs.iis` (strategy FromLp) proposes a core for any linear model, confirmed and shrunk with the run's own backend; no core, the full search. `bench/results/2026-09-23-native-iis.md`: never more probes, rota L 2 against 45, facility little saved, ~0.5 s fixed; HiGHS's Irreducible flag measured at 49 s vs 1 s and off. Live: feed blend with a 60 kg protein floor, infeasible on GLOP, conflict c_protein + c_fibre (worked by hand: 60 kg of protein carries at least 8.2 kg of fibre against a 5 kg cap), minimal, method iis, 3 probes, 0.48 s.)*
- [x] (11) CP-SAT assumption cores — done when CP-SAT diagnoses via enforcement literals and `SufficientAssumptionsForInfeasibility`. *(`3ec5a42`: `cpsat.core` -- a literal per rule instance beside any `when` switch, all assumed; `explain` takes an ordered list of named cores, a CP-SAT run trying its own first. Rota S/M/L: 2 probes against 24-45, 0.01-0.12 s. Live: x whole in 0..10 with 2x = 1 -- infeasible on CP-SAT, conflict c_half, minimal, method cp-sat, 2 probes, 0.008 s; HiGHS's relaxation offers nothing there.)*
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
