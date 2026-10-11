"""Three runs of the tuning set as one reading: per case, how many of the three were right, built and warned,
and the totals as a mean and a range (the issues report of 11 October 2026, A.1). Counts only: safe over the
hidden set too.

    python -m bench.phase1.three runs <tag>          (reads runs/<p>-S-<tag>-1 .. -3)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _rows(base: Path, tag: str) -> dict[str, list[dict]]:
    by_case: dict[str, list[dict]] = {}
    for folder in sorted(base.glob(f"*-S-{tag}-[0-9]")):
        score = folder / "score.json"
        if not score.exists():
            continue
        try:
            row = json.loads(score.read_text(encoding="utf-8"))
        except ValueError:
            continue
        by_case.setdefault(folder.name.split("-")[0], []).append(row)
    return by_case


def main(root: str, tag: str) -> None:
    base = Path(__file__).parent / root
    by_case = _rows(base, tag)
    print(f"{'case':8} {'runs':>4} {'right':>5} {'built':>5} {'warned':>6} {'min (mean)':>10}")
    rights, builts, wrongs = [], [], []
    for case, rows in by_case.items():
        right = sum(1 for r in rows if r.get("right_goal") and not r.get("violations"))
        built = sum(1 for r in rows if r.get("built"))
        warned = sum(1 for r in rows if r.get("warned_on_card"))
        wrong = sum(1 for r in rows if r.get("built") and r.get("status") and not (r.get("right_goal") and not r.get("violations"))
                    and not r.get("warned_on_card"))
        minutes = sum(float(r.get("minutes") or 0) for r in rows) / max(len(rows), 1)
        rights.append(right); builts.append(built); wrongs.append(wrong)
        print(f"{case:8} {len(rows):>4} {right:>5} {built:>5} {warned:>6} {minutes:>10.1f}")
    runs = max((len(r) for r in by_case.values()), default=0)
    if runs:
        per_run = [sum(1 for rows in by_case.values() if len(rows) > i and rows[i].get("right_goal") and not rows[i].get("violations"))
                   for i in range(runs)]
        print(f"\nright per run: {per_run} -> mean {sum(per_run) / runs:.1f} of {len(by_case)}, "
              f"range {min(per_run)}-{max(per_run)}; wrong unwarned (case-runs): {sum(wrongs)} of {sum(len(r) for r in by_case.values())}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
