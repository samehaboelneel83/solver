"""Setting `solve.gap_rel`: how close to proven best an answer must be.

A branch-and-bound solver can stop once its answer is proven within a
fraction of the best. HiGHS and the pywraplp wrapper did that silently at
their own default of 1e-4 and called the answer optimal. The fraction is now
a setting, at the three levels of migration 0014, and 0 by default: prove
the optimum. A run stopped at a wider gap is recorded as `feasible` with its
gap (0029), never as `optimal`.

`solve.workers` has existed since 0014; runs now use it rather than a
hardcoded 8. Nothing to migrate for that.
"""

import sqlalchemy as sa
from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "INSERT INTO setting_key (key, value_type, default_value, description)"
            " VALUES ('solve.gap_rel', 'number', CAST('0' AS jsonb),"
            "         'Stop once the answer is proven within this fraction of the best;"
            " 0 proves the optimum, and a run stopped short of it is not called optimal')"
        )
    )


def downgrade() -> None:
    op.execute("DELETE FROM setting_key WHERE key = 'solve.gap_rel'")
