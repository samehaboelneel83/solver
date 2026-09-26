"""Fair claim under load (queue R33).

    python -m bench.load [--orgs 5] [--per-org 40] [--check]

Enqueues the same number of tiny plans per organization, claims them one by
one (finishing each immediately so concurrency does not hide unfairness),
and checks that each organization's share of claims is within ±10% of an
equal share and that nobody is starved. Postgres stays the queue; no Redis.
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


def fairness_trial(
    db: Session,
    scenarios: list[int],
    *,
    per_org: int = 40,
) -> dict[str, Any]:
    """Enqueue ``per_org`` runs per scenario and claim until the queue is empty.

    Each claim is finished at once (``status='optimal'``) so the fair claim's
    "fewest running" rule sees a level field and the shares reflect submit
    fairness, not concurrency caps.
    """
    from app.solve.service import claim_next, enqueue_run

    org_of: dict[int, object] = {}
    for scenario in scenarios:
        org = db.execute(
            text("SELECT organization_id FROM scenario WHERE id = :s"), {"s": scenario}
        ).scalar_one()
        org_of[scenario] = org
        for _ in range(per_org):
            enqueue_run(db, scenario, time_limit=5.0, reuse=False)

    claimed: dict[object, int] = {org: 0 for org in org_of.values()}
    total = 0
    while (run_id := claim_next(db)) is not None:
        org = db.execute(
            text("SELECT organization_id FROM run WHERE id = :r"), {"r": run_id}
        ).scalar_one()
        claimed[org] = claimed.get(org, 0) + 1
        total += 1
        db.execute(
            text(
                "UPDATE run SET status = 'optimal', finished_at = now(),"
                " started_at = coalesce(started_at, now()), heartbeat_at = now()"
                " WHERE id = :r"
            ),
            {"r": run_id},
        )
        db.commit()

    expected = 1.0 / max(len(claimed), 1)
    shares = {str(org): (n / total if total else 0.0) for org, n in claimed.items()}
    starved = [org for org, n in claimed.items() if n == 0]
    within = all(abs(share - expected) <= 0.10 * expected + 1e-12 for share in shares.values()) if total else False
    # ±10% of equal share: for 5 orgs, equal=0.20, band is 0.18–0.22.
    return {
        "total": total,
        "per_org": dict((str(o), n) for o, n in claimed.items()),
        "shares": shares,
        "expected_share": expected,
        "starved": [str(o) for o in starved],
        "within_ten_percent": within and not starved,
    }


def _seed_scenarios(db: Session, n_orgs: int) -> list[int]:
    """Tiny one-variable models, one scenario per fresh organization."""
    ir = (
        '{"version":1,"sets":[],"parameters":{},'
        '"variables":{"x":{"index":[],"domain":"binary"}},'
        '"constraints":[],'
        '"objective":{"sense":"maximize","terms":[{"id":"o","weight":1,'
        '"expression":{"var":"x","index":[]}}]}}'
    )
    scenarios: list[int] = []
    suffix = uuid.uuid4().hex[:8]
    for i in range(n_orgs):
        org = db.execute(
            text(
                "INSERT INTO iam.organization (id, code, name)"
                " VALUES (gen_random_uuid(), :c, :n) RETURNING id"
            ),
            {"c": f"load-{suffix}-{i}", "n": f"Load {i}"},
        ).scalar_one()
        db.execute(
            text(
                "INSERT INTO iam.quota (organization_id, max_concurrent_runs)"
                " VALUES (:o, 100)"
                " ON CONFLICT (organization_id) DO UPDATE SET max_concurrent_runs = 100"
            ),
            {"o": org},
        )
        domain = db.execute(
            text(
                "INSERT INTO domain (name, organization_id) VALUES (:n, :o) RETURNING id"
            ),
            {"n": f"load-domain-{suffix}-{i}", "o": org},
        ).scalar_one()
        problem = db.execute(
            text(
                "INSERT INTO problem (domain_id, name, organization_id)"
                " VALUES (:d, :n, :o) RETURNING id"
            ),
            {"d": domain, "n": f"load-problem-{i}", "o": org},
        ).scalar_one()
        version = db.execute(
            text(
                "INSERT INTO model_version (problem_id, ir, organization_id)"
                " VALUES (:p, CAST(:ir AS jsonb), :o) RETURNING id"
            ),
            {"p": problem, "ir": ir, "o": org},
        ).scalar_one()
        scenario = db.execute(
            text(
                "INSERT INTO scenario (problem_id, model_version_id, name, organization_id)"
                " VALUES (:p, :v, 'load', :o) RETURNING id"
            ),
            {"p": problem, "v": version, "o": org},
        ).scalar_one()
        scenarios.append(int(scenario))
    db.commit()
    return scenarios


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bench.load")
    parser.add_argument("--orgs", type=int, default=5)
    parser.add_argument("--per-org", type=int, default=40)
    parser.add_argument(
        "--check",
        action="store_true",
        help="seed orgs in the current DB, run the trial, exit 1 on unfair shares",
    )
    args = parser.parse_args(argv)

    # Prefer an explicit test URL (same convention as conftest / check.sh).
    # Must run before importing app.core.db so the engine binds to the test DB.
    if os.environ.get("TEST_DATABASE_URL"):
        os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

    from app.core.config import get_settings

    get_settings.cache_clear()
    url = get_settings().database_url
    # Same guard as check.sh / conftest: never empty the live `solver` database.
    db_name = url.rsplit("/", 1)[-1].split("?", 1)[0]
    if not db_name.endswith("_test"):
        print(
            f"refusing: DATABASE_URL database is {db_name!r}; "
            "bench.load only runs against a name ending in _test",
            file=sys.stderr,
        )
        return 2

    from app.core.db import SessionLocal

    db = SessionLocal()
    try:
        db.execute(text("DELETE FROM run"))
        db.commit()
        scenarios = _seed_scenarios(db, args.orgs)
        result = fairness_trial(db, scenarios, per_org=args.per_org)
        print(
            f"load: {result['total']} claims across {args.orgs} orgs; "
            f"shares={[round(s, 3) for s in result['shares'].values()]}; "
            f"within_10%={result['within_ten_percent']}; starved={result['starved']}"
        )
        return 0 if result["within_ten_percent"] else 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
