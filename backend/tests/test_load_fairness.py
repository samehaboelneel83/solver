"""Fair claim under load (queue R33): 200 submits across 5 organizations."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.ops import load as load_ops
from tests.test_quadratic import empty_queue  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


def test_fair_claim_shares_within_ten_percent_and_starves_nobody(db, empty_queue):  # noqa: F811
    db.execute(text("DELETE FROM run"))
    db.commit()
    scenarios = load_ops._seed_scenarios(db, 5)
    result = load_ops.fairness_trial(db, scenarios, per_org=40)
    assert result["total"] == 200
    assert result["starved"] == []
    assert result["within_ten_percent"] is True
    for org, share in result["shares"].items():
        assert 0.18 <= share <= 0.22, (org, share, result)
