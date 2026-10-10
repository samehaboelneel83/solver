"""Does the Assistant build a described problem first time?

    python -m bench.assistant [--case NAME] [--runs N] [--out PATH] [--nudges N]

Each case is one message a person would write (`bench/assistant_cases/<name>.txt`) and the goal value the right
model reaches. The case is sent to the running platform's Assistant as the admin user, in "describe a problem"
mode; a plan it proposes is approved; a reply that neither proposes nor builds is answered "continue", at most
`--nudges` times. What is measured, per case:

    built        the plan was built (a plan whose trial says "NO answer exists" is not approved: it is sent
                 back as a person would, which counts as a "continue")
    first time   built with no "continue" and no stop ("the same problem came back ...")
    corrections  steps the platform sent back for the Assistant to put right
    goal         the built problem's solved goal value, against the case's

The Nile Juice trace (10 October 2026) is the first case: it took two conversations and several "continue"s.
Run inside the backend container (it calls the API on the loopback, as the Assistant itself does); it uses the
live language model and makes a workspace per case, named "bench <stamp> <case>". Exit 1 unless every case is
built first time with the right goal.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from datetime import date
from pathlib import Path
from typing import Any

CASES_DIR = Path(__file__).parent / "assistant_cases"
#: case name -> the goal value the right model reaches (proven, checked against an independent solve).
EXPECT: dict[str, float] = {"nile_juice": 116235.0, "delta_pharma": 189900.0, "ward_roster": 14370.0,
                            "feed_mill": 3937795.79}
STOPS = ("came back", "so I stopped", "I could not write")


def _token() -> str:
    from app.core.config import get_settings
    from app.core.db import SessionLocal
    from app.core.security import create_access_token
    from app.models.iam import UserAccount

    db = SessionLocal()
    try:
        user = db.query(UserAccount).filter(UserAccount.username == get_settings().admin_username).first()
        return create_access_token(user.username, 240, token_version=user.token_version or 0)
    finally:
        db.close()


def _turn(base: str, headers: dict[str, str], body: dict[str, Any]) -> list[dict[str, Any]]:
    import httpx

    events: list[dict[str, Any]] = []
    with httpx.stream("POST", base + "/api/v1/agent/chat", headers=headers, json=body,
                      timeout=httpx.Timeout(3600, connect=30)) as response:
        if response.status_code != 200:
            response.read()
            return [{"type": "error", "text": f"HTTP {response.status_code}: {response.text[:300]}"}]
        for line in response.iter_lines():
            if line.strip():
                event = json.loads(line)
                if event.get("type") not in ("ping", "state"):
                    events.append(event)
    return events


def _goal(base: str, headers: dict[str, str], scenario_id: int, wait: float = 300.0) -> tuple[float | None, str]:
    """The scenario's latest run: its goal and status, once every run of it has settled."""
    import httpx

    until = time.monotonic() + wait
    asked = False
    while True:
        rows = httpx.get(base + f"/api/v1/runs?scenario_id={scenario_id}", headers=headers, timeout=60).json()
        rows = rows.get("items", rows) if isinstance(rows, dict) else rows
        rows = [r for r in rows if r.get("scenario_id") == scenario_id]
        settled = [r for r in rows if r.get("status") not in ("queued", "running")]
        if rows and len(settled) == len(rows):
            best = max(settled, key=lambda r: r["id"])
            return best.get("objective"), f"{best.get('status')}/{best.get('optimality')}"
        if time.monotonic() > until:
            return None, "still solving" if rows else "no run"
        if not rows and not asked:
            # The Assistant built but did not solve: the run a person would ask for next.
            httpx.post(base + f"/api/v1/scenarios/{scenario_id}/runs", headers=headers, json={}, timeout=60)
            asked = True
        time.sleep(5)


def run_case(name: str, base: str, headers: dict[str, str], nudges: int, stamp: str) -> dict[str, Any]:
    text = (CASES_DIR / f"{name}.txt").read_text(encoding="utf-8").replace("{workspace}", f"bench {stamp} {name}")
    conversation = uuid.uuid4().hex
    record: dict[str, Any] = {"case": name, "conversation": conversation, "built": False, "nudged": 0, "stopped": 0,
                              "corrections": 0, "warned": 0, "turns": 0, "goal": None, "status": "", "why": []}
    started = time.monotonic()
    body: dict[str, Any] = {"mode": "model", "text": text}
    scenario = None
    while True:
        events = _turn(base, headers, {**body, "conversation_id": conversation, "server_history": True})
        record["turns"] += 1
        kinds = [e.get("type") for e in events]
        for e in events:
            if e.get("type") == "result" and e.get("ok") is False:
                record["corrections"] += 1
                record["why"].append(str(e.get("preview"))[:160])
            if e.get("type") == "error":
                record["why"].append("error: " + str(e.get("text"))[:160])
        said = " ".join(str(e.get("text") or "") for e in events if e.get("type") == "answer")
        if any(s in said for s in STOPS):
            record["stopped"] += 1
        built = next((e for e in events if e.get("type") == "built"), None)
        if built is not None:
            record["built"], scenario = True, built.get("scenario_id")
            break
        plan = next((e for e in events if e.get("type") == "plan"), None)
        if plan is not None and "NO answer exists" in str(plan.get("readback") or plan.get("summary") or ""):
            # A person reads the plan card: a trial with no answer is not approved, it is sent back in their words.
            record["warned"] += 1
            if record["nudged"] >= nudges:
                break
            record["nudged"] += 1
            body = {"mode": "model", "text": "The trial on the plan says no answer exists, but this problem has one. "
                                             "Check the rules it names against what I described and fix the model."}
            continue
        if "plan" in kinds or "confirm" in kinds:
            body = {"mode": "model", "confirm": {"allow": True}}
            continue
        if record["nudged"] >= nudges:
            break
        record["nudged"] += 1
        body = {"mode": "model", "text": "continue"}
    record["seconds"] = round(time.monotonic() - started)
    if scenario is not None:
        record["goal"], record["status"] = _goal(base, headers, int(scenario))
    want = EXPECT.get(name)
    record["right"] = (record["goal"] is not None and want is not None
                       and abs(float(record["goal"]) - want) <= 1e-6 * max(1.0, abs(want)))
    record["first_time"] = record["built"] and record["nudged"] == 0 and record["stopped"] == 0
    return record


def report_md(day: str, model: str, rows: list[dict[str, Any]]) -> str:
    first = sum(1 for r in rows if r["first_time"] and r["right"])
    wrong = sum(1 for r in rows if r["built"] and not r["right"])
    lines = [f"# The Assistant, building described problems -- {day}", "",
             f"Language model: {model}. {first} of {len(rows)} runs built first time with the right goal; "
             f"{wrong} built a model that did not reach it.", ""]
    names = list(dict.fromkeys(r["case"] for r in rows))
    if len(rows) > len(names):
        # The language model's answers vary from run to run, so a case is its share of runs, not one of them.
        lines += ["| case | runs | first time, right goal | built wrong | not built | median seconds |", "|---|---|---|---|---|---|"]
        for name in names:
            mine = [r for r in rows if r["case"] == name]
            seconds = sorted(r["seconds"] for r in mine)
            lines.append(f"| {name} | {len(mine)} | {sum(1 for r in mine if r['first_time'] and r['right'])} "
                         f"| {sum(1 for r in mine if r['built'] and not r['right'])} "
                         f"| {sum(1 for r in mine if not r['built'])} | {seconds[len(seconds) // 2]} |")
        lines.append("")
    lines += [
             '| case | built | first time | right goal | goal | "continue" | stops | corrections | turns | seconds |',
             "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['case']} | {r['built']} | {r['first_time']} | {r['right']} | {r['goal']} ({r['status']}) "
                     f"| {r['nudged']} | {r['stopped']} | {r['corrections']} | {r['turns']} | {r['seconds']} |")
    for r in rows:
        if r["why"]:
            lines += ["", f"## {r['case']}: what was sent back", ""] + [f"- {w}" for w in r["why"]]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    import httpx

    parser = argparse.ArgumentParser(prog="python -m bench.assistant")
    parser.add_argument("--case", action="append", help="a case by name (default: all)")
    parser.add_argument("--runs", type=int, default=1, help="how many times to run each case (default 1)")
    parser.add_argument("--nudges", type=int, default=3, help='how many times to answer "continue" (default 3)')
    parser.add_argument("--base", default="http://localhost:8000")
    parser.add_argument("--out", default=None, help="report path (default: bench/results/<day>-assistant.md)")
    args = parser.parse_args(argv)
    names = args.case or sorted(p.stem for p in CASES_DIR.glob("*.txt"))
    headers = {"Authorization": f"Bearer {_token()}"}
    status = httpx.get(args.base + "/api/v1/agent/status", headers=headers, timeout=60).json()
    if not status.get("enabled") or status.get("ok") is False:
        print(f"the Assistant is not ready: {json.dumps(status)[:300]}")
        return 2
    stamp = time.strftime("%m%d-%H%M")
    rows = []
    for attempt in range(1, max(1, args.runs) + 1):
        for name in names:
            row = run_case(name, args.base, headers, args.nudges, f"{stamp}-{attempt}")
            rows.append(row)
            print(json.dumps({k: v for k, v in row.items() if k != "why"}), flush=True)
    day = date.today().isoformat()
    out = Path(args.out) if args.out else Path(__file__).parent / "results" / f"{day}-assistant.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report_md(day, str(status.get("model")), rows), encoding="utf-8")
    print(f"report in {out}")
    return 0 if all(r["first_time"] and r["right"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
