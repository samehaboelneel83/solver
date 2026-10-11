"""A plan sent back is patched, not rewritten (getting-better plan, lever 1.1).

The Assistant's `propose_plan` may carry only what changes -- the rules it fixed, a goal, a decision -- and the
platform completes it from the draft: the last plan it proposed, folded from the conversation's own
`propose_plan` calls (so nothing is held between turns, and the browser's round trip carries it). Every unbuilt
case of 11 October 2026 was lost to time, and a send-back that made the model rewrite 30,000 characters twice
was the commonest cause.

    merge(previous, partial)      the partial spec on the previous one
    draft_from(messages)          the draft before the call now being checked
    complete(spec, messages)      `spec` if whole, else merged onto the draft
"""

from __future__ import annotations

import copy
import json
from typing import Any


def is_partial(spec: dict[str, Any]) -> bool:
    """A spec with no seed, or with an IR that declares no decisions, is a patch on the last plan."""
    if not isinstance(spec, dict):
        return False
    ir = spec.get("ir")
    return "seed" not in spec or (isinstance(ir, dict) and "variables" not in ir)


def merge(previous: dict[str, Any] | None, partial: dict[str, Any]) -> dict[str, Any]:
    """The partial spec on the previous one: what the patch names replaces, what it leaves out stays; rules by
    id (`{"id": "c_x", "drop": true}` removes one; a new id is added); decisions and parameters by name."""
    if not isinstance(previous, dict):
        return partial
    out = copy.deepcopy(previous)
    for key, value in partial.items():
        if key == "ir" and isinstance(value, dict) and isinstance(out.get("ir"), dict):
            ir = out["ir"]
            for k, v in value.items():
                if k == "constraints" and isinstance(v, list) and isinstance(ir.get("constraints"), list):
                    by_id = {c.get("id"): i for i, c in enumerate(ir["constraints"]) if isinstance(c, dict)}
                    keep = list(ir["constraints"])
                    for rule in v:
                        if not isinstance(rule, dict):
                            continue
                        rid = rule.get("id")
                        if rule.get("drop"):
                            keep = [c for c in keep if not (isinstance(c, dict) and c.get("id") == rid)]
                        elif rid in by_id:
                            keep[by_id[rid]] = rule
                        else:
                            keep.append(rule)
                    ir["constraints"] = [c for c in keep if not (isinstance(c, dict) and c.get("drop"))]
                elif k in ("variables", "parameters") and isinstance(v, dict) and isinstance(ir.get(k), dict):
                    ir[k] = {**ir[k], **v}
                else:
                    ir[k] = v
        else:
            out[key] = value
    return out


def draft_from(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The plan as last proposed before the call now being checked: every earlier `propose_plan` call's spec,
    each merged onto the one before (a chain of patches resolves to one plan)."""
    from app.agent import repair

    calls: list[dict[str, Any]] = []
    for m in messages:
        if m.get("role") != "assistant":
            continue
        for c in m.get("tool_calls") or []:
            if (c.get("function") or {}).get("name") == "propose_plan":
                calls.append(c)
    if len(calls) < 2:
        return None  # nothing before the call being checked
    draft: dict[str, Any] | None = None
    for c in calls[:-1]:
        raw = (c.get("function") or {}).get("arguments")
        try:
            args = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except ValueError:
            continue
        spec, _ = repair.spec_of(args)
        draft = merge(draft, spec) if is_partial(spec) else spec
    return draft


def complete(spec: dict[str, Any], messages: list[dict[str, Any]]) -> tuple[dict[str, Any], str | None]:
    """`spec` whole, or the patch on the draft; the note says what was kept."""
    if not is_partial(spec):
        return spec, None
    draft = draft_from(messages)
    if draft is None:
        return spec, None
    merged = merge(draft, spec)
    changed = []
    ir = spec.get("ir") if isinstance(spec.get("ir"), dict) else {}
    if ir.get("constraints"):
        changed.append(f"{len(ir['constraints'])} rule(s)")
    for k in ("objective", "variables", "parameters", "sets", "relationships"):
        if k in ir:
            changed.append(k)
    if "seed" in spec:
        changed.append("the seed")
    return merged, ("the plan was completed from your last one: " + (", ".join(changed) or "nothing") + " changed, "
                    "everything else kept")
