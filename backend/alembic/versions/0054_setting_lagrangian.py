"""Setting `solve.lagrangian`: a Lagrangian bound beside an answer without a proof (queue R5).

When on, a run that ends with an answer but no proof, on a model that is a
few blocks tied by a few rules (`blocks.structure`), spends a further quarter
of its time relaxing those rules into the goal and searching their prices
(`app.solve.lagrange`); the bound is kept when it is tighter than the
solver's own. The default is the bench's call
(bench/results/2026-09-24-lagrangian.md).
"""

import sqlalchemy as sa
from alembic import op

revision = "0054"
down_revision = "0053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "INSERT INTO setting_key (key, value_type, default_value, description)"
            " VALUES ('solve.lagrangian', 'boolean', CAST('false' AS jsonb),"
            "         'Beside an answer without a proof, a bound from relaxing the few rules that tie the model')"
        )
    )


def downgrade() -> None:
    op.execute("DELETE FROM setting WHERE key = 'solve.lagrangian'")
    op.execute("DELETE FROM setting_key WHERE key = 'solve.lagrangian'")
