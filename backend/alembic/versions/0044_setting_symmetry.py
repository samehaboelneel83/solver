"""Setting `solve.symmetry`: order interchangeable entities for HiGHS and the MILP wrapper.

When on, a model solved by HiGHS or the MILP wrapper gets, for each class of
interchangeable entities (`app.solve.symmetry`), rows ordering their totals
on one variable -- cutting the mirror images of each answer, never the
optimum. CP-SAT and SCIP detect symmetry themselves and are left alone.
The default is the bench's (bench/results/2026-09-23-symmetry.md).
"""

import sqlalchemy as sa
from alembic import op

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "INSERT INTO setting_key (key, value_type, default_value, description)"
            " VALUES ('solve.symmetry', 'boolean', CAST('false' AS jsonb),"
            "         'For HiGHS and the MILP wrapper, order interchangeable entities"
            " (same attributes, data and links) so each answer is searched once, not once per ordering')"
        )
    )


def downgrade() -> None:
    op.execute("DELETE FROM setting WHERE key = 'solve.symmetry'")
    op.execute("DELETE FROM setting_key WHERE key = 'solve.symmetry'")
