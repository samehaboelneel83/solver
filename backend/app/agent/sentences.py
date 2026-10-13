"""Every sentence of the request mapped (build-protocol plan, Phase 3.2): a sentence of the person's that states
a rule or a goal, and that no add_rule claimed and no stage_goal covers, is a card line -- CHECK THIS: no rule
holds "...". The request on the left, the model on the right.

Only on the protocol path (a plan built in stages): there each rule carries the sentence it holds, so the
mapping is exact. A plan written whole carries the model's own notes, not the person's words, and the line
would be noise.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.agent.files import _row_like

#: A sentence that states a rule: a limit, an obligation, a prohibition, an exact count.
RULE_WORDS = re.compile(
    r"^\s*no\b|\b(?:must(?:n't| not)?|never|cannot|can't|can not|may not|not allowed|is not permitted|has to|"
    r"have to|at most|at least|no more than|no less than|no fewer than|not more than|not less than|not exceed|"
    r"exceed|up to|maximum|minimum|limit(?:ed)?|only|exactly|within|without|before|after|between|capacity|"
    r"deadline|required|at a time|per\b)", re.I)
#: A sentence that states the goal.
GOAL_WORDS = re.compile(
    r"\b(?:minimi[sz]e|maximi[sz]e|lowest|highest|cheapest|fewest|smallest|largest|(?<!at )least|(?<!at )most|"
    r"best|as (?:few|many|little|much|low|high|cheap) as possible|goal|objective|optimi[sz]e)\b", re.I)
_SPLIT = re.compile(r"(?<=[.!?;])\s+|\n+")
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)]|[a-z][.)])\s+", re.I)
_STOP = {"the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "is", "are", "be", "that", "this", "it",
         "with", "as", "by", "at", "each", "every", "all", "any", "than", "from", "we", "our", "you", "your", "i",
         "they", "their", "its", "not", "no", "can", "should", "would", "will", "per", "one", "two"}
#: How alike a claim and a sentence must be (the share of the shorter one's words the other holds).
MATCH = 0.6
#: How many sentences the card names at most.
NAMED = 8


def sentences_of(text: str) -> list[str]:
    """The sentences of a message's prose: split on full stops and lines, bullets stripped, a pasted table's
    rows and anything under four words left out."""
    out: list[str] = []
    for raw in _SPLIT.split(text or ""):
        line = _BULLET.sub("", raw).strip()
        if len(line.split()) < 4 or _row_like(line) >= 2:
            continue
        out.append(line)
    return out


def states_a_rule(sentence: str) -> bool:
    return bool(RULE_WORDS.search(sentence))


def states_a_goal(sentence: str) -> bool:
    return bool(GOAL_WORDS.search(sentence))


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOP}


def alike(sentence: str, claim: str) -> bool:
    """A claim holds a sentence when one is inside the other, or they share most of their words."""
    a, b = sentence.strip().lower(), claim.strip().lower()
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return False
    return len(wa & wb) / min(len(wa), len(wb)) >= MATCH


def staged(messages: list[dict[str, Any]]) -> bool:
    """Whether the plan was built in stages (any add_rule call): the mapping applies only then."""
    return any((c.get("function") or {}).get("name") == "add_rule"
               for m in messages if m.get("role") == "assistant" for c in m.get("tool_calls") or [])


def claims(messages: list[dict[str, Any]], spec: dict[str, Any] | None = None) -> tuple[list[str], bool]:
    """The sentences the rules claim (every add_rule's sentence, every rule's note) and whether a goal is staged."""
    said: list[str] = []
    goal = False
    for m in messages:
        if m.get("role") != "assistant":
            continue
        for c in m.get("tool_calls") or []:
            name = (c.get("function") or {}).get("name")
            if name not in ("add_rule", "stage_goal"):
                continue
            try:
                raw = (c.get("function") or {}).get("arguments")
                args = json.loads(raw) if isinstance(raw, str) else (raw or {})
            except ValueError:
                continue
            if name == "stage_goal":
                goal = True
                if isinstance(args.get("sentence"), str):
                    said.append(args["sentence"])
            elif isinstance(args.get("sentence"), str) and args["sentence"].strip():
                said.append(args["sentence"])
    ir = (spec or {}).get("ir") if isinstance((spec or {}).get("ir"), dict) else {}
    for c in ir.get("constraints") or []:
        if isinstance(c, dict) and isinstance(c.get("note"), str) and c["note"].strip():
            said.append(c["note"])
    goal = goal or isinstance(ir.get("objective"), dict)
    return said, goal


def persons_sentences(messages: list[dict[str, Any]]) -> list[str]:
    """What the person wrote, sentence by sentence (never the platform's own messages)."""
    from app.agent.core import PLATFORM

    out: list[str] = []
    for m in messages:
        if m.get("role") == "user" and not str(m.get("content") or "").startswith(PLATFORM):
            out.extend(sentences_of(str(m.get("content") or "")))
    return out


def unmatched(messages: list[dict[str, Any]], spec: dict[str, Any] | None = None) -> dict[str, list[str]]:
    """The person's rule sentences no rule claims, and the goal sentences when no goal is staged: {"rules":
    [...], "goal": [...]}; empty off the protocol path."""
    if not staged(messages):
        return {"rules": [], "goal": []}
    said, goal = claims(messages, spec)
    rules: list[str] = []
    goals: list[str] = []
    for s in persons_sentences(messages):
        if any(alike(s, c) for c in said):
            continue
        if states_a_rule(s):
            rules.append(s)
        elif states_a_goal(s) and not goal:
            goals.append(s)
    return {"rules": rules, "goal": goals}


def sentences_for_person(messages: list[dict[str, Any]], spec: dict[str, Any] | None = None) -> str:
    """The card lines: each rule sentence no rule holds, and the goal sentence when no goal is staged."""
    missing = unmatched(messages, spec)
    lines = [f'\n- CHECK THIS: no rule holds "{s[:160]}" -- if it is a rule of the problem, it is missing' for s in missing["rules"][:NAMED]]
    if len(missing["rules"]) > NAMED:
        lines.append(f"\n- CHECK THIS: {len(missing['rules']) - NAMED} more sentence(s) that state a rule are held by no rule")
    lines.extend(f'\n- CHECK THIS: no goal holds "{s[:160]}"' for s in missing["goal"][:2])
    return "".join(lines)


def mapping(messages: list[dict[str, Any]], spec: dict[str, Any] | None = None) -> list[tuple[str, str]]:
    """The request on the left, the model on the right: each of the person's rule or goal sentences with the
    rule id that claims it, or "--" (for the card's table, Phase 3.5)."""
    ir = (spec or {}).get("ir") if isinstance((spec or {}).get("ir"), dict) else {}
    notes = [(str(c.get("id")), c["note"]) for c in ir.get("constraints") or []
             if isinstance(c, dict) and isinstance(c.get("note"), str)]
    out: list[tuple[str, str]] = []
    for s in persons_sentences(messages):
        if not (states_a_rule(s) or states_a_goal(s)):
            continue
        held = [rid for rid, note in notes if alike(s, note)]
        out.append((s, ", ".join(held) if held else "--"))
    return out
