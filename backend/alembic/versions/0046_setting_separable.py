"""Setting `solve.separable`: solve a model's independent blocks at once.

When on, a model whose compiled rows fall into more than one independent
block (`app.solve.blocks`) is solved block by block -- up to four at a time,
each in its own child with its share of the threads -- and the
answers are put together: the goal summed, the status the worst. A model
whose goal or rewrites tie the blocks together is solved whole, and the run
says why. On by default, on the bench's evidence
(bench/results/2026-09-23-separable.md): faster on every family and backend
that could finish, never slower, never a different optimum.
"""

import sqlalchemy as sa
from alembic import op

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "INSERT INTO setting_key (key, value_type, default_value, description)"
            " VALUES ('solve.separable', 'boolean', CAST('true' AS jsonb),"
            "         'Solve a model whose parts share no decision one part at a time, several at once,"
            " and add the answers up')"
        )
    )


def downgrade() -> None:
    op.execute("DELETE FROM setting WHERE key = 'solve.separable'")
    op.execute("DELETE FROM setting_key WHERE key = 'solve.separable'")
