"""Independent acceptance of a solver answer (OAAS Phase 4 / Q02).

Runs after the solver returns and before a plan is presented as usable.
Checks are on the **compiled original semantics** (hard-rule residuals,
bounds, integrality, finite numbers) — not on transformed solver rows alone.

See `docs/contracts/result-verification.md`.
"""

from __future__ import annotations

import math
from dataclasses import replace
from decimal import Decimal
from typing import Any

from app.solve.compile import Compiled, quadratic_at, slack_of
from app.solve.result import Solution

#: Relative / absolute room for floating residuals on hard rules.
TOLERANCE = Decimal("1e-6")


def _magnitude(constraint, assignments) -> Decimal:
    """The size a hard rule's residual is judged against: the larger of its
    two sides at the assignment, and never less than one. A breach of 4e-5 on
    a rule whose sides are near 1000 is floating noise; on a rule near 1 it
    is not."""
    left = constraint.left.evaluated_at(assignments, skip_names={_VIOLATION})
    left += quadratic_at(constraint.quadratic, assignments)
    right = constraint.right.evaluated_at(assignments, skip_names={_VIOLATION})
    return max(Decimal(1), abs(left), abs(right))

_VIOLATION = "__violation"
_PWL = "__pwl"
_FN = "__fn"
_AUX = {_VIOLATION, _PWL, _FN}


def accept(compiled: Compiled, result: Solution, approximate: float | None = None) -> dict[str, Any]:
    """Return a verification report. `accepted` is False when the answer must not
    be shown as a usable plan.

    `approximate` is the stated tolerance of a solver that answers to one
    rather than proving (PDLP). Its guarantee is model-wide -- the residual
    norm within tolerance times (1 + the norm of the rules' sizes) -- so a
    single rule is judged against that scale rather than its own size alone;
    a breach beyond what the solver promised is still refused."""
    report: dict[str, Any] = {
        "accepted": True,
        "checks": [],
        "failures": [],
    }
    if result.status not in ("optimal", "feasible"):
        report["checks"].append("status_not_usable")
        return report
    if not result.assignments:
        report["accepted"] = False
        report["failures"].append({"kind": "empty_assignment", "detail": "usable status without assignments"})
        return report

    report["checks"].append("assignments_present")

    if result.objective is not None and not math.isfinite(float(result.objective)):
        report["accepted"] = False
        report["failures"].append({"kind": "non_finite_objective", "detail": str(result.objective)})
    else:
        report["checks"].append("finite_objective")

    soft_ids = set(compiled.violations)
    hard = [
        c for c in compiled.constraints
        if c.id not in soft_ids and c.schedule is None and c.is_active(result.assignments)
    ]
    magnitudes = {id(c): _magnitude(c, result.assignments) for c in hard}
    if approximate is not None:
        scale = Decimal(1) + sum((m * m for m in magnitudes.values()), Decimal(0)).sqrt()
        allowed = Decimal(str(approximate)) * scale
    for constraint in compiled.constraints:
        if constraint.id in soft_ids:
            continue
        if constraint.schedule is not None:
            # Scheduling rules have no single residual; documented boundary.
            continue
        if not constraint.is_active(result.assignments):
            continue
        slack = slack_of(constraint, result.assignments)
        # Relative to the rule's own magnitude (the contract), not to the
        # residual: scaling by the residual made every breach over 1e-6 fail.
        tol = TOLERANCE * magnitudes[id(constraint)]
        if approximate is not None:
            tol = max(tol, allowed)
        if slack < -tol:
            report["accepted"] = False
            report["failures"].append(
                {
                    "kind": "hard_rule_residual",
                    "constraint_id": constraint.id,
                    "index": dict(constraint.index),
                    "slack": float(slack),
                }
            )
            if len(report["failures"]) >= 20:
                break
    if not any(f["kind"] == "hard_rule_residual" for f in report["failures"]):
        report["checks"].append("hard_rules")

    for key, var in compiled.variables.items():
        if key[0] in _AUX:
            continue
        raw = result.assignments.get(key)
        if raw is None:
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            report["accepted"] = False
            report["failures"].append({"kind": "non_numeric", "var": key[0], "index": list(key[1])})
            continue
        if not math.isfinite(value):
            report["accepted"] = False
            report["failures"].append({"kind": "non_finite_value", "var": key[0], "index": list(key[1])})
            continue
        lo, hi = float(var.lower), float(var.upper)
        # The guard ceiling on a decision with no upper bound is not the model's bound: an answer the
        # rules hold above it (raised once to be sure, app.solve.service) is not out of bounds.
        if getattr(var, "default_upper", False):
            hi = math.inf
        if value < lo - 1e-6 or value > hi + 1e-6:
            report["accepted"] = False
            report["failures"].append(
                {
                    "kind": "bound",
                    "var": key[0],
                    "index": list(key[1]),
                    "value": value,
                    "lower": lo,
                    "upper": hi,
                }
            )
        if var.domain in ("binary", "integer"):
            if abs(value - round(value)) > 1e-6:
                report["accepted"] = False
                report["failures"].append(
                    {
                        "kind": "integrality",
                        "var": key[0],
                        "index": list(key[1]),
                        "value": value,
                    }
                )
    if not any(f["kind"] in ("bound", "integrality", "non_finite_value", "non_numeric") for f in report["failures"]):
        report["checks"].append("bounds_and_integrality")

    # Epic ML: a prediction the model optimized over is re-made by the trained
    # model itself at the answer's inputs, and must agree with what the rows
    # said -- the check that the lowering (`app.solve.predict`) is the model.
    # An input sitting on a threshold may take either side and is waived.
    mismatched = False
    for prediction in getattr(compiled, "predictions", []) or []:
        if prediction.on_a_threshold(result.assignments):
            continue
        embedded = prediction.embedded_at(result.assignments)
        actual = prediction.value_at(result.assignments)
        if abs(embedded - actual) > 1e-6 * (1 + abs(actual)):
            mismatched = True
            report["accepted"] = False
            report["failures"].append(
                {"kind": "prediction_mismatch", "predictor": prediction.name,
                 "embedded": embedded, "model": actual}
            )
    if getattr(compiled, "predictions", None) and not mismatched:
        report["checks"].append("predictions")

    return report


def reject_unverified(result: Solution, report: dict[str, Any]) -> Solution:
    """Strip usable status when verification failed; keep wall time and solver id."""
    if report.get("accepted", True):
        return result
    return replace(result, status="unknown", optimal=False)
