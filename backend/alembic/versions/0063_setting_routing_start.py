"""Setting `solve.routing_start`: routes from OR-Tools' routing search to start from (queue R15b).

On: a model with one `route` rule (vehicle routing, IR version 2) is handed
routes found by OR-Tools' routing library -- cheapest arc, then guided
local search, for a fifth of the time (at most 30 s) -- with the load each
vehicle carries on each arc, so every row holds (`app.solve.routing`).
CP-SAT, HiGHS and SCIP take it as a start; if the solver ends with nothing,
the routes are the run's answer, feasible and claiming nothing
(bench/results/2026-09-25-routing.md).
"""

import sqlalchemy as sa
from alembic import op

revision = "0063"
down_revision = "0062"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "INSERT INTO setting_key (key, value_type, default_value, description)"
            " VALUES ('solve.routing_start', 'boolean', CAST('true' AS jsonb),"
            "         'Start vehicle routing from routes found by a routing search')"
        )
    )


def downgrade() -> None:
    op.execute("DELETE FROM setting WHERE key = 'solve.routing_start'")
    op.execute("DELETE FROM setting_key WHERE key = 'solve.routing_start'")
