# The districting family: where the exact flow stops — 2026-09-24

`python -m bench.run --family districting --sizes S,M,L,XL --instances 2 --time-limit 120`
(GIS 8). The region template's model on square grids: every cell in one
zone, each zone's people within 10% of an even share, each zone one
connected piece (`connected`, compiled to the exact single-commodity flow of
GIS 5), and compactness as the least moment of inertia about fixed centres.
S is 10 x 10 cells in 4 zones, M 14 x 14 in 6, L 20 x 20 in 8, XL 40 x 40 in
12. People are uneven: dense around a centre placed per instance.

**Why uneven people.** A first run with people spread evenly (randint
50-500 per cell) was proven optimal by every backend at every size,
XL included, in seconds -- and both XL instances had the same objective.
With even people the nearest-centre split is already balanced, connected and
optimal, so the balance and the flow never bind and the run measures
nothing. That run is not reported below; the family now places a city.

**Verdict.** The exact flow is proven at 100 cells and, on one of two
instances, at 196; at 400 cells and beyond no backend finds even a feasible
partition in 120 s. **Approach C is needed beyond about 200 cells**:
separation of connectivity cuts (lazy, on the incumbent's disconnected
pieces), or a heuristic start -- a balanced, connected partition grown from
the centres -- handed to the solver as a warm start. Until then the platform
serves districting up to a couple of hundred cells, which is why the
`region_partitioning` template uses 1 km cells (90) rather than 500 m (360).

What the rows also say:

- **CP-SAT is the one to route to at this size.** At S it proves each
  instance in 2-5 s where HiGHS, MILP and SCIP take up to 78 s; at M it
  proves instance 1 in 1.8 s.
- **At M instance 0 only CP-SAT and HiGHS find answers** (3.8% and 2.3%
  from their bounds); MILP and SCIP find nothing. A partition found and not
  proven is reported as feasible, with its gap, never as optimal.
- **No backend disagrees** where two proved (0 wrong rows).

| size | instance | backend | status | objective | bound | gap | solve s |
|---|---|---|---|---|---|---|---|
| S | districting-S-0 | cp-sat | optimal | 610 | 610 | 0 | 4.5 |
| S | districting-S-0 | highs | optimal | 610 | 610 | 0 | 72.2 |
| S | districting-S-0 | milp | optimal | 610 | 610 | 0 | 53.7 |
| S | districting-S-0 | scip | optimal | 610 | 610 | 0 | 62.9 |
| S | districting-S-1 | cp-sat | optimal | 575 | 575 | 0 | 2.2 |
| S | districting-S-1 | highs | optimal | 575 | 575 | 0 | 3.6 |
| S | districting-S-1 | milp | optimal | 575 | 575 | 0 | 4.2 |
| S | districting-S-1 | scip | optimal | 575 | 575 | 0 | 30.4 |
| M | districting-M-0 | cp-sat | feasible | 1875 | 1803 | 3.8% | 120.4 |
| M | districting-M-0 | highs | feasible | 1839 | 1797 | 2.3% | 120.7 |
| M | districting-M-0 | milp | unknown | -- | -- | -- | 120.9 |
| M | districting-M-0 | scip | unknown | -- | -- | -- | 120.1 |
| M | districting-M-1 | cp-sat | optimal | 1297 | 1297 | 0 | 1.8 |
| M | districting-M-1 | highs | optimal | 1297 | 1297 | 0 | 3.4 |
| M | districting-M-1 | milp | optimal | 1297 | 1297 | 0 | 54.9 |
| M | districting-M-1 | scip | optimal | 1297 | 1297 | 0 | 77.9 |
| L | districting-L-0 | cp-sat | unknown | -- | -- | -- | 120.6 |
| L | districting-L-0 | highs | unknown | -- | -- | -- | 121.1 |
| L | districting-L-0 | milp | unknown | -- | -- | -- | 122.3 |
| L | districting-L-0 | scip | unknown | -- | -- | -- | 120.4 |
| L | districting-L-1 | cp-sat | unknown | -- | -- | -- | 120.6 |
| L | districting-L-1 | highs | unknown | -- | -- | -- | 121.3 |
| L | districting-L-1 | milp | unknown | -- | -- | -- | 122.1 |
| L | districting-L-1 | scip | unknown | -- | -- | -- | 120.4 |
| XL | districting-XL-0 | cp-sat | unknown | -- | -- | -- | 123.7 |
| XL | districting-XL-0 | highs | unknown | -- | -- | -- | 125.5 |
| XL | districting-XL-0 | milp | unknown | -- | -- | -- | 139.0 |
| XL | districting-XL-0 | scip | unknown | -- | -- | -- | 123.1 |
| XL | districting-XL-1 | cp-sat | unknown | -- | -- | -- | 123.8 |
| XL | districting-XL-1 | highs | unknown | -- | -- | -- | 126.6 |
| XL | districting-XL-1 | milp | unknown | -- | -- | -- | 139.9 |
| XL | districting-XL-1 | scip | unknown | -- | -- | -- | 122.4 |
