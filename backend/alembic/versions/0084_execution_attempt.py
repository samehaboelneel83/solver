"""0084: execution_attempt fencing for stale workers (OAAS S03).

Each claim bumps `execution_attempt`. Settling writes only succeed when the
attempt still matches, so a reclaimed run's old worker cannot overwrite the
new attempt's result.
"""

from alembic import op

revision = "0084"
down_revision = "0083"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE run
            ADD COLUMN execution_attempt integer NOT NULL DEFAULT 0;
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE run DROP COLUMN IF EXISTS execution_attempt;")
