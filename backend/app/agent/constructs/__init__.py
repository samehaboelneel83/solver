"""The constructs library (build-protocol plan, Phase 2): the modelling knowledge of the platform, deterministic
and tested, so the model selects a construct and fills its fields and never hand-writes the algebra.

A rule in the spec may be one of these compact objects instead of `left`/`relation`/`right`; before the spec is
checked it is expanded here into ordinary rules (and the seed parts they need), so the contract, the validators
and the solvers see nothing new, and the plan card shows the rules it became. Each construct has one way to be
written, the right one: the mistakes the phase 1 evaluation found in hand-written rules cannot be expressed.

One module per construct, each with its `KEYS` (the rule keys it answers to), `FIELDS` (each field and what it
holds), `DESCRIPTION` (one neutral paragraph the instructions include verbatim; the neutrality test scans it)
and `expand(rid, body, rule, ir, seed, kind)` -> the rules it stands for. The registry here maps every key to
its module; `expand(spec)` is the one call the canonical pass makes (app/agent/canon.py).
"""

from __future__ import annotations

from types import ModuleType
from typing import Any

from app.agent.constructs import allowed_pairs, carried, largest_of, one_per_group, only_if
from app.agent.constructs._common import ConstructRefused

#: `IdiomRefused` was the name before the package (neutrality plan, step 3); kept for what reads it.
IdiomRefused = ConstructRefused

#: Every construct module, in the order the instructions describe them.
MODULES: tuple[ModuleType, ...] = (carried, only_if, allowed_pairs, largest_of, one_per_group)

#: Rule key -> the module that expands it.
REGISTRY: dict[str, ModuleType] = {key: module for module in MODULES for key in module.KEYS}

#: The rule keys that mark a construct (the order matters where a rule carries two by mistake: the first wins).
KEYS: tuple[str, ...] = tuple(REGISTRY)


def describe() -> list[str]:
    """Each construct's paragraph, for the instructions."""
    return [module.DESCRIPTION for module in MODULES]


def expand(spec: dict[str, Any]) -> list[str]:
    """Every construct rule of the spec's IR replaced by the rules it stands for, in place; returns notes."""
    ir = spec.get("ir")
    if not isinstance(ir, dict) or not isinstance(ir.get("constraints"), list):
        return []
    if not isinstance(spec.get("seed"), dict):
        spec["seed"] = {}
    seed = spec["seed"]
    out: list[Any] = []
    notes: list[str] = []
    for rule in ir["constraints"]:
        kind = next((k for k in KEYS if isinstance(rule, dict) and k in rule), None)
        if kind is None:
            out.append(rule)
            continue
        rid = str(rule.get("id") or f"c_{kind}")
        try:
            made = REGISTRY[kind].expand(rid, rule[kind], rule, ir, seed, kind)
        except ConstructRefused as exc:
            raise ConstructRefused(f'rule {rid} ("{kind}"): {exc}') from None
        for r in made:
            r.setdefault("severity", rule.get("severity", "hard"))
            if rule.get("severity") == "soft" and "weight" in rule:
                r.setdefault("weight", rule["weight"])
        out.extend(made)
        notes.append(f'rule {rid} written as the idiom "{kind}" became {", ".join(r["id"] for r in made)}')
    ir["constraints"] = out
    return notes
