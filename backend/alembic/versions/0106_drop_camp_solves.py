"""0106: camp layouts are gone from the platform: their solve queue goes with them.

The camp feature (the Camps tab of map data, its layout engine and worker jobs) was removed.
`camp_solve` held only its queued and finished layouts. A camp's own records -- the `camp`
kind of record, its doors and zones -- are ordinary domain data and are left as they are.

The downgrade makes the table again, empty, as 0096 made it.
"""
import importlib.util
from pathlib import Path

from alembic import op

revision = "0106"
down_revision = "0105"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS camp_solve")


def downgrade() -> None:
    spec = importlib.util.spec_from_file_location("camp_plans_0096", Path(__file__).with_name("0096_camp_plans.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.upgrade()
