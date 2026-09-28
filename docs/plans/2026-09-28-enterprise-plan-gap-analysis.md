# Enterprise plan v1.2 — gap analysis against the repository

**Date:** 2026-09-28 · **Base commit:** `2b66ebb` · **Status:** Sprint 0 of the technical implementation plan

The technical implementation plan (v1.2, written 2026-09-28) assumed a linear-only modeling app,
based on a design discussion from 2026-09-21. The repository is far ahead of that: `handover.md`
(as of 2026-09-26) and `OAAS_CUMULATIVE_WORK_REPORT.md` (2026-09-28) record 150+ delivered items.
This document maps every area of the plan to what exists, so that only real gaps get built.

**Result:** about 85% of the plan is already delivered. The real gaps are one new capability area
(machine learning in modeling), five solver-engine completions, the open product/UX items from the
OAAS report, and one decision about commercial solvers.

## 1. Plan area → current state

| Plan area | State | Evidence in the repository |
| --- | --- | --- |
| IR as single source of truth, versioned contract | Delivered | `docs/contracts/problem-ir.md`, IR v2 with Pydantic parity (`d8a4473`), Python + TypeScript validators with the same refusal codes |
| Tier 1 IR: bounds, indicators, big-M from bounds, piecewise linear | Delivered | `51a0079`, `ec0c7e4`, `6ebc2a1` |
| Tier 2 IR: quadratic, nonlinear functions, DCP, McCormick, SOCP | Delivered | `0c89b46`, `9a1195d`, `3f71f80`, `e550d2f`; `solve/dcp.py`, `convexity.py`, `mccormick.py`, `socp.py` |
| Tier 3 IR: intervals, no-overlap, cumulative, precedence | Delivered | `3b629fa` … `5343dc6` |
| Classification + solver choice recorded per run | Delivered | `solve/classify.py`, `backends.py`, `24c894e` |
| Open-source solvers | Delivered | OR-Tools (CP-SAT, GLOP, routing, min-cost flow, PDLP), HiGHS, SCIP, IPOPT |
| Sandboxed solves, CPU/memory limits | Delivered | `solve/sandbox.py`, `6342afb` |
| Queue, worker, fair claim, immutable runs | Delivered | Postgres queue (standing decision: no Redis) |
| Result cache, warm starts | Delivered | `solve/cache.py`, `warm.py` |
| Independent verification of answers | Delivered | `solve/verify.py`, `docs/contracts/result-verification.md` |
| Duals, reduced costs, LP ranging, what-if | Delivered | R27 `4f1b722` |
| IIS / minimal conflicts, business-language explanation | Delivered | `solve/diagnose.py` (deletion filter on solver cores), `79d8b1a` |
| "Why not?" and stay-close re-planning, locks | Delivered | Track A, R23–R28 |
| Pareto front (epsilon-constraint) | Delivered | `solve/pareto.py`, `1e78f90` |
| Uncertainty: robust, two-stage stochastic, chance constraints | Delivered | `df34fc4`, R7, R8 |
| Portfolio racing | Delivered | `solve/race.py` (R2, probe race 17b, off by default) |
| Large neighbourhood search | Delivered | `solve/lns.py` (R3) |
| Separable blocks, Lagrangian bound, per-template decomposition | Delivered | R4, R5, R12, `14a/b` |
| Parameter tuning behind a bench gate | Delivered | `solve/params.py`, R10 |
| Symmetry breaking | Delivered | `bae4704` |
| PSO, genetic algorithm, CMA-ES | Delivered | `solve/evolve.py` (R14) |
| Network lane, vehicle routing, time windows | Delivered | `solve/network.py`, `routing.py` (R15a–c) |
| Learned solver selector | Partial — shadow mode only | `solve/selector.py` (nearest neighbours on fingerprints) |
| Multi-tenancy (RLS), API keys, quotas, tiers | Delivered | Phase 7, R40 |
| OIDC SSO, SCIM, audit log, retention, org export/delete | Delivered | R34–R37 |
| Helm chart, worker scale-out, backups/DR | Delivered | R33, R38, R39 |
| Structured logs, metrics, OpenTelemetry, ClickHouse run facts | Delivered | Phase 8 |
| Offline / air-gapped install | Delivered, partly | `scripts/offline-bundle.sh`; clean-machine test still open (OAAS §12 P2) |
| Model CI, shadow runs, nightly bench, golden suite, MIPLIB | Delivered | Track B, Phase 6 |
| Editors: forms, blocks, graph, templates | Delivered, with open P1 items | OAAS report §2, §12 |

## 2. Real gaps

### 2.1 Machine learning in modeling (new; not in the repository)

No ML library is a dependency today (`grep sklearn|lightgbm|xgboost|onnx` finds nothing).

| Item | From plan | What it adds |
| --- | --- | --- |
| ML-1 Forecast parameter source | §5.8.3 A | Parameters filled by a registered model; quantile random forests give p10/p50/p90; predictions frozen into the run's data snapshot with the model version |
| ML-2 Embedding tree ensembles in the MILP | §5.8.3 B | New IR term that lowers a random forest / boosted trees into rows and binaries, so the solver optimizes over the prediction |
| ML-3 Run-time estimate | §5.8.3 C | Random-forest ETA shown before and during a run |
| ML-4 Model registry | §5.8.3 D | Models stored as JSON/ONNX (never pickle), versioned, per organization, audited |

Constraints from standing decisions: offline install (the wheels must go into the offline bundle),
no data leaving the platform (training runs on the worker, in the sandbox).

### 2.2 Solver-engine completions

| Item | State today | Gap |
| --- | --- | --- |
| E-1 Solution pool ("show 5 alternative plans within 2%") | Not present | No-good cuts under an objective bound; diversity mode |
| E-2 Multistart NLP | IPOPT lane labels answers `local` | Several starting points, best-of-N, optional SCIP bound for small models |
| E-3 Generic Benders | Decomposition is per template (R12) | A general master/sub loop for models annotated with stages |
| E-4 Learned selector acting | Shadow only (R11) | Switch on per class once stored-run evidence shows it beats the rules (the handover's own condition) |
| E-5 Faster IIS on large models | Deletion filter on the solver core | QuickXplain splitting when the core is large |

### 2.3 Product and UX (open items from `OAAS_CUMULATIVE_WORK_REPORT.md` §12)

| Priority | Work package |
| --- | --- |
| P1 | Navigation completion (searchable large collections, deep-link/role matrix) |
| P1 | Complete graph authoring (inspectors, typed connections, keyboard authoring) |
| P1 | Guided pattern expansion (scheduling/routing patterns, units, model review) |
| P1 | Import/mapping workflow (source setup, preview, mapping, dataset publication) |
| P1 | Pre-run and result experience (required inputs, compatible solvers, status explanations) |
| P2 | Release validation, product/solver benchmarks, portable offline distribution |

### 2.4 Decision needed: commercial solvers

The plan's v1.1 removed Gurobi and CPLEX. In the repository they are **not bundled or required**:
Track D (R41–R44) lets an organization plug in its own licensed solver through a manifest, and the
standing decision is "nothing is bought". The Gurobi/CPLEX/Xpress manifests are documented but
untested. Two options:

| Option | Effect |
| --- | --- |
| A. Keep Track D as is | The platform runs fully on open-source solvers; customers who own a licence can still plug theirs in. No code change. |
| B. Remove commercial adapters | Delete the Gurobi/CPLEX/Xpress manifest guidance and the licence store (R42), keep only open-source backends. Removes a delivered customer feature. |

## 3. Proposed order

1. **Epic ML** (2.1) — the only capability area that is entirely missing, and the one asked for most recently.
2. **Epic ENGINE** (2.2) — E-1 and E-2 first (small, visible to users), then E-5, E-3, E-4.
3. **Epic UX** (2.3) — the P1 items in the OAAS report's recommended sequence.

Each epic stops for review before the next starts.

## 4. Verification limits of this analysis

- Based on the documents and a code search of the shallow clone at `2b66ebb`; the full test suite
  was not run here (`scripts/check.sh` needs the Docker stack and a test database).
- "Delivered" is taken from `handover.md` and checked by the presence of the named module or commit;
  behaviour was not re-tested.
