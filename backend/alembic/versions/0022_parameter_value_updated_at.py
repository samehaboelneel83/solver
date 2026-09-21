"""0022: optimistic locking on parameter_value

0010 left this table out because the grid writes one cell at a time.
That still holds for two people editing *different* cells -- the PUT
names only dirty ones -- but two people typing the same cell is the
same silent overwrite 0010 closed for a whole row.

``set_updated_at()`` already exists (0010). This revision only attaches
it to ``parameter_value``. A PUT cell that omits ``updated_at`` is still
not checked, so scripts and a first write into an empty cell keep working.

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-21
"""
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE parameter_value
            ADD COLUMN updated_at timestamptz NOT NULL DEFAULT clock_timestamp();

        CREATE TRIGGER parameter_value_set_updated_at
            BEFORE INSERT OR UPDATE ON parameter_value
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER IF EXISTS parameter_value_set_updated_at ON parameter_value;
        ALTER TABLE parameter_value DROP COLUMN IF EXISTS updated_at;
        """
    )
