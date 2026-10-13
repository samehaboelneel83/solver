"""The build protocol's stages (build-protocol plan, Phase 3.1): the Assistant builds a plan in stages through
tool calls -- the data, the decisions, one rule at a time with the sentence it holds, the goal -- and the
platform checks each stage as it comes and assembles the plan at propose_plan.

What is here is pure: every check takes the draft (the fold of the stage calls so far, app/agent/draft.py)
and returns what to say, or the refusal that names the fix. The Assistant's tools call these; the stage
calls themselves are the draft's state (the browser round-trips the conversation, nothing is kept between
turns), and `assemble` turns the draft into the spec the canonical pass and the build take.

    stage_data      -> the seed's parts (files loaded by the caller; the report per entry)
    stage_decisions -> check_decisions(draft): every index set has records; bounds; the read-back
    add_rule        -> check_rule(draft, rule, sentence): the one rule canonicalised, checked in the draft's
                       model, its range and what it reads
    stage_goal      -> check_goal(draft): the goal checked in the draft's model; the read-back
    propose_plan    -> assemble(draft) -> the spec, through the canonical pass and the build as before
"""

from __future__ import annotations

import copy
from typing import Any

from app.agent import canon, constructs, readback
from app.agent.constructs._common import ConstructRefused
from app.agent.files import FileRefused
from app.ir.validate import Refusal, check_shape
from app.solve.lint import _names_read

#: The stages in order; a stage called before the one it needs is refused with the one to call.
ORDER = ("stage_data", "stage_decisions", "add_rule", "stage_goal", "propose_plan")


class StageRefused(FileRefused):
    """A stage that cannot be taken as written: the message says what to write or which stage to do first."""


# ---------------------------------------------------------------------------------------------------------------
# The draft's parts


def _seed(draft: dict[str, Any] | None) -> dict[str, Any]:
    return draft.get("seed") if isinstance(draft, dict) and isinstance(draft.get("seed"), dict) else {}


def _ir(draft: dict[str, Any] | None) -> dict[str, Any]:
    return draft.get("ir") if isinstance(draft, dict) and isinstance(draft.get("ir"), dict) else {}


def records_per_kind(seed: dict[str, Any]) -> dict[str, int]:
    """How many records of each kind the seed types; a kind loaded from a file counts as -1 (known at propose)."""
    counts: dict[str, int] = {}
    for et in seed.get("entity_types") or []:
        if isinstance(et, dict) and et.get("name"):
            counts.setdefault(str(et["name"]), 0)
    for e in seed.get("entities") or []:
        if isinstance(e, dict) and e.get("type"):
            counts[str(e["type"])] = counts.get(str(e["type"]), 0) + 1
    for entry in seed.get("entities_from_file") or []:
        if isinstance(entry, dict) and entry.get("type") and not counts.get(str(entry["type"])):
            counts[str(entry["type"])] = -1
    return counts


def _index_sets(ir: dict[str, Any]) -> list[str]:
    """Every set the model indexes over, in first-seen order: the decisions', the parameters', the bindings'."""
    seen: list[str] = []

    def add(name: Any) -> None:
        if isinstance(name, str) and name not in seen:
            seen.append(name)

    for v in (ir.get("variables") or {}).values():
        for s in (v.get("index") or []) if isinstance(v, dict) else []:
            add(s)
    for p in (ir.get("parameters") or {}).values():
        for s in (p.get("index") or []) if isinstance(p, dict) else []:
            add(s)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            # A binding wherever it is written: a rule's forall, a sum's over, a construct's or a place rule's parts.
            if isinstance(node.get("set"), str) and "index" in node:
                add(node["set"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk([ir.get("constraints"), ir.get("objective")])
    return seen


def _relationships_read(ir: dict[str, Any]) -> list[str]:
    """Every relationship the model walks: a binding's via, a connected or route rule's, a join's ends."""
    seen: list[str] = []

    def add(name: Any) -> None:
        if isinstance(name, str) and name not in seen:
            seen.append(name)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            via = node.get("via")
            if isinstance(via, dict):
                add(via.get("rel"))
            for key in ("connected", "route", "join"):
                body = node.get(key)
                if isinstance(body, dict):
                    add(body.get("via"))
                    add(body.get("depot_by"))
                    for end in body.get("ends") or [] if isinstance(body.get("ends"), list) else []:
                        add(end)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk([ir.get("constraints"), ir.get("objective")])
    return seen


def assemble(draft: dict[str, Any] | None) -> dict[str, Any]:
    """The spec the draft stands for: the seed as staged; the IR with its sets and relationships derived from
    what the model indexes over and walks (one less thing to write), the rest as staged. The canonical pass
    and the contract run on it after, as on a spec written whole."""
    seed = copy.deepcopy(_seed(draft))
    ir = copy.deepcopy(_ir(draft))
    out: dict[str, Any] = {"version": 2}
    out["sets"] = ir.get("sets") if isinstance(ir.get("sets"), list) and ir.get("sets") else _index_sets(ir)
    rels = ir.get("relationships") if isinstance(ir.get("relationships"), list) else None
    declared = [str(r.get("name")) for r in seed.get("relationship_types") or [] if isinstance(r, dict) and r.get("name")]
    read = _relationships_read(ir)
    out["relationships"] = rels if rels else [r for r in dict.fromkeys(read + declared) if r in read or r in declared]
    out["parameters"] = ir.get("parameters") if isinstance(ir.get("parameters"), dict) else {}
    out["variables"] = ir.get("variables") if isinstance(ir.get("variables"), dict) else {}
    out["constraints"] = [c for c in ir.get("constraints") or [] if isinstance(c, dict) and not c.get("drop")]
    if isinstance(ir.get("objective"), dict):
        out["objective"] = ir["objective"]
    spec = {k: v for k, v in (draft or {}).items() if k not in ("seed", "ir")}
    spec["seed"] = seed
    spec["ir"] = out
    return spec


# ---------------------------------------------------------------------------------------------------------------
# The checks, one per stage


def _refusal_said(refusal: Refusal) -> str:
    loc = ".".join(str(p) for p in refusal.loc) if refusal.loc else "the model"
    return f"{refusal.message} (at {loc})"


def _shape_problem(spec: dict[str, Any], *, without_goal_ok: bool) -> str | None:
    """The contract's shape check on the assembled model; with no goal staged yet, a refusal about the goal
    alone is not one."""
    ir = copy.deepcopy(spec["ir"])
    if without_goal_ok and not isinstance(ir.get("objective"), dict):
        ir["objective"] = {"sense": "minimize", "terms": []}
    refusal = check_shape(ir)
    if refusal is None:
        return None
    if without_goal_ok and refusal.loc and str(refusal.loc[0]) == "objective":
        return None
    return _refusal_said(refusal)


def check_decisions(draft: dict[str, Any] | None, workspace_counts: dict[str, int] | None = None) -> str:
    """stage_decisions: every set a decision or parameter is declared over has records (in the staged data or
    the workspace), bounds are numbers in order; returns the decisions read back, or raises StageRefused."""
    ir = _ir(draft)
    variables = ir.get("variables") if isinstance(ir.get("variables"), dict) else {}
    if not variables:
        raise StageRefused('stage_decisions carries "variables": {<name>: {"index": [<kinds>], "domain": '
                           '"continuous" | "integer" | "binary", "lower": 0, "upper": ...}}')
    counts = {**(workspace_counts or {}), **{k: v for k, v in records_per_kind(_seed(draft)).items()}}
    problems: list[str] = []
    for name, v in variables.items():
        if not isinstance(v, dict):
            problems.append(f"{name}: a decision is an object with index and domain")
            continue
        for s in v.get("index") or []:
            if str(s) not in counts:
                problems.append(f'{name} is declared over "{s}", which the data stage did not give (no records of that '
                                'kind): stage the records first, or declare the decision over a kind that has them')
            elif counts[str(s)] == 0:
                problems.append(f'{name} is declared over "{s}", which has no records: load or type them in stage_data')
        lo, hi = v.get("lower"), v.get("upper")
        if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) and lo > hi:
            problems.append(f"{name}: lower {lo} is above upper {hi}")
    if problems:
        raise StageRefused("; ".join(problems))
    spec = assemble(draft)
    problem = _shape_problem(spec, without_goal_ok=True)
    if problem:
        raise StageRefused(problem)
    lines = []
    for name, v in variables.items():
        over = ", ".join(f"{s} ({counts.get(str(s), 0) if counts.get(str(s), 0) >= 0 else 'from a file'})" for s in v.get("index") or [])
        bounds = ", ".join(f"{k} {v[k]}" for k in ("lower", "upper") if isinstance(v.get(k), (int, float)))
        lines.append(f"- {name}: {v.get('domain', 'continuous')}" + (f" per {over}" if over else " (one number)")
                     + (f", {bounds}" if bounds else ""))
    return "Decisions staged:\n" + "\n".join(lines)


def _range(rule: dict[str, Any], counts: dict[str, int]) -> str:
    """How many records the rule ranges over: the product of its forall sets' counts ("up to" with a filter)."""
    forall = rule.get("forall") if isinstance(rule.get("forall"), list) else []
    if not forall:
        return "once"
    n = 1
    about = False
    for b in forall:
        if not isinstance(b, dict):
            continue
        c = counts.get(str(b.get("set")), 0)
        if c < 0:
            return "over records loaded from a file (counted at propose)"
        n *= c
        about = about or bool(b.get("where")) or bool(b.get("via"))
    return f"{'up to ' if about else ''}{n} {'record' if n == 1 else 'records'}"


def check_rule(draft: dict[str, Any] | None, rule: Any, sentence: str | None = None,
               workspace_counts: dict[str, int] | None = None) -> tuple[dict[str, Any], str]:
    """add_rule: the one rule canonicalised (a construct expanded, the term shapes put right), checked in the
    draft's model, with its range and what it reads. Returns (the rule as it stands, what to say); raises
    StageRefused with the fix."""
    if not isinstance(_ir(draft).get("variables"), dict) or not _ir(draft)["variables"]:
        raise StageRefused("declare the decisions first with stage_decisions, then add the rules one at a time")
    if not isinstance(rule, dict) or not rule.get("id"):
        raise StageRefused('add_rule carries "sentence" (the request\'s words the rule holds) and "rule": {"id": ..., '
                           '"forall": [...], "left": <term>, "relation": "<=", "right": <term>, "severity": "hard"} '
                           "or a construct")
    rule = copy.deepcopy(rule)
    if isinstance(sentence, str) and sentence.strip() and not rule.get("note"):
        rule["note"] = sentence.strip()
    trial = assemble(merge_rule(draft, rule))
    notes: list[str] = []
    try:
        notes.extend(constructs.expand(trial))
    except ConstructRefused as exc:
        raise StageRefused(str(exc)) from None
    notes.extend(canon.repair(trial))
    canon.literal_keys(trial, notes)
    made = [c for c in trial["ir"]["constraints"] if isinstance(c, dict)
            and (c.get("id") == rule["id"] or str(c.get("id", "")).startswith(str(rule["id"]) + "_"))]
    problem = _shape_problem(trial, without_goal_ok=True)
    if problem:
        raise StageRefused(problem)
    counts = {**(workspace_counts or {}), **records_per_kind(_seed(draft))}
    attrs: set[str] = set()
    pars: set[str] = set()
    for c in made:
        _names_read({k: v for k, v in c.items() if k in ("left", "right", "forall")}, attrs, pars)
    reads = sorted(attrs | pars)
    ranges = "; ".join(f"{c.get('id')} ranges over {_range(c, counts)}" for c in made) or "nothing made"
    said = (f'rule {rule["id"]} holds "{rule.get("note", "")}": {ranges}'
            + (f"; reads {', '.join(reads)}" if reads else "; reads no data")
            + ("; " + "; ".join(notes) if notes else ""))
    return (made[0] if len(made) == 1 else rule), said


def merge_rule(draft: dict[str, Any] | None, rule: dict[str, Any]) -> dict[str, Any]:
    from app.agent.draft import merge

    return merge(copy.deepcopy(draft) if isinstance(draft, dict) else {"seed": {}, "ir": {}},
                 {"ir": {"constraints": [rule]}})


def check_goal(draft: dict[str, Any] | None, objective: Any) -> str:
    """stage_goal: the goal checked in the draft's model (the sense, every term's data); the read-back."""
    if not isinstance(_ir(draft).get("variables"), dict) or not _ir(draft)["variables"]:
        raise StageRefused("declare the decisions first with stage_decisions, then the goal")
    if not isinstance(objective, dict) or objective.get("sense") not in ("minimize", "maximize") \
            or not isinstance(objective.get("terms"), list) or not objective["terms"]:
        raise StageRefused('stage_goal carries "objective": {"sense": "minimize" | "maximize", "terms": [{"id": ..., '
                           '"weight": 1, "expression": <term>}]}')
    from app.agent.draft import merge

    trial = assemble(merge(copy.deepcopy(draft), {"ir": {"objective": copy.deepcopy(objective)}}))
    for term in trial["ir"]["objective"].get("terms") or []:
        if isinstance(term, dict):
            term.pop("note", None)
    notes: list[str] = []
    notes.extend(canon.repair(trial))
    canon.literal_keys(trial, notes)
    problem = _shape_problem(trial, without_goal_ok=False)
    if problem:
        raise StageRefused(problem)
    attrs: set[str] = set()
    pars: set[str] = set()
    _names_read(trial["ir"]["objective"], attrs, pars)
    declared = set((trial["ir"].get("parameters") or {}).keys())
    missing = sorted(p for p in pars if p not in declared)
    if missing:
        raise StageRefused(f"the goal reads {', '.join(missing)}, which no stage declared: declare it with "
                           "stage_decisions (parameters) and give its values in stage_data")
    terms = trial["ir"]["objective"]["terms"]
    said = (f"Goal staged: {objective['sense']} " + " + ".join(
        f"{t.get('weight', 1)} x {readback.term(t.get('expression'))}" if isinstance(t, dict) else "?" for t in terms)
        + (f"; reads {', '.join(sorted(attrs | pars))}" if attrs or pars else "")
        + ("; " + "; ".join(notes) if notes else ""))
    return said
