# Benchmark: pywraplp model build (D7)

How long GLOP and the MILP wrapper take to receive a model, from `Compiled`
to a solver ready to solve -- the Python work before any solving.
`python -m bench.build_speed --repeat 3` (median of three), 2026-09-23.

| model | entries | engine | expr (s) | coef (s) | proto (s) | same answer |
|---|---|---|---|---|---|---|
| synthetic-lp-200k | 200,000 | GLOP | 0.435 | 0.175 | 0.043 | yes |
| synthetic-lp-200k | 200,000 | SCIP | 0.443 | 0.175 | 0.046 | yes |
| feed_blend-XL | 121,862 | GLOP | 0.344 | 0.102 | 0.028 | yes |
| feed_blend-XL | 121,862 | SCIP | 0.347 | 0.107 | 0.031 | yes |
| facility-XL | 320,080 | SCIP | 1.561 | 0.711 | 0.370 | yes |

- `expr`: the build until 2026-09-23 -- `solver.Sum(var * coeff ...)`,
  `solver.Add(expr >= rhs)`.
- `coef`: `solver.Constraint(lb, ub)` and one `SetCoefficient` per entry.
- `proto`: an `MPModelProto` filled with two bulk `extend`s per row and
  loaded once (`app/solve/pywraplp_model.py`).

## Reading

The proto is 8-10x faster than the expression build on the 200,000-entry
LP (0.435 s to 0.043 s on GLOP) and 4x on the largest MILP (1.56 s to
0.37 s), and every build solves to the same objective. Adopted for both
backends. What remains on `facility-XL` is the rearranging of each rule
into one row in Python, which every build pays; HiGHS's array build is at
the same order (0.23 s on 200,000 entries).
