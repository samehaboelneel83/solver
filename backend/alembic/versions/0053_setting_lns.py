"""Setting `solve.lns`: improve a stalled answer by large-neighbourhood search (queue R3).

When on, an integer model solved by HiGHS or the MILP wrapper that is not
proved within the first 30% of its time gets the rest improved by
fix-and-optimize (`app.solve.lns`): most decisions held, the rest solved
again from the answer. Its answer is `feasible` unless it meets the first
solve's proven bound. The default is the bench's call
(bench/results/2026-09-24-lns.md).
"""

import sqlalchemy as sa
from alembic import op

revision = "0053"
down_revision = "0052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "INSERT INTO setting_key (key, value_type, default_value, description)"
            " VALUES ('solve.lns', 'boolean', CAST('false' AS jsonb),"
            "         'Improve a stalled answer by fixing most of it and solving the rest again')"
        )
    )


def downgrade() -> None:
    op.execute("DELETE FROM setting WHERE key = 'solve.lns'")
    op.execute("DELETE FROM setting_key WHERE key = 'solve.lns'")
