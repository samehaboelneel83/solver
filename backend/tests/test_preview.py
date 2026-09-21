"""live_data is the snapshot's JSON without the INSERT.

The editor compiles a draft against this. If it drifted from
`snapshot_dataset()`, a vacuous forall would be reported on a run and
missed on the editor, or the other way around.
"""

from __future__ import annotations

from sqlalchemy import text

from app.seed import seed_workforce_demo
from app.solve.preview import live_data
from tests.test_v1_problem_run import db  # noqa: F401


def test_live_data_matches_a_fresh_snapshot(db):
    created = seed_workforce_demo(db)
    db.commit()
    ir = db.execute(
        text("SELECT ir FROM model_version WHERE id = :v"),
        {"v": created["model_version_id"]},
    ).scalar_one()
    dataset_id = db.execute(
        text("SELECT snapshot_dataset(:v)"), {"v": created["model_version_id"]}
    ).scalar_one()
    frozen = db.execute(
        text("SELECT data FROM dataset WHERE id = :i"), {"i": dataset_id}
    ).scalar_one()

    preview = live_data(db, created["domain_id"], ir)

    assert preview["sets"] == frozen["sets"]
    assert preview["parameters"] == frozen["parameters"]
    assert preview["parameter_defaults"] == frozen["parameter_defaults"]
    assert preview["relationships"] == frozen["relationships"]
    assert preview["labels"] == frozen["labels"]
