"""Setting `solve.rolling_horizon`: relax-and-fix over a model's time set (queue R9).

When on, a model with whole-number decisions indexed by a time set (an entity
type with the role `time`) is solved a window of periods at a time: the
window whole, later periods relaxed, earlier ones held (`app.solve.horizon`).
A heuristic: its answer is `feasible`, never proven best. The default is the
bench's call (bench/results/2026-09-25-rolling-horizon.md).
"""

import sqlalchemy as sa
from alembic import op

revision = "0057"
down_revision = "0056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "INSERT INTO setting_key (key, value_type, default_value, description)"
            " VALUES ('solve.rolling_horizon', 'boolean', CAST('false' AS jsonb),"
            "         'Solve a model over time a window at a time: this window whole, later ones relaxed')"
        )
    )


def downgrade() -> None:
    op.execute("DELETE FROM setting WHERE key = 'solve.rolling_horizon'")
    op.execute("DELETE FROM setting_key WHERE key = 'solve.rolling_horizon'")
