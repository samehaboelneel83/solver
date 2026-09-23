"""Setting `solve.warm_start`: start from the nearest earlier answer.

When on, a run of a problem that has an earlier answer offers it to the
backend as a hint -- CP-SAT `AddHint`, HiGHS `setSolution`, SCIP a partial
solution (`app.solve.warm`) -- and records `warm_start_from`. It changes how
fast an answer is found, never which answer is proven. Off by default: the
bench decides (bench/results/2026-09-23-warm-start.md).
"""

import sqlalchemy as sa
from alembic import op

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "INSERT INTO setting_key (key, value_type, default_value, description)"
            " VALUES ('solve.warm_start', 'boolean', CAST('false' AS jsonb),"
            "         'Start each solve from the nearest earlier answer of the same problem,"
            " as a hint the solver may use or drop')"
        )
    )


def downgrade() -> None:
    op.execute("DELETE FROM setting WHERE key = 'solve.warm_start'")
    op.execute("DELETE FROM setting_key WHERE key = 'solve.warm_start'")
