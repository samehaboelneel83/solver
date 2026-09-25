"""Setting `solve.connected_start`: a connected, balanced partition to start from (queue R13).

On (the default): a model with one `connected` rule is handed a complete start -- groups
grown from their seeds, balanced, each connected, and the flow that proves
it -- built in a tenth of the time (at most 10 s) by `app.solve.partition`.
CP-SAT, HiGHS and SCIP take it; an earlier answer (`solve.warm_start`) is
preferred where there is one. Past about 200 cells the exact flow found no
partition at all in two minutes (bench/results/2026-09-24-districting.md);
from the start CP-SAT improved it at 400 cells, never did worse where both
found answers, and a solver that ends with nothing leaves the start as the
run's answer (bench/results/2026-09-25-connected-start.md).
"""

import sqlalchemy as sa
from alembic import op

revision = "0060"
down_revision = "0059"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "INSERT INTO setting_key (key, value_type, default_value, description)"
            " VALUES ('solve.connected_start', 'boolean', CAST('true' AS jsonb),"
            "         'Start a connected partition (districting) from a balanced, connected one built first')"
        )
    )


def downgrade() -> None:
    op.execute("DELETE FROM setting WHERE key = 'solve.connected_start'")
    op.execute("DELETE FROM setting_key WHERE key = 'solve.connected_start'")
