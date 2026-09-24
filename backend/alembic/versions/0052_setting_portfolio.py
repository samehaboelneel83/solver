"""Setting `solve.portfolio`: race every admissible solver on an integer model for the whole time (queue R2).

When on, no solver is named and memory has no evidence, an IP or MILP with
two or more admissible solvers is solved by all of them at once, the threads
shared out; the first proof ends the race, else the best answer at the
deadline is the run's (`app.solve.race.run_portfolio`). It takes the probe
race's place when both are on. The default is the bench's call
(bench/results/2026-09-24-portfolio.md).
"""

import sqlalchemy as sa
from alembic import op

revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "INSERT INTO setting_key (key, value_type, default_value, description)"
            " VALUES ('solve.portfolio', 'boolean', CAST('false' AS jsonb),"
            "         'Race every solver that fits an integer model at once; the first proof wins')"
        )
    )


def downgrade() -> None:
    op.execute("DELETE FROM setting WHERE key = 'solve.portfolio'")
    op.execute("DELETE FROM setting_key WHERE key = 'solve.portfolio'")
