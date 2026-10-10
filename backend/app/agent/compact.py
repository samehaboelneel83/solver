"""Compacting a long Assistant conversation into a summary, so it never outgrows the model's context.

The model's memory is its context (vLLM's `--max-model-len`). Every turn re-sends the whole conversation:
the brief, the files read, every tool call and result. A field test filled 32k tokens in one problem, and
`fit()` then dropped the oldest exchanges outright, with what they held (the camp-bed retest lost the
brief and asked "What decision are you making?").

Instead, when the conversation passes a share of the context (`LLM_COMPACT_AT`, 0.6 by default), the older
part is **summarized by the model itself** into one message, and the recent part is kept word for word:

- the summary has fixed headings: problem, agreed, data, platform ids, done, open. Every id, file name and
  number is kept exactly;
- the person's first message (the brief) and, when it falls in the summarized part, their latest request
  are carried word for word;
- what the platform's checks rely on is carried by code, not by the model's summary:
  - the numbers the person gave and the tools computed (`[on record] numbers:`), which the data-values check
    accepts. The summary's own prose vouches for nothing;
  - the build (`[on record] built:`), which permits solving;
- a summary of a summary rolls forward: the older summary is folded into the new one;
- a transcript longer than the context is summarized in pieces, each piece folded into the summary so far.

The compacted history goes back to the browser in the turn's `state`, so the next turn sends the short
version. The person can also ask for it: a message that is just `/compact` summarizes the conversation now
and shows the summary.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable

#: Starts with core.PLATFORM ("[Platform] "): a platform message, not the person's words.
SUMMARY_MARK = "[Platform] EARLIER CONVERSATION, SUMMARIZED"
ACK = "Understood. I have the summary of our earlier conversation and will continue from it."
COMMANDS = ("/compact", "/summarize", "/summarise")
RESETS = ("/reset", "/new", "/clear")
NUMBERS_LINE = "[on record] numbers: "
BUILT_LINE = "[on record] built: "
TURNS_LINE = "[on record] user turns: "
MAX_NUMBERS = 4000
BRIEF_CHARS = 4000
BRIEF_END = "(end of the first message)"
#: Each message's share of a transcript sent to be summarized.
TOOL_CHARS = 2500
ARGS_CHARS = 1500
TEXT_CHARS = 6000
#: The fewest messages worth summarizing.
MIN_SUMMARIZED = 4

SUMMARIZER = """You compress a working conversation between a person and the platform's Assistant (an \
optimization modelling platform: map data, records, relationships, data values, models, solves) so the \
Assistant can continue the work without the original conversation.

Write compact notes under exactly these headings:
## Problem
The person's goal, in their words.
## Agreed
Every rule, choice, preference and number the person gave or confirmed, with units.
## Data
Files attached (sheets, layers); what was read or computed (run_python scripts and the files they wrote, \
queries), and the numbers found, each with where it came from.
## Platform
Every id and what it is: domain_id, map data (dataset) ids, kinds of record, relationship types, \
parameters, problem_id, model version, scenario_id, run ids with their status and goal value.
## Done
The steps completed, in order.
## Open
Questions not answered yet, errors still to fix (the exact message), and the next step.

Rules: keep every id, file name, field name and number EXACTLY as written. Never invent anything. Drop \
small talk, the details of failed attempts (keep only what was learned), and tool output a later one \
replaced. Plain notes, no preamble. At most {words} words."""


def is_summary(message: dict[str, Any]) -> bool:
    return message.get("role") == "user" and str(message.get("content") or "").startswith(SUMMARY_MARK)


def is_command(message: dict[str, Any] | None) -> bool:
    return bool(message) and message.get("role") == "user" and \
        str(message.get("content") or "").strip().lower() in COMMANDS


def size(messages: list[dict[str, Any]]) -> int:
    """Characters as sent: the same measure `fit()` uses."""
    return sum(len(json.dumps(m, ensure_ascii=False, default=str)) for m in messages)


def recorded_numbers(message: dict[str, Any]) -> set[float]:
    """The numbers a summary carries on record (written by code, never by the model)."""
    out: set[float] = set()
    for line in str(message.get("content") or "").splitlines():
        if line.startswith(NUMBERS_LINE):
            for raw in line[len(NUMBERS_LINE):].split(","):
                try:
                    out.add(round(float(raw.strip()), 6))
                except ValueError:
                    continue
    return out


def recorded_build(message: dict[str, Any]) -> dict[str, Any] | None:
    for line in str(message.get("content") or "").splitlines():
        if line.startswith(BUILT_LINE):
            try:
                return json.loads(line[len(BUILT_LINE):])
            except ValueError:
                return {"built": True}
    return None


def recorded_turns(message: dict[str, Any]) -> int:
    if not is_summary(message):
        return 0
    for line in str(message.get("content") or "").splitlines():
        if line.startswith(TURNS_LINE):
            try:
                return max(0, int(line[len(TURNS_LINE):]))
            except ValueError:
                return 0
    return 0


def _body(message: dict[str, Any]) -> str:
    """A summary's notes, without its carried lines."""
    text = str(message.get("content") or "")[len(SUMMARY_MARK):]
    return "\n".join(l for l in text.splitlines() if not l.startswith(("[on record]",))).strip()


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + f" ...[{len(text) - limit} characters more]"


def _clip_ends(text: str, limit: int, tail: int = 800) -> str:
    """Its beginning and its end: a request's last lines are often what to do ("propose the model without further
    questions") -- clipped off, the go-ahead was lost in the phase 1 rerun (10 October 2026)."""
    if len(text) <= limit:
        return text
    return text[:limit - tail] + f" ...[{len(text) - limit} characters left out]... " + text[-tail:]


def transcript(messages: list[dict[str, Any]]) -> list[str]:
    """The conversation as lines a summarizer reads, one per message."""
    lines = []
    for m in messages:
        role, content = m.get("role"), str(m.get("content") or "")
        if role == "user":
            lines.append(f"PERSON: {_clip(content, TEXT_CHARS)}" if not content.startswith("[Platform]")
                         else f"PLATFORM NOTE: {_clip(content, TOOL_CHARS)}")
        elif role == "assistant":
            parts = [f"ASSISTANT: {_clip(content, TEXT_CHARS)}"] if content.strip() else []
            for c in m.get("tool_calls") or []:
                fn = c.get("function") or {}
                parts.append(f"ASSISTANT CALLS {fn.get('name')}: {_clip(str(fn.get('arguments') or ''), ARGS_CHARS)}")
            lines.append("\n".join(parts) or "ASSISTANT: (no text)")
        elif role == "tool":
            lines.append(f"RESULT of {m.get('name')}: {_clip(content, TOOL_CHARS)}")
    return lines


def cut_point(messages: list[dict[str, Any]], keep_chars: int) -> int | None:
    """Where the kept, word-for-word part starts: as much of the end as fits `keep_chars`, starting at the
    person's message or at an Assistant message (never at a tool result, which needs its call)."""
    best = None
    tail = 0
    for i in range(len(messages) - 1, 0, -1):
        tail += size([messages[i]])
        if tail > keep_chars:
            break
        if messages[i].get("role") in ("user", "assistant") and not is_summary(messages[i]) \
                and messages[i].get("content") != ACK:
            best = i
    if best is None:
        # Even the last exchange is too big to keep whole: keep from the last boundary there is.
        best = next((i for i in range(len(messages) - 1, 0, -1)
                     if messages[i].get("role") in ("user", "assistant") and not is_summary(messages[i])
                     and messages[i].get("content") != ACK), None)
    if best is None:
        return None
    summarized = [m for m in messages[:best] if not is_summary(m) and m.get("content") != ACK]
    return best if len(summarized) >= MIN_SUMMARIZED else None


def compact(messages: list[dict[str, Any]], *, summarize: Callable[[str, str], str], keep_chars: int,
            piece_chars: int, numbers: Callable[[list[dict[str, Any]]], set[float]],
            force: bool = False) -> dict[str, Any] | None:
    """Replace the older part of `messages` (in place) by one summary message. Returns what was done, or None
    when there is too little to summarize. `summarize(transcript_piece, summary_so_far)` asks the model."""
    cut = cut_point(messages, 1 if force else keep_chars)
    if cut is None:
        return None
    old, tail = messages[:cut], messages[cut:]
    earlier = [m for m in old if is_summary(m)]
    plain = [m for m in old if not is_summary(m) and not (m.get("role") == "assistant" and m.get("content") == ACK)]
    notes = _body(earlier[-1]) if earlier else ""
    lines = transcript(plain)
    piece: list[str] = []
    for line in lines:
        if piece and sum(len(l) for l in piece) + len(line) > piece_chars:
            notes = summarize("\n\n".join(piece), notes)
            piece = []
        piece.append(line)
    if piece:
        notes = summarize("\n\n".join(piece), notes)
    carried: set[float] = set()
    for m in earlier:
        carried |= recorded_numbers(m)
    carried |= numbers(plain)
    built = next((recorded_build(m) for m in reversed(earlier) if recorded_build(m)), None)
    for m in plain:
        content = str(m.get("content") or "")
        if m.get("role") == "tool" and m.get("name") == "propose_plan" and content.startswith("BUILT "):
            try:
                built = json.loads(content[6:].split(" Now explain")[0])
            except ValueError:
                built = {"built": True}
    real_users = [m for m in plain if m.get("role") == "user" and not str(m.get("content") or "").startswith("[Platform]")]
    brief = _brief(earlier, real_users)
    latest = None
    if real_users and not any(m.get("role") == "user" and not str(m.get("content") or "").startswith("[Platform]")
                              for m in tail):
        latest = str(real_users[-1].get("content") or "")
        if brief and latest == brief:
            latest = None
    parts = [SUMMARY_MARK + " (to stay within the model's memory; the recent messages follow word for word)"]
    parts.append(TURNS_LINE + str(len(real_users) + sum(recorded_turns(m) for m in earlier)))
    if brief:
        parts.append("The person's first message, word for word:\n" + _clip_ends(brief, BRIEF_CHARS) + "\n" + BRIEF_END)
    parts.append(notes.strip() or "(no notes)")
    if latest:
        parts.append("The person's latest request, word for word (still being worked on):\n" + _clip(latest, BRIEF_CHARS))
    if carried:
        shown = sorted(carried)[:MAX_NUMBERS]
        parts.append(NUMBERS_LINE + ", ".join(f"{v:g}" for v in shown))
    if built:
        parts.append(BUILT_LINE + json.dumps(built, default=str))
    summary = {"role": "user", "content": "\n\n".join(parts)}
    head = [summary] + ([{"role": "assistant", "content": ACK}] if tail and tail[0].get("role") == "user" else [])
    before = len(messages)
    before_chars = size(messages)
    messages[:] = head + tail
    return {"summarized": len(plain), "kept": len(tail), "before": before, "after": len(messages),
            "chars_before": before_chars, "chars_after": size(messages), "notes": notes}


def _brief(earlier: list[dict[str, Any]], real_users: list[dict[str, Any]]) -> str | None:
    """The first thing the person wrote: from an earlier summary when there is one, else the first message."""
    if earlier:
        text = str(earlier[0].get("content") or "")
        found = re.search(r"The person's first message, word for word:\n(.*?)\n" + re.escape(BRIEF_END), text, re.S)
        if found:
            return found.group(1)
    return str(real_users[0].get("content") or "") if real_users else None
