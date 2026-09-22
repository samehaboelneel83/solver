"""The nightly benchmark: run the large instances, store them, and say what got worse.

    python -m bench.nightly [--out-dir bench/nightly_results] [--sizes L] [--instances 3] [--seeds 2]

Runs `bench.run` with `--store` (so the history is in `bench_result`),
writes the night's rows to `<out-dir>/<date>.json` and a summary to
`<out-dir>/<date>.md`, and compares them with the most recent earlier night
in the same directory. Exit status 1 when anything below is found, so the
job that runs this (`scripts/nightly.sh`) reports a failed night.

What counts as worse -- each is a fact about the two nights' rows, not a
judgement:

* **wrong** -- a row `bench.run` marked wrong: it contradicts the proven
  answers of the other backends on its instance.
* **error** -- a backend raised instead of answering.
* **optimum moved** -- the generators are seeded, so an instance is the
  same model every night; its proven optimal value must not change. Last
  night's value and tonight's differing beyond 1e-6 relative means one of
  the two nights was wrong, even if every backend agreed tonight.
* **proof lost** -- a (instance, backend, seed) proven last night and not
  tonight.
* **2x slower** -- an (instance, backend) whose median solve time, shifted
  by one second so that noise on a 20 ms solve is not a regression, more
  than doubled.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

PROVEN = ("optimal", "infeasible", "unbounded")
TOLERANCE = 1e-6
SHIFT_S = 1.0
SLOWER = 2.0


def _optima(rows: list[dict[str, Any]]) -> dict[str, float]:
    """The proven optimal value of each instance, from rows not marked wrong."""
    found: dict[str, float] = {}
    for row in rows:
        if row["status"] == "optimal" and row.get("objective") is not None and not row.get("wrong"):
            found.setdefault(row["instance"], float(row["objective"]))
    return found


def _times(rows: list[dict[str, Any]]) -> dict[tuple[str, str], float]:
    grouped: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in rows:
        grouped[(row["instance"], row["backend"])].append(float(row["solve_s"]))
    return {key: statistics.median(values) for key, values in grouped.items()}


def compare(previous: list[dict[str, Any]] | None, rows: list[dict[str, Any]]) -> list[str]:
    """Everything tonight's rows show to be worse, one sentence each."""
    problems: list[str] = []
    for row in rows:
        where = f"{row['instance']} on {row['backend']} (seed {row['seed']})"
        if row.get("wrong"):
            problems.append(f"wrong: {where} answered {row['status']} {row.get('objective')}")
        if row["status"] == "error":
            problems.append(f"error: {where}")
    if previous is None:
        return problems

    before, now = _optima(previous), _optima(rows)
    for instance in sorted(before.keys() & now.keys()):
        a, b = before[instance], now[instance]
        if abs(a - b) > TOLERANCE * max(abs(a), abs(b), 1.0):
            problems.append(f"optimum moved: {instance} was {a}, now {b}")

    was_proven = {
        (r["instance"], r["backend"], r["seed"]) for r in previous if r["status"] in PROVEN
    }
    for row in rows:
        key = (row["instance"], row["backend"], row["seed"])
        if key in was_proven and row["status"] not in PROVEN:
            problems.append(
                f"proof lost: {row['instance']} on {row['backend']} (seed {row['seed']})"
                f" is {row['status']} tonight"
            )

    old, new = _times(previous), _times(rows)
    for key in sorted(old.keys() & new.keys()):
        ratio = (new[key] + SHIFT_S) / (old[key] + SHIFT_S)
        if ratio > SLOWER:
            problems.append(
                f"2x slower: {key[0]} on {key[1]}, {old[key]:.3f} s -> {new[key]:.3f} s"
            )
    return problems


def _previous(out_dir: Path, tonight: str) -> tuple[str, list[dict[str, Any]]] | None:
    earlier = sorted(p for p in out_dir.glob("*.json") if p.stem < tonight)
    if not earlier:
        return None
    return earlier[-1].stem, json.loads(earlier[-1].read_text())


def summary(night: str, rows: list[dict[str, Any]], against: str | None, problems: list[str]) -> str:
    proven = sum(1 for r in rows if r["status"] in PROVEN)
    lines = [
        f"# Nightly benchmark {night}",
        "",
        f"{len(rows)} runs, {proven} proven; compared with "
        + (f"{against}." if against else "nothing (first night)."),
        "",
        "## " + ("Worse than before" if problems else "Nothing got worse"),
        "",
    ]
    lines += [f"- {p}" for p in problems] or ["- none"]
    lines += ["", "| instance | backend | seed | status | objective | solve (s) |", "|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: (r["instance"], r["backend"], r["seed"])):
        lines.append(
            f"| {r['instance']} | {r['backend']} | {r['seed']} | {r['status']}"
            f" | {r.get('objective')} | {float(r['solve_s']):.3f} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bench.nightly")
    parser.add_argument("--out-dir", default=str(Path(__file__).parent / "nightly_results"))
    parser.add_argument("--sizes", default="L")
    parser.add_argument("--instances", type=int, default=3)
    parser.add_argument("--seeds", type=int, default=2)
    parser.add_argument("--time-limit", type=float, default=30.0)
    parser.add_argument("--no-store", action="store_true", help="do not write bench_result")
    parser.add_argument("--night", default=date.today().isoformat(), help="names the files")
    args = parser.parse_args(argv)

    from bench import run

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows_path = out_dir / f"{args.night}.json"
    run_args = [
        "--sizes", args.sizes,
        "--instances", str(args.instances),
        "--seeds", str(args.seeds),
        "--time-limit", str(args.time_limit),
        "--out", str(rows_path),
    ]
    if not args.no_store:
        run_args.append("--store")
    status = run.main(run_args)
    if status:
        print(f"bench.run exited {status}", file=sys.stderr)
        return status

    rows = json.loads(rows_path.read_text())
    found = _previous(out_dir, args.night)
    against, previous = found if found else (None, None)
    problems = compare(previous, rows)
    (out_dir / f"{args.night}.md").write_text(summary(args.night, rows, against, problems))
    for problem in problems:
        print(problem)
    print(f"{len(rows)} runs, {len(problems)} problems; summary in {out_dir / (args.night + '.md')}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
