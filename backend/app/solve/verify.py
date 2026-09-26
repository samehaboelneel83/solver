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

from app.solve.compile import Compiled, slack_of
from app.solve.result import Solution

#: Relative / absolute room for floating residuals on hard rules.
TOLERANCE = Decimal("1e-6")

_VIOLATION = "__violation"
_PWL = "__pwl"
_FN = "__fn"
_AUX = {_VIOLATION, _PWL, _FN}


def accept(compiled: Compiled, result: Solution) -> dict[str, Any]:
    """Return a verification report. `accepted` is False when the answer must not
    be shown as a usable plan."""
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
    for constraint in compiled.constraints:
        if constraint.id in soft_ids:
            continue
        if constraint.schedule is not None:
            # Scheduling rules have no single residual; documented boundary.
            continue
        if not constraint.is_active(result.assignments):
            continue
        slack = slack_of(constraint, result.assignments)
        tol = TOLERANCE * max(Decimal(1), abs(slack) if slack != 0 else Decimal(1))
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

    return report


def reject_unverified(result: Solution, report: dict[str, Any]) -> Solution:
    """Strip usable status when verification failed; keep wall time and solver id."""
    if report.get("accepted", True):
        return result
    return replace(result, status="unknown", optimal=False)
