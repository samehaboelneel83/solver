"""Where each case's time went, from the backend's own log lines -- content-free, so it runs over the hidden set
(build-protocol plan, 16 Oct mission, Phase B/C). The log carries per reply: seconds, tokens read and written,
finish reason, and the tool calls' names and sizes; per call that yields no model, the argument keys and the
spec's type; per send-back, the platform's message (masked here to its template, as causes.py does).

    python -m bench.phase1.latency <log of assistant lines> <runner log> [utc offset hours, default 3]

<runner log> is runs/hidden-<tag>.log or runs-<tag>.log ("HH:MM:SS start <case>" / "HH:MM:SS done <case>").
Prints one row per case and the run's totals; never a problem's text.
"""

from __future__ import annotations

import collections
import json
import re
import statistics
import sys
from datetime import datetime, timedelta
from pathlib import Path

from bench.phase1.causes import template

_REPLY = re.compile(r"assistant\.reply seconds=([\d.]+) read=(\S+) wrote=(\S+) thinking=(\S+) finish=(\S+)"
                    r"(?: text=(\d+) calls=(\S+))?")
_SHAPE = re.compile(r"assistant\.spec_shape keys=(\[[^\]]*\]) spec_type=(\w+)")


def _windows(runner_log: Path, day: str, offset: int) -> list[tuple[str, datetime, datetime]]:
    starts: dict[str, datetime] = {}
    out = []
    base = datetime.fromisoformat(day)
    prev = None
    for line in runner_log.read_text(encoding="utf-8").splitlines():
        m = re.match(r"(\d\d:\d\d:\d\d) (start|done) (\S+)", line)
        if not m:
            continue
        t = datetime.combine(base.date(), datetime.strptime(m[1], "%H:%M:%S").time())
        if prev and t < prev:  # past midnight
            base += timedelta(days=1)
            t += timedelta(days=1)
        prev = t
        utc = t - timedelta(hours=offset)
        if m[2] == "start":
            starts[m[3]] = utc
        elif m[3] in starts:
            out.append((m[3], starts.pop(m[3]), utc))
    return out


def main(log: Path, runner_log: Path, day: str, offset: int = 3) -> None:
    events = []
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        ts = datetime.fromisoformat(e["timestamp"].replace("Z", "")[:26])
        events.append((ts, e["event"]))
    print(f"{'case':6} {'min':>5} {'replies':>7} {'model_s':>7} {'med_s':>5} {'p90_s':>5} {'wrote':>6} {'read':>6} "
          f"{'len':>3} {'plans':>5} {'checks':>6} {'noir':>4} {'sent':>4}  sent-back kinds")
    tot = collections.Counter()
    all_secs: list[float] = []
    for case, a, b in _windows(runner_log, day, offset):
        secs, wrote, read, length, plans, checks, noir, sent = [], [], [], 0, 0, 0, 0, collections.Counter()
        for ts, ev in events:
            if not a <= ts <= b:
                continue
            m = _REPLY.search(ev)
            if m:
                secs.append(float(m[1]))
                if m[3].isdigit():
                    wrote.append(int(m[3]))
                if m[2].isdigit():
                    read.append(int(m[2]))
                length += m[5] == "length"
                calls = m[7] or ""
                plans += calls.count("propose_plan:")
                checks += calls.count("check_spec:")
                continue
            if "assistant.spec_shape" in ev and _SHAPE.search(ev):
                noir += 1
                continue
            if "assistant.sent_back" in ev:
                sent[template(ev.split("assistant.sent_back", 1)[1])[:50]] += 1
        all_secs += secs
        minutes = (b - a).total_seconds() / 60
        q = statistics.quantiles(secs, n=10)[-1] if len(secs) >= 10 else (max(secs) if secs else 0)
        print(f"{case:6} {minutes:5.1f} {len(secs):7} {sum(secs):7.0f} {statistics.median(secs) if secs else 0:5.0f} "
              f"{q:5.0f} {statistics.mean(wrote) if wrote else 0:6.0f} {max(read) if read else 0:6} {length:3} {plans:5} "
              f"{checks:6} {noir:4} {sum(sent.values()):4}  " + "; ".join(f"{n}x {k}" for k, n in sent.most_common(3)))
        tot.update(replies=len(secs), model_s=int(sum(secs)), plans=plans, checks=checks, noir=noir,
                   sent=sum(sent.values()), length=length, wall_s=int((b - a).total_seconds()))
    if all_secs:
        print(f"\nall: {tot['replies']} replies, model time {tot['model_s']} s of {tot['wall_s']} s wall "
              f"({100 * tot['model_s'] / max(tot['wall_s'], 1):.0f}%), reply median {statistics.median(all_secs):.0f} s, "
              f"p90 {statistics.quantiles(all_secs, n=10)[-1]:.0f} s; whole plans {tot['plans']}, checks {tot['checks']}, "
              f"no-model calls {tot['noir']}, send-backs {tot['sent']}, cut at length {tot['length']}")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], int(sys.argv[4]) if len(sys.argv) > 4 else 3)
