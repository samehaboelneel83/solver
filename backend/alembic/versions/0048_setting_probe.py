"""Setting `solve.probe`: race the admissible solvers briefly when there is nothing to remember.

When on, no solver is named and memory has no evidence, each admissible
solver runs a short probe at once and the best continues (`app.solve.race`);
a small model is left to the rules. Off by default, on the bench's evidence
(bench/results/2026-09-24-probe.md): 2x faster on one family, but twice as slow where no probe proves the model and the winner starts again.
"""

import sqlalchemy as sa
from alembic import op

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "INSERT INTO setting_key (key, value_type, default_value, description)"
            " VALUES ('solve.probe', 'boolean', CAST('false' AS jsonb),"
            "         'With nothing to remember, give each solver a short probe and let the best continue')"
        )
    )


def downgrade() -> None:
    op.execute("DELETE FROM setting WHERE key = 'solve.probe'")
    op.execute("DELETE FROM setting_key WHERE key = 'solve.probe'")
