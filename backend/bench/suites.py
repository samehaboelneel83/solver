"""Re-ask every problem's acceptance cases (queue R32).

    python -m bench.suites [--night YYYY-MM-DD] [--max-seconds N] [--out PATH]
    python -m bench.suites --check   # fast self-check for scripts/check.sh (≤5 s cases)

Writes `suite_nightly` and a markdown report. Exit 1 when any case fails.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session


def report_md(night: str, rows: list[dict[str, Any]]) -> str:
    failed = [r for r in rows if not r["passed"]]
    lines = [
        f"# Nightly acceptance suites {night}",
        "",
        f"{len(rows)} cases, {len(failed)} failed.",
        "",
        "## " + ("Failures" if failed else "All passed"),
        "",
    ]
    lines += [f"- case {r['case_id']} on version {r['model_version_id']}: {'; '.join(r['reasons']) or r['status']}"
              for r in failed] or ["- none"]
    lines += [
        "",
        "| problem | version | case | status | objective | seconds | passed |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['problem_id']} | {r['model_version_id']} | {r['case_id']} | {r['status']}"
            f" | {r.get('objective')} | {r.get('seconds')} | {r['passed']} |"
        )
    return "\n".join(lines) + "\n"


def run_night(
    db: Session,
    *,
    night: date,
    max_seconds: float | None = None,
    out: Path | None = None,
) -> tuple[list[dict[str, Any]], int]:
    from app.solve import suite

    rows = suite.nightly(db, night=night, max_seconds=max_seconds)
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report_md(night.isoformat(), rows))
    failed = sum(1 for r in rows if not r["passed"])
    return rows, (1 if failed else 0)


def self_check() -> int:
    """Build one seeded rota case in the current DB and re-ask it with a 5 s cap."""
    from datetime import date as date_cls

    from sqlalchemy import text

    from app.core.db import SessionLocal
    from app.solve import suite
    from app.solve.service import claim_next, enqueue_run, execute_run
    from tests.test_diagnose import _scenario_for
    from tests.test_solve import _feasible

    db = SessionLocal()
    try:
        db.execute(text("DELETE FROM run"))
        db.commit()
        version, _ = _feasible(db)
        run = enqueue_run(db, _scenario_for(db, version), time_limit=10.0, reuse=False)
        assert claim_next(db) == run
        execute_run(db, run)
        problem = db.execute(
            text("SELECT problem_id FROM model_version WHERE id = :v"), {"v": version}
        ).scalar_one()
        suite.from_run(db, run, "check.sh seed", "check")
        db.commit()
        rows, status = run_night(db, night=date_cls.today(), max_seconds=5.0)
        print(f"suite self-check: {len(rows)} cases, exit {status}")
        for row in rows:
            print(f"  case {row['case_id']}: {'pass' if row['passed'] else 'FAIL'} {row['reasons']}")
        return status
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bench.suites")
    parser.add_argument("--night", default=date.today().isoformat())
    parser.add_argument("--max-seconds", type=float, default=None)
    parser.add_argument(
        "--out",
        default=None,
        help="markdown report path (default: bench/results/<night>-suites.md)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="fast self-check for scripts/check.sh (one seeded case, ≤5 s)",
    )
    args = parser.parse_args(argv)
    if args.check:
        return self_check()

    from app.core.db import SessionLocal

    night = date.fromisoformat(args.night)
    out = Path(args.out) if args.out else Path(__file__).parent / "results" / f"{args.night}-suites.md"
    db = SessionLocal()
    try:
        rows, status = run_night(db, night=night, max_seconds=args.max_seconds, out=out)
    finally:
        db.close()
    print(f"{len(rows)} cases, {sum(1 for r in rows if not r['passed'])} failed; report in {out}")
    return status


if __name__ == "__main__":
    sys.exit(main())
