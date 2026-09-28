# Trained models in optimization (Epic ML)

The platform can **forecast** a number with a trained model and **optimize over** a trained model's
prediction. Both use one idea: a trained model is domain data, like a parameter, called a
**predictor**.

| You want | You write | What happens |
| --- | --- | --- |
| A forecast as a coefficient (predict-then-optimize) | `predict` of data, e.g. `{"predict": "demand_model", "of": [{"const": 4}, {"par": "promo", "index": ["d"]}]}` | The compiler evaluates the model once; the term is a number |
| The best decision given what a model predicts | `predict` of decisions, e.g. `{"predict": "demand_model", "of": [{"var": "price", "index": []}, ...]}` | The compiler writes the model as exact mixed-integer rows; the solver optimizes over it |

Supported models: **random forests** and **gradient-boosted trees** (regression), trained here or
uploaded as `tree-ensemble/1` JSON. The contract is in `docs/contracts/problem-ir.md` §3.6 and §4.6.

## 1. Get a predictor into a domain

**Train one from the domain's own entities** (`domain.edit`):

```http
POST /api/v1/predictors/train
{
  "domain_id": 7,
  "name": "sales_model",
  "entity_type": "store",
  "features": ["price", "footfall"],
  "target": "sales",
  "kind": "random_forest",
  "trees": 50,
  "max_depth": 6
}
```

- Rows are the active entities of the type (and its subtypes); a row missing a number in a feature
  or the target is skipped and counted (`metrics.rows_skipped`).
- Metrics (`r2`, `mae`, `rmse`) are measured on a held-out 20%, then the model is refitted on every
  row. With fewer than 10 rows no accuracy is claimed.
- `kind`: `random_forest` or `gradient_boosting`. Limits: 200 trees, depth 12, 200,000 rows.
- `"replace": true` retrains an existing predictor in place. Earlier runs keep the model they froze.

**Or upload one trained elsewhere** as `tree-ensemble/1` JSON (`POST /api/v1/predictors`). To
export a scikit-learn model: `app.ml.trees.from_sklearn(model, ["price", "footfall"])`. The export
is exact: the JSON predicts what the scikit-learn model predicted.

Other routes: `GET /api/v1/predictors?domain_id=`, `GET /api/v1/predictors/{id}?include_model=true`,
`POST /api/v1/predictors/{id}/predict` (up to 1,000 rows), `DELETE /api/v1/predictors/{id}` (refused
while a model version reads it). Every write is in the audit log.

## 2. Use it in a model (IR version 2)

```json
{
  "version": 2,
  "sets": [], "parameters": {},
  "predictors": { "sales_model": { "inputs": 2 } },
  "variables": {
    "price": { "index": [], "domain": "continuous", "lower": 1, "upper": 10 },
    "stock": { "index": [], "domain": "integer",    "lower": 0, "upper": 500 }
  },
  "constraints": [
    { "id": "c_price_floor", "severity": "hard",
      "left": { "var": "price", "index": [] }, "relation": ">=", "right": { "const": 4 } },
    { "id": "c_stock_covers_sales", "severity": "hard",
      "left":  { "var": "stock", "index": [] }, "relation": ">=",
      "right": { "predict": "sales_model", "of": [ {"var": "price", "index": []}, {"const": 640} ] } }
  ],
  "objective": { "sense": "maximize", "terms": [
    { "id": "o_sales", "weight": 1,
      "expression": { "predict": "sales_model", "of": [ {"var": "price", "index": []}, {"const": 640} ] } } ] }
}
```

The model picks the price, at 4 or above, that the trained model predicts sells most in a store
with a footfall of 640, and holds enough stock to cover that prediction.

Rules to know:

- Inputs are **linear** terms, in the predictor's input order.
- A decision read by a prediction needs a **declared upper bound**: the rows' big-M values come
  from the bounds, and the platform's guard ceiling is not a bound you chose. Tighter bounds also
  make the model smaller, because leaves the bounds rule out are dropped.
- The same prediction written twice is compiled once.
- A model version that reads a predictor is **mixed-integer with fractional data**, so CP-SAT is
  not offered it; HiGHS, SCIP and the MILP wrapper are.

## 3. How big it gets

Each tree adds one binary per reachable leaf, one equality, and at most two rows per input per
leaf. A forest of 50 trees of depth 6 is at most 3,200 binaries. Past **20,000 reachable leaves**
the compile is refused with what to change: fewer or shallower trees, or narrower input bounds.

## 4. What is checked

- The format, before anything is stored (`app.ml.trees.check_ensemble`): shape, limits, finite
  numbers, input positions, every node reached exactly once.
- Every answer (`app.solve.verify`): the prediction the rows imply equals the trained model's own
  prediction at the answer's inputs. Otherwise the answer is refused.
- Optimizing over a model finds what enumerating every input finds
  (`backend/tests/test_predict.py`, on HiGHS, SCIP and the MILP wrapper, for both model kinds and
  both senses).

## 5. Run-time estimate

`GET /api/v1/runs/{run_id}/eta` estimates how long a compiled run will take, from the
organization's own settled runs: a random forest on the run's fingerprint, solver and time limit.
It answers with no number, and says why, before the run has compiled or while fewer than 30 runs
have settled. The range is the spread of the forest's trees, not a calibrated interval, and never
exceeds the run's time limit.

## 6. Not yet

- Quantile forests (p10/p90 forecasts): they need each leaf's training targets stored.
- Classification models, neural networks, ONNX import.
- A Predictors page and a guided-form pattern; today predictions are written in the Exact IR or
  Blocks editors, and the term editor edits their inputs.
