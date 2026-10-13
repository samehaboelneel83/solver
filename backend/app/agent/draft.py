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
    # A seed alone (new data for a refused plan) is a patch too (12 October 2026: taken whole, refused for
    # having no model, twice on one case).
    return "seed" not in spec or not isinstance(ir, dict) or "variables" not in ir


#: How each seed list is keyed, so a patch replaces its own entries and leaves the others.
SEED_KEYS = {"entity_types": ("name",), "relationship_types": ("name",), "parameters": ("name",),
             "entities": ("type", "key"), "relationships": ("type", "from", "to"),
             "parameter_values": ("parameter", "entities"), "entities_from_file": ("type",),
             "parameter_values_from_file": ("parameter",), "relationships_from_file": ("type",),
             "relationships_in_order": ("type",), "distances_from_fields": ("name",)}


def _key(row: Any, fields: tuple[str, ...]) -> str:
    return json.dumps([row.get(f) for f in fields] if isinstance(row, dict) else row, sort_keys=True, default=str)


def _merge_seed(previous: dict[str, Any], partial: dict[str, Any]) -> dict[str, Any]:
    """A seed part sent alone (a new parameter and its file entry, a record kind) joins the draft's seed: each
    list by its entries' keys (12 October 2026: a partial seed replaced the whole one, and the next refusal was
    "no value loaded" for everything else, eleven times)."""
    out = copy.deepcopy(previous)
    for key, value in partial.items():
        if key in SEED_KEYS and isinstance(value, list) and isinstance(out.get(key), list):
            fields = SEED_KEYS[key]
            kept = list(out[key])
            index = {_key(r, fields): i for i, r in enumerate(kept)}
            for row in value:
                k = _key(row, fields)
                if isinstance(row, dict) and row.get("drop"):
                    kept = [r for r in kept if _key(r, fields) != k]
                    index = {_key(r, fields): i for i, r in enumerate(kept)}
                elif k in index:
                    kept[index[k]] = row
                else:
                    index[k] = len(kept)
                    kept.append(row)
            out[key] = kept
        else:
            out[key] = value
    return out


def merge(previous: dict[str, Any] | None, partial: dict[str, Any]) -> dict[str, Any]:
    """The partial spec on the previous one: what the patch names replaces, what it leaves out stays; rules by
    id (`{"id": "c_x", "drop": true}` removes one; a new id is added); decisions and parameters by name; the
    seed's lists by their entries' keys."""
    if not isinstance(previous, dict):
        return partial
    out = copy.deepcopy(previous)
    for key, value in partial.items():
        if key == "seed" and isinstance(value, dict) and isinstance(out.get("seed"), dict):
            out["seed"] = _merge_seed(out["seed"], value)
        elif key == "ir" and isinstance(value, dict) and isinstance(out.get("ir"), dict):
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


#: The build protocol's stage tools (build-protocol plan, Phase 3.1): each call is a patch on the draft.
STAGE_TOOLS = ("stage_data", "stage_decisions", "add_rule", "stage_goal")
#: What a stage_data call may carry: the seed's own parts.
SEED_PARTS = tuple(SEED_KEYS) + ("patterns_that_fit",)


def stage_patch(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """The partial spec a stage call stands for: the data as a seed, the decisions (and declared parameters)
    as the IR's, one rule (its sentence kept as the note it has none of), the goal."""
    if name == "stage_data":
        return {"seed": {k: v for k, v in args.items() if k in SEED_PARTS}}
    if name == "stage_decisions":
        ir: dict[str, Any] = {"variables": args.get("variables") if isinstance(args.get("variables"), dict) else {}}
        if isinstance(args.get("parameters"), dict):
            ir["parameters"] = args["parameters"]
        return {"ir": ir}
    if name == "add_rule":
        rule = dict(args.get("rule")) if isinstance(args.get("rule"), dict) else {}
        if isinstance(args.get("sentence"), str) and args["sentence"].strip() and not rule.get("note"):
            rule["note"] = args["sentence"].strip()
        if isinstance(args.get("drop"), str) and not rule:
            rule = {"id": args["drop"], "drop": True}
        return {"ir": {"constraints": [rule]}}
    if name == "stage_goal":
        return {"ir": {"objective": args.get("objective")}}
    return {}


def draft_from(messages: list[dict[str, Any]], before: str | None = None) -> dict[str, Any] | None:
    """The plan as last proposed before the call now being checked: every earlier `propose_plan` call's spec,
    each merged onto the one before (a chain of patches resolves to one plan), and every stage call's patch
    (STAGE_TOOLS). `before` is the id of the call being checked: everything earlier is folded; left out, the
    last call is the one being checked."""
    from app.agent import canon  # here, not at the top: canon imports this module

    # A summary carries the draft of the calls it folded (compact.py): the fold starts from the latest one.
    calls: list[Any] = []
    for m in messages:
        if m.get("role") == "user" and isinstance(m.get("draft"), dict):
            calls = [m["draft"]]
            continue
        if m.get("role") != "assistant":
            continue
        for c in m.get("tool_calls") or []:
            if (c.get("function") or {}).get("name") in ("propose_plan", *STAGE_TOOLS):
                calls.append(c)
    if before is not None:
        at = next((i for i, c in enumerate(calls) if isinstance(c, dict) and c.get("id") == before), None)
        calls = calls[:at] if at is not None else calls
    else:
        calls = calls[:-1]  # the last call is the one being checked
    if not calls:
        return None  # nothing before the call being checked
    draft: dict[str, Any] | None = None
    for c in calls:
        if "function" not in c:  # a summary's draft, already whole
            draft = c
            continue
        raw = (c.get("function") or {}).get("arguments")
        try:
            args = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except ValueError:
            continue
        name = (c.get("function") or {}).get("name")
        if name in STAGE_TOOLS:
            draft = merge(draft, stage_patch(name, args if isinstance(args, dict) else {}))
            continue
        spec, _ = canon.spec_of(args)
        draft = merge(draft, spec) if is_partial(spec) else spec
    return draft


WHOLE_MARK = "[whole plan next]"


def _plan_results(messages: list[dict[str, Any]]) -> list[str]:
    """What propose_plan answered so far, oldest first (the tool messages of the conversation)."""
    return [str(m.get("content") or "") for m in messages
            if m.get("role") == "tool" and m.get("name") == "propose_plan"]


def repeated(verdict: str, messages: list[dict[str, Any]]) -> int:
    """How many earlier propose_plan answers began as this one does (the first 160 characters, numbers aside):
    the same refusal coming back after a patch."""
    import re

    head = re.sub(r"\d+", "#", verdict[:160])
    return sum(1 for r in _plan_results(messages) if re.sub(r"\d+", "#", r)[:len(head)] == head)


def complete(spec: dict[str, Any], messages: list[dict[str, Any]]) -> tuple[dict[str, Any], str | None]:
    """`spec` whole, or the patch on the draft; the note says what was kept. After a send-back that asked for
    the whole plan (WHOLE_MARK in the last propose_plan answer), the spec is taken as it is, no merge."""
    if not is_partial(spec):
        return spec, None
    results = _plan_results(messages)
    if results and WHOLE_MARK in results[-1]:
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
