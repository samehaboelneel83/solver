# Platform check — 2026-09-22

A full check of the solver platform: every automated suite, the live stack,
and every scenario in the live database solved through the running worker.
It ends with what is still open and a recommended next step.

**Bottom line:** the platform is healthy. Every check passes, the live stack
matches the code, and every live scenario behaves as designed. The linear
side of the roadmap is complete. The next frontier is nonlinear models, and
the recommendation is to start with quadratic objectives, because that is the
one nonlinear class where "is this the best answer?" can be *proven* rather
than hoped.

---

## 1. Automated checks

Run with `scripts/check.sh` against the working tree, including the
uncommitted changes listed in §3.

| Check | Result |
|---|---|
| Frontend dependencies | match `package-lock.json` |
| Frontend lint (`--max-warnings 0`) | **pass** |
| Frontend typecheck (`tsc --noEmit`) | **pass** |
| Frontend tests (vitest) | **pass** |
| Frontend production build (vite) | **pass** |
| Backend tests (pytest, 1193 tests, isolated `solver_test` database) | **pass** |

**6 of 6 passed, none skipped, in 178 s.**

## 2. Live stack

| Item | State |
|---|---|
| Containers | `postgres`, `clickhouse` healthy; `backend`, `worker`, `frontend` up |
| API `/api/health` | 200 |
| Frontend `/` | 200 |
| API without a token | 401, as it should be |
| Live database migration | `0026`, which is the code's head |
| Backend and worker image | one shared image, built after the last commit, so all committed code is deployed |
| Worker | polling, idle |

### Solvers available in the running image

| Solver | Takes | Technique |
|---|---|---|
| `cp-sat` | IP | constraint programming |
| `glop` | LP | simplex |
| `highs` | IP, LP, MILP | HiGHS (in a child process) |
| `milp` | IP, LP, MILP | branch and cut (SCIP/CBC) |

### Every live scenario, solved through the worker

| Problem / scenario | Status | Class | Solver | Objective | Notes |
|---|---|---|---|---|---|
| weekly_rota / relaxed_cover | error | IP | cp-sat | — | Points at model version 1, which predates the IR contract and has nothing to solve. Correct behaviour, but see finding F4. |
| weekly_rota / relaxed_cover_solved | optimal | IP | cp-sat | 3621 | 0.01 s |
| weekly_rota / coverage_non_negotiable | infeasible | IP | cp-sat | — | Conflict set **proven minimal** |
| weekly_rota / traversal_acceptance | optimal | IP | cp-sat | 3669 | 0.006 s |
| weekly_rota / from run 19 | optimal | IP | cp-sat | 3621 | 0.007 s |
| weekly_rota_copy / as modelled | infeasible | IP | cp-sat | — | Conflict set **proven minimal** |

### The linear-programming path, in the running image

No live scenario is continuous, so the LP path was exercised separately: a
small feed-blending LP, solved in memory with nothing written to the
database.

| Step | Result |
|---|---|
| Classified as | **LP**, needs `continuous`, `fractional-data`, `linear` |
| Chosen | **glop**: "the highest-ranked solver for a LP model; highs, milp could also take it" |
| glop | optimal, 54.0 (barley 8, maize 30) |
| highs | optimal, 54.0, same answer |
| milp | optimal, 53.99999999999999, same answer (see F3) |
| cp-sat | **refused**: "cp-sat has no continuous variables". It refuses rather than rounding, as intended. |

Three independent techniques agree on the optimum, which is the strongest
evidence the selection policy and compiler are right.

---

## 3. Findings

None of these block anything. They are ordered by how soon they would bite.

**F1. Uncommitted work in progress is not deployed.** 15 tracked files carry
uncommitted changes (templates API, CRUD factory, meta routes, entity form,
term builder, roadmap, README; +360/−55 lines). All suites pass *with* those
changes. The backend image predates them, so they are not live. The
frontend image was built more recently and may include the frontend half.
If it does, the live frontend is ahead of the live backend. **Action:**
commit that work and rebuild both images together, or rebuild the frontend
from the last commit.

**F2. Scratch files at the repository root and in `frontend/`.** Eight
untracked `frontend/_browser_check_*.mjs` scripts and
`cursor-prompt-rule-editor-redesign.md`. **Action:** keep them deliberately
or add them to `.gitignore`, so they are not swept into a commit by accident.

**F3. `milp` reports a floating-point tail on continuous models**
(`53.99999999999999` for 54). The stored value is correct, because
`run.objective` is `numeric(15, 6)` and rounds it to `54.000000`, but an
in-memory result or comparison sees the tail. **Action:** round continuous
results to six decimal places at the backend boundary, which is the precision
the schema promises anyway.

**F4. A scenario that can only ever fail.** `weekly_rota / relaxed_cover`
points at model version 1, from before the IR contract. Every run of it errors,
correctly and with a clear reason. To an end user it still looks like a broken
button. **Action:** repoint it at a contract-era version or remove it from
the demo.

**F5. The demo has no continuous model.** LP, MILP, duals and reduced costs
are covered by tests and by the in-memory check above, but a person exploring
the live product never meets them. **Action:** add a small blending or
production-planning problem to the seed, so the platform's widest capability
is also its most visible.

**F6. Deprecation warnings that will become failures.** The backend suite
emits ~3,100 warnings. Most are harmless noise (`jose` calling
`datetime.utcnow()`, FastAPI's `on_event`), but one is a deadline: **`passlib`
imports `crypt`, which Python 3.13 removes.** Password hashing breaks on the
first 3.13 image. **Action:** move to `bcrypt` or `argon2-cffi` directly,
before a base-image upgrade forces it.

---

## 4. Where the roadmap stands

| Phase | Status |
|---|---|
| 0. Model contract | Done |
| Traversal gap | Closed |
| 1. Model authoring | Done (document-first) |
| 2. Solver selection | **Done for every linear class**: IP, LP, MILP |
| 3. Runs | Done, including cancellation and heartbeat |
| 4. Results and explanation | Done: names, conflicts, comparison, slack, duals, reduced costs |
| 5. Roles and configuration | Done: capabilities, three-level settings, templates |
| Cross-cutting debt | Paid |

**The one open frontier is nonlinear models (QP, NLP, MINLP).** They are
blocked by the *term language*, not by the schema: `mul` admits at most one
variable factor, so no model the contract can express is nonlinear.

---

## 5. Recommendation: nonlinear, in three stages

The platform's selection machinery (capabilities as data, and refusing
rather than substituting) already works. The limit is that the contract gives
it nothing nonlinear to choose between. Widen the contract one step at a time
and let the existing registry route.

The hard part of nonlinear optimisation is not solving. It is being honest
about what was solved. A nonconvex model can return a *local* optimum that
looks exactly like the global one. Showing that as "the best answer" would
be the worst failure this feature can have. So the order below is chosen by
how much honesty each stage can *prove*.

### Stage 1: the honesty rule, before any nonlinear model exists

- Add `run.optimality` (`global` | `local` | `none`) and show it beside
  `optimal` on every result.
- Every existing backend reports `global` for what it solves today, so
  nothing visible changes yet. The field exists before the first model that
  needs it.
- **Why first:** the roadmap already calls this a precondition. Retrofitting
  honesty after local answers have been shown means some of them were shown
  wrongly.

### Stage 2: quadratic objectives (QP / MIQP)

- Contract: allow `mul` of two variable factors **in the objective only**.
  Constraints stay linear.
- Classifier: new classes `QP` and `MIQP`, and a new need `quadratic`.
- **Convexity is decidable here.** A quadratic objective is convex exactly
  when its matrix is positive semidefinite, and that is a fast eigenvalue
  check. So the platform can *prove* a result is global rather than claim
  it. This is why QP is the right first nonlinear class.
- Backends: **HiGHS** for convex QP (already installed); **SCIP** for
  nonconvex and mixed-integer QP (global, via `pyscipopt`).
- Typical uses: least-squares fitting, portfolio variance, smoothing a
  schedule (penalise large changes), balancing load evenly.

### Stage 3: general nonlinear (NLP / MINLP)

- Contract: products in constraints, then a small, closed set of functions
  (`pow` with a constant exponent, `exp`, `log`, `abs`), each marked
  convex, concave or neither.
- Backends: **SCIP** as the global MINLP solver (slow, proves optimality);
  **IPOPT** as the fast local NLP solver, **always labelled `local`** unless
  convexity was proven.
- The policy gains its first real speed-versus-guarantee trade-off, so it
  should take a per-problem setting (the settings layer already exists):
  "prefer a proven answer" or "prefer a fast answer".

### What not to do

- **Do not add IPOPT first.** It is the easiest nonlinear solver to wire
  in. It is also the one most likely to return a confident local optimum,
  and until Stage 1 exists nothing would say so.
- **Do not let a nonlinear term into the contract without its convexity
  label.** A term the classifier cannot reason about makes every downstream
  guarantee void.

---

## Appendix: how this check was run

- `bash scripts/check.sh`: every suite, against the working tree.
- `docker compose ps`, image ages, and `alembic_version` compared with the
  code's migration head.
- `curl` against `/api/health`, the frontend, and an authenticated route
  without a token.
- Every live scenario queued through `enqueue_run` and solved by the running
  worker. This adds six runs to the live database (runs 33–38); nothing else
  was changed.
- The LP check ran in memory inside the backend container and wrote nothing.
