"""0020: reduced costs on solution -- which unused (or capped) decisions
would move the goal.

Duals (0019) sit on rules. Reduced costs sit on variables: how the
objective would move if this decision changed. Same honesty as duals --
only a linear solver at a vertex has them, so CP-SAT and a mixed-integer
search leave the column null rather than inventing a number.

Stored as jsonb in the same shape as a roster grouped by variable name,
with the index tuple and the value, omitting near-zeros so a large model
does not dump a wall of nothing. Nullable so a run written before this
migration, and a run from a backend that has none, still read.
"""

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE solution
            ADD COLUMN reduced_costs jsonb;
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE solution DROP COLUMN reduced_costs;")
