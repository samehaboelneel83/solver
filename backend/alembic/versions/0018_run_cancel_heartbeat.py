"""0018: cancel a run, and a heartbeat so a dead worker is noticed.

A run could only be waited out: there was no status for "stop", and a worker
that died mid-solve stayed `running` until start-up reclaim at thirty minutes.
That is a coarse substitute for the worker saying it is still alive.

**`cancelled` is a settled status**, like `error`. A queued run becomes it
immediately. A running one is asked to stop (`cancel_requested`); the worker
records `cancelled` instead of an answer. A dead worker that had already been
asked to stop is marked cancelled rather than solved again.

**`heartbeat_at` is liveness.** The worker touches it while solving. Reclaim
looks at that, not at `started_at`, so a slow run that is still working is
not stolen from its worker.

The extra enum label stays on downgrade: Postgres cannot drop a value without
rewriting the type, and a leftover label hurts nothing.
"""

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE run_status ADD VALUE IF NOT EXISTS 'cancelled'")
    op.execute(
        """
        ALTER TABLE run
            ADD COLUMN heartbeat_at timestamptz,
            ADD COLUMN cancel_requested boolean NOT NULL DEFAULT false;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE run
            DROP COLUMN heartbeat_at,
            DROP COLUMN cancel_requested;
        """
    )
