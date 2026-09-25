"""Setting `solve.decompose`: an exact template decomposition where it applies (queue R12).

On (the default): a model that is separable convex pieces tied by one rule
-- a resource allocation, `app.solve.allocation` -- is solved by pricing that
rule and solving each piece in closed form; the answer is proven by its dual
bound. The decomposition gate found it the one case the solvers could not
close (bench/results/2026-09-25-decomposition.md); where it does not apply,
nothing changes.
"""

import sqlalchemy as sa
from alembic import op

revision = "0059"
down_revision = "0058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "INSERT INTO setting_key (key, value_type, default_value, description)"
            " VALUES ('solve.decompose', 'boolean', CAST('true' AS jsonb),"
            "         'Solve a resource allocation exactly by pricing the one rule that ties it together')"
        )
    )


def downgrade() -> None:
    op.execute("DELETE FROM setting WHERE key = 'solve.decompose'")
    op.execute("DELETE FROM setting_key WHERE key = 'solve.decompose'")
