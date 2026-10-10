"""Score one phase 1 case from what drive_case.mjs saved (docs/plans/2026-10-10-phase1-evaluation.md).

    python -m bench.phase1.score <problem module> <case dir> <out dir>

Prints one JSON row: built, first time, the goal against the reference, the independent checker's violations,
the run's status and gap, the platform's own verification, alternative plans, sensitivity, timings, and how many
of the problem's expected-output bullets the Assistant's final answer contains.
"""

from __future__ import annotations

import importlib
import json
import re
import sys
from pathlib import Path


def main(module: str, case: Path, out: Path) -> dict:
    expected = json.loads((case / "expected.json").read_text(encoding="utf-8"))
    result = json.loads((out / "result.json").read_text(encoding="utf-8")) if (out / "result.json").exists() else {}
    panel = (out / "panel.txt").read_text(encoding="utf-8") if (out / "panel.txt").exists() else ""
    page = (out / "run-page.txt").read_text(encoding="utf-8") if (out / "run-page.txt").exists() else ""
    row: dict = {"case": f"{expected['problem']}/{expected['size']}", "built": bool(result.get("built")),
                 "continues": result.get("continues"), "minutes": result.get("minutes"),
                 "corrected": len(re.findall(r"corrected automatically", panel)) and int(
                     sum(int(n) for n in re.findall(r"(\d+) corrected automatically", panel)))}
    row["first_time"] = row["built"] and not result.get("continues")
    run = json.loads((out / "run.json").read_text(encoding="utf-8")) if (out / "run.json").exists() else None
    if run:
        params = run.get("params") or {}
        row.update(status=run.get("status"), optimality=run.get("optimality"), goal=run.get("objective"),
                   bound=run.get("best_bound"), gap=run.get("gap"), solver=run.get("solver"),
                   verified=(params.get("verification") or {}).get("ok", params.get("verification")),
                   phases=params.get("phases"), size=(params.get("fingerprint") or {}).get("variables"),
                   rows=(params.get("fingerprint") or {}).get("rows"))
        want = expected.get("goal")
        if want is not None and row["goal"] is not None:
            row["right_goal"] = abs(float(row["goal"]) - float(want)) <= 1e-6 * max(1.0, abs(float(want)))
        problem = importlib.import_module(f"bench.phase1.{module}")
        found = problem.check(case, (out / "export.csv").read_text(encoding="utf-8")) if (out / "export.csv").exists() else ["no export"]
        row["violations"] = [v for v in found if not v.startswith("COST")]
        row["checker_goal"] = next((float(v.split()[1]) for v in found if v.startswith("COST")), None)
    alts = result.get("alternative_runs") or []
    row["alternatives"] = [a.get("objective") for a in alts]
    alt_text = (out / "alternatives.txt").read_text(encoding="utf-8") if (out / "alternatives.txt").exists() else ""
    row["alternatives_shown"] = len(re.findall(r"(?im)^\s*(?:plan|alternative)\s*\d", alt_text)) or (alt_text[:160] if alt_text else "")
    row["sensitivity_on_page"] = bool(re.search(r"may move|between .* and|ranges?\b|what-if|What if", page))
    row["binding_on_page"] = bool(re.search(r"\btight\b|binding|holds with no room|no room", page + panel))
    bullets = expected.get("report", [])
    answer = panel.split("Approved")[-1]
    row["report"] = {b: bool(re.search(p, answer, re.I)) for b, p in bullets}
    row["report_coverage"] = f"{sum(row['report'].values())}/{len(bullets)}" if bullets else None
    row["browser_problems"] = result.get("browser_problems")
    row["error"] = result.get("error") or result.get("alternatives_error")
    return row


if __name__ == "__main__":
    print(json.dumps(main(sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])), indent=1, default=str))
