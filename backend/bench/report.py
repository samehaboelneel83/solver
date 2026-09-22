"""Turn benchmark rows into the report a default is decided on.

    python -m bench.report results.json --label gap_rel [--out bench/results]

For each family, size and backend, and each technique value against the
first (the baseline):

- **SGM time**: the shifted geometric mean of solve time, shift 10 s. A
  plain mean lets one slow instance decide; a plain geometric mean lets
  near-zero times decide. The shift is the usual compromise.
- **wins / losses / ties**: per (instance, seed), which value was more than
  10% faster, or reached a smaller final gap.
- **regressions**: every instance more than 2x slower than the baseline.
- **wrong**: rows whose answer contradicts the proven ones (`bench.run`).

The enable-by-default rule is printed with a verdict: at least 10% better
SGM time (or final gap) on at least two families, nothing more than 2x
slower, and zero wrong answers.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
from collections import defaultdict
from typing import Any

SHIFT = 10.0


def sgm(times: list[float], shift: float = SHIFT) -> float:
    if not times:
        return math.nan
    return math.exp(sum(math.log(t + shift) for t in times) / len(times)) - shift


def _time(row: dict[str, Any]) -> float:
    """Time to the answer; a run that did not prove its answer is charged the
    full time limit, as the roadmap's rule counts time-to-optimal."""
    if row["status"] in ("optimal", "infeasible", "unbounded"):
        return row["solve_s"]
    return max(row["solve_s"], row.get("time_limit") or row["solve_s"])


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = []
    for row in rows:
        if row["value"] not in values:
            values.append(row["value"])
    baseline = values[0] if values else None

    table: list[dict[str, Any]] = []
    groups: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(row["family"], row["size"], row["backend"], row["value"])].append(row)
    for (family, size, backend, value), group in sorted(groups.items(), key=lambda kv: tuple(map(str, kv[0]))):
        gaps = [row["gap"] for row in group if row["gap"] is not None]
        table.append(
            {
                "family": family,
                "size": size,
                "backend": backend,
                "value": value,
                "runs": len(group),
                "proven": sum(row["status"] in ("optimal", "infeasible", "unbounded") for row in group),
                "sgm_s": sgm([_time(row) for row in group]),
                "mean_gap": sum(gaps) / len(gaps) if gaps else None,
                "wrong": sum(bool(row.get("wrong")) for row in group),
            }
        )

    comparisons = []
    keyed = {(row["instance"], row["backend"], row["seed"], row["value"]): row for row in rows}
    for value in values[1:]:
        wins = losses = ties = 0
        regressions: list[str] = []
        improved_families = set()
        family_times: dict[str, tuple[list[float], list[float]]] = defaultdict(lambda: ([], []))
        for (instance, backend, seed, v), row in keyed.items():
            if v != value:
                continue
            base = keyed.get((instance, backend, seed, baseline))
            if base is None:
                continue
            t_new, t_base = _time(row), _time(base)
            family_times[row["family"]][0].append(t_base)
            family_times[row["family"]][1].append(t_new)
            if t_new < t_base * 0.9 or _better_gap(row, base):
                wins += 1
            elif t_new > t_base * 1.1 or _better_gap(base, row):
                losses += 1
            else:
                ties += 1
            if t_new > 2 * t_base and t_new - t_base > 0.05:
                regressions.append(f"{instance} on {backend}, seed {seed}: {t_base:.3f}s -> {t_new:.3f}s")
        for family, (base_times, new_times) in family_times.items():
            if sgm(new_times) <= 0.9 * sgm(base_times):
                improved_families.add(family)
        wrong = sum(bool(row.get("wrong")) for row in rows if row["value"] == value)
        comparisons.append(
            {
                "value": value,
                "wins": wins,
                "losses": losses,
                "ties": ties,
                "regressions": regressions,
                "improved_families": sorted(improved_families),
                "wrong": wrong,
                "enable": len(improved_families) >= 2 and not regressions and wrong == 0,
            }
        )
    return {"baseline": baseline, "table": table, "comparisons": comparisons}


def _better_gap(row: dict[str, Any], other: dict[str, Any]) -> bool:
    if row["gap"] is None or other["gap"] is None:
        return False
    return row["gap"] < other["gap"] * 0.9 - 1e-12


def markdown(rows: list[dict[str, Any]], label: str) -> str:
    summary = summarise(rows)
    technique = next((row["technique"] for row in rows if row["technique"]), None)
    lines = [
        f"# Benchmark: {label}",
        "",
        f"{len(rows)} runs; technique `{technique or 'none'}`, baseline `{summary['baseline']}`. "
        f"Time is the shifted geometric mean (shift {SHIFT:g} s), charging an unproven answer the full time limit.",
        "",
        "| family | size | backend | value | runs | proven | SGM time (s) | mean gap | wrong |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for row in summary["table"]:
        gap = "—" if row["mean_gap"] is None else f"{row['mean_gap']:.2%}"
        lines.append(
            f"| {row['family']} | {row['size']} | {row['backend']} | {row['value']} | {row['runs']} "
            f"| {row['proven']} | {row['sgm_s']:.3f} | {gap} | {row['wrong']} |"
        )
    for comparison in summary["comparisons"]:
        lines += [
            "",
            f"## `{technique}={comparison['value']}` against `{summary['baseline']}`",
            "",
            f"- wins / losses / ties: {comparison['wins']} / {comparison['losses']} / {comparison['ties']}",
            f"- families at least 10% faster: {', '.join(comparison['improved_families']) or 'none'}",
            f"- wrong answers: {comparison['wrong']}",
            f"- more than 2x slower: {len(comparison['regressions'])}",
        ]
        lines += [f"  - {item}" for item in comparison["regressions"]]
        lines.append(
            "- **enable by default: "
            + ("yes" if comparison["enable"] else "no")
            + "** (needs >= 2 families 10% better, nothing 2x slower, zero wrong)"
        )
    wrong_total = sum(bool(row.get("wrong")) for row in rows)
    if wrong_total:
        lines += ["", f"**{wrong_total} wrong answers** -- see the rows with `wrong: true`."]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bench.report")
    parser.add_argument("rows", help="JSON written by bench.run --out")
    parser.add_argument("--label", required=True, help="what was compared; names the file")
    parser.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "results"))
    args = parser.parse_args(argv)
    with open(args.rows, encoding="utf-8") as handle:
        rows = json.load(handle)
    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, f"{dt.date.today().isoformat()}-{args.label}.md")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(markdown(rows, args.label))
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
