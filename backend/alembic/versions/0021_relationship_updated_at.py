"""0021: optimistic locking on relationship

0010 covered the three tables that had an editable form. A relationship's
``attrs`` are now edited as a whole JSON object beside the canvas -- the
same wholesale replacement 0010 existed to detect -- so the row needs the
same timestamp, the same trigger, and the same opt-in PATCH check.

The function ``set_updated_at()`` already exists (0010). This revision
only attaches it to ``relationship``. A PATCH that omits ``updated_at``
is still not checked, so scripts and the graph's node rename keep working.

Revision ID: 0021
Revises: 0020
Create Date: 2026-09-21
"""
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE relationship
            ADD COLUMN updated_at timestamptz NOT NULL DEFAULT clock_timestamp();

        CREATE TRIGGER relationship_set_updated_at
            BEFORE INSERT OR UPDATE ON relationship
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER IF EXISTS relationship_set_updated_at ON relationship;
        ALTER TABLE relationship DROP COLUMN IF EXISTS updated_at;
        """
    )
