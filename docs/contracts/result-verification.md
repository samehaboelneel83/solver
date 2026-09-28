# Result verification boundary (OAAS Q02 / Phase 4)

**Purpose:** document what must hold before a run is presented as a usable
plan (`optimal` / `feasible`), independent of any single solver’s word.

## Boundary

After the solver returns and **before** a solution is persisted as usable,
`app.solve.verify.accept` checks:

| Check | Rule |
|---|---|
| Usable status | Only `optimal` / `feasible` enter acceptance; other statuses skip |
| Assignments | A usable status without assignments is rejected |
| Finite objective | Objective, when present, must be a finite number |
| Hard-rule residuals | Every active hard rule’s slack ≥ −tolerance on the **original** compiled semantics (soft rules use violation variables and are reported, not rejected here) |
| Bounds | Decision values lie within declared lower/upper |
| Integrality | Binary / integer decisions are within 1e−6 of an integer |

Tolerance: `1e-6` relative to magnitude (`app.solve.verify.TOLERANCE`). A
rule's magnitude is the larger of its two sides at the answer, and never less
than one — not the size of the residual itself.

An **approximate** solver (`proves="approximate"`, PDLP) states its own
tolerance, and its guarantee is model-wide: the residual norm is within that
tolerance times one plus the norm of the rules' magnitudes. Its answers are
checked against that same scale, so a breach within what the solver promised
passes and anything beyond it is still refused. The run records the tolerance
in `params.tolerance`.

## Explicit non-claims

- Scheduling rules (`no_overlap` / `cumulative`) have no single residual; they
  are not residual-checked here (solver-native). Documented gap.
- A proof (`optimality`) still means “of the encoded model and tolerances,”
  not of the real-world process.
- Transformations (big-M, PWL, McCormick, symmetry rows) are recorded on the
  run; verification re-checks original hard rules after recovery.
- Infeasible / unbounded / unknown / cancelled remain distinct outcomes.
  Infeasibility still requires conflict evidence where the diagnose path runs.

## Failure behaviour

If acceptance fails, the run is recorded as `error` with
`params.verification` (checks + failures). The candidate is **not** stored
as an accepted plan. Soft-constraint reporting and chunked amounts are not
written for that path.

## Related

- Constraint outcomes for successful runs: `constraint_result` rows in `_record`
- Chunked amounts: `docs/contracts/approvals-and-chunks.md`
- Promotion / benches: `docs/contracts/family-policies.md`
