"""0019: dual on constraint_result -- the shadow price, when the solver has one.

Slack (0017) is the residual at the assignment and every backend can fill
it. A dual is different: it says how the objective would move if this
rule moved, and only a linear solver at a vertex knows it. GLOP and HiGHS
on a pure LP fill it; CP-SAT and a mixed-integer search leave it null.
That is honest rather than a gap -- inventing a dual for an integer
model would be a number the answer does not have.

Nullable so a run written before this migration, and a run from a
backend that has no duals, still read.
"""

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE constraint_result
            ADD COLUMN dual numeric(15, 6);
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE constraint_result DROP COLUMN dual;")
