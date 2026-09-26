"""Independent result verification (OAAS Q02)."""

from __future__ import annotations

from typing import Any

from app.solve import compile_model
from app.solve.result import Solution
from app.solve.verify import accept, reject_unverified

NO_DATA: dict[str, Any] = {"sets": {}, "parameters": {}, "parameter_defaults": {}, "relationships": {}}


def _cover_one() -> dict:
    return {
        "version": 1,
        "sets": [],
        "parameters": {},
        "variables": {"x": {"index": [], "domain": "binary"}},
        "constraints": [
            {
                "id": "c_cover",
                "left": {"var": "x", "index": []},
                "relation": ">=",
                "right": {"const": 1},
                "severity": "hard",
            }
        ],
        "objective": {
            "sense": "minimize",
            "terms": [{"id": "o", "weight": 1, "expression": {"var": "x", "index": []}}],
        },
    }


def test_accept_ok_assignment():
    compiled = compile_model(_cover_one(), NO_DATA)
    key = ("x", ())
    result = Solution("optimal", True, 1, {key: 1}, 0.01, "cp-sat")
    report = accept(compiled, result)
    assert report["accepted"] is True
    assert "hard_rules" in report["checks"]


def test_reject_hard_violation():
    compiled = compile_model(_cover_one(), NO_DATA)
    key = ("x", ())
    result = Solution("optimal", True, 0, {key: 0}, 0.01, "cp-sat")
    report = accept(compiled, result)
    assert report["accepted"] is False
    assert any(f["kind"] == "hard_rule_residual" for f in report["failures"])
    rejected = reject_unverified(result, report)
    assert rejected.status == "unknown"


def test_reject_integrality():
    ir = {
        "version": 1,
        "sets": [],
        "parameters": {},
        "variables": {"n": {"index": [], "domain": "integer", "lower": 0, "upper": 5}},
        "constraints": [],
        "objective": {
            "sense": "minimize",
            "terms": [{"id": "o", "weight": 1, "expression": {"var": "n", "index": []}}],
        },
    }
    compiled = compile_model(ir, NO_DATA)
    key = ("n", ())
    result = Solution("feasible", False, 1.5, {key: 1.5}, 0.01, "highs")
    report = accept(compiled, result)
    assert report["accepted"] is False
    assert any(f["kind"] == "integrality" for f in report["failures"])
