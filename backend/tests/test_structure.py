"""Near-separable detection (app.solve.blocks.structure, queue R4): the few rules that tie blocks together."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app.solve import compile_model
from app.solve.blocks import said, structure
from bench.families import generate
from tests.test_api_runs import auth_headers, ensure_admin_seeded, seeded  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


def _structure(family: str, size: str = "M"):
    case = generate(family, size, 0)
    return structure(compile_model(case.ir, case.data))


@pytest.mark.parametrize(
    "family, blocks, by, linking",
    [
        # One site's shipments per site, tied only by each customer's demand.
        ("facility", 15, "site", ["c_served"]),
        # One person's rota per person, tied only by each shift's cover.
        ("rota", 30, "person", ["c_cover"]),
        # One zone's cells per zone, tied only by each cell going to one zone.
        ("districting", 4, "zone", ["c_one_zone"]),
    ],
)
def test_a_near_separable_model_names_its_blocks_and_the_rules_that_tie_them(family, blocks, by, linking):
    found = _structure(family, "S" if family == "districting" else "M")
    assert (found["blocks"], found["by"], found["linking"]) == (blocks, by, linking)
    assert 0 < found["linking_rules"] and found["largest_share"] <= 0.8


def test_a_separable_model_has_no_linking_rules():
    found = _structure("knapsack_depots")
    assert (found["blocks"], found["linking_rules"], found["by"]) == (4, 0, None)
    assert said(found) == "it falls into 4 independent parts, solved separately when that is on"


def test_a_model_that_does_not_split_is_one_block_and_says_nothing():
    found = _structure("feed_blend", "L")
    assert found == {"blocks": 1, "linking_rules": 0, "linking": [], "by": None, "largest_share": 1.0}
    assert said(found) is None


def test_the_planner_sentence_names_the_parts_and_the_linking_rule():
    assert said(_structure("rota")) == "it is 30 parts, one per person, tied together only by 21 instances of c_cover"


def test_classify_reports_the_structure_with_live_data(seeded, auth_headers, db):  # noqa: F811
    ir = db.execute(text("SELECT ir FROM model_version WHERE id = :v"), {"v": seeded["model_version_id"]}).scalar_one()
    body = TestClient(app).post("/api/v1/classify", json={"ir": ir, "problem_id": seeded["problem_id"]},
                                headers=auth_headers).json()
    found = body["structure"]
    assert set(found) == {"blocks", "linking_rules", "linking", "by", "largest_share"}
    if found["blocks"] > 1:
        assert said(found) in body["planner"]
    # Without the domain there is nothing compiled to split.
    assert TestClient(app).post("/api/v1/classify", json={"ir": ir}, headers=auth_headers).json()["structure"] is None
