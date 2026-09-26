"""The conformance kit from a shell (queue R43, app.solve.conformance).

    python -m bench.conformance <solver> [--store]

Prints each check and whether the solver passed; `--store` keeps the report, so a passing added
solver may then be chosen unasked. An added solver that needs a licence is run without one here:
set it through the API and run the kit from the Solvers page instead.
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("solver")
    parser.add_argument("--store", action="store_true", help="keep the report")
    args = parser.parse_args(argv)

    from app.solve import conformance
    from app.solve.backends import by_name

    backend = by_name(args.solver)
    if backend is None:
        print(f"no solver called {args.solver!r}", file=sys.stderr)
        return 2
    report = conformance.run(backend)
    for check in report.checks:
        print(f"{check['result']:>5}  {check['check']:<22} {check['detail']}")
    print(f"{args.solver} {report.version}: {'passed' if report.passed else 'FAILED'}")
    if args.store:
        from app.core.db import SessionLocal

        with SessionLocal() as db:
            conformance.store(db, report, "bench.conformance")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
