"""Equal-budget technique comparison (OAAS Phase 4 / Q04).

Wraps `bench.run` so a challenger is only compared to a baseline when both
use the same wall-time limit and worker count. Prints wins, losses, and
wrong answers; exit 1 if any wrong or if the challenger is never faster.

    python -m bench.equal_budget --family rota --sizes S --seeds 1 \\
        --baseline workers=8 --challenger workers=4 --time-limit 10

The first `--technique` value in ordinary `bench.run` is already the
baseline; this module exists to make the equal-budget gate explicit and to
refuse accidental unfair budgets (e.g. eight solvers × eight threads vs one).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


def compare(rows: list[dict[str, Any]], *, baseline_label: str, challenger_label: str) -> dict[str, Any]:
    """Pair rows that share (family, size, instance, seed) across two technique values."""
    by_key: dict[tuple, dict[str, dict]] = defaultdict(dict)
    for row in rows:
        key = (row["family"], row["size"], row["instance"], row.get("seed"))
        label = str(row.get("value") if row.get("technique") else row.get("backend"))
        by_key[key][label] = row

    wins = losses = ties = missing = 0
    wrong = 0
    pairs: list[dict[str, Any]] = []
    for key, sides in sorted(by_key.items()):
        left = sides.get(baseline_label)
        right = sides.get(challenger_label)
        if left is None or right is None:
            missing += 1
            continue
        if left.get("wrong") or right.get("wrong"):
            wrong += 1
        lt = left.get("solve_s")
        rt = right.get("solve_s")
        if lt is None or rt is None:
            missing += 1
            continue
        if rt < lt * 0.9:
            wins += 1
            verdict = "win"
        elif lt < rt * 0.9:
            losses += 1
            verdict = "loss"
        else:
            ties += 1
            verdict = "tie"
        pairs.append(
            {
                "instance": f"{key[0]}-{key[1]}-{key[2]}",
                "seed": key[3],
                "baseline_s": lt,
                "challenger_s": rt,
                "verdict": verdict,
                "wrong": bool(left.get("wrong") or right.get("wrong")),
            }
        )
    return {
        "baseline": baseline_label,
        "challenger": challenger_label,
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "missing": missing,
        "wrong": wrong,
        "pairs": pairs,
    }


def report_md(summary: dict[str, Any]) -> str:
    lines = [
        f"# Equal-budget comparison: {summary['challenger']} vs {summary['baseline']}",
        "",
        f"- wins (≥10% faster): **{summary['wins']}**",
        f"- losses (≥10% slower): **{summary['losses']}**",
        f"- ties: {summary['ties']}",
        f"- wrong answers: **{summary['wrong']}**",
        f"- unpaired rows: {summary['missing']}",
        "",
        "| instance | seed | baseline_s | challenger_s | verdict |",
        "|---|---|---|---|---|",
    ]
    for p in summary["pairs"]:
        lines.append(
            f"| {p['instance']} | {p['seed']} | {p['baseline_s']} | {p['challenger_s']} | {p['verdict']} |"
        )
    lines += [
        "",
        "Promotion requires zero wrong answers and wins > losses on the held family",
        "(see `docs/contracts/family-policies.md`).",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    from bench.run import parse_technique, run as run_bench

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", required=True)
    parser.add_argument("--sizes", default="S")
    parser.add_argument("--seeds", type=int, default=1)
    parser.add_argument("--time-limit", type=float, default=30.0)
    parser.add_argument("--workers", type=int, default=8, help="Shared worker budget for both sides")
    parser.add_argument(
        "--technique",
        required=True,
        help="gap_rel / workers / backend.option with baseline,challenger values (first = baseline)",
    )
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    technique = parse_technique(args.technique)
    if len(technique.values) < 2:
        print("--technique needs at least two values (baseline,challenger)", file=sys.stderr)
        return 2

    rows = run_bench(
        families=args.family.split(","),
        sizes=args.sizes.split(","),
        count=1,
        seeds=args.seeds,
        time_limit=args.time_limit,
        workers=args.workers,
        technique=technique,
    )
    baseline = str(technique.values[0])
    challenger = str(technique.values[1])
    summary = compare(rows, baseline_label=baseline, challenger_label=challenger)
    text = report_md(summary)
    print(text)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text)
        args.out.with_suffix(".json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=2))
    if summary["wrong"]:
        return 1
    if summary["wins"] == 0 and summary["losses"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
