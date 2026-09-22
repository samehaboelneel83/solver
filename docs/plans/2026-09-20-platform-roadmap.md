# Building out the solving platform — roadmap

**Written for:** whoever picks this up next, including a future session of this
project. It assumes the schema-v1 migration (merged at `aefc84c`) as its
starting point and does not re-explain it.

**Status:** Phase 0 is **done** (merged at `7c283a1`); the rest is proposed.
The phases are ordered by dependency, not by appetite.

Update, 2026-09-20: the checking infrastructure is merged too (`f30f1b6`) —
`bash scripts/check.sh` runs both suites the one correct way.

---

## 1. Where the platform actually is

Facts, not impressions — **as at 2026-09-20**. The table is left as written
because the phases below are answers to it; where a row has since been
overtaken, the phase that overtook it says so. The short version on
2026-09-21: migrations run to `0016`, the solver exists and is chosen by
class, and the run subsystem has its API, worker, queue and UI. Tests are
1112 backend and 1493 frontend.

| | state |
|---|---|
| Schema | 16 v1 tables, migrations `0006`–`0010`, live at `0010` |
| Domain modelling | entity types, typed attributes, entities, relationship types, relationships, indexed parameters — **complete and usable** |
| Problem modelling | `problem`, `model_version` (immutable, hashed), `scenario` (a patch over a version) exist as **tables**; `model_version.ir` is opaque `jsonb` |
| Run subsystem | `dataset`, `run`, `solution`, `constraint_result` exist as tables with immutability triggers and a `snapshot_dataset()` that works. **No API, no worker, no queue, no UI** |
| Solver | **absent.** Not in this repository |
| Tests | 754 backend, 1268 frontend, axe 0 across 59 states |

**The gap that matters:** a user can model a domain completely and cannot
express a single constraint. There is no route in the product to create a model
version, because nothing knows what belongs inside one.

## 2. The blocker, stated plainly

`model_version.ir` is a JSON document whose shape is defined by a solver
(`ProblemIR`, `psp/data.py`) that is **not in this repository**. Everything
downstream inherits that uncertainty:

- no expression editor can be built, because nothing defines what a valid
  expression is;
- `snapshot_dataset()` already reads `ir.sets` and `ir.parameters` and will
  raise on anything else — so the contract is already half-committed, by
  accident rather than by design;
- `scenario.patch` references constraint ids that nothing validates;
- solver selection cannot classify a model it cannot parse.

**Phase 0 exists to end this.** Every later phase depends on it, and no amount
of UI work substitutes for it.

## 3. Design principles

These are the "dynamic and flexible" requirement made concrete. Each one is a
test you can apply to a proposed change.

1. **Model structure is data, not code.** A new kind of constraint is a row,
   not a deployment. The domain half already works this way — attributes are
   `attribute_def` rows, not columns — and the problem half should match.
2. **The database is the last line of defence, the UI is the first.** Every
   rule that matters gets a CHECK or trigger; routers shadow it for a good
   message. This is already the established pattern (Rulings 16, 32) and it is
   what let the seed be trusted.
3. **One definition, many consumers.** The expression catalogue is shared
   between TypeScript and Python through one file, with a parity test that
   fails if they drift (Ruling 37). Solver capabilities must work the same way.
4. **Reproducibility is a property of the schema.** A run already points at an
   immutable version *and* an immutable dataset, both content-hashed. Keep
   that: a result nobody can reproduce is not a result.
5. **Refusals name the field and say what to do next.** One 422 shape, `kind`
   present exactly when the database judged (Rulings 19, 30).

---

## Phase 0 — The model contract — **DONE** (`7c283a1`)

Delivered: `docs/contracts/problem-ir.md` (the contract, with worked examples),
one shared artefact both languages read, a validator on each side with a parity
test, shared fixtures, enforcement at `POST /versions` (an invalid IR is now a
422 naming the path, where an unknown set used to be a 500 inside
`snapshot_dataset()`), patch ids validated against their version, and the
seeded model rewritten so its constraints carry mathematics instead of prose.

**Three decisions it took, which the rest of this roadmap now inherits:**

1. ~~**v1 admits `binary` and `integer` variables and refuses `continuous` by
   name.**~~ **Reversed 2026-09-21**; the reasoning is kept because reversing
   it is what the entry was written to allow. There was no solver to run a
   continuous model, and admitting one would have made the contract promise
   what the platform could not keep. It also closed a back door — entity
   attributes include `number`, so arithmetic over a `number` attribute would
   have let fractional coefficients in while parameters stayed integral, and
   nobody would have decided that. Arithmetic was restricted to `integer`
   attributes; `number` attributes remained usable in filters.

   Both halves are answered rather than dropped: GLOP is the solver, and the
   back door is now a front door with a sign on it — `fractional-data` is
   detected and named on the run. See decision #2.
2. **No unexpressed constraint is admitted**, so the seed was rewritten rather
   than the contract weakened.
3. ~~**Traversal is not expressible**~~ — a *consequence* rather than a choice:
   `snapshot_dataset()` froze entities and parameters but **no
   relationships**, so the frozen input a solver read contained no edges, and
   the spec's own example (`unit.descendants`) could not be written. The most
   consequential thing Phase 0 surfaced, and **closed on 2026-09-21** by
   removing the cause — see "The traversal gap" below.

Read §9 of the contract first: it separates what was **derived** from existing
code (changing it contradicts something real) from what was **invented** here
(a later reader, or your solver, may reopen it).

---

## The traversal gap — **CLOSED 2026-09-21** (`cb7a684`)

*Kept because the reasoning is the record of why it was worth doing, and
because the last paragraph turned out to be right.*

A hierarchy is the reason `relationship` exists, and a planner's first
interesting constraint usually crosses one: *staffing for a region, counting
its sub-units*; *nobody reports to someone in another division*. None of that
was expressible, because the dataset a run is frozen against carried no
relationships at all.

Three ways out were listed, in increasing order of cost:

1. **Freeze the edges too.** Extend `snapshot_dataset()` to emit relationships
   per type, and give the term algebra a traversal form. Reproducibility is
   preserved because the edges are frozen with everything else. — **taken**,
   except that the term algebra did not have to grow: see decision #3 below.
2. **Precompute closures.** Emit `entity_descendants()` output for hierarchy
   types as derived sets. Cheaper to express, less general. — **not needed as
   a separate mechanism**; it is `depth: any_or_self`.
3. **Leave it.** Constraints stay flat; hierarchy is presentational only.

> This is a schema-and-contract change, so it belongs before model authoring
> rather than after — an editor built on a term algebra that cannot traverse
> will need reworking when traversal arrives.

That was half right, and the half it got wrong is the more useful lesson. The
sequencing warning was sound — this landed after the editor, and the editor
did need reworking. But the rework was small, and it was small *because*
traversal turned out to be a binding rather than a term: `TermBuilder`'s term
half was untouched, and the change was one picker in the binding editor. The
cost of getting the sequencing wrong is paid in the shape of the thing you
have to change, not in the calendar.

The first of the three inexpressible planner sentences — "North Region needs
three on lates, counting its depots" — is now a constraint in the seeded demo.

## Phase 1 — Model authoring — **DONE via (a), the document** (`90eef1e`, `349a863`, `c4b76a6`)

The choice below was taken: the editor reads and writes the IR document
directly, with the contract's validator as its safety net. Sets, parameters
and variables are declared in the product; constraints and objectives are
built with react-querybuilder over the same expression catalogue; versions
are started from nothing or from any earlier one; scenarios ask the same
model a different question.

**(b), promotion to rows, remains open and should stay open** until a
concrete need appears -- diffing two versions rule by rule, reusing a
constraint across problems, or per-constraint permissions. The record below
is the design for when it does.

**Goal:** a user can build a model in the product, and what they build is
inspectable, diffable and reusable.

**First, a question Phase 0 reopened.** This section was written when the IR
was opaque; it no longer is. There are now two defensible designs, and the
choice should be deliberate:

- **(a) Author the document.** The IR is already validated on both sides, with
  a `loc`-shaped refusal per rule. An editor could read and write the document
  directly, with the validator as its safety net. One source of truth, no
  compile step, and the editor is honest by construction because it cannot
  save what the contract refuses.
- **(b) Promote to rows,** as sketched below, and compile a version from them.
  Better for diffing two versions, for reusing a constraint across problems,
  for per-constraint permissions, and for querying ("which models use this
  parameter?"). Costs a second representation to keep in step with the
  contract.

**Recommendation: (a) first, (b) when a concrete need appears.** The
contract's refusals are already field-shaped, so (a) gets a usable editor much
sooner; the rows in (b) pay for themselves only once versions are being
compared and constraints reused, which nothing does yet. Revisit at the first
of those needs — not before.

**Schema, if (b).** Promote the model's parts from opaque JSON to first-class
rows, while keeping the compiled IR as the immutable artefact:

```
variable_def       (problem_id, name, index_type_ids[], domain: binary|integer|continuous,
                    lower, upper, unit)
constraint_def     (problem_id, name, kind, expression jsonb, relation, rhs,
                    scope_type_ids[], severity: hard|soft, penalty_weight)
objective_def      (problem_id, name, sense: min|max, terms jsonb, weight)
```

Rationale: this is the same move that made the domain half work. `attribute_def`
rows are why an entity form can be generated; `constraint_def` rows are why a
model editor can be generated, why two versions can be diffed meaningfully, and
why a solver adapter can classify a model without parsing free text.

`model_version.ir` stays: it is the **compiled, frozen** form. Authoring edits
the rows; publishing a version compiles them into the IR and hashes it. That
preserves immutability and reproducibility while making authoring editable.

**Expressions.** Extend the existing expression core rather than inventing a
second one. Today it produces boolean condition trees (`14c`/`14d`); a model
needs *arithmetic*: `sum over set`, coefficients, products of a variable and a
parameter, comparison to a bound. Two shapes, one catalogue, one validator,
one parity mechanism.

**UI.** Three editors following the established page conventions, plus a model
overview that shows a version's variables, constraints and objectives, and a
diff between two versions. This finally makes the "Model versions" screen
honest — today it advertises a workflow that does not exist.

**Watch:** `scenario.patch` (`disable`/`harden`/`soften`) must line up with
`constraint_def` ids once they exist. Today it references ids nothing
validates.

---

## Phase 2 — Solver selection for linear and nonlinear problems — **DONE for every linear class** (`24c894e`, `aeb5a6e`, + continuous)

Three backends (CP-SAT, GLOP and branch-and-cut MILP) plus **HiGHS** when
`highspy` is installed, capabilities as data in
a registry, and a policy recorded on every run: an explicit choice wins or is
refused, otherwise the highest-ranked backend that fits, with the reason in
`run.params.why_solver`. HiGHS sits at the same rank as MILP and ahead of it
in the registry, so a mixed model prefers it when the package is there; GLOP
still wins a pure LP and CP-SAT a pure integer model. HiGHS runs in a child
process: `highspy` and `ortools` both ship `libHighs` and cannot load in one
interpreter. The test that gives it meaning is that two backends
reach the same optimum on the same model -- with one backend, a wrong policy
would have been invisible.

**LP is now done too.** The schema decision named at the end of this section
was taken rather than deferred: migration `0015` makes parameters, defaults,
`run.objective` and `constraint_result`'s two numeric columns `numeric(15, 6)`,
the contract admits `continuous` variables and fractional coefficients
(contract §7), and GLOP is a third backend. The policy does real work now --
before this, `LP` and `MILP` were labels on a model that went to the same
solver either way, and a classifier that cannot change the outcome is
decoration.

One consequence worth carrying forward: **classification is no longer a pure
function of the IR.** A model whose variables are all binary is still out of
CP-SAT's reach if a parameter is 2.5, and the IR does not contain 2.5 -- the
dataset does. So `classify()` takes the frozen dataset as an optional second
input and may add `fractional-data` to what a backend must provide. It never
changes the class.

**Nonlinear, stage 1 -- the honesty rule -- DONE** (migration `0028`). Every
run records `optimality`: `global`, `local` or `none`. It comes from what each
backend declares its optimum proves -- a required registry field, so a local
solver cannot be added without saying so -- and a local optimum is shown as
"not proven the best overall", never as the best answer. It landed before any
nonlinear model could exist, on purpose.

**Nonlinear, stage 2 -- quadratic objectives -- DONE.** A weighted objective
may multiply two variables (contract §4); rules stay linear. QP is the right
first nonlinear class because its convexity is *decidable* -- an eigenvalue
check on the compiled coefficients -- so an optimum can be proven global
rather than hoped to be:

- an all-integer quadratic model (`MIQP`) goes to **CP-SAT**, which holds each
  product of two variables equal to a new integer exactly, so it proves the
  global optimum convex or not;
- a continuous one (`QP`) goes to **HiGHS** only when proven convex (or
  concave, when maximising);
- a continuous model not proven convex, or a quadratic goal over mixed
  decisions, goes to **SCIP** (stage 3a, below). A build without PySCIPOpt
  still refuses these with the reason, because a local solver would call a
  nearby answer optimal.

**Nonlinear, stage 3a -- a global solver -- DONE.** SCIP, through PySCIPOpt
(`app/solve/scip.py`), is rank 2 and takes only `QP` and `MIQP`, so a convex
QP stays with HiGHS and an all-integer one with CP-SAT. Its spatial
branch-and-bound proves the optimum global whatever the curvature, so it
declares `proves="global"`. The quadratic part of the objective goes in as
one constraint on an auxiliary variable. It runs in the worker process: unlike
`libHighs`, its bundled SCIP does not clash with OR-Tools'. The templates
`feed_blend` (LP) and `load_balance` (convex QP) make continuous and quadratic
solving visible in the product.

**Still open:** stage 3b, general nonlinear terms (NLP / MINLP): products in
rules and a closed set of functions, each labelled convex, concave or
neither. SCIP already takes them. A local solver (IPOPT) may join, but only
declaring `proves="local"`. The Model editor's live "which solver will
take this" runs the same convexity step as a run (`convexity.refine`), so the
two cannot disagree about a quadratic model.

**Goal:** the platform picks an appropriate technique, explains its choice, and
lets a user override it.

**Classify the model, from the rows Phase 1 created:**

| class | detection |
|---|---|
| LP | continuous variables only; all expressions linear |
| MILP | as LP with integer or binary variables |
| QP / QCQP | quadratic objective or constraints, otherwise linear |
| NLP | continuous, any nonlinear expression |
| MINLP | discrete variables and nonlinear expressions |
| CP / scheduling | discrete, with combinatorial structure (all-different, no-overlap, precedence) |

Classification is a pure function of the model, so it is testable without a
solver and belongs in the shared catalogue.

**A solver registry, capabilities as data:**

```
solver_backend  (name, version, classes[], supports_indicator, supports_sos,
                 supports_nonconvex, supports_warm_start, licence, is_available)
```

Candidate adapters, roughly in order of usefulness here: **CP-SAT** (the
schema's integer-only design is already aimed at it), **HiGHS** (LP/MILP,
permissive licence), **IPOPT** (continuous NLP), **Bonmin/Couenne** (MINLP),
with a commercial adapter (Gurobi/CPLEX) as a licence-gated option. Adapters
are processes behind one interface, not libraries linked into the API.

**Selection policy**, in this order, and visible to the user:
1. an explicit choice on the problem or scenario wins;
2. otherwise the highest-ranked available backend whose capabilities cover the
   model class;
3. record *why* on the run (`chosen_backend`, `classified_as`, `reason`);
4. a portfolio mode may race two backends and keep the first result, for the
   cases where classification is ambiguous.

**Nonlinear needs an explicit honesty rule:** convexity is not decidable in
general. Where the platform cannot prove convexity it must say the result is a
*local* optimum, not a global one. A silent local optimum presented as the
answer is the worst failure mode this feature can have.

**Note the existing constraint** — *taken, 2026-09-21; kept for the record.*
`parameter_value.value` and `parameter_def.default_value` were `int`,
deliberately, for CP-SAT (spec §2). Continuous solvers need rational or float
parameters, so Phase 2 had either to add a numeric type to parameters or
restrict continuous models to non-parameter coefficients. **This is a schema
decision, not an adapter detail.** It went the first way: migration `0015`,
`numeric(15, 6)`, sized so the JSON bridge is lossless. Contract §7.4 records
why decimal rather than float, and why no stored hash moved.

---

## Phase 3 — Runs — **DONE** (`dac2f03`, `aeb5a6e`)

A database-backed queue claimed with `FOR UPDATE SKIP LOCKED`, a worker
service, snapshot-on-submit, full provenance on the run, and a UI that
follows a run until it settles and then stops asking. Stale runs from a
dead worker are reclaimed at start-up.

**Cancellation and heartbeat** -- done. Migration `0018` records
`cancel_requested_at` and `last_heartbeat_at` on `run`. The worker polls
the flag, CP-SAT / GLOP / CBC honour it, a missed heartbeat reclaims the
row, and the Runs UI can stop a live solve instead of waiting it out.

**Goal:** press solve, watch it, get a result you can trust and reproduce.

The tables exist and are immutable; what is missing is everything around them.

- **Queue and worker.** A run is queued, claimed by a worker, and reports
  progress. Prefer a database-backed queue over adding a broker until the load
  justifies one — `run` already has the status enum and the timestamps.
- **API:** create a run from (version, scenario, dataset), poll it, cancel it,
  stream its log.
- **Snapshot on submit:** `snapshot_dataset()` already produces the frozen
  input and dedupes identical snapshots by hash. Wire it in.
- **Record provenance:** solver name and version, model hash, data hash, seed,
  time limit, gap. Two runs of the same triple must be comparable.
- **UI:** a run list, a run detail with live status, and the result.

---

## Phase 4 — Results, and why they are what they are — **mostly DONE** (`9dafbd1`, `f89c152`, `edff8ad`, slack `0017`)

- **Solution viewer in domain language** -- done. Migration 0012 freezes
  display names into the snapshot, so a run reads back in the names that
  were current when it was asked rather than today's.
- **Infeasibility diagnosis** -- done, by deletion filtering, reported into
  `run.conflict` per instance. `run.conflict_minimal` says whether the set
  was proven irreducible, so the UI promises "relax any one of these" only
  when that is true.
- **Scenario comparison** -- done, with the caveat attached: the comparison
  states what the two runs differ by and whether the patch is the only
  difference, because crediting a rule for a change the data caused is a
  wrong answer dressed as an insight.
- **Sensitivity** -- **slack done, duals done.** Migration `0017` adds
  `constraint_result.slack`; GLOP and CBC write it, CP-SAT reports `0` on
  a binding integer constraint, and an infeasible run's conflict set
  names the rule with no room left. Migration `0019` adds
  `constraint_result.dual`: GLOP and HiGHS fill it on a pure LP; CP-SAT
  and a mixed-integer search leave it null. Reduced costs on variables
  are on `solution.reduced_costs` (migration `0020`), same honesty.
- **Empty ranges on the editor** -- done. `POST /api/v1/classify` takes
  an optional `problem_id`, compiles against a live read of the domain
  (no `snapshot_dataset()` insert), and the Model editor lists a
  `where`/`via` that matched nobody before publish, in the same words a
  run uses.
- **choose() on the editor** -- done. The same classify response now
  carries `would_solve`: `choose()`'s pick in planner language, no
  picker. The editor still never names a backend.

A number is not an answer. The value of this phase is that it turns the tool
from a calculator into something a planner can argue with.

- **Solution viewer** mapped back to domain language — entities by name, not
  variable indices.
- **Infeasibility diagnosis.** When there is no solution, say which constraints
  conflict (an irreducible infeasible set where the backend supports it,
  otherwise a relaxation search over soft constraints). `constraint_result`
  exists for exactly this.
- **Sensitivity** where the class supports it: shadow prices and reduced costs
  for LP, slack per constraint generally.
- **Scenario comparison:** two runs side by side, differing only by their
  patch, with the objective and the changed assignments highlighted.

---

## Phase 5 — Roles and configuration — **DONE** (`671fac8`, `237049c`)

- **Capabilities** -- done. Migration 0013 makes them rows granted to
  roles, enforced by one dependency, and reported by `GET /api/v1/me` so
  a screen and the server cannot disagree. The split that matters holds:
  a planner may solve without being able to change the model.
- **Settings at three levels** -- done. Migration 0014; problem beats
  domain beats platform beats the built-in default, every resolved value
  says which level supplied it, and a run records it too.
- **Templates** -- done. `POST /api/v1/templates/{id}/apply` plants
  `domain_seed` (types, entities, relationships, parameters) then publishes
  the stored IR; the weekly-rota seed is what Dashboard's Start uses on an
  empty domain.

**Domain-editing UI** now hides New / Save / Delete unless `GET /api/v1/me`
lists `domain.edit`, matching Runs and Settings. The API still refuses a
write that arrives anyway.

**Goal:** the flexible configuration the request asks for, for roles as well as
for model parts.

- **Permissions are currently nominal.** `iam` has users, roles and
  memberships, and every authenticated user can do everything. Introduce
  capabilities (`domain.edit`, `model.publish`, `run.submit`,
  `solver.configure`) granted to roles, enforced in one dependency in the API
  and reflected in the UI so unavailable actions are absent, not broken.
- **Settings as data, at three levels** — platform, domain, problem — each
  overriding the last: default solver, time limit, optimality gap, thread
  count, whether nonconvex problems may run at all.
- **Templates.** The `template` table exists and is unused. A template is a
  starting model plus a domain seed: "weekly rota", "shift coverage". This is
  what makes the platform teachable, and it is cheap once Phase 1 exists.

---

## Cross-cutting, and existing debt worth paying

Carried from the migration's ledger; none of it blocks, all of it compounds:

- **Parameter re-index race** — **done.** PUT `/values` takes `FOR SHARE` on
  `parameter_def`; PATCH and DELETE take `FOR UPDATE`, so an uncommitted
  cell write cannot hide from the re-index cell-count.
- **No keyboard route to create or delete a relationship** — **done.**
  The Relationships page already had forms and named Delete buttons.
  The graph canvas now does too: with a node focused, `C` then Enter on
  another node opens the same type picker as a Connect drag; `E` then
  Enter opens the relationship panel, whose Delete is a real button.
- **`translate_db_error` discards a trigger's own message on 23503** — **done.**
  A 23503 with no `constraint_name` (entity_type_guard's DELETE) forwards
  the trigger sentence, which names the parameters; a real FK still uses
  `conflict_detail()`.
- **Unbounded payloads** — **done.** GET `/graph` refuses a domain over
  10,000 nodes or 50,000 edges (counted before the rows load). PUT
  `/parameters/{id}/values` refuses more than 10,000 cells.
- **Five string-detail 422s** in the generic CRUD layer — **done.** The list
  route now raises FastAPI's list shape with `loc` starting at `query`.
- **The checks script** (branch `checks`) — **done.** `scripts/check.sh`
  runs both suites the one correct way; `scripts/install-hooks.sh` installs
  the pre-commit hook. Merged at `f30f1b6`.
- **Lint** — **done.** `npm run lint` is on with `--max-warnings 0`;
  `scripts/check.sh` runs it. Twelve disable comments remain, recorded
  in the README.

---

## Decisions needed before Phase 0 can finish

1. ~~Is the solver's IR available?~~ **Answered by events.** It was not
   supplied, so the contract was defined here and the solver becomes the
   consumer that adapts. If the real `ProblemIR` turns up, reconcile it
   against §9's invented list — those are the points most likely to differ.
2. ~~**Integer-only, or continuous too?**~~ **Settled 2026-09-21: continuous
   too.** The refusal was deliberately made "visible and reversible", and this
   is it being reversed. Migration `0015` took the schema change this entry
   named (`parameter_value.value`, `parameter_def.default_value`,
   `run.objective`, and `constraint_result`'s two numeric columns), the
   `integer`-attributes-only rule is relaxed, and GLOP is the continuous
   solver that made it worth doing. Contract §7 carries the full argument,
   including which of the original three reasons actually held.

   The part worth remembering: reason 2 of the old refusal — that a
   half-continuous model would arrive *by accident* through `number`
   attributes — was never an argument against continuous. It was an argument
   against admitting it silently, and it is answered by `fractional-data`
   being detected and named on the run rather than assumed.
3. ~~**The traversal gap**~~ **Settled 2026-09-21: option 1, freeze the edges.**
   Done in the two steps migration `0011`'s docstring set out — `0011` froze
   them, `0016` narrowed the emission to the types a model declares, the same
   contract `sets` already had. Contract §4.2 is the form.

   Two things about it were not in the three options. The term algebra did
   **not** gain a traversal form: a walk is a property of a *binding*, so
   `termKinds` is unchanged and `sum`, `forall` and `where` compose with it
   without knowing it exists. And option 2 did not have to be chosen against —
   `depth: one | any | any_or_self` makes the closure a mode of the one
   mechanism rather than a second one, which is what the traversal decision
   note had recommended.

   Deferred, in the contract rather than in silence: an edge's own
   `valid_from`, `valid_to` and `attrs`. `0011` freezes them; §5 records why
   no term reads them yet.
4. **Where do solvers run?** In-process, as sidecar containers, or on a remote
   worker pool. This determines the queue design in Phase 3 and the licence
   handling in Phase 2.
5. **How much does the platform promise?** Specifically: may it run a nonconvex
   model and present a local optimum, with a warning, or should it refuse?
6. **Who is the user?** If planners self-serve, Phase 5's permissions and Phase
   4's explanations matter more than raw solver coverage. If a modelling team
   drives it, invert that.

## Sequencing

```
Phase 0  ── blocks everything
   └── Phase 1 ── model authoring
          ├── Phase 2 ── solver selection      (needs the model to classify)
          │      └── Phase 3 ── runs           (needs something to run)
          │             └── Phase 4 ── results
          └── Phase 5 ── roles and settings    (can start in parallel with 2)
```

Phase 5's permission work is the one piece that can proceed without Phase 0,
and it is the right thing to hand to a second pair of hands.
