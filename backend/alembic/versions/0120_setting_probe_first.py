"""Setting `solve.probe_first`: the solver alone first, the steps before a solve only when it settles nothing.

On (the default): before a run builds a start or adds rows (the join rule's start and cuts, the fixed-charge
start, the implied rows), the chosen solver tries the model as it is for a fifth of the time allowed (2 to 30
seconds). A proof there is the run's answer; otherwise the steps run with what it found as their start
(`app.solve.service`, bench/results/2026-10-09-pipeline.md). Off: the steps always run first.
"""

import sqlalchemy as sa
from alembic import op

revision = "0120"
down_revision = "0119"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "INSERT INTO setting_key (key, value_type, default_value, description)"
            " VALUES ('solve.probe_first', 'boolean', CAST('true' AS jsonb),"
            "         'Try the solver alone briefly before building starts or adding rows')"
        )
    )


def downgrade() -> None:
    op.execute("DELETE FROM setting WHERE key = 'solve.probe_first'")
    op.execute("DELETE FROM setting_key WHERE key = 'solve.probe_first'")
