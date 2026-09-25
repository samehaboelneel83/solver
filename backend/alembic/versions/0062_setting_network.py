"""Setting `solve.network`: a model that is a network, solved as one (queue R15a).

On (the default): a model whose every rule is flow in less flow out -- a
transportation, assignment, shortest path or maximum flow, however it is
written -- with decisions in whole numbers is solved by min-cost flow
(`app.solve.network`): proven optimal (or proven infeasible), a 400 x 400
assignment in 1 s where CP-SAT ran out of memory and HiGHS took 12 s. A
continuous network stays with the LP solvers, which also give shadow prices
(bench/results/2026-09-25-network.md). Anything else goes to the solvers as
before.
"""

import sqlalchemy as sa
from alembic import op

revision = "0062"
down_revision = "0061"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "INSERT INTO setting_key (key, value_type, default_value, description)"
            " VALUES ('solve.network', 'boolean', CAST('true' AS jsonb),"
            "         'Solve a model that is a network (transport, assignment, paths, flows) by min-cost flow')"
        )
    )


def downgrade() -> None:
    op.execute("DELETE FROM setting WHERE key = 'solve.network'")
    op.execute("DELETE FROM setting_key WHERE key = 'solve.network'")
