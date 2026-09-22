"""`run.fact_written_at`: which settled runs are in ClickHouse's `run_fact`.

An outbox, not a hook. A run settles in several places -- the worker, a
cancel of a queued run in the API, a stale run reclaimed as cancelled --
and ClickHouse may be down when it does. The worker sweeps settled runs
whose fact is not yet written (`app.analytics.publish_facts`), writes them,
and stamps this column; a failed write leaves it null for the next sweep.
The partial index keeps that sweep a lookup however long the run table
grows. Existing runs start null, so the first sweep backfills them all.
"""

from alembic import op

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE run ADD COLUMN fact_written_at timestamptz")
    op.execute(
        "CREATE INDEX run_fact_pending_idx ON run (id)"
        " WHERE fact_written_at IS NULL AND status NOT IN ('queued', 'running')"
    )


def downgrade() -> None:
    op.execute("DROP INDEX run_fact_pending_idx")
    op.execute("ALTER TABLE run DROP COLUMN fact_written_at")
