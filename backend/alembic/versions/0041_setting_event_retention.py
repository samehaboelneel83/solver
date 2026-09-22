"""Setting `run.event_retention_days`: how long a settled run keeps its progress events.

`run_event` (migration 0036) records every better answer and every tighter
bound while a run solves -- worth having while someone watches it, and for
a while after, but not for ever: a busy platform writes rows by the
thousand. The worker prunes the events of runs that settled more than this
many days ago (`app.retention`), at every level of migration 0014: a
problem or domain can keep its runs' curves longer, or shorter. 0 keeps
them for ever. The run itself, its answer and its `run_fact` stay; only the
curve goes.
"""

import sqlalchemy as sa
from alembic import op

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "INSERT INTO setting_key (key, value_type, default_value, description)"
            " VALUES ('run.event_retention_days', 'number', CAST('30' AS jsonb),"
            "         'Days a settled run keeps its progress events (the live curve);"
            " 0 keeps them for ever. The answer itself is kept either way')"
        )
    )


def downgrade() -> None:
    op.execute("DELETE FROM setting WHERE key = 'run.event_retention_days'")
    op.execute("DELETE FROM setting_key WHERE key = 'run.event_retention_days'")
