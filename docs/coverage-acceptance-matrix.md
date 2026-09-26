# Coverage and benchmark acceptance matrix (OAAS Q01)

**Purpose:** one place that states which mathematical classes the platform
claims to run, which built-in backends cover them, what “optimal” means, and
which recorded benches gate promotion.  
**Evidence paths** are relative to the repository root. This is not a market
ranking claim.

## How to read a claim

- **Class** — output of `app.solve.classify` (model class + capability needs).
- **Backend** — entry in `app.solve.backends` (or a verified adapter).
- **Proof** — `proves`: `global` | `local` | `approximate` (shown honestly in the UI).
- **Gate** — what must pass before changing defaults or promoting a selector.

## Built-in backends × classes

| Backend | Classes (declared) | Proof | Role |
|---|---|---|---|
| cp-sat | IP, MIQP, MIQCQP, trivial | global | Default combinatorial / scheduling / routing |
| glop | LP, trivial | global | Pure continuous LP |
| highs | IP, LP, MILP, QP, trivial | global | Mixed / LP when installed |
| milp | IP, LP, MILP, trivial | global | OR-Tools CBC-based generalist fallback |
| scip | QP, MIQP, QCQP, MIQCQP, IP, MILP, LP, NLP, MINLP | global (when applicable) | Broader nonlinear / MIP |
| pdlp | LP | approximate | Large LP; tolerance recorded |
| ipopt | NLP, QP, QCQP | local | Local nonlinear |
| cma-es / pso / ga | continuous (+ ga: some discrete) | approximate | Search heuristics; never labelled proven best |

Capability needs (scheduling, connected, route, quadratic, …) further restrict
which backends may be chosen — see `classify.py` refusals and each backend’s
`provides` set in `backends.py`.

## Adapter path

Customer adapters (`docs/solver-adapters.md`) are **never** chosen automatically
until the conformance kit passes for that version (`app.solve.conformance`).
Gurobi / Xpress / CPLEX manifests are documented but **untested here** without
a customer licence.

## Acceptance suites (correctness)

| Suite | What it protects | Where |
|---|---|---|
| Golden / hand-solved models | Solvers agree on known answers | Backend test suite + suite cases (R29) |
| Version checks / gate | Candidate model versions | `VersionChecks`, gate override audit (R30) |
| Shadow runs | Candidate vs production on real traffic | Shadow card (R31); rate default 0 |
| Nightly regression | Broader drift | Nightly infra (R32) |
| Adapter conformance | Customer solver eligibility | `python -m bench.conformance` / API |

## Recorded performance benches (evidence, not universal superiority)

| Report | Family / focus | Operator takeaway |
|---|---|---|
| `backend/bench/results/2026-09-24-portfolio.md` | Portfolio / scheduling mix | Some gains; some 2–4× slowdowns — leave portfolio off by default |
| `backend/bench/results/2026-09-25-selector.md` | Learned solver pick | Shadow only; confidence ≠ calibrated P(success) |
| `backend/bench/results/2026-09-23-miplib.md` | MIPLIB sample, two backends @ 60s | Regression evidence; not universal ranking |
| Other `backend/bench/results/2026-09-*.md` | Params, routing, network, metaheuristics, … | Promote only with equal-budget re-runs |

## Promotion policy (defaults)

1. Correctness suites green on the target family.
2. Equal CPU/memory budget vs the pinned baseline; publish regressions as well as wins.
   Use `python -m bench.equal_budget …` (`docs/contracts/family-policies.md`).
3. Learned selection and broad portfolios stay **shadow / off** until evidence supports them (current standing decision).
4. A release claim names the family, budget, and commit — never “fastest on all problems.”
5. Independent verification boundary: `docs/contracts/result-verification.md` (Q02);
   phase timings on runs: `params.phases` (Q03).

## Planner workflow acceptance (orthogonal to solver speed)

From OAAS Phase 1: find a problem, change a scenario, open the latest result,
and reopen a bookmark without silent substitution (see N02 / N06 tests).
