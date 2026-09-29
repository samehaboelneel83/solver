"""0090: solve workers say they are alive (Epic UX, U-5).

A planner about to solve should know whether anything will pick the run up.
Each worker process upserts its row here as it polls (`app.worker`); a worker
seen within the last minute and a half is online. Not tenant data -- the same
workers serve every organization -- and nothing about a run is kept here.
"""

from alembic import op

revision = "0090"
down_revision = "0089"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE worker_heartbeat (
            worker_id   text PRIMARY KEY CHECK (length(worker_id) BETWEEN 1 AND 200),
            host        text NOT NULL,
            pid         integer NOT NULL,
            started_at  timestamptz NOT NULL DEFAULT now(),
            last_seen   timestamptz NOT NULL DEFAULT now()
        );
        GRANT SELECT ON worker_heartbeat TO solver_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS worker_heartbeat")
