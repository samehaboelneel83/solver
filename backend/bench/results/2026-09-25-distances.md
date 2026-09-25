# Distances from the map: what they cost -- 2026-09-25 (queue R16a)

Measured on the test database (solver-backend-test, one request each), with
1,000 sites and 1,000 customers placed at random in a 0.5 x 0.5 degree box
near Cairo:

| request | written | time |
|---|---|---|
| `POST .../distances`, every pair | 1,000,000 values | 134.5 s |
| `POST .../distances`, `nearest: 10` | 10,000 values | 1.9 s |
| `POST .../within`, 3 km | 9,925 edges | 2.2 s |
| the geodesic matrix alone (`distance.matrix`), in memory | 1,000,000 | 0.45 s |

**Verdict.** Computing is cheap; writing is not: every `parameter_value` row
passes the validating trigger, about 7,500 a second. A full matrix is
therefore capped at 250,000 pairs a request (500 x 500, about 35 s); past
that the endpoint asks for `nearest`, which is also what a model of that
size should read -- a solver handed a million distance terms spends its
time on the terms. The template (8 x 40) computes in well under a second.
