"""Where computed data came from: `source` on parameters and relationship types (queue R16a).

Distances between places and "within 5 km" links are made by the platform
from the map (`app.api.distances`), not typed in. `source` records how --
the metric, the unit, the date, what was left out -- so a run that reads
them can say which distances it used. NULL: typed in, as before.
"""

from alembic import op

revision = "0064"
down_revision = "0063"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE parameter_def ADD COLUMN source jsonb")
    op.execute("ALTER TABLE relationship_type ADD COLUMN source jsonb")


def downgrade() -> None:
    op.execute("ALTER TABLE relationship_type DROP COLUMN source")
    op.execute("ALTER TABLE parameter_def DROP COLUMN source")
