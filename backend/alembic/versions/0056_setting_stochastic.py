"""Setting `solve.stochastic_samples`: a two-stage stochastic solve over that many sampled futures (queue R7).

0 (the default) solves the model as written. More, on a model with decisions
marked stage 2 and data declared uncertain within a range, solves the
extensive form over that many sampled futures (at most 50) and costs the plan
on fresh ones (`app.solve.stochastic`). Not a technique the bench switches
on: it asks a different question, so a problem or domain opts in.
"""

import sqlalchemy as sa
from alembic import op

revision = "0056"
down_revision = "0055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "INSERT INTO setting_key (key, value_type, default_value, description)"
            " VALUES ('solve.stochastic_samples', 'number', CAST('0' AS jsonb),"
            "         'Sampled futures for a two-stage stochastic solve; 0 solves the model as written')"
        )
    )


def downgrade() -> None:
    op.execute("DELETE FROM setting WHERE key = 'solve.stochastic_samples'")
    op.execute("DELETE FROM setting_key WHERE key = 'solve.stochastic_samples'")
