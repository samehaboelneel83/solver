"""Rules filter on text as people write it (benchmark round 4: `where status = 'existing'`)."""

from __future__ import annotations

from app.solve import compile_model
from app.solve.backends import by_name
from app.solve.service import solve_compiled


def test_a_text_filter_reads_case_and_spaces_aside():
    ir = {"version": 2, "sets": ["site"], "parameters": {}, "variables": {"open": {"index": ["site"], "domain": "binary"}},
          "constraints": [{"id": "keep", "forall": [{"index": "s", "set": "site", "where": [{"attr": "status", "op": "=", "value": "existing"}]}],
                           "left": {"var": "open", "index": ["s"]}, "relation": "=", "right": {"const": 1}, "severity": "hard"}],
          "objective": {"sense": "minimize", "terms": [{"id": "n", "weight": 1, "expression": {
              "sum": {"var": "open", "index": ["s"]}, "over": [{"index": "s", "set": "site"}]}}]}}
    data = {"sets": {"site": [{"id": "a", "status": "existing"}, {"id": "b", "status": "candidate"}, {"id": "c", "status": "Existing "}]},
            "parameters": {}, "parameter_defaults": {}}
    result, _ = solve_compiled(by_name("highs"), compile_model(ir, data), time_limit=10, seed=1)
    assert {k[1][0] for k, v in result.assignments.items() if v} == {"a", "c"}
