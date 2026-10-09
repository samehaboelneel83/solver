"""A replay set: recorded conversations scored again by today's reply checks (handover of 8 October 2026,
honest answers: "a replay set that counts unsupported statements").

Each final answer of each conversation is checked against what it rested on -- the tool results since the person's
message before it (or, if it called no tool, the latest run results before it) and what the person had said -- with
the checks the Assistant's answers go through now:

- `contradiction`: a statement the results contradict, an unproven "optimal" among them (`reply_contradictions`);
- `stale_total`: a total near, but not, what the tools gave (`stale_totals`);
- `unsupported_number`: a number no result, person or single step of arithmetic gives (`unsupported_numbers`);
- `unsupported_what_if`: what a change would do, with no what-if run or ranged rate behind it
  (`unsupported_what_ifs`).

Answers the platform already sent back while the conversation ran are kept in the history as "(... not shown)";
they are counted as caught, by kind. A set is a JSON-lines file, one conversation per line ({"id", "mode",
"messages"}), so the same conversations can be scored again after each change:

    python -m app.agent.replay export SET.jsonl [--days 30]     recorded conversations, every organization
    python -m app.agent.replay score SET.jsonl [--json]         the counts, and examples of each kind
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from typing import Any, Iterable

from app.agent.core import (PLATFORM, _REPORTS_RUN, reply_contradictions, stale_totals, unsupported_numbers,
                            unsupported_what_ifs)

#: How the loop marks an answer it sent back (app.agent.core), by the kind of check that caught it.
_CAUGHT = {"an answer with numbers the results do not give": "unsupported_number",
           "an answer with what-if amounts no run gives": "unsupported_what_if",
           "an answer the results contradict": "contradiction",
           "an answer with a wrong total": "stale_total",
           "an answer with second thoughts in it": "second_thoughts",
           "a reply that ran to the length limit": "length_limit"}
KINDS = ("contradiction", "stale_total", "unsupported_number", "unsupported_what_if")
#: Examples kept per kind in a report.
EXAMPLES = 5


def _text(m: dict) -> str:
    content = m.get("content")
    if isinstance(content, list):  # parts
        return " ".join(str(p.get("text") or "") for p in content if isinstance(p, dict))
    return str(content or "")


def _person(m: dict) -> bool:
    return m.get("role") == "user" and not _text(m).startswith(PLATFORM)


def answers(messages: list[dict]) -> Iterable[tuple[int, str, list[str], list[str], list[str]]]:
    """Each final answer: (index, answer, the results it rested on, every tool text before it, the person's words)."""
    for i, m in enumerate(messages):
        text = _text(m)
        if m.get("role") != "assistant" or m.get("tool_calls") or not text.strip() or text.startswith("("):
            continue
        turn: list[str] = []
        for prior in reversed(messages[:i]):
            if _person(prior):
                break
            if prior.get("role") == "tool":
                turn.append(_text(prior))
        before = [_text(p) for p in messages[:i] if p.get("role") == "tool"]
        if not turn:  # no tool this turn: the latest run results before it
            turn = [t for t in before if re.search(r"\bRUN \d+: ", t)][-2:]
        person = [_text(p) for p in messages[:i] if p.get("role") == "user"]
        yield i, text, turn, before, person


def score_conversation(messages: list[dict]) -> dict[str, Any]:
    found: dict[str, list[dict]] = {k: [] for k in KINDS}
    caught: Counter = Counter()
    checked = 0
    for m in messages:
        if m.get("role") == "assistant":
            said = _text(m)
            for marker, kind in _CAUGHT.items():
                if said.startswith("(" + marker):
                    caught[kind] += 1
    for i, answer, basis, before, person in answers(messages):
        checked += 1
        reports = any(_REPORTS_RUN.search(t) for t in basis)
        got = {
            "contradiction": reply_contradictions(answer, basis),
            "stale_total": [f"{said} for {field} (the tools say {right})" for said, right, field in stale_totals(answer, basis)],
            "unsupported_number": unsupported_numbers(answer, basis, person + before) if reports else [],
            "unsupported_what_if": unsupported_what_ifs(answer, before, person) if reports else [],
        }
        for kind, items in got.items():
            if items:
                found[kind].append({"answer": i, "items": list(items)[:8], "text": answer[:300]})
    return {"answers": checked, "flagged": {k: sum(len(f["items"]) for f in v) for k, v in found.items()},
            "answers_flagged": len({f["answer"] for v in found.values() for f in v}), "caught_live": dict(caught),
            "found": found}


def score(conversations: Iterable[dict]) -> dict[str, Any]:
    total: Counter = Counter()
    caught: Counter = Counter()
    examples: dict[str, list[dict]] = {k: [] for k in KINDS}
    per: list[dict] = []
    answers_checked = answers_flagged = 0
    for c in conversations:
        got = score_conversation(c.get("messages") or [])
        answers_checked += got["answers"]
        answers_flagged += got["answers_flagged"]
        total.update(got["flagged"])
        caught.update(got["caught_live"])
        per.append({"id": c.get("id"), "mode": c.get("mode"), "answers": got["answers"], "flagged": got["flagged"]})
        for kind, items in got["found"].items():
            for item in items:
                if len(examples[kind]) < EXAMPLES:
                    examples[kind].append({"conversation": c.get("id"), **item})
    return {"conversations": len(per), "answers": answers_checked, "answers_flagged": answers_flagged,
            "flagged": {k: total.get(k, 0) for k in KINDS}, "caught_live": dict(caught), "examples": examples,
            "by_conversation": per}


def as_text(report: dict[str, Any]) -> str:
    lines = [f"{report['conversations']} conversations, {report['answers']} final answers; "
             f"{report['answers_flagged']} answers would be sent back by today's checks."]
    for kind in KINDS:
        lines.append(f"  {kind}: {report['flagged'][kind]}")
    if report["caught_live"]:
        lines.append("Already sent back while they ran: " + ", ".join(f"{k} {v}" for k, v in sorted(report["caught_live"].items())))
    for kind, items in report["examples"].items():
        for e in items:
            lines.append(f"- {kind} in {e['conversation']} (message {e['answer']}): {', '.join(map(str, e['items']))}")
    return "\n".join(lines)


def export(path: str, days: int = 30) -> int:
    """Every organization's recorded conversations of the last `days`, as a replay set (system code, run by the
    operator in the backend container)."""
    from sqlalchemy import text
    from sqlalchemy.orm import Session

    from app.core.db import engine

    n = 0
    with Session(bind=engine) as db, open(path, "w", encoding="utf-8") as out:
        for cid, mode, messages in db.execute(text(
                "SELECT id, mode, messages FROM agent_conversation WHERE updated_at > now() - make_interval(days => :d)"
                " ORDER BY updated_at"), {"d": days}):
            out.write(json.dumps({"id": cid, "mode": mode, "messages": messages}, ensure_ascii=False, default=str) + "\n")
            n += 1
    return n


def load(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.agent.replay", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    e = sub.add_parser("export", help="write recorded conversations to a replay set")
    e.add_argument("path")
    e.add_argument("--days", type=int, default=30)
    s = sub.add_parser("score", help="score a replay set with today's checks")
    s.add_argument("path")
    s.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "export":
        print(f"{export(args.path, args.days)} conversations written to {args.path}")
        return 0
    report = score(load(args.path))
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str) if args.json else as_text(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
