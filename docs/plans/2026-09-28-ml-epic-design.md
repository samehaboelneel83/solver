# Epic ML — trained models in the problem IR

**Date:** 2026-09-28 · **Follows:** `2026-09-28-enterprise-plan-gap-analysis.md` §2.1 · **Branch:** `epic/ml`

## Decision in one paragraph

A trained model is **data the model reads**, like a parameter. A domain holds named
**predictors** (a registry, one table). A model version declares the predictors it reads in a
new optional IR key, `predictors`, and uses one through one new term, `predict`.
`snapshot_dataset()` freezes the declared predictors into the run's dataset, so a run stays
reproducible. The compiler then does one of two things:

- **Applied to data** (a forecast): it evaluates the model and the term is a number. This is
  predict-then-optimize, with no change to any backend.
- **Applied to decisions** (optimizing over the prediction): it lowers the tree ensemble to
  **exact rows and binaries**, the way `connected` and `route` lower to rows, so every MILP
  backend takes it with no backend change.

## Scope of this epic

| Item | In | Notes |
| --- | --- | --- |
| Predictor registry (migration 0087, RLS, API, audit) | yes | Models stored as JSON only; never pickle |
| Training from domain data (random forest, gradient boosting) | yes | scikit-learn, run in the API request with size limits; holdout metrics stored |
| Upload a model trained elsewhere | yes | The JSON tree format below |
| IR `predictors` key + `predict` term, Python + TypeScript validators | yes | Version 2 only; a widening (§10.1 of the contract) |
| Compile: of data → number; of decisions → exact MILP rows | yes | Leaves pruned by the arguments' bounds |
| Classification: a predict of decisions makes the model mixed-integer | yes | |
| Independent check: the embedded prediction equals the model's own prediction at the answer | yes | Added to `verify.py` |
| Run-time estimate (ETA) from stored runs | yes | Random forest on run fingerprints |
| Quantile forests (p10/p90) | no | Follow-up; needs leaf-level training targets stored |
| Editor support (forms, blocks, graph) and a Predictors page | no | Follow-up in Epic UX; the Exact IR editor and the API work now |

## The JSON tree format (`tree-ensemble/1`)

```json
{
  "format": "tree-ensemble/1",
  "inputs": ["price", "promotion"],
  "aggregation": "mean",
  "base": 0,
  "trees": [
    {"nodes": [
      {"feature": 0, "threshold": 4.5, "left": 1, "right": 2},
      {"value": 120.0},
      {"value": 80.0}
    ]}
  ]
}
```

- Node 0 is the root. A split sends `x[feature] <= threshold` left, otherwise right
  (scikit-learn's rule). A leaf has only `value`.
- `aggregation`: `mean` (random forest) or `sum` (gradient boosting, where `base` is the initial
  prediction and leaf values already include the learning rate).
- Limits: 1–32 inputs, 1–500 trees, depth ≤ 16, 100,000 nodes in total, finite numbers only,
  every node reachable exactly once.

## IR

```json
"predictors": { "demand_model": { "inputs": 2 } },
...
{ "predict": "demand_model", "of": [ {"var": "price", "index": []}, {"par": "promo", "index": ["d"]} ] }
```

- `predictors` (optional, version 2): each key names a predictor of the problem's domain;
  `inputs` must equal the predictor's input count (checked against the domain at submit).
- `predict`: `of` holds exactly `inputs` linear arguments, in the predictor's input order.
- Degree: 1 when any argument reads a decision (the term stands for a decision of its own),
  0 when all are data.

Refusals: `predict_needs_version_2`, `predict_malformed`, `predict_unknown`, `predict_arity`,
`predict_argument_nonlinear`, `predictors_malformed` (shape); `predictor_not_in_domain`,
`predictor_inputs_mismatch` (domain).

## Lowering a tree ensemble (per distinct `predict` of decisions)

For tree `t` with reachable leaves `ℓ` (a leaf is dropped when its path cannot hold within the
arguments' bounds):

```text
z[t,ℓ] ∈ {0,1}                      Σ_ℓ z[t,ℓ] = 1
split on path to ℓ, going left:     a_f ≤ θ + (hi_f − θ)(1 − z[t,ℓ])
split on path to ℓ, going right:    a_f ≥ θ + δ − (θ + δ − lo_f)(1 − z[t,ℓ])
y = base + s · Σ_t Σ_ℓ value[t,ℓ] · z[t,ℓ]      s = 1/T for mean, 1 for sum
```

- `a_f` is the f-th argument (a linear expression); `lo_f`, `hi_f` come from the decisions'
  bounds. An argument without a finite range is refused before any solve
  (`Unsupported`, naming the rule).
- `δ = 1e-6`: an argument exactly on a threshold goes left, as scikit-learn sends it.
- Rows carry the id `__predict`; `__`-prefixed rows are not written to `constraint_result`.
- A second identical `predict` (same predictor, same arguments) reuses the same `y`.

## Files

| File | Change |
| --- | --- |
| `backend/alembic/versions/0087_predictors.py` | table, RLS, grants, capability, `snapshot_dataset()` freezes declared predictors |
| `backend/app/ml/trees.py` | format validation, evaluation, scikit-learn export |
| `backend/app/ml/train.py` | training from entity rows, holdout metrics |
| `backend/app/ml/eta.py` | run-time estimate |
| `backend/app/api/predictors.py` | registry API |
| `backend/app/ir/contract.json`, `contract.py`, `validate.py`, `models.py` | key, term, refusals |
| `frontend/src/ir/contract.ts`, `validate.ts` | parity |
| `backend/tests/ir_fixtures.json` | one fixture per new refusal, one valid document |
| `backend/app/solve/predict.py`, `compile.py`, `classify.py`, `verify.py`, `service.py` | lowering, classification, check, persistence filter |
| `docs/contracts/problem-ir.md`, `docs/ml.md` | contract and guide |
| `backend/requirements.txt` | `scikit-learn` |
