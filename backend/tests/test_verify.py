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


def _at_least(bound: float) -> dict:
    """A continuous `y >= bound`: a linear program's rule, as PDLP answers it."""
    return {
        "version": 1,
        "sets": [],
        "parameters": {},
        "variables": {"y": {"index": [], "domain": "continuous", "lower": 0, "upper": 1_000_000}},
        "constraints": [
            {
                "id": "c_batch",
                "left": {"var": "y", "index": []},
                "relation": ">=",
                "right": {"const": bound},
                "severity": "hard",
            }
        ],
        "objective": {
            "sense": "minimize",
            "terms": [{"id": "o", "weight": 1, "expression": {"var": "y", "index": []}}],
        },
    }


def test_residual_tolerance_is_relative_to_the_rules_magnitude():
    """A first-order solver's 1e-6 is relative: 4e-5 short of 1000 is inside
    it, and was refused while the tolerance scaled with the residual."""
    key = ("y", ())
    large = compile_model(_at_least(1000), NO_DATA)
    near = Solution("optimal", True, 999.99996, {key: 999.99996}, 0.01, "pdlp")
    assert accept(large, near)["accepted"] is True
    # The same absolute shortfall on a rule of size one is a real breach.
    small = compile_model(_at_least(1), NO_DATA)
    short = Solution("optimal", True, 0.99996, {key: 0.99996}, 0.01, "pdlp")
    assert accept(small, short)["accepted"] is False
    # And a relative breach stays one at any size.
    far = Solution("optimal", True, 999.9, {key: 999.9}, 0.01, "pdlp")
    assert accept(large, far)["accepted"] is False


def test_an_approximate_answer_is_held_to_its_solvers_stated_tolerance():
    """PDLP stops when the residual is within tolerance of the whole model's
    scale, so a small rule may be off by more than its own 1e-6 -- but never
    by more than the solver promised."""
    key = ("y", ())
    small = compile_model(_at_least(5), NO_DATA)
    close = Solution("optimal", True, 4.9999944, {key: 4.9999944}, 0.01, "pdlp")
    assert accept(small, close)["accepted"] is False
    assert accept(small, close, approximate=1e-6)["accepted"] is True
    far = Solution("optimal", True, 4.99, {key: 4.99}, 0.01, "pdlp")
    assert accept(small, far, approximate=1e-6)["accepted"] is False
