"""What kind of model is this?

Phase 2 of the roadmap wants the platform to pick a technique and say why.
Classification is a pure function of the IR -- no dataset, no solver -- so it
is testable on its own and belongs beside the contract rather than inside a
backend adapter.

v1 can only express one class (integral and linear, by decision -- see the
contract's §7), so this returns `IP` for everything it accepts. It exists
anyway, and says *why* it concluded that, because the moment a second class
is expressible the selection policy needs a classifier that was not bolted
on afterwards.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Classification:
    model_class: str
    reasons: list[str]
    # What a backend must support to run it.
    needs: set[str]


def classify(ir: dict[str, Any]) -> Classification:
    domains = {spec.get("domain", "binary") for spec in ir.get("variables", {}).values()}
    reasons: list[str] = []
    needs = {"linear"}

    if not domains:
        reasons.append("no variables, so nothing is decided")
        return Classification("trivial", reasons, needs)

    if domains == {"binary"}:
        reasons.append("every variable is binary")
    elif domains <= {"binary", "integer"}:
        reasons.append(f"variables are integral ({', '.join(sorted(domains))})")
    else:  # pragma: no cover -- the contract refuses `continuous` by name
        reasons.append(f"variable domains {sorted(domains)} are not integral")
        return Classification("unsupported", reasons, needs)

    needs.add("integral")
    reasons.append("all terms are linear (the contract refuses a product of two variables)")
    if any(c.get("severity") == "soft" for c in ir.get("constraints", [])):
        needs.add("soft-constraints")
        reasons.append("at least one constraint is soft, so the backend must carry penalties")
    return Classification("IP", reasons, needs)
