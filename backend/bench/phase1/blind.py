"""Aggregate scores of a set of cases, without their content (the hidden set must stay unread by whoever fixes
the platform: docs/plans/2026-10-10-neutrality-plan.md).

    python -m bench.phase1.blind <runs dir> <tag>

Prints, per case, only yes/no and numbers -- built, first time, right goal, rule violations (a count), warned on
the plan card, minutes -- and the totals. Never the problem, the violations' text, the goal or the reply.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main(runs: Path, tag: str) -> None:
    rows = []
    for score in sorted(runs.glob(f"*-{tag}/score.json")):
        case = score.parent.name[: -len(tag) - 1]
        try:
            s = json.loads(score.read_text(encoding="utf-8"))
        except ValueError:
            rows.append((case, "score unreadable"))
            continue
        violations = [v for v in (s.get("violations") or []) if not v.startswith("no ")]
        unreadable = any(v.startswith("no ") for v in (s.get("violations") or []))
        right = bool(s.get("right_goal")) and not violations and not unreadable
        rows.append((case, {
            "built": bool(s.get("built")), "first_time": bool(s.get("first_time")), "solved": s.get("status") in ("optimal", "feasible"),
            "right": right, "violations": len(violations), "checker_could_not_read": unreadable,
            "warned": int(s.get("warned_on_card") or 0), "minutes": s.get("minutes")}))
    print(f"{'case':<14} built  first  solved right  viol  warned  min")
    for case, r in rows:
        if isinstance(r, str):
            print(f"{case:<14} {r}")
            continue
        yn = lambda b: "yes" if b else "no"  # noqa: E731
        print(f"{case:<14} {yn(r['built']):<6} {yn(r['first_time']):<6} {yn(r['solved']):<6} {yn(r['right']):<5} "
              f"{r['violations']:<5} {r['warned']:<7} {r['minutes']}" + ("  (checker could not read the plan)" if r["checker_could_not_read"] else ""))
    good = [r for _, r in rows if isinstance(r, dict)]
    print(f"\n{sum(r['right'] for r in good)} right of {len(good)}; built {sum(r['built'] for r in good)}; "
          f"wrong but solved {sum(r['solved'] and not r['right'] for r in good)} "
          f"(of them warned on the card {sum(r['solved'] and not r['right'] and r['warned'] > 0 for r in good)})")


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2])
