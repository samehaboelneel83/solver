"""0118: an extraction may read only what changed since the source's last read.

A database source may name a column that grows when a row changes (`changed_column`: an update time, or a version
number). An extraction job asked to be incremental reads the rows whose value is at least the highest one the
source's last read saw (its manifest's `high_water`), and a refresh from such a read adds and updates records but
never takes any away: a row it did not read is unchanged, not gone. A full read still finds what was removed.
"""
from alembic import op

revision = "0118"
down_revision = "0117"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE ingestion_job ADD COLUMN incremental boolean NOT NULL DEFAULT false")


def downgrade() -> None:
    op.execute("ALTER TABLE ingestion_job DROP COLUMN incremental")
